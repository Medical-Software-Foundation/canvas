"""Rule 5: Each coverage subscriber must have an address on file.

When the patient is a dependent on someone else's policy, the coverage
subscriber is a separate Patient record. Health Gorilla requires the coverage
subscriber to have a complete address. When the coverage subscriber IS the
patient, Rule 4 already covers it and this rule skips the check to avoid
duplicate errors.
"""

from lab_order_validation.rules._helpers import (
    has_meaningful_content,
    is_active_coverage,
    sanitize_for_display,
)


def _active_coverages(patient) -> list:
    return [c for c in patient.coverages.all() if is_active_coverage(c)]


def _has_complete_address(person) -> bool:
    for address in person.addresses.all():
        if (
            has_meaningful_content(address.line1)
            and has_meaningful_content(address.city)
            and has_meaningful_content(address.state_code)
            and has_meaningful_content(address.postal_code)
        ):
            return True
    return False


def _display_name(person) -> str:
    name = getattr(person, "full_name", None)
    if name:
        return name
    first = getattr(person, "first_name", "") or ""
    last = getattr(person, "last_name", "") or ""
    combined = f"{first} {last}".strip()
    return combined or "the coverage subscriber"


def check(patient) -> list[str]:
    errors: list[str] = []
    seen: set = set()
    patient_id = getattr(patient, "id", None)

    for coverage in _active_coverages(patient):
        subscriber = getattr(coverage, "subscriber", None)
        if subscriber is None:
            continue
        subscriber_id = getattr(subscriber, "id", None)
        if subscriber_id is None:
            continue
        # If the coverage subscriber is the patient, Rule 4 already covers their address.
        if patient_id is not None and subscriber_id == patient_id:
            continue
        if subscriber_id in seen:
            continue
        seen.add(subscriber_id)

        if not _has_complete_address(subscriber):
            name = sanitize_for_display(_display_name(subscriber))
            errors.append(
                f"Coverage subscriber '{name}' has no complete address. "
                "Update their address on their patient chart."
            )

    return errors
