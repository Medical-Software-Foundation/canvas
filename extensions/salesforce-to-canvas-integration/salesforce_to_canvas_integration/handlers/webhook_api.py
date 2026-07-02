"""Inbound webhook endpoint, accepts the Salesforce deliberate sync callout.

Shared verify, parse, dedup, capture, and ack live in
:mod:`salesforce_to_canvas_integration.handlers.webhook_base`. This module
declares the single leaf handler. ``SalesforceWebhookSync`` exposes the one
canonical sync URL.

The Salesforce Contact carries one Canvas Sync field whose value sets the body
``intent``, Sync to ``sync`` and Delete to ``delete``, and the plugin derives
create, modify, or delete from that intent and the record's link state. This
replaces the three per action routes, create, modify, and delete, that the URL
used to carry. See journal cnv-938/001 and cnv-938/002.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import api

from salesforce_to_canvas_integration.handlers.webhook_base import (
    SalesforceWebhookBase,
)


class SalesforceWebhookSync(SalesforceWebhookBase):
    """Capture one deliberate Salesforce sync event as an audit row.

    ``/webhooks/patient/sync`` is the single inbound URL. The body carries a top
    level ``intent``, either ``sync`` or ``delete``, and a ``record`` object that
    holds the Salesforce Id and the mapped fields. A ``delete`` intent is
    captured as a delete action. A ``sync`` intent is captured as a modify when
    the Salesforce Id is already linked to a Canvas patient and as a create when
    it is not, so the action label the admin console already buckets on stays
    create, modify, or delete.

    The plugin does not write to Canvas at ingestion. The row lands in the admin
    audit table where the operator resolves it. See journal cnv-938/001.
    """

    @api.post("/webhooks/patient/sync")
    def sync_route(self) -> list[Response | Effect]:
        return self._handle_sync()
