"""Business-line resolution for per-referral-source message customization.

Referral sources are tracked as *business lines* — a first-class Canvas
data model (``canvas_sdk.v1.data.BusinessLine``) attached to the **patient**
(``Patient.business_line``), not the appointment. A patient has exactly one
business line (or none). We read it; we never derive it.

Routing keys off the business line's ``name`` so admin config and presets stay
human-readable and portable across environments (the integer id is per-instance).
"""
from typing import Any


def get_business_line_name(patient: Any) -> str:
    """Return the patient's business line name, or ``""`` if none/unavailable.

    Guarded because ``business_line`` is a nullable FK and test doubles may not
    populate it. Never raises — a missing business line simply routes to the
    default template/attribution.
    """
    try:
        business_line = patient.business_line
    except Exception:
        return ""
    if business_line is None:
        return ""
    return getattr(business_line, "name", "") or ""


def resolve_attribution(config: Any, business_line_name: str) -> str:
    """Resolve the patient-facing attribution text for a business line.

    Precedence: per-business-line override (``business_line_overrides[name]``
    ``attribution`` field) → ``config.default_attribution``. Returns the default
    when the business line is unknown/unmapped or its override sets no attribution.
    """
    if business_line_name:
        entry = config.business_line_overrides.get(business_line_name)
        if entry:
            attribution = str(entry.get("attribution") or "").strip()
            if attribution:
                return attribution
    return str(config.default_attribution)


def get_business_line_from_number(config: Any, business_line_name: str) -> str:
    """Return the SMS "from" number configured for a business line, or ``""``.

    Each business line's SMS is sent from its own outbound number. The
    per-BL number lives in the plugin config (``business_line_overrides[name]``
    ``from_number``) because the Canvas SDK does not expose the underlying
    ``BusinessLineSetting`` — same limitation as ``OrganizationSetting``. An
    empty return means "no per-BL number", and the caller falls back to the
    global ``twilio-phone-number`` secret.
    """
    if business_line_name:
        entry = config.business_line_overrides.get(business_line_name)
        if entry:
            return str(entry.get("from_number") or "").strip()
    return ""
