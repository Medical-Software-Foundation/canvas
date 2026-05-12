"""Forward PATIENT_PAYMENT_PROCESSED events to the /report-payment endpoint."""

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log

from candid.effect_helpers import schedule_async_post


class OnPatientPaymentProcessed(BaseHandler):
    """Report a patient payment to Candid when it is processed in Canvas."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_PAYMENT_PROCESSED)

    def compute(self) -> list[Effect]:
        log.info("Candid plugin: dispatching payment report")
        return [
            schedule_async_post(
                self.environment,
                self.secrets,
                "report-payment",
                self.event.context,
            )
        ]
