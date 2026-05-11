"""Rule 4: Patient must have a home address marked Postal or Both.

Health Gorilla silently drops orders when the only home address is
type=Physical. The fix is to mark the address as Postal or Both.
"""

HOME_USE = "home"
ACCEPTED_TYPES = {"postal", "both"}


def _normalize(value) -> str:
    """Coerce enum or string to a lowercase string for comparison."""
    if value is None:
        return ""
    inner = getattr(value, "value", value)
    return str(inner).strip().lower()


def check(patient) -> list[str]:
    addresses = list(patient.addresses.all())

    for address in addresses:
        if _normalize(address.use) != HOME_USE:
            continue
        if _normalize(address.type) not in ACCEPTED_TYPES:
            continue
        if (
            address.line1
            and address.city
            and address.state_code
            and address.postal_code
        ):
            return []

    if not addresses:
        return [
            "Patient has no address on file. Add a home address (type Postal "
            "or Both) in demographics."
        ]

    return [
        "Patient's home address must be type Postal or Both with complete "
        "street/city/state/zip. Fix in demographics."
    ]
