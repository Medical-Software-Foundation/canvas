from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.v1.data.claim import ClaimQueue, ClaimQueues
from canvas_sdk.handlers import BaseHandler
from logger import log
from candid.effect_helpers import schedule_async_post

SUBMISSION_QUEUE = ClaimQueues.QUEUED_FOR_SUBMISSION
SYNC_TRIGGER_QUEUES = {ClaimQueues.PATIENT_BALANCE}
GRACE_PERIOD_SECONDS = 60


class OnClaimQueueMoved(BaseHandler):
    """Handle claim queue moves for Candid integration.

    - **QueuedForSubmission**: Asynchronously dispatch a submission to Candid via the
      plugin's ``/submit`` SimpleAPI route after a ``GRACE_PERIOD_SECONDS`` delay
      (60s). During that window the user can move the claim out of the queue;
      the submit handler's queue re-check will then skip the submission.
    - **PatientBalance**: Asynchronously dispatch to ``/sync-patient-payments`` to pull
      patient payments from Candid for this claim.
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

    def _schedule_async_post(self, path: str, delay_seconds: int) -> list[Effect]:
        return [
            schedule_async_post(
                self.environment,
                self.secrets,
                path,
                {"claim_id": str(self.event.target.id)},
                delay_seconds=delay_seconds,
            )
        ]

    def _schedule_submission(self) -> list[Effect]:
        """Schedule a delayed claim submission to Candid."""
        log.info(
            f"Candid plugin: scheduling submission check for claim "
            f"{self.event.target.id} in {GRACE_PERIOD_SECONDS}s"
        )
        return self._schedule_async_post("submit", GRACE_PERIOD_SECONDS)

    def _schedule_patient_payment_sync(self) -> list[Effect]:
        """Schedule an async patient payment sync when claim enters Patient Balance."""
        log.info(
            f"Candid plugin: scheduling patient payment sync for claim "
            f"{self.event.target.id}"
        )
        return self._schedule_async_post("sync-patient-payments", 0)
