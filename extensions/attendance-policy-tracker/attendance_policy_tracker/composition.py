"""The composition root.

One place names every concrete implementation, sets the ordering, and wires the
pieces together. Nothing else in the plugin names a concrete detector, a concrete
attribution rule, the Canvas adapter, or the settings store, so adding a rule or a
counted event type is a new class plus one line here.

Ordering is the part that carries meaning rather than being incidental. Detectors
run no show first, then late move, then late cancellation, because a moved visit
ends up with a cancelled status and letting the cancellation detector see it first
would lose the distinction the policy is built on. Attribution rules run no show,
then the patient portal signal, then the clinic tag, then the configured default,
so the default can never take a cancellation the patient plainly made themselves.

Policy comes from a store the plugin owns rather than from its installation
variables. A plugin cannot write its variables, there is no effect for it, so
policy kept there could only ever be edited in Canvas administration as a column
of text boxes. The store is writable, which is what makes a configuration screen
with real controls possible. The one thing that stays in administration is who may
open that screen, and it stays there precisely because the plugin cannot change
it.

Coercion lives here and nowhere else. A store holds text, a form sends text, and
policy wants numbers and lists, so both directions of that translation sit
together in this file where they can be read against each other.
"""

import json
from typing import Any

import arrow

from attendance_policy_tracker.canvas.actions import CanvasActions
from attendance_policy_tracker.canvas.settings_store import NamespaceSettingsStore
from attendance_policy_tracker.canvas.source import CanvasVisitSource
from attendance_policy_tracker.canvas.states import (
    CANCELLED_STATES,
    NO_SHOW_STATES,
    REVERTED_STATES,
)
from attendance_policy_tracker.canvas.tasks import CanvasTaskReader
from attendance_policy_tracker.core.attribution import (
    AttributionChain,
    ClinicTagRule,
    ConfiguredDefaultRule,
    NoShowRule,
    PatientPortalRule,
)
from attendance_policy_tracker.core.clock import Clock
from attendance_policy_tracker.core.config import Config
from attendance_policy_tracker.core.contracts import (
    DETECTOR_METHODS,
    RULE_METHODS,
    STORE_METHODS,
    TASK_READER_METHODS,
    validate,
)
from attendance_policy_tracker.core.detectors import (
    LateCancellationDetector,
    LateMoveDetector,
    NoShowDetector,
)
from attendance_policy_tracker.core.engine import AttendanceEngine

# Every setting the configuration screen may write, grouped by how its text is
# read back. A name absent from all three groups cannot be saved, which is what
# stops a crafted request writing a key that policy would later trust.
INT_SETTINGS = (
    "late_cutoff_hours",
    "move_boundary_hours",
    "counting_window_months",
    "holding_window_minutes",
    "run_count",
    "run_window_minutes",
    "warning_line",
    "discharge_review_line",
)

LIST_SETTINGS = (
    "counted_kinds",
    "warning_task_labels",
    "discharge_review_task_labels",
)

STRING_SETTINGS = (
    "default_attribution",
    "warning_team_id",
    "discharge_review_team_id",
    "clinic_tag",
)

# The install floor reads and writes on its own path rather than joining the
# string settings, because its text is a moment rather than a plain label, and
# it goes through arrow in both directions instead of a bare strip.
DATETIME_SETTINGS = ("install_floor",)

EDITABLE_SETTINGS = INT_SETTINGS + LIST_SETTINGS + STRING_SETTINGS + DATETIME_SETTINGS


def _as_list(raw: Any) -> list[str] | None:
    """Read a list setting written either as JSON or as separated text.

    The screen writes JSON. Accepting separated text as well costs nothing and
    means a value typed by hand during support still reads correctly, with
    whitespace and commas both separating.
    """
    if raw is None:
        return None
    text = f"{raw}".strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
        return [f"{item}".strip() for item in parsed if f"{item}".strip()]
    separated = text.replace(",", " ").split()
    return [item for item in separated if item]


