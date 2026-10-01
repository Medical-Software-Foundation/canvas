from datetime import date

from canvas_sdk.v1.data.observation import Observation
from canvas_sdk.v1.data.patient import Patient
from logger import log

from sleep_screening.scoring.base import PatientContext

# Committed, non-error vital observations. Matches the proven filter set used by
# the bmi_coding_automation reference plugin.
_VITAL_FILTERS = {
    "deleted": False,
    "entered_in_error_id__isnull": True,
    "committer_id__isnull": False,
    "category": "vital-signs",
}


def _age(birth_date, today: date) -> int | None:
    if birth_date is None:
        return None
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years = years - 1
    return years


def _normalize_sex(sex) -> str | None:
    if not sex:
        return None
    upper = str(sex).upper()
    if upper.startswith("M"):
        return "M"
    if upper.startswith("F"):
        return "F"
    return None


def _latest_vital(patient, name: str):
    return (
        Observation.objects.filter(patient=patient, name=name, **_VITAL_FILTERS)
        .exclude(value="")
        .order_by("created")
        .last()
    )


def _weight_lbs(patient) -> float | None:
    obs = _latest_vital(patient, "weight")
    if obs is None or obs.value in (None, ""):
        return None
    try:
        value = float(obs.value)
    except (ValueError, TypeError):
        return None
    if obs.units == "oz":
        return value / 16
    return value


def _height_inches(patient) -> float | None:
    obs = _latest_vital(patient, "height")
    if obs is None or obs.value in (None, ""):
        return None
    try:
        return float(obs.value)
    except (ValueError, TypeError):
        return None


def _bmi(patient) -> float | None:
    """Compute BMI from the latest committed height + weight vitals. Canvas does
    not store adult BMI as its own observation; it is derived from height/weight
    (same approach as bmi_coding_automation). Returns None if either is missing."""
    weight_lbs = _weight_lbs(patient)
    height_inches = _height_inches(patient)
    # `not height_inches` already excludes 0, so no divide-by-zero is possible.
    if not weight_lbs or not height_inches:
        return None
    return 703.0 * weight_lbs / (height_inches * height_inches)


def build_context(patient_id: str, today: date) -> PatientContext:
    try:
        patient = Patient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        log.info("sleep_screening: patient not found: " + str(patient_id))
        return PatientContext()
    return PatientContext(
        age=_age(patient.birth_date, today),
        sex=_normalize_sex(patient.sex_at_birth),
        bmi=_bmi(patient),
    )
