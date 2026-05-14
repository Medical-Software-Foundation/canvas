"""Rule 3: Every payer on an active coverage must have an address and phone.

Health Gorilla rejects with 422 when a payer record is missing structured
contact info. We check the Transactor (issuer) attached to each active
coverage on the patient.
"""

from datetime import date


def _has_complete_address(transactor) -> bool:
    for address in transactor.addresses.all():
        if (
            address.line1
            and address.city
            and address.state_code
            and address.postal_code
        ):
            return True
    return False


def _has_phone(transactor) -> bool:
    for phone in transactor.phones.all():
        if phone.value:
            return True
    return False


def check(patient) -> list[str]:
    today = date.today()
    errors: list[str] = []
    seen_issuer_dbids: set = set()

    for coverage in patient.coverages.all():
        start = coverage.coverage_start_date
        end = coverage.coverage_end_date
        if start and start > today:
            continue
        if end and end < today:
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
                f"Payer '{issuer.name}' is missing {missing_list}. "
                "Update the payer record."
            )

    return errors
