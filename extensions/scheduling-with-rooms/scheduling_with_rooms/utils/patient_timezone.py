"""Read a patient's preferred scheduling timezone from the SDK data models.

The modal renders slot times in the patient's timezone. Canvas stores the
authoritative value as a ``PatientSetting`` row named
``preferredSchedulingTimezone``, so this is a plain DB read — no FHIR client,
no OAuth credentials, no outbound HTTP.

``Patient.last_known_timezone`` remains the fallback for patients with no
setting, and the browser's own timezone is the last resort.
"""

from canvas_sdk.v1.data.patient import PatientSetting, PatientSettingConstants
from logger import log


def get_patient_timezone(patient_id: str) -> str:
    """Return the patient's preferred scheduling timezone, or ``""``.

    Most patients have no setting row; an empty string tells the caller to fall
    back rather than signalling an error.
    """
    row = (
        PatientSetting.objects.filter(
            patient__id=patient_id,
            name=PatientSettingConstants.PREFERRED_SCHEDULING_TIMEZONE,
        )
        .values("value")
        .first()
    )
    if not row:
        return ""

    # `value` is a JSONField holding a bare string, e.g. "America/New_York",
    # so it arrives already deserialized.
    value = row["value"]
    if not isinstance(value, str):
        log.warning(
            "patient timezone: unexpected %s value for patient %s: %r",
            PatientSettingConstants.PREFERRED_SCHEDULING_TIMEZONE,
            patient_id,
            value,
        )
        return ""
    return value.strip()


__all__ = ("get_patient_timezone",)
