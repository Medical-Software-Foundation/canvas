"""Shared builders for the outstanding-required-consents chart banner.

One place that fixes the banner's key, copy, placement (chart) and intent
(warning), used by both the event-driven ``ConsentBanner`` handler and the admin
backfill endpoint, so they always place and clear the exact same alert.
"""

from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert

from consent_capture.constants import BANNER_KEY, BANNER_NARRATIVE


def add_banner_effect(patient_id):
    """Build the (applied) AddBannerAlert effect for one patient. It is keyed, so
    re-applying updates rather than duplicates the banner (and refreshes its copy
    and placement)."""
    return AddBannerAlert(
        patient_id=patient_id,
        key=BANNER_KEY,
        narrative=BANNER_NARRATIVE,
        placement=[AddBannerAlert.Placement.CHART, AddBannerAlert.Placement.PROFILE],
        intent=AddBannerAlert.Intent.WARNING,
    ).apply()


def remove_banner_effect(patient_id):
    """Build the (applied) RemoveBannerAlert effect clearing this patient's banner."""
    return RemoveBannerAlert(key=BANNER_KEY, patient_id=patient_id).apply()