def config_from(raw: dict[str, Any] | None) -> Config:
    """Resolve policy from stored text, layered over the shipped defaults.

    A setting that is absent, empty, or unreadable falls through to its default
    rather than failing, so a partly configured install still runs a coherent
    policy. A setting that is present but contradictory, such as a review line
    below the warning line, is refused loudly by the policy itself.
    """
    raw = raw or {}
    overrides: dict[str, Any] = {}

    for name in INT_SETTINGS:
        value = raw.get(name)
        if value is None or f"{value}".strip() == "":
            continue
        try:
            overrides[name] = int(f"{value}".strip())
        except ValueError:
            # An unreadable number is ignored so its default stands, rather than
            # taking down every read on the strength of one bad field.
            continue

    for name in LIST_SETTINGS:
        parsed = _as_list(raw.get(name))
        if parsed is not None:
            overrides[name] = parsed

    for name in STRING_SETTINGS:
        value = raw.get(name)
        if value is not None and f"{value}".strip():
            overrides[name] = f"{value}".strip()

    for name in DATETIME_SETTINGS:
        value = raw.get(name)
        if value is None or f"{value}".strip() == "":
            continue
        try:
            overrides[name] = arrow.get(f"{value}".strip()).to("utc").datetime
        except (ValueError, TypeError):
            # An unreadable moment is ignored so its default stands, the same
            # fallback an unreadable number already gets.
            continue

    return Config(overrides)


def to_raw(values: dict[str, Any]) -> dict[str, str]:
    """Turn submitted values into the text a store holds.

    Only names the screen is allowed to write survive this, so an unexpected key
    in a request body is dropped here rather than reaching storage.
    """
    written: dict[str, str] = {}
    for name in EDITABLE_SETTINGS:
        if name not in values:
            continue
        value = values[name]
        if value is None:
            written[name] = ""
        elif name in LIST_SETTINGS:
            items = value if isinstance(value, list) else [value]
            written[name] = json.dumps([f"{item}".strip() for item in items if f"{item}".strip()])
        elif name in DATETIME_SETTINGS:
            text = f"{value}".strip()
            if not text:
                written[name] = ""
                continue
            try:
                written[name] = arrow.get(text).to("utc").isoformat()
            except (ValueError, TypeError):
                # An unparseable submission is refused silently, so a garbled
                # moment never reaches storage and whatever floor already
                # stands, or the default, is left exactly where it was.
                continue
        else:
            written[name] = f"{value}".strip()
    return written


def build_engine(config: Config, clock: Any = None, source: Any = None) -> AttendanceEngine:
    """Wire the engine with its detectors, its rules, and its Canvas adapter."""
    clock = clock or Clock()
    source = source or CanvasVisitSource()

    detectors = [
        validate(
            NoShowDetector(NO_SHOW_STATES, REVERTED_STATES), DETECTOR_METHODS, "detector"
        ),
        validate(
            LateMoveDetector(clock, config.move_boundary_hours),
            DETECTOR_METHODS,
            "detector",
        ),
        validate(
            LateCancellationDetector(
                clock, config.late_cutoff_hours, CANCELLED_STATES, REVERTED_STATES
            ),
            DETECTOR_METHODS,
            "detector",
        ),
    ]

    rules = [
        validate(NoShowRule(), RULE_METHODS, "rule"),
        validate(PatientPortalRule(), RULE_METHODS, "rule"),
        validate(ClinicTagRule(config.clinic_tag), RULE_METHODS, "rule"),
        validate(ConfiguredDefaultRule(config.default_attribution), RULE_METHODS, "rule"),
    ]

    return AttendanceEngine(
        config=config,
        source=source,
        detectors=detectors,
        chain=AttributionChain(rules),
        clock=clock,
        cancelled_states=CANCELLED_STATES,
    )


def build(
    store: Any = None, clock: Any = None, source: Any = None, task_reader: Any = None
) -> dict[str, Any]:
    """Everything a handler needs, built once from stored policy."""
    store = validate(store or NamespaceSettingsStore(), STORE_METHODS, "settings store")
    task_reader = validate(
        task_reader or CanvasTaskReader(), TASK_READER_METHODS, "task reader"
    )
    config = config_from(store.read())
    return {
        "config": config,
        "engine": build_engine(config, clock=clock, source=source),
        "actions": CanvasActions(config, task_reader),
        "store": store,
    }
