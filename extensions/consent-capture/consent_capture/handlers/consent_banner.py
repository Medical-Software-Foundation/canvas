"""Chart banner alert for outstanding required consents.

Surfaces a warning banner on the patient's chart whenever the patient has at least
one required consent that is not on file (never recorded, or expired), and clears
it once none remain. Recomputed whenever the patient's consents change (recorded,
updated, or deleted) and when the patient record changes.

Banners can only carry an ``href`` link, not launch the in-EHR modal, so this one
is informational: staff open the consents from the red "Consents" chart button or
the app drawer.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from consent_capture.banner import add_banner_effect, remove_banner_effect
from consent_capture.constants import banners_enabled
from consent_capture.service import has_incomplete_required, is_eligible_patient


class ConsentBanner(BaseHandler):
    """Add or remove the outstanding-required-consents banner on the patient profile."""

    RESPONDS_TO = [
        EventType.Name(EventType.CONSENT_CREATED),
        EventType.Name(EventType.CONSENT_UPDATED),
        EventType.Name(EventType.CONSENT_DELETED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    def _patient_id(self):
        """The patient in context. Consent events carry ``context.patient.id``;
        patient events carry the patient id as the event ``target``."""
        context = getattr(self, "context", None) or {}
        patient = context.get("patient") or {}
        return patient.get("id") or getattr(self, "target", None) or ""

    def compute(self) -> list[Effect]:
        patient_id = self._patient_id()
        if not patient_id:
            return []
        # Feature flag (CONSENT_BANNERS_ENABLED plugin variable, default on). When
        # banners are turned off, actively clear any we placed — RemoveBannerAlert is
        # idempotent, so as each patient hits a consent/patient event the banner comes
        # off; the admin backfill can sweep the rest at once.
        secrets = getattr(self, "secrets", None) or {}
        if not banners_enabled(secrets.get("CONSENT_BANNERS_ENABLED", "")):
            return [remove_banner_effect(patient_id)]
        # Never show the banner on an inactive or deceased patient. Clear it if the
        # patient is not eligible; becoming active/living again fires PATIENT_UPDATED,
        # which re-adds the banner if a required consent is still missing.
        if not is_eligible_patient(patient_id):
            return [remove_banner_effect(patient_id)]
        if has_incomplete_required(patient_id):
            return [add_banner_effect(patient_id=patient_id)]
        # Active, but no required consent missing: clear any banner we placed.
        # RemoveBannerAlert is idempotent, so this is safe even if none exists.
        return [remove_banner_effect(patient_id)]
