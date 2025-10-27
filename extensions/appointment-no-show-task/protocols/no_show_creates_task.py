"""Protocol to create a task for admin team when appointment is marked as no-show."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.team import Team
from logger import log


class NoShowCreatesTask(BaseProtocol):
    """
    Create a Task for admin team when an appointment status changes to 'no-show'.

    This protocol responds to APPOINTMENT_UPDATED events and creates a task
    assigned to the admin team to reschedule the appointment.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_UPDATED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    ]

    def compute(self) -> list[Effect]:
        """
        Check if appointment was marked as no-show and create a task if so.

        Returns:
            list[Effect]: List containing an AddTask effect if status is 'no-show',
                         otherwise an empty list.
        """
        # Log the entire event for debugging
        log.info(f"NoShowCreatesTask: Event received - Type: {self.event.type}")
        log.info(f"NoShowCreatesTask: Event name: {self.event.name}")
        log.info(f"NoShowCreatesTask: Event target: {self.target}")
        log.info(f"NoShowCreatesTask: Event context: {self.context}")

        # Get the appointment ID from the event target
        # Target is a string UUID for APPOINTMENT_NO_SHOWED event
        appointment_id = self.target
        log.info(f"NoShowCreatesTask: Extracted appointment ID: {appointment_id}")

        if not appointment_id:
            log.error("NoShowCreatesTask: No appointment ID found in event target")
            return []

        log.info(f"NoShowCreatesTask: Processing appointment ID: {appointment_id}")

        try:
            # Fetch the appointment to get patient details
            appointment = Appointment.objects.get(id=appointment_id)
            log.info(f"NoShowCreatesTask: Found appointment with status: '{appointment.status}'")
        except Appointment.DoesNotExist:
            log.error(f"NoShowCreatesTask: Appointment {appointment_id} not found")
            return []

        # Since APPOINTMENT_NO_SHOWED event fired, we know it's a no-show
        # No need to check status - the event itself confirms this
        log.info(f"NoShowCreatesTask: Processing no-show appointment {appointment_id}")

        # Get patient information
        patient_id = appointment.patient.id
        patient_name = appointment.patient.first_name + " " + appointment.patient.last_name

        # Get appointment details for task description
        appointment_date = appointment.start_time.strftime("%Y-%m-%d %H:%M")

        # Get the team from plugin secrets
        team_id = None
        team_name = self.secrets.get("TEAM_NAME")

        if not team_name:
            log.error(
                "NoShowCreatesTask: TEAM_NAME secret not configured. "
                "Task will be created without team assignment."
            )
        else:
            try:
                team = Team.objects.get(name=team_name)
                team_id = str(team.id)
                log.info(f"NoShowCreatesTask: Task will be assigned to team '{team_name}' (ID: {team_id})")
            except Team.DoesNotExist:
                log.error(
                    f"NoShowCreatesTask: Team '{team_name}' not found. "
                    "Task will be created without team assignment."
                )

        # Get labels from plugin secrets
        labels_str = self.secrets.get("LABELS", "no-show,reschedule")
        # Parse comma-separated labels and strip whitespace
        labels = [label.strip() for label in labels_str.split(",") if label.strip()]
        log.info(f"NoShowCreatesTask: Task labels: {labels}")

        # Create the task
        task_title = f"Reschedule no-show appointment for {patient_name}"

        log.info(
            f"NoShowCreatesTask: Creating task for patient {patient_id} "
            f"(appointment {appointment_id})"
        )

        effect = AddTask(
            patient_id=patient_id,
            title=task_title,
            team_id=team_id,
            labels=labels,
        )

        return [effect.apply()]
