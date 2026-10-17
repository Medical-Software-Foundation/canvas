from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from logger import log
from patient_numbering.models import PatientProxy
from patient_numbering.numbering import assign_number, backfill_complete, number_effects


class NumberNewPatient(BaseHandler):
    """Give each newly created patient the next number."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CREATED)

    def compute(self) -> list[Effect]:
        """Assign the next number, unless the backfill of existing patients is still pending."""
        # Until the backfill finishes, leave new patients to it. It numbers in creation
        # order, so a patient created mid-backfill still gets the right place in line.
        if not backfill_complete():
            log.info(f"patient_numbering: backfill pending, skipping patient {self.event.target.id}")
            return []

        patient = PatientProxy.objects.filter(id=self.event.target.id).first()
        if patient is None:
            log.warning(f"patient_numbering: patient {self.event.target.id} not found")
            return []
        number, newly_assigned = assign_number(patient)
        if not newly_assigned:
            return []

        log.info(f"patient_numbering: assigned {number} to patient {self.event.target.id}")
        return number_effects(self.event.target.id, number)
