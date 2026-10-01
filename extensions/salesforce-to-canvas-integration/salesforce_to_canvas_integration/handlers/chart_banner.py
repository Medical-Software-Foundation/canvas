"""Patient chart banner that links to the linked Salesforce record.

The banner shows under the patient name on the chart, the ``Placement.CHART``
slot, for any patient carrying the ``salesforce`` external identifier the sync
writes. Its ``href`` is the same record URL the admin Synced tab Salesforce
column builds, from the live org ``instance_url`` and the stored record id, so
the two surfaces cannot drift. The header action button slot does not render in
this Canvas build, see journal cnv-928/019, so the banner is the surface that
actually paints under the name and is not tied to any clinical section.

The handler emits one banner per linked patient. On ``PLUGIN_CREATED`` and
``PLUGIN_UPDATED`` it backfills and refreshes every linked patient, which seeds
existing links and keeps the stored href current against an org domain rename on
each reinstall. On ``PATIENT_CREATED`` and ``PATIENT_UPDATED`` it handles the
single patient that just changed, so a newly linked patient gets the banner at
link time without waiting for a redeploy.
"""

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.patient import Patient

from logger import log

from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)
from salesforce_to_canvas_integration.services.salesforce_links import (
    build_salesforce_record_url,
)
from salesforce_to_canvas_integration.services.storage import TokenStore

BANNER_KEY = "salesforce-record"
BANNER_NARRATIVE = "Open linked Salesforce record"

_PATIENT_EVENTS = (EventType.PATIENT_CREATED, EventType.PATIENT_UPDATED)


class SalesforceChartBanner(BaseHandler):
    """Maintain the Salesforce record link banner on linked patient charts."""

    RESPONDS_TO = [
        EventType.Name(EventType.PLUGIN_CREATED),
        EventType.Name(EventType.PLUGIN_UPDATED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    def _instance_url(self) -> str:
        """Return the org base, live token first, then the secret fallback."""
        tokens = TokenStore(get_cache()).load()
        return (tokens.instance_url if tokens else "") or (
            self.secrets.get("SF_INSTANCE_URL") or ""
        ).strip().rstrip("/")

    def _source_object(self, external_id: str) -> str:
        """Recover the source object from the newest captured event for the record."""
        newest = (
            IncomingPatientRecord.objects.filter(external_id=external_id)
            .order_by("-received_at")
            .first()
        )
        if newest is None:
            return ""
        return newest.source_object or ""

    def _banner(
        self, patient_id: str, external_id: str, instance_url: str
    ) -> Effect | None:
        """Build the chart banner for a linked patient, or None when no URL."""
        url = build_salesforce_record_url(
            instance_url, external_id, self._source_object(external_id)
        )
        if not url:
            return None
        return AddBannerAlert(
            patient_id=patient_id,
            key=BANNER_KEY,
            narrative=BANNER_NARRATIVE,
            placement=[AddBannerAlert.Placement.CHART],
            intent=AddBannerAlert.Intent.INFO,
            href=url,
        ).apply()

    def compute(self) -> list[Effect]:
        """Emit the banner for the affected patient, or backfill all on plugin events."""
        instance_url = self._instance_url()

        if self.event.type in _PATIENT_EVENTS:
            patient_id = self.event.target.id
            if not patient_id:
                return []
            external_id = (
                Patient.objects.filter(
                    id=patient_id,
                    external_identifiers__system=SALESFORCE_IDENTIFIER_SYSTEM,
                )
                .values_list("external_identifiers__value", flat=True)
                .first()
            )
            if not external_id:
                return []
            effect = self._banner(str(patient_id), str(external_id), instance_url)
            return [effect] if effect is not None else []

        # Plugin created or updated, backfill and refresh every linked patient.
        rows = (
            Patient.objects.filter(
                external_identifiers__system=SALESFORCE_IDENTIFIER_SYSTEM
            )
            .values_list("id", "external_identifiers__value")
            .distinct()
        )
        effects: list[Effect] = []
        for patient_id, external_id in rows:
            if not external_id:
                continue
            effect = self._banner(str(patient_id), str(external_id), instance_url)
            if effect is not None:
                effects.append(effect)
        log.info(
            "SalesforceChartBanner backfilled %d linked patient banners"
            % len(effects)
        )
        return effects
