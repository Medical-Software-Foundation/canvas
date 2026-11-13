"""Load / save / seed the questionnaire pairing rules (custom_data).

The config is one JSON document in a single FollowUpConfig row. On first load
(no row yet) it is seeded with the two standard short->long pairs, then
persisted, so the admin page opens populated rather than blank.

The seeded rules ship DISABLED on purpose. They point at national-standard LOINC
codes, and an instance may have loaded its questionnaires under different codes -
a rule pointing at a code this instance does not have would silently never fire,
which is worse than a rule that is visibly off. An admin reviews each one against
the questionnaire picker and turns it on.
"""

import json
from typing import Any
from uuid import uuid4

from logger import log

from questionnaire_followup.models import FollowUpConfig
from questionnaire_followup.services.questionnaires import resolve_names

_CONFIG_KEY = "active"

# When the shipped defaults were last checked against published guidance. Shown
# in the admin page so a practice reviews them rather than assuming they track
# the latest recommendation.
DEFAULTS_CURRENT_AS_OF = "2026-09-10"

# Rule defaults, applied to any rule field the stored document is missing.
DEFAULT_THRESHOLD = 3
DEFAULT_TRIGGER_LOOKBACK_DAYS = 30
DEFAULT_SUPPRESSION_DAYS = 90

# Every portal page load reads the whole rule set, so it is capped: a runaway config
# would slow every patient's portal, not just the admin page. Far above what a
# practice pairs in practice (depression, anxiety, alcohol use, a few others).
MAX_RULES = 50

# How a screen's score is compared with the rule's threshold. The stored value is
# the key; the editor renders the label. Both live here so the page, the handler
# and the save endpoint cannot drift apart.
#
# Only these four. "greater than" and "less than" are deliberately absent: scores
# are integer sums, so `> 2` is exactly `>= 3`, and offering both ways to write
# one rule invites an operator flipped without its number. "at most" is not
# redundant with them - it is how an instrument where a LOW score is the
# concerning one (Mini-Cog, MNA-SF) is paired at all. "completed" ignores the
# score, which is the only way to pair an instrument whose answers are not
# numeric ordinals and therefore cannot be scored.
COMPARATOR_AT_LEAST = "at_least"
COMPARATOR_AT_MOST = "at_most"
COMPARATOR_BETWEEN = "between"
COMPARATOR_COMPLETED = "completed"

# Ordered: the editor builds its dropdown from this, in this order.
COMPARATOR_LABELS: dict[str, str] = {
    COMPARATOR_AT_LEAST: "scores at least",
    COMPARATOR_AT_MOST: "scores at most",
    COMPARATOR_BETWEEN: "scores between",
    COMPARATOR_COMPLETED: "is completed",
}
COMPARATORS = tuple(COMPARATOR_LABELS)

# Every rule written before comparators existed means this one.
DEFAULT_COMPARATOR = COMPARATOR_AT_LEAST

# The questionnaire each seeded code is meant to name. Used only at seed time: the
# instance is asked what IT loaded under that name, and the code below is the
# fallback when the name does not resolve.
#
# This exists because the shipped panel codes were wrong on the first real instance
# they were checked against - PHQ-2 was 58120-7, not 55758-7, and GAD-2 was SNOMED,
# not LOINC at all - while PHQ-9 and GAD-7 matched exactly. A short->long plugin
# keys off the short instrument, so both shipped pairings were inert there. See
# CLAUDE.md, open question 1.
_SEED_QUESTIONNAIRE_NAMES: dict[str, str] = {
    "55758-7": "PHQ-2",
    "44249-1": "PHQ-9",
    "69736-7": "GAD-2",
    "69737-5": "GAD-7",
}

# LOINC panel codes for the two pairs practices ask for first. Cutoffs are the
# published ones: PHQ-2 >= 3 and GAD-2 >= 3 are the standard positive screens.
_SEED_RULES: list[dict[str, Any]] = [
    {
        "name": "Depression (PHQ-2 → PHQ-9)",
        "trigger_code": "55758-7",
        "followup_code": "44249-1",
        "threshold": 3,
    },
    {
        "name": "Anxiety (GAD-2 → GAD-7)",
        "trigger_code": "69736-7",
        "followup_code": "69737-5",
        "threshold": 3,
    },
]


