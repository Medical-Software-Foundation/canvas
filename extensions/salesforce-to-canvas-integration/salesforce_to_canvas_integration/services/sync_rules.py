"""Auto apply filter evaluator for the deliberate Salesforce sync.

Given a derived action, the mapped payload, the operator settings, and a small
set of history facts the caller gathers, decide whether the sync applies
automatically or holds for a human, and when it holds, name why.

The evaluator is the pure heart of phase two. It imports nothing from the
Canvas SDK so it unit tests in isolation exactly like the old patient matcher
did. It only reads :class:`MappedPatient`, which is itself SDK free.

The model is hard gates above two configurable layers. Hard gates never bend
and always hold. Layer one decides whether automation is allowed for the event
at all. Layer two decides whether this particular record earns it. A filter
only ever promotes a sync to automatic, it never auto applies something a human
would otherwise have to gate. See journal cnv-938/029 and the plan in 030.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from salesforce_to_canvas_integration.services.field_mapping import MappedPatient

# Derived actions, the existing stored vocabulary. Create and modify are the
# two derived verbs of the Sync event, delete is the Delete event.
ACTION_CREATE = "create"
ACTION_MODIFY = "modify"
ACTION_DELETE = "delete"
SYNC_ACTIONS: tuple[str, ...] = (ACTION_CREATE, ACTION_MODIFY)

# Configurable delete actions, the three mechanisms that already exist as
# routes. Unlink is selectable but never the default because the next sync for
# an unlinked contact derives create and would spawn a duplicate patient.
DELETE_ACTION_MARK_INACTIVE = "mark_inactive"
DELETE_ACTION_TAG_DELETED = "tag_deleted"
DELETE_ACTION_UNLINK = "unlink"
DELETE_ACTIONS: tuple[str, ...] = (
    DELETE_ACTION_MARK_INACTIVE,
    DELETE_ACTION_TAG_DELETED,
    DELETE_ACTION_UNLINK,
)

# Defaults live here as code constants. A missing settings row or a missing key
# means defaults, so the plugin behaves before anyone touches the Settings tab.
DEFAULT_AUTO_CREATE = True
DEFAULT_AUTO_MODIFY = True
DEFAULT_AUTO_DELETE = False
DEFAULT_DELETE_ACTION = DELETE_ACTION_MARK_INACTIVE
DEFAULT_REQUIRED_FIELDS: tuple[str, ...] = (
    "first_name",
    "last_name",
    "date_of_birth",
    "phone",
)
DEFAULT_ADDRESS_GROUP_INTEGRITY = True
DEFAULT_VALIDITY_CHECKS = True

# The demographic fields an operator may mark required in the Settings form. The
# form renders one checkbox per entry and the PUT settings route validates the
# submitted required set against this catalog, so the route and the form share
# one vocabulary. Every field is a regular toggle, including last name, the
# operator owns the whole set. The address parts stay out, the address group
# integrity rule governs them as a unit rather than one at a time.
REQUIRED_FIELD_CHOICES: tuple[str, ...] = (
    "first_name",
    "last_name",
    "date_of_birth",
    "sex_at_birth",
    "email",
    "phone",
)

# The create only floor. Last name is always required to create a Canvas patient,
# the writer rejects a create without it. The evaluator unions this into the
# required set for a create regardless of the operator settings, so a record that
# would otherwise auto apply into a writer rejection holds with a clear reason
# instead. Modify passes no floor, it stays a delta on a linked patient that
# already carries a last name. See journal cnv-941/036.
CREATE_REQUIRED_FLOOR: tuple[str, ...] = ("last_name",)

# The address group, all or nothing. Country stays out because the effect
# builder defaults it to US, so requiring it would hold most real records.
ADDRESS_GROUP: tuple[str, ...] = (
    "address_line_1",
    "city",
    "state",
    "postal_code",
)

# Sex at birth values the writer accepts. Mirrors ``_SEX_AT_BIRTH`` in the
# effect builder so the validity check can never drift from the writer.
_VALID_SEX: frozenset[str] = frozenset({"male", "female", "other", "unknown"})

# Country values treated as US for state and postal format checks.
_US_COUNTRIES: frozenset[str] = frozenset({"US", "USA", "UNITED STATES"})

# Hold reason strings. Short and stable, they are stored on rows and rendered in
# the Records details, so changing them changes what an operator reads.
REASON_MAPPING_FAILED = "field mapping failed"
REASON_PREVIOUSLY_SKIPPED = "previously skipped"
REASON_LINK_PENDING = "create accepted, link pending"
REASON_DUPLICATE_MATCH = "matches an existing patient"
REASON_AUTO_CREATE_OFF = "auto create disabled"
REASON_AUTO_MODIFY_OFF = "auto modify disabled"
REASON_AUTO_DELETE_OFF = "auto delete disabled"
REASON_INCOMPLETE_ADDRESS = "incomplete address"


@dataclass(frozen=True)
class SyncSettings:
    """Operator tunable filter settings. Defaults match the code constants."""

    auto_create: bool = DEFAULT_AUTO_CREATE
    auto_modify: bool = DEFAULT_AUTO_MODIFY
    auto_delete: bool = DEFAULT_AUTO_DELETE
    delete_action: str = DEFAULT_DELETE_ACTION
    required_fields: tuple[str, ...] = DEFAULT_REQUIRED_FIELDS
    address_group_integrity: bool = DEFAULT_ADDRESS_GROUP_INTEGRITY
    validity_checks: bool = DEFAULT_VALIDITY_CHECKS


@dataclass(frozen=True)
class SyncFacts:
    """History the caller gathers about this record before evaluating.

    ``linked`` is whether a Canvas patient is already linked to the external id.
    ``accepted_create_exists`` is whether a create for this external id was
    already accepted but its asynchronous link has not landed yet, the race in
    finding four. ``previously_skipped`` is whether the most recent decision for
    this external id was a skip. ``duplicate_match`` is whether an unlinked
    create matches an existing patient on the live duplicate check.
    ``mapping_failed`` is whether the row was captured raw only.
    """

    linked: bool = False
    accepted_create_exists: bool = False
    previously_skipped: bool = False
    duplicate_match: bool = False
    mapping_failed: bool = False


@dataclass(frozen=True)
class SyncDecision:
    """Auto apply or hold, plus the named reasons when it holds."""

    auto_apply: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def held(self) -> bool:
        return not self.auto_apply


def evaluate(
    *,
    action: str,
    mapped: MappedPatient,
    settings: SyncSettings,
    facts: SyncFacts,
    today: date,
) -> SyncDecision:
    """Decide auto apply or hold for one captured record.

    Evaluation order is hard gates first, then layer one decides whether
    automation is allowed for the event at all, then layer two decides whether
    this record earns it. ``today`` is supplied by the caller so the future
    birthdate check stays deterministic and the module stays clock free.
    """
    gate_reasons = _hard_gate_reasons(action, facts)
    if gate_reasons:
        return SyncDecision(False, tuple(gate_reasons))

    layer_one = _layer_one_reason(action, settings)
    if layer_one is not None:
        return SyncDecision(False, (layer_one,))

    # Delete writes no demographics, so layer two never touches it.
    if action == ACTION_DELETE:
        return SyncDecision(True)

    # Create carries the last name floor, modify carries none.
    floor = CREATE_REQUIRED_FLOOR if action == ACTION_CREATE else ()
    layer_two = _layer_two_reasons(mapped, settings, today=today, floor=floor)
    if layer_two:
        return SyncDecision(False, tuple(layer_two))

    return SyncDecision(True)


def _hard_gate_reasons(action: str, facts: SyncFacts) -> list[str]:
    """Reasons that always hold, regardless of any setting."""
    reasons: list[str] = []
    if facts.mapping_failed:
        reasons.append(REASON_MAPPING_FAILED)
    if facts.previously_skipped:
        reasons.append(REASON_PREVIOUSLY_SKIPPED)
    if action == ACTION_CREATE:
        if facts.accepted_create_exists:
            reasons.append(REASON_LINK_PENDING)
        if facts.duplicate_match:
            reasons.append(REASON_DUPLICATE_MATCH)
    return reasons


def _layer_one_reason(action: str, settings: SyncSettings) -> str | None:
    """Hold reason when automation is disabled for this event, else None."""
    if action == ACTION_CREATE and not settings.auto_create:
        return REASON_AUTO_CREATE_OFF
    if action == ACTION_MODIFY and not settings.auto_modify:
        return REASON_AUTO_MODIFY_OFF
    if action == ACTION_DELETE and not settings.auto_delete:
        return REASON_AUTO_DELETE_OFF
    return None


def _layer_two_reasons(
    mapped: MappedPatient,
    settings: SyncSettings,
    *,
    today: date,
    floor: tuple[str, ...] = (),
) -> list[str]:
    """Promotion rule failures, accumulated so the operator sees them all."""
    reasons: list[str] = []
    fields = mapped.canvas_fields

    # Required set, the operator set plus the caller supplied floor, deduped with
    # order preserved. The floor is empty for modify and delete, so only a create
    # gains the last name requirement on top of the operator choices.
    required = tuple(dict.fromkeys(settings.required_fields + floor))
    for name in required:
        if not _present(fields.get(name)):
            reasons.append(f"missing required {_humanize(name)}")

    # Address group, all or nothing over street, city, state, postal code.
    if settings.address_group_integrity:
        present = [k for k in ADDRESS_GROUP if _present(fields.get(k))]
        if present and len(present) != len(ADDRESS_GROUP):
            reasons.append(REASON_INCOMPLETE_ADDRESS)

    # Validity, a populated value must survive the coercion the writer applies.
    if settings.validity_checks:
        reasons.extend(_validity_reasons(fields, today=today))

    return reasons


def _validity_reasons(fields: dict[str, Any], *, today: date) -> list[str]:
    """One reason per populated field that fails its validity check."""
    reasons: list[str] = []

    dob = fields.get("date_of_birth")
    if _present(dob) and not _valid_birthdate(dob, today=today):
        reasons.append(f"invalid {_humanize('date_of_birth')}")

    sex = fields.get("sex_at_birth")
    if _present(sex) and not _valid_sex(sex):
        reasons.append(f"invalid {_humanize('sex_at_birth')}")

    email = fields.get("email")
    if _present(email) and not _valid_email(email):
        reasons.append(f"invalid {_humanize('email')}")

    phone = fields.get("phone")
    if _present(phone) and not _valid_phone(phone):
        reasons.append(f"invalid {_humanize('phone')}")

    # State and postal format only apply when the country reads as US or empty.
    if _is_us(fields.get("country")):
        state = fields.get("state")
        if _present(state) and not _valid_state(state):
            reasons.append(f"invalid {_humanize('state')}")
        postal = fields.get("postal_code")
        if _present(postal) and not _valid_postal(postal):
            reasons.append(f"invalid {_humanize('postal_code')}")

    return reasons


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _humanize(field_name: str) -> str:
    return field_name.replace("_", " ")


def _parse_date(value: Any) -> date | None:
    """Mirror ``_coerce_date`` in the effect builder so the check cannot drift."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _valid_birthdate(value: Any, *, today: date) -> bool:
    parsed = _parse_date(value)
    if parsed is None:
        return False
    return parsed <= today


