"""Rule 5: Each insurance subscriber must have an address on file.

When the patient is a dependent on someone else's policy, the subscriber is a
separate Patient record. Health Gorilla requires the subscriber to have a
complete address. When the subscriber IS the patient, Rule 4 already covers it
and this rule skips the check to avoid duplicate errors.
"""

from datetime import date


def _active_coverages(patient) -> list:
    today = date.today()
    out = []
    for coverage in patient.coverages.all():
        start = coverage.coverage_start_date
        end = coverage.coverage_end_date
        if start and start > today:
            continue
        if end and end < today:
            continue
        out.append(coverage)
    return out


def _has_complete_address(person) -> bool:
    for address in person.addresses.all():
        if (
            address.line1
            and address.city
            and address.state_code
            and address.postal_code
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
    return combined or "the subscriber"


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
        # If the subscriber is the patient, Rule 4 already covers their address.
        if patient_id is not None and subscriber_id == patient_id:
            continue
        if subscriber_id in seen:
            continue
        seen.add(subscriber_id)

        if not _has_complete_address(subscriber):
            name = _display_name(subscriber)
            errors.append(
                f"Subscriber '{name}' has no complete address. "
                "Update the subscriber's profile from the Coverages tab."
            )

    return errors
