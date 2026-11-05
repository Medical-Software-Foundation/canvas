"""Read the plugin's configuration from its secrets.

Everything is configured in the plugin's settings in Canvas, so a practice can
change who gets faxed without a code change or a reinstall:

- ``AUTO_FAX_MODE``: ``off``, ``dry_run`` or ``live``. Blank or anything else
  means ``off``. Only ``live`` sends faxes; ``dry_run`` logs what it would send.
- ``AUTO_FAX_RULES``: a JSON list of rules (see README). A rule fires on a note
  state change (the default), or, with ``"trigger": "fax_orders_button"``, it
  sets up the note's **Fax orders** button. Invalid JSON, or a rule that can't be read, is logged and
  ignored, never guessed at.
- ``AUTO_FAX_TEST_FAX_NUMBER``: optional. When set, every fax goes to this one
  number instead of the real recipient, so a practice can try ``live`` mode
  against its own fax line first.

The module fails closed: missing or broken configuration sends nothing.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from logger import log

from auto_fax.services.fax_number import ten_digits

MODE_OFF = "off"
MODE_DRY_RUN = "dry_run"
MODE_LIVE = "live"
MODES = frozenset({MODE_OFF, MODE_DRY_RUN, MODE_LIVE})

# Note states a rule can fire on. LKD is the first lock, SGN a signature on a
# note type that requires one, RLK a lock after the note was unlocked.
STATE_LOCKED = "LKD"
STATE_SIGNED = "SGN"
STATE_RELOCKED = "RLK"
TRIGGER_STATES = frozenset({STATE_LOCKED, STATE_SIGNED, STATE_RELOCKED})

ANY_NOTE_TYPE = "*"

# When a rule fires. ``note_state`` (the default) fires on a note state change
# (``trigger_states``). ``fax_orders_button`` adds a **Fax orders** button to
# the note; a staff member clicks it to fax the note's committed orders, signed
# or not (``order_types``, ``send_as``).
TRIGGER_NOTE_STATE = "note_state"
TRIGGER_FAX_ORDERS_BUTTON = "fax_orders_button"
TRIGGERS = frozenset({TRIGGER_NOTE_STATE, TRIGGER_FAX_ORDERS_BUTTON})

# How a button rule sends. The SDK can fax a whole note, or the own document of
# a referral, imaging order or lab order. It has no way to fax a page with only
# some of a note's commands on it.
#  - ``whole_note``: one fax per recipient, the note as it stands (every order
#    is in it, and so is the rest of the note).
#  - ``order_documents``: one fax per order, each order's own document. Only
#    referral, imaging and lab orders have one.
SEND_WHOLE_NOTE = "whole_note"
SEND_ORDER_DOCUMENTS = "order_documents"
SEND_AS = frozenset({SEND_WHOLE_NOTE, SEND_ORDER_DOCUMENTS})

# Order types a ``fax_orders_button`` rule can name. The first three have their
# own fax document in Canvas (the referral, the imaging order, the lab
# requisition). The rest have none, so they can only go in a ``whole_note`` fax.
ORDER_REFERRAL = "referral"
ORDER_IMAGING = "imaging"
ORDER_LAB = "lab"
ORDER_DME = "dme"
ORDER_PRESCRIBE = "prescribe"
ORDER_ADJUST_PRESCRIPTION = "adjust_prescription"
ORDER_REFILL = "refill"
ORDER_CHANGE_MEDICATION = "change_medication"
ORDER_STOP_MEDICATION = "stop_medication"
ORDER_MEDICATION_STATEMENT = "medication_statement"
OWN_DOCUMENT_ORDER_TYPES = frozenset({ORDER_REFERRAL, ORDER_IMAGING, ORDER_LAB})
MEDICATION_ORDER_TYPES = frozenset(
    {
        ORDER_PRESCRIBE,
        ORDER_ADJUST_PRESCRIPTION,
        ORDER_REFILL,
        ORDER_CHANGE_MEDICATION,
        ORDER_STOP_MEDICATION,
        ORDER_MEDICATION_STATEMENT,
    }
)
WHOLE_NOTE_ORDER_TYPES = MEDICATION_ORDER_TYPES | {ORDER_DME}
ORDER_TYPES = OWN_DOCUMENT_ORDER_TYPES | WHOLE_NOTE_ORDER_TYPES
# Shorthand a rule can use for every medication order type.
ORDER_ALIAS_MEDICATION = "medication"

RECIPIENT_CARE_TEAM_ROLE = "care_team_role"
RECIPIENT_FACILITY = "facility"
RECIPIENT_FIXED = "fixed"
RECIPIENT_TYPES = frozenset(
    {RECIPIENT_CARE_TEAM_ROLE, RECIPIENT_FACILITY, RECIPIENT_FIXED}
)

# FaxNoteEffect coversheet fields have no documented length limit, but fax
# coversheets print these on one line, so keep them short.
_SUBJECT_MAX = 100
_COMMENT_MAX = 500


@dataclass(frozen=True)
class RecipientSpec:
    """Who a rule faxes. Exactly one of the ``type`` shapes applies."""

    type: str
    role_codes: frozenset[str] = frozenset()
    name: str = ""
    fax_digits: str | None = None


@dataclass(frozen=True)
class CoverSheet:
    """The coversheet a rule adds in front of the note."""

    subject: str
    comment: str


@dataclass(frozen=True)
class Rule:
    """One rule: which notes (or orders), on which trigger, go to whom."""

    name: str
    note_type_codes: frozenset[str]
    trigger_states: frozenset[str]
    recipients: tuple[RecipientSpec, ...]
    location_ids: frozenset[str] = frozenset()
    cover_sheet: CoverSheet | None = None
    trigger: str = TRIGGER_NOTE_STATE
    order_types: frozenset[str] = frozenset()
    # Command metadata every order must carry, compared case-insensitively,
    # e.g. {"alert_facility": "Yes"}. Empty means no metadata check.
    command_metadata: tuple[tuple[str, str], ...] = ()
    send_as: str = SEND_WHOLE_NOTE

    def matches_metadata(self, metadata: dict[str, str]) -> bool:
        """Whether a command with this metadata passes the rule's metadata check."""
        return all(
            (metadata.get(key) or "").strip().casefold() == value.casefold()
            for key, value in self.command_metadata
        )

    def matches(self, note_type_code: str | None, location_id: str | None) -> bool:
        """Whether a note of this type, at this location, is covered by the rule."""
        if (
            ANY_NOTE_TYPE not in self.note_type_codes
            and note_type_code not in self.note_type_codes
        ):
            return False
        return not self.location_ids or location_id in self.location_ids


