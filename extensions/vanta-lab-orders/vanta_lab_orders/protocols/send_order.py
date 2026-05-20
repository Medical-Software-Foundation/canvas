"""Protocol: send a signed Vanta lab order to LKCareEvolve (ELLKAY).

Listens for LAB_ORDER_COMMAND__POST_COMMIT. Filters to the Vanta lab partner
only (silent no-op for all other partners). Builds the ELLKAY Orders JSON v2.2
payload and POSTs it to LKCareEvolve.

Out-of-scope (v1):
    - TODO: Add CancelVantaOrder protocol for LAB_ORDER_COMMAND__POST_DELETE and
      LAB_ORDER_COMMAND__POST_ENTER_IN_ERROR once ELLKAY confirms the cancel
      envelope contract for LKCareEvolve.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.lab import LabOrder
from logger import log

from vanta_lab_orders.lkcareevolve_client import post_order
from vanta_lab_orders.payload import build_order_payload
from vanta_lab_orders.settings import (
    lkcareevolve_api_key,
    lkcareevolve_base_url,
    vanta_lab_partner_name,
)


class SendVantaOrder(BaseHandler):
    """Send a committed Vanta lab order to LKCareEvolve via ELLKAY Orders JSON v2.2."""

    RESPONDS_TO = EventType.Name(EventType.LAB_ORDER_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        """Build and POST the ELLKAY order payload to LKCareEvolve.

        Returns:
            Empty list — this handler's side-effect is the outbound HTTP POST.
        """
        context = self.event.context

        # Extract lab_partner info from event context to filter cheaply
        # before loading the full LabOrder from the DB.
        lab_partner_dict = context.get("fields", {}).get("lab_partner") or {}
        # Canvas emits lab_partner as a select-option dict with 'text' holding
        # the partner's display name (also mirrored in 'value').
        partner_name_in_event: str = lab_partner_dict.get("text", "") or ""

        expected_partner = vanta_lab_partner_name(self.secrets)

        if partner_name_in_event != expected_partner:
            # Not a Vanta order — silent no-op.
            return []

        # Resolve the LabOrder. The Canvas data module has no FK between
        # Command and LabOrder, so we identify the order as the most
        # recently signed (committer set) LabOrder on this note for this
        # patient. POST_COMMIT fires synchronously with signing, so the
        # newest committed order on the note is the one we just committed.
        note_uuid: str = context["note"]["uuid"]
        patient_id: str = context["patient"]["id"]

        lab_order = (
            LabOrder.objects.select_related(
                "patient",
                "note__location",
                "ordering_provider",
            )
            # `_build_insurances` and `_build_diagnoses` issue their own
            # filtered queries against coverages and reasons; prefetching
            # those at the root would be wasted (Django invalidates the
            # cache when the related manager is re-filtered).
            .prefetch_related(
                "patient__addresses",
                "patient__telecom",
                "tests",
            )
            .filter(
                note__id=note_uuid,
                patient__id=patient_id,
                deleted=False,
                committer__isnull=False,
            )
            .order_by("-modified")
            .first()
        )
        if lab_order is None:
            log.error(
                f"[vanta_lab_orders] No signed LabOrder found for "
                f"note_uuid={note_uuid} patient_id={patient_id}"
            )
            return []

        note = lab_order.note
        location_id = str(note.location.id) if (note and note.location) else "unknown"
        test_count = lab_order.tests.count()

        log.info(
            "[vanta_lab_orders] Sending lab order to LKCareEvolve: "
            f"order_id={lab_order.id} patient_id={patient_id} "
            f"location_id={location_id} test_count={test_count}"
        )

        order_payload = build_order_payload(lab_order, self.secrets)

        base_url = lkcareevolve_base_url(self.secrets)
        api_key = lkcareevolve_api_key(self.secrets)

        response = post_order(order_payload, base_url, api_key)

        log.info(
            "[vanta_lab_orders] LKCareEvolve accepted order: "
            f"order_id={lab_order.id} http_status={response.status_code}"
        )

        return []