def _valid_sex(value: Any) -> bool:
    return str(value).strip().lower() in _VALID_SEX


def _valid_email(value: Any) -> bool:
    text = str(value).strip()
    if text.count("@") != 1:
        return False
    local, _, domain = text.partition("@")
    if not local or not domain:
        return False
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        return False
    return True


def _valid_phone(value: Any) -> bool:
    digits = [c for c in str(value) if c.isdigit()]
    return len(digits) >= 10


def _is_us(country: Any) -> bool:
    if not _present(country):
        return True
    return str(country).strip().upper() in _US_COUNTRIES


def _valid_state(value: Any) -> bool:
    text = str(value).strip()
    return len(text) == 2 and text.isalpha()


def _valid_postal(value: Any) -> bool:
    text = str(value).strip()
    if any(c not in "0123456789-" for c in text):
        return False
    digits = [c for c in text if c.isdigit()]
    return len(digits) in (5, 9)


__all__ = (
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_MODIFY",
    "ADDRESS_GROUP",
    "CREATE_REQUIRED_FLOOR",
    "DEFAULT_ADDRESS_GROUP_INTEGRITY",
    "DEFAULT_AUTO_CREATE",
    "DEFAULT_AUTO_DELETE",
    "DEFAULT_AUTO_MODIFY",
    "DEFAULT_DELETE_ACTION",
    "DEFAULT_REQUIRED_FIELDS",
    "DEFAULT_VALIDITY_CHECKS",
    "DELETE_ACTION_MARK_INACTIVE",
    "DELETE_ACTION_TAG_DELETED",
    "DELETE_ACTION_UNLINK",
    "DELETE_ACTIONS",
    "REASON_AUTO_CREATE_OFF",
    "REASON_AUTO_DELETE_OFF",
    "REASON_AUTO_MODIFY_OFF",
    "REASON_DUPLICATE_MATCH",
    "REASON_INCOMPLETE_ADDRESS",
    "REASON_LINK_PENDING",
    "REASON_MAPPING_FAILED",
    "REASON_PREVIOUSLY_SKIPPED",
    "REQUIRED_FIELD_CHOICES",
    "SYNC_ACTIONS",
    "SyncDecision",
    "SyncFacts",
    "SyncSettings",
    "evaluate",
)