def new_rule(**overrides: Any) -> dict[str, Any]:
    """Build a rule with every field populated, so callers never see a missing key."""
    rule: dict[str, Any] = {
        "id": uuid4().hex,
        "enabled": False,
        "name": "New pairing",
        "trigger_code": "",
        "followup_code": "",
        "comparator": DEFAULT_COMPARATOR,
        "threshold": DEFAULT_THRESHOLD,
        "threshold_max": DEFAULT_THRESHOLD,
        "trigger_lookback_days": DEFAULT_TRIGGER_LOOKBACK_DAYS,
        "suppression_days": DEFAULT_SUPPRESSION_DAYS,
    }
    rule.update(overrides)
    return rule


def _default_document() -> dict[str, Any]:
    """Build the seed config (disabled defaults; the admin owns these after seed)."""
    return {
        "version": 1,
        "defaults_current_as_of": DEFAULTS_CURRENT_AS_OF,
        "defaults_reviewed": False,
        "rules": [new_rule(**seed) for seed in _SEED_RULES],
    }


def _seed_document() -> dict[str, Any]:
    """Build the seed config, pointed at the questionnaires THIS instance loaded.

    Costs one extra query, and only ever on the very first load, when there is no
    stored config yet. Each seeded code is looked up by the questionnaire name it
    stands for; a name the instance does not carry, or carries twice, leaves the
    published panel code in place for the admin to correct in the editor.

    The rules still ship **disabled** either way. A name match is a better first
    guess than a code guessed in advance, not a substitute for someone reviewing
    what the pairing points at.
    """
    doc = _default_document()
    by_name = resolve_names(set(_SEED_QUESTIONNAIRE_NAMES.values()))
    substituted: list[str] = []
    for rule in doc["rules"]:
        for side in ("trigger_code", "followup_code"):
            name = _SEED_QUESTIONNAIRE_NAMES.get(rule[side])
            code = by_name.get(name, "") if name else ""
            if code and code != rule[side]:
                substituted.append(f"{name} {rule[side]} -> {code}")
                rule[side] = code
    if substituted:
        log.info(
            "questionnaire_followup seeded the default pairings with this instance's "
            "codes: " + "; ".join(substituted)
        )
    return doc


def _coerce_int(value: Any, fallback: int) -> int:
    """Read an int out of whatever the form sent, falling back on anything unusable."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_comparator(value: Any) -> str:
    """Read a stored comparator, defaulting a missing one to the original behaviour.

    A rule written before comparators existed carries no key at all and has to
    keep meaning "at least". An unrecognized one - a document saved by a NEWER
    version of this plugin and read back by this one - is kept verbatim rather
    than mapped onto a comparator this version does understand: ``active_rules``
    then leaves that rule inert, which is safer than firing it with a meaning
    nobody chose (an "at most" rule read as "at least" is its own inverse).
    """
    comparator = str(value or "").strip()
    return comparator or DEFAULT_COMPARATOR


def normalize_rule(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill in defaults and coerce types for one stored rule.

    Runs on read as well as write: a document saved by an older version of the
    admin page must not hand the handler a missing or string-typed threshold.
    """
    threshold = _coerce_int(raw.get("threshold"), DEFAULT_THRESHOLD)
    return new_rule(
        id=str(raw.get("id") or uuid4().hex),
        enabled=bool(raw.get("enabled", False)),
        name=str(raw.get("name") or "Untitled pairing"),
        trigger_code=str(raw.get("trigger_code") or "").strip(),
        followup_code=str(raw.get("followup_code") or "").strip(),
        comparator=_coerce_comparator(raw.get("comparator")),
        threshold=threshold,
        # A rule saved before ranges existed carries only one number. Reading the
        # high end as the low one makes a "between" conversion mean "exactly N"
        # rather than a band that silently spans everything above it.
        threshold_max=_coerce_int(raw.get("threshold_max"), threshold),
        trigger_lookback_days=max(
            1, _coerce_int(raw.get("trigger_lookback_days"), DEFAULT_TRIGGER_LOOKBACK_DAYS)
        ),
        suppression_days=max(
            0, _coerce_int(raw.get("suppression_days"), DEFAULT_SUPPRESSION_DAYS)
        ),
    )


