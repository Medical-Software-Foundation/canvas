"""Write the new Canvas patient id back to the linked Salesforce record.

A create is a Canvas effect, so the new patient id does not exist at webhook
time. It only becomes knowable when Canvas emits ``PATIENT_CREATED`` for the
landed patient, which is the seam this handler rides. On that event, for a
patient carrying the ``salesforce`` external identifier the sync writes, the
handler PATCHes ``Canvas_Patient_ID__c`` on the Salesforce record over the
stored OAuth connection, closing the link so the Salesforce contact shows the
Canvas patient id.

The writeback is outbound HTTP, not a Canvas effect, so ``compute`` returns no
effects. A patient with no salesforce identifier is not ours and is ignored. A
missing OAuth connection or any Salesforce failure degrades to a logged skip,
patient creation is never broken by a writeback failure. The local stack does
not deliver ``PATIENT_*`` events to the runner, so this handler loads but does
not fire locally, the same as the chart banner.
"""

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.utils.http import Http
from canvas_sdk.v1.data.patient import Patient

from logger import log

from salesforce_to_canvas_integration.services.config import (
    ConfigError,
    PluginConfig,
    load_config,
)
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)
from salesforce_to_canvas_integration.services.sf_client import (
    SalesforceClient,
    SalesforceError,
)
from salesforce_to_canvas_integration.services.storage import TokenStore


class SalesforceCanvasIdWriteback(BaseHandler):
    """Push the Canvas patient id onto the linked Salesforce record on create."""

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
    ]

    def _build_client(self, config: PluginConfig) -> SalesforceClient:
        """Construct the Salesforce client. A seam tests override.

        Mirrors the status API and webhook client seams so tests swap a fake
        client without monkey patching the SDK ``Http`` import or the cache.
        """
        return SalesforceClient(
            http=Http(),
            tokens=TokenStore(get_cache()),
            login_url=config.login_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )

    def _linked_salesforce_id(self, patient_id: str) -> str:
        """Return the salesforce external id on the patient, or empty when none.

        ``PATIENT_CREATED`` fires for every patient created in Canvas, so the
        reverse lookup is what scopes the handler to sync created patients. The
        create effect writes the identifier in the same effect that lands the
        patient, so it is present when the event fires, the same seam the chart
        banner relies on.
        """
        external_id = (
            Patient.objects.filter(
                id=patient_id,
                external_identifiers__system=SALESFORCE_IDENTIFIER_SYSTEM,
            )
            .values_list("external_identifiers__value", flat=True)
            .first()
        )
        return str(external_id) if external_id else ""

    def compute(self) -> list[Effect]:
        """Write the Canvas id back to Salesforce for a freshly linked patient."""
        patient_id = self.event.target.id
        if not patient_id:
            return []

        sf_record_id = self._linked_salesforce_id(str(patient_id))
        if not sf_record_id:
            return []

        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            log.warning(
                "Salesforce writeback skipped, config error patient=%s err=%s",
                patient_id,
                exc,
            )
            return []

        try:
            client = self._build_client(config)
            client.write_canvas_id(
                sobject=config.source_sobject,
                sf_record_id=sf_record_id,
                canvas_patient_id=str(patient_id),
            )
        except SalesforceError as exc:
            # Not connected and reconnect required both subclass SalesforceError,
            # alongside a failed PATCH. A disconnected plugin is the common case
            # before an admin connects through the Settings tab, so this is the
            # expected quiet path, logged at info, not an error.
            log.info(
                "Salesforce writeback skipped patient=%s record=%s reason=%s",
                patient_id,
                sf_record_id,
                exc,
            )
            return []

        log.info(
            "Salesforce writeback wrote canvas id patient=%s record=%s sobject=%s",
            patient_id,
            sf_record_id,
            config.source_sobject,
        )
        return []
