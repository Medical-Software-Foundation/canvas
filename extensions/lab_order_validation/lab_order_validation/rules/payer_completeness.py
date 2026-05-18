"""Rule 3: Every payer on an active coverage must have an address and phone.

Health Gorilla rejects with 422 when a payer record is missing structured
contact info. We check the Transactor (issuer) attached to each active
coverage on the patient.
"""

from lab_order_validation.rules._helpers import (
    has_meaningful_content,
    is_active_coverage,
    sanitize_for_display,
)


def _has_complete_address(transactor) -> bool:
    for address in transactor.addresses.all():
        if (
            has_meaningful_content(address.line1)
            and has_meaningful_content(address.city)
            and has_meaningful_content(address.state_code)
            and has_meaningful_content(address.postal_code)
        ):
            return True
    return False


def _has_phone(transactor) -> bool:
    for phone in transactor.phones.all():
        if has_meaningful_content(phone.value, min_alnum=7):
            return True
    return False


def check(patient) -> list[str]:
    errors: list[str] = []
    seen_issuer_dbids: set = set()

    for coverage in patient.coverages.all():
        if not is_active_coverage(coverage):
            continue
        issuer = coverage.issuer
        if issuer is None or issuer.dbid in seen_issuer_dbids:
            continue
        seen_issuer_dbids.add(issuer.dbid)

        missing: list[str] = []
        if not _has_complete_address(issuer):
            missing.append("address")
        if not _has_phone(issuer):
            missing.append("phone")

        if missing:
            missing_list = " and ".join(missing)
            errors.append(
                f"Payer '{sanitize_for_display(issuer.name)}' is missing {missing_list}. "
                "Update the payer record."
            )

    return errors
