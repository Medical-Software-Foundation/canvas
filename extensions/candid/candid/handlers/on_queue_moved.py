import json

from canvas_sdk.effects import Effect
from canvas_sdk.effects.http_request import HttpRequestEffect
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.claim import ClaimQueue, ClaimQueues
from canvas_sdk.handlers import BaseHandler
from logger import log

SUBMISSION_QUEUE = ClaimQueues.QUEUED_FOR_SUBMISSION
SYNC_TRIGGER_QUEUES = {ClaimQueues.PATIENT_BALANCE}
GRACE_PERIOD_SECONDS = 60


class OnClaimQueueMoved(BaseHandler):
    """Handle claim queue moves for Candid integration.

    - **QueuedForSubmission**: Schedule a delayed submission to Candid (60s grace period).
    - **Patient Responsibility** (or other sync triggers): Pull adjudication data from Candid.
    """

    RESPONDS_TO = EventType.Name(EventType.CLAIM_QUEUE_MOVED)

    def compute(self) -> list[Effect]:
        queue_entered_id = self.event.context.get("queue_entered", {}).get("id")
        if not queue_entered_id:
            return []

        queue_sort_ordering = (
            ClaimQueue.objects.values_list("queue_sort_ordering", flat=True)
            .filter(id=queue_entered_id)
            .first()
        )
        if queue_sort_ordering == SUBMISSION_QUEUE:
            return self._schedule_submission()

        if queue_sort_ordering in SYNC_TRIGGER_QUEUES:
            return self._schedule_patient_payment_sync()

        return []

    def _get_instance_url(self) -> str:
        customer_id = self.environment.get("CUSTOMER_IDENTIFIER", "")
        return f"https://{customer_id}.canvasmedical.com"

    def _schedule_submission(self) -> list[Effect]:
        """Schedule a delayed claim submission to Candid."""
        claim_id = str(self.event.target.id)
        instance_url = self._get_instance_url()

        log.info(
            f"Candid plugin: scheduling submission check for claim {claim_id} "
            f"in {GRACE_PERIOD_SECONDS}s"
        )

        return [
            HttpRequestEffect(
                url=f"{instance_url}/plugin-io/api/candid/submit",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self.secrets["CANDID_CLIENT_SECRET"],
                },
                body=json.dumps({"claim_id": claim_id}),
            )
            .apply()
            .set_async(delay_seconds=GRACE_PERIOD_SECONDS),
        ]

    def _schedule_patient_payment_sync(self) -> list[Effect]:
        """Schedule an async patient payment sync when claim enters Patient Balance."""
        claim_id = str(self.event.target.id)
        instance_url = self._get_instance_url()

        log.info(f"Candid plugin: scheduling patient payment sync for claim {claim_id}")

        return [
            HttpRequestEffect(
                url=f"{instance_url}/plugin-io/api/candid/sync-patient-payments",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self.secrets["CANDID_CLIENT_SECRET"],
                },
                body=json.dumps({"claim_id": claim_id}),
            )
            .apply()
            .set_async(delay_seconds=0),
        ]
