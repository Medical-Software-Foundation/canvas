"""Shared logic for the patient-sex banner effect.

Used by both the event handler (single patient, real time) and the one-time
backfill cron task, so the two paths always build the same banner.
"""
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert
from canvas_sdk.v1.data.patient import SexAtBirth

BANNER_KEY = "sex-banner"

# Sex-at-birth values that transmit cleanly for EPCS; anything else gets a banner.
BINARY_SEXES = (SexAtBirth.FEMALE.value, SexAtBirth.MALE.value)

NARRATIVE = "WARNING: Patient sex is {sex}. EPCS Rx requires a sex of F or M for successful transmission"


def sex_needs_banner(sex_at_birth) -> bool:
    """Return True when the sex-at-birth value would block EPCS transmission."""
    return sex_at_birth not in BINARY_SEXES


def add_banner_effect(patient):
    """Build the applied AddBannerAlert effect for a patient needing the banner."""
    return AddBannerAlert(
        patient_id=patient.id,
        key=BANNER_KEY,
        narrative=NARRATIVE.format(sex=patient.sex_at_birth),
        placement=[
            AddBannerAlert.Placement.TIMELINE,
            AddBannerAlert.Placement.CHART,
            AddBannerAlert.Placement.PROFILE,
        ],
        intent=AddBannerAlert.Intent.ALERT,
    ).apply()


def remove_banner_effect(patient):
    """Build the applied RemoveBannerAlert effect for a patient no longer needing the banner."""
    return RemoveBannerAlert(key=BANNER_KEY, patient_id=patient.id).apply()


def banner_effect_for_patient(patient):
    """Return the single add-or-remove Effect that reconciles this patient's banner."""
    if sex_needs_banner(patient.sex_at_birth):
        return add_banner_effect(patient)
    return remove_banner_effect(patient)