@dataclass(frozen=True)
class Config:
    """The parsed configuration."""

    mode: str = MODE_OFF
    rules: tuple[Rule, ...] = ()
    test_fax_digits: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)


def _string_set(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item).strip() for item in value if str(item).strip())


def _parse_recipient(raw: Any, where: str, errors: list[str]) -> RecipientSpec | None:
    if not isinstance(raw, dict):
        errors.append(f"{where}: a recipient must be an object")
        return None
    kind = raw.get("type")
    if kind not in RECIPIENT_TYPES:
        errors.append(f"{where}: unknown recipient type {kind!r}")
        return None
    if kind == RECIPIENT_CARE_TEAM_ROLE:
        codes = _string_set(raw.get("role_codes"))
        if not codes:
            errors.append(f"{where}: care_team_role needs at least one role code")
            return None
        return RecipientSpec(type=kind, role_codes=codes)
    if kind == RECIPIENT_FIXED:
        name = str(raw.get("name") or "").strip()
        digits = ten_digits(str(raw.get("fax") or ""))
        if not name or not digits:
            errors.append(f"{where}: fixed needs a name and a valid US fax number")
            return None
        return RecipientSpec(type=kind, name=name, fax_digits=digits)
    return RecipientSpec(type=kind)


def _parse_cover_sheet(raw: Any, where: str, errors: list[str]) -> CoverSheet | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append(f"{where}: cover_sheet must be an object")
        return None
    subject = str(raw.get("subject") or "").strip()[:_SUBJECT_MAX]
    comment = str(raw.get("comment") or "").strip()[:_COMMENT_MAX]
    if not subject or not comment:
        errors.append(f"{where}: cover_sheet needs a subject and a comment")
        return None
    return CoverSheet(subject=subject, comment=comment)


def _parse_rule(raw: Any, index: int, errors: list[str]) -> Rule | None:
    where = f"rule {index + 1}"
    if not isinstance(raw, dict):
        errors.append(f"{where}: a rule must be an object")
        return None
    name = str(raw.get("name") or where).strip()
    where = f"rule {name!r}"
    if raw.get("enabled", True) is not True:
        return None

    note_types = _string_set(raw.get("note_type_codes"))
    if not note_types:
        errors.append(
            f'{where}: note_type_codes is required (use ["*"] for every note type)'
        )
        return None

    trigger = str(raw.get("trigger") or TRIGGER_NOTE_STATE).strip()
    if trigger not in TRIGGERS:
        errors.append(f"{where}: trigger must be one of {sorted(TRIGGERS)}")
        return None

    states: frozenset[str] = frozenset()
    order_fields: dict[str, Any] = {}
    if trigger == TRIGGER_NOTE_STATE:
        if any(raw.get(key) is not None for key in _ORDER_ONLY_FIELDS):
            errors.append(
                f"{where}: {', '.join(_ORDER_ONLY_FIELDS)} need "
                f'"trigger": "{TRIGGER_FAX_ORDERS_BUTTON}"'
            )
            return None
        states = _string_set(raw.get("trigger_states", [STATE_LOCKED]))
        unknown = states - TRIGGER_STATES
        if not states or unknown:
            errors.append(
                f"{where}: trigger_states must be from {sorted(TRIGGER_STATES)}"
            )
            return None
    else:
        parsed_order_fields = _parse_order_fields(raw, where, errors)
        if parsed_order_fields is None:
            return None
        order_fields = parsed_order_fields

    raw_recipients = raw.get("recipients")
    if not isinstance(raw_recipients, list) or not raw_recipients:
        errors.append(f"{where}: recipients must be a non-empty list")
        return None
    recipients = []
    for position, raw_recipient in enumerate(raw_recipients):
        spec = _parse_recipient(
            raw_recipient, f"{where} recipient {position + 1}", errors
        )
        if spec is None:
            # One unreadable recipient disables the whole rule rather than
            # faxing a partial list nobody asked for.
            return None
        recipients.append(spec)

    cover_sheet = _parse_cover_sheet(raw.get("cover_sheet"), where, errors)
    if raw.get("cover_sheet") is not None and cover_sheet is None:
        return None

    return Rule(
        name=name,
        note_type_codes=note_types,
        trigger_states=states,
        recipients=tuple(recipients),
        location_ids=_string_set(raw.get("location_ids")),
        cover_sheet=cover_sheet,
        trigger=trigger,
        **order_fields,
    )


