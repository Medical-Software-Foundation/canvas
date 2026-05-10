from uuid import uuid4

import arrow
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.prescription import Prescription
from logger import log


class RxErrorNotificationHandler(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PRESCRIPTION_ERRORED)

    def _get_medication_name(self, prescription):
        """Get the medication display name from codings."""
        if not prescription.medication:
            return "Unknown Medication"
        try:
            coding = prescription.medication.codings.first()
            if coding and coding.display:
                return coding.display
        except Exception:
            pass
        return "Unknown Medication"

    def compute(self) -> list:
        try:
            prescription = Prescription.objects.select_related(
                "prescriber", "patient", "medication"
            ).get(id=self.target)

            patient = prescription.patient
            prescriber = prescription.prescriber

            if not patient or not prescriber:
                log.warning(
                    f"Prescription {self.target} missing patient or prescriber"
                )
                return []

            patient_name = f"{patient.first_name} {patient.last_name}"
            medication_name = self._get_medication_name(prescription)

            task_title = f"RX ERROR {patient_name} - {medication_name}"

            # Build detail lines for the task comment
            details = []
            if medication_name != "Unknown Medication":
                details.append(f"Medication: {medication_name}")
            if prescription.sig_original_input:
                details.append(f"Sig: {prescription.sig_original_input}")
            if prescription.dose_quantity:
                details.append(f"Dose Quantity: {prescription.dose_quantity}")
            if prescription.dispense_quantity:
                details.append(
                    f"Dispense Quantity: {prescription.dispense_quantity}"
                )
            if prescription.count_of_refills_allowed is not None:
                details.append(
                    f"Refills: {prescription.count_of_refills_allowed}"
                )
            if prescription.pharmacy_name:
                details.append(f"Pharmacy: {prescription.pharmacy_name}")
            if prescription.error_message:
                details.append(f"Error: {prescription.error_message}")

            task_comment = "\n".join(details)

            # Generate an explicit UUID so we can reference it in the comment
            task_id = str(uuid4())

            add_task = AddTask(
                id=task_id,
                assignee_id=prescriber.id,
                patient_id=patient.id,
                title=task_title,
                due=arrow.utcnow().datetime,
                status=TaskStatus.OPEN,
                labels=["RX-ERROR"],
            )

            effects = [add_task.apply()]

            if task_comment:
                add_comment = AddTaskComment(
                    task_id=task_id,
                    body=task_comment,
                )
                effects.append(add_comment.apply())

            return effects

        except Prescription.DoesNotExist:
            log.error(f"Prescription {self.target} not found")
            return []
        except Exception as e:
            log.error(f"Error handling prescription error event: {e}")
            return []