def normalize_document(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a config document with every rule normalized and every key present.

    Rules past ``MAX_RULES`` are dropped. The save endpoint refuses such a document
    outright; this is the backstop for one that arrived any other way.
    """
    rules = raw.get("rules")
    return {
        "version": _coerce_int(raw.get("version"), 1),
        "defaults_current_as_of": str(
            raw.get("defaults_current_as_of") or DEFAULTS_CURRENT_AS_OF
        ),
        "defaults_reviewed": bool(raw.get("defaults_reviewed", False)),
        "rules": [normalize_rule(r) for r in rules if isinstance(r, dict)][:MAX_RULES]
        if isinstance(rules, list)
        else [],
    }


def load_config() -> dict[str, Any]:
    """Return the stored config, seeding and persisting the defaults on first use.

    Never raises. A failure to read config degrades to the (disabled) defaults
    rather than breaking the patient's portal page load - the handler that calls
    this runs on every portal request.

    The degraded path returns the published panel codes without looking anything
    up. Only the seed path asks the instance what it loaded, so the one extra
    query happens once rather than on every portal load of a broken install.
    """
    try:
        row = FollowUpConfig.objects.filter(key=_CONFIG_KEY).first()
        if row and row.payload:
            return normalize_document(json.loads(row.payload))
    except Exception as exc:  # missing namespace/table or bad payload -> defaults
        log.warning(f"questionnaire_followup config load failed, using defaults: {exc}")
        return _default_document()
    doc = _seed_document()
    save_config(doc)  # best-effort seed; never raises
    return doc


def save_config(doc: dict[str, Any]) -> bool:
    """Persist the config document; return False if custom_data is unavailable.

    Broad catch is deliberate - a missing namespace/table must not crash the
    request; the caller decides how to report it.
    """
    try:
        payload = json.dumps(normalize_document(doc))
        row = FollowUpConfig.objects.filter(key=_CONFIG_KEY).first()
        if row:
            row.payload = payload
            row.save()
        else:
            FollowUpConfig.objects.create(key=_CONFIG_KEY, payload=payload)
        return True
    except Exception as exc:  # custom_data namespace/table not ready
        log.warning(f"questionnaire_followup config save failed (custom_data unavailable?): {exc}")
        return False


def describe_rule(rule: dict[str, Any]) -> str:
    """The rule's score condition as a sentence fragment, e.g. "scores at least 3".

    The editor, the handler's trace and the admin diagnostic all read the
    vocabulary from here, so the words a practice sees in one place are the words
    it sees in the others.
    """
    comparator = rule.get("comparator", DEFAULT_COMPARATOR)
    label = COMPARATOR_LABELS.get(comparator)
    if label is None:
        return f"unrecognized score rule '{comparator}'"
    if comparator == COMPARATOR_COMPLETED:
        return label
    if comparator == COMPARATOR_BETWEEN:
        return f"{label} {rule['threshold']} and {rule['threshold_max']}"
    return f"{label} {rule['threshold']}"


def inactive_reason(rule: dict[str, Any]) -> str | None:
    """Why this rule can never fire as written, or None when it is live.

    The single definition of "active": ``active_rules`` keeps the rules this
    returns None for, and the diagnostic reports the sentence for the rest. A new
    disqualifier added here reaches both without touching either.
    """
    if not rule.get("enabled"):
        return "switched off"
    if not rule.get("trigger_code"):
        return "no trigger questionnaire chosen"
    if not rule.get("followup_code"):
        return "no follow-up questionnaire chosen"
    if rule.get("comparator") not in COMPARATORS:
        # A document written by a NEWER version of this plugin. Kept verbatim and
        # left inert rather than coerced onto a comparator this version knows.
        return f"unrecognized score rule '{rule.get('comparator')}'"
    return None


def active_rules(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The rules that are switched on, fully addressed and readable, in configured order."""
    return [rule for rule in doc.get("rules", []) if inactive_reason(rule) is None]
