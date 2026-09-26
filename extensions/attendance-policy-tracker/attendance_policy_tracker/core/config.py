"""Policy configuration and its shipped defaults.

Defaults live here in code rather than in stored configuration, because a fresh
install has no stored row at all and the plugin has to behave sensibly before
anybody opens its configuration tab. Stored values are overrides layered on top,
weakest to strongest, the same way the rest of the workspace layers settings.

Nothing about authorization appears here. Who may open the configuration screen
is not policy, it is a permission, it lives in Canvas administration rather than
in this plugin's storage, and it is handled in `core.access`.

Five of these values are assumptions rather than agreed policy, the late cutoff,
the move boundary, the two lines, and what happens when a patient crosses both
lines at once. They are recorded as open questions in the specification and a
practice changes them without a code change, which is the whole point of them
being settings.
"""

from typing import Any, cast

from attendance_policy_tracker.core.contracts import ATTRIBUTIONS, PATIENT

# Kinds of incident, which double as the vocabulary of the counted events
# setting. A kind switched off is never counted and never tagged.
KIND_NO_SHOW = "no_show"
KIND_LATE_CANCELLATION = "late_cancellation"
KIND_LATE_MOVE = "late_move"

ALL_KINDS = (KIND_NO_SHOW, KIND_LATE_CANCELLATION, KIND_LATE_MOVE)

DEFAULTS: dict[str, Any] = {
    # Hours before the appointment start inside which a cancellation counts.
    "late_cutoff_hours": 24,
    # Hours before the appointment start inside which moving a visit counts.
    "move_boundary_hours": 24,
    # How far back a total reaches, rolling from the moment of the read rather
    # than from the start of a calendar year.
    "counting_window_months": 12,
    # How long the plugin waits after an incident before anything it creates
    # becomes visible, so a tag applied shortly afterwards costs nothing.
    "holding_window_minutes": 15,
    # How many cancellations against one provider inside the run window get
    # tagged as the clinic's by the plugin itself.
    "run_count": 3,
    "run_window_minutes": 15,
    # The two lines. The review line must sit above the warning line.
    "warning_line": 3,
    "discharge_review_line": 5,
    # Who an unattributed cancellation counts against. Tag the exception and
    # count everything else, so an untagged staff cancellation lands on the
    # patient.
    "default_attribution": PATIENT,
    # Which kinds count. Empty means all of them.
    "counted_kinds": list(ALL_KINDS),
    # Teams that receive each task. Empty means the task is not raised, because
    # a task with nobody to own it is worse than no task.
    "warning_team_id": "",
    "discharge_review_team_id": "",
    # Labels applied to each generated task.
    "warning_task_labels": [],
    "discharge_review_task_labels": [],
    # The label that marks a cancellation as the clinic's.
    "clinic_tag": "clinic-cancelled",
    # The moment this plugin was installed, stamped once by a handler that
    # runs on the platform's own install event. No floor means everything
    # counts, which is today's behaviour and the safe fallback until that
    # handler has had its one chance to write it.
    "install_floor": None,
}

# Ceilings paired with the lower bound check in _validate below. Every one of
# these used to be harmless past a certain size, because the read they bound
# fetched everything regardless of what a setting claimed. Once the query in
# canvas.source is pushed down to the window a stored value describes, that
# stops being true, counting_window_months in particular now decides how much
# of a patient's real history a single read pulls off the database, so an
# absurd number here turns straight into an absurd query. A five year rolling
# window is already far past any attendance policy a practice plausibly runs,
# so sixty months is the ceiling for it. The hour settings get a week, a late
# cutoff or a move boundary measured in weeks has already stopped meaning
# late. The two minute settings get a day, a holding period or a run window
# that wide no longer describes a short pause. Run count gets fifty, more
# cancellations than that inside one run window is not a pattern the rule was
# built to describe. Every ceiling here exists to keep a stored number from
# turning a bounded read into an unbounded one, not to express agreed policy,
# so a practice that genuinely needs something wider is a code change away
# rather than a setting away.
UPPER_BOUNDS: dict[str, int] = {
    "late_cutoff_hours": 168,
    "move_boundary_hours": 168,
    "counting_window_months": 60,
    "holding_window_minutes": 1440,
    "run_count": 50,
    "run_window_minutes": 1440,
    "warning_line": 1000,
}


class ConfigError(ValueError):
    """A stored configuration that cannot be used as policy."""


class Config:
    """Resolved policy, defaults with stored overrides layered on top."""

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        values = dict(DEFAULTS)
        if overrides:
            for key, value in overrides.items():
                # An unknown key is ignored rather than fatal, so a
                # configuration written by a newer version of the plugin does
                # not stop an older one from running.
                if key in values and value is not None and value != "":
                    values[key] = value
        self._values: dict[str, Any] = values
        self._validate()

    def _validate(self) -> None:
        """Refuse a configuration that cannot express a coherent policy."""
        if self.discharge_review_line <= self.warning_line:
            raise ConfigError(
                "The review threshold has to sit above the warning threshold. "
                f"Warning is {self.warning_line} and review is "
                f"{self.discharge_review_line}."
            )
        if self.default_attribution not in ATTRIBUTIONS:
            allowed = ", ".join(ATTRIBUTIONS)
            raise ConfigError(
                f"default_attribution must be one of {allowed}, got {self.default_attribution}."
            )
        for kind in self.counted_kinds:
            if kind not in ALL_KINDS:
                allowed = ", ".join(ALL_KINDS)
                raise ConfigError(f"counted_kinds may only contain {allowed}, got {kind}.")
        for name in (
            "late_cutoff_hours",
            "move_boundary_hours",
            "counting_window_months",
            "holding_window_minutes",
            "run_count",
            "run_window_minutes",
            "warning_line",
        ):
            # Scoped to this named tuple rather than to every stored key, on
            # purpose. A stored setting this plugin does not recognise, such as
            # another handler's own cursor riding on the same store, must pass
            # through untouched rather than tripping a bound written for a name
            # it was never about.
            value = int(self._values[name])
            if value < 0:
                raise ConfigError(f"{name} cannot be negative.")
            upper = UPPER_BOUNDS.get(name)
            if upper is not None and value > upper:
                raise ConfigError(f"{name} cannot be greater than {upper}.")

    def __getattr__(self, name: str) -> Any:
        """Expose every configured value as an attribute."""
        values = self.__dict__.get("_values") or {}
        if name in values:
            return values[name]
        raise AttributeError(name)

    def counts(self, kind: str) -> bool:
        """True when this kind of incident is switched on."""
        return kind in self.counted_kinds

    def team_for(self, line: str) -> str:
        """The team that receives the task for a given line, or empty."""
        if line == "warning":
            return cast(str, self.warning_team_id)
        if line == "discharge_review":
            return cast(str, self.discharge_review_team_id)
        return ""

    def labels_for(self, line: str) -> list[str]:
        """The labels applied to the task for a given line."""
        if line == "warning":
            return list(self.warning_task_labels)
        if line == "discharge_review":
            return list(self.discharge_review_task_labels)
        return []

    def as_dict(self) -> dict[str, Any]:
        """The resolved policy, for a configuration screen to render.

        Every other value here is already plain text or a plain number, the
        install floor is the one value resolved into a real datetime, so it is
        turned back into the same ISO text a screen and a JSON response can
        both carry.
        """
        values = dict(self._values)
        floor = values.get("install_floor")
        if floor is not None:
            values["install_floor"] = floor.isoformat()
        return values