_ORDER_ONLY_FIELDS = ("order_types", "command_metadata", "send_as")


def _parse_order_fields(
    raw: dict[str, Any], where: str, errors: list[str]
) -> dict[str, Any] | None:
    """The ``fax_orders_button`` fields of a rule, or None (with an error) when unreadable."""
    if raw.get("trigger_states") is not None:
        errors.append(
            f"{where}: trigger_states only applies to note_state rules; "
            "a fax_orders_button rule sends when staff click the button"
        )
        return None

    names = _string_set(raw.get("order_types"))
    if ORDER_ALIAS_MEDICATION in names:
        names = (names - {ORDER_ALIAS_MEDICATION}) | MEDICATION_ORDER_TYPES
    unknown = names - ORDER_TYPES
    if not names or unknown:
        errors.append(
            f"{where}: order_types must be from "
            f"{sorted(ORDER_TYPES | {ORDER_ALIAS_MEDICATION})}"
        )
        return None

    # No default: whether the facility gets the whole note is the practice's
    # call, so the rule has to say it.
    send_as = str(raw.get("send_as") or "").strip()
    if send_as not in SEND_AS:
        errors.append(f"{where}: send_as must be one of {sorted(SEND_AS)}")
        return None
    whole_note_only = sorted(names & WHOLE_NOTE_ORDER_TYPES)
    if send_as == SEND_ORDER_DOCUMENTS and whole_note_only:
        errors.append(
            f"{where}: {', '.join(whole_note_only)} have no document of their own; "
            f'use "send_as": "{SEND_WHOLE_NOTE}" or remove them'
        )
        return None

    raw_metadata = raw.get("command_metadata", {})
    if not isinstance(raw_metadata, dict):
        errors.append(f"{where}: command_metadata must be an object of key: value")
        return None
    metadata = tuple(
        sorted(
            (str(key).strip(), str(value).strip())
            for key, value in raw_metadata.items()
            if str(key).strip()
        )
    )
    if any(not value for _, value in metadata):
        errors.append(f"{where}: every command_metadata value must be non-empty")
        return None

    return {
        "order_types": names,
        "command_metadata": metadata,
        "send_as": send_as,
    }


def load_config(secrets: Any) -> Config:
    """Parse the plugin secrets into a ``Config``. Never raises on bad input."""
    errors: list[str] = []

    mode = str(secrets.get("AUTO_FAX_MODE") or "").strip().lower()
    if mode not in MODES:
        if mode:
            errors.append(
                f"AUTO_FAX_MODE {mode!r} is not one of {sorted(MODES)}; treating as off"
            )
        mode = MODE_OFF

    test_raw = str(secrets.get("AUTO_FAX_TEST_FAX_NUMBER") or "").strip()
    test_digits = ten_digits(test_raw)
    if test_raw and not test_digits:
        # A test number that can't be read must not fall through to real
        # recipients, so the whole plugin goes off.
        errors.append(
            "AUTO_FAX_TEST_FAX_NUMBER is not a valid US fax number; treating as off"
        )
        mode = MODE_OFF

    rules: list[Rule] = []
    raw_rules = str(secrets.get("AUTO_FAX_RULES") or "").strip()
    if raw_rules:
        try:
            parsed = json.loads(raw_rules)
        except json.JSONDecodeError as exc:
            errors.append(
                f"AUTO_FAX_RULES is not valid JSON: {exc.msg} (line {exc.lineno})"
            )
            parsed = []
        if not isinstance(parsed, list):
            errors.append("AUTO_FAX_RULES must be a JSON list of rules")
            parsed = []
        for index, raw_rule in enumerate(parsed):
            rule = _parse_rule(raw_rule, index, errors)
            if rule is not None:
                rules.append(rule)

    for error in errors:
        log.warning(f"[auto_fax] config: {error}")

    return Config(
        mode=mode, rules=tuple(rules), test_fax_digits=test_digits, errors=tuple(errors)
    )
