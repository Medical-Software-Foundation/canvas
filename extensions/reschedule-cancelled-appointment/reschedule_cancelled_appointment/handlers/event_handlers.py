import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.team import Team
from logger import log

#: Secret holding the exact name of the Team that reschedule tasks should be
#: assigned to. If unset/blank or no team matches, the task falls back to the
#: appointment's provider.
SCHEDULING_TEAM_NAME_SECRET = "SCHEDULING_TEAM_NAME"

#: Number of days from cancellation until the reschedule task is due.
RESCHEDULE_DUE_DAYS = 1

#: Label applied to every reschedule task so they can be filtered in the UI.
RESCHEDULE_LABEL = "Reschedule"


class RescheduleCancelledAppointmentHandler(BaseHandler):
    """Create a reschedule task when an appointment is cancelled.

    The task is routed to a scheduling team (configured by name via the
    ``SCHEDULING_TEAM_NAME`` secret) when one is found, otherwise to the
    appointment's provider.
    """

    RESPONDS_TO = [EventType.Name(EventType.APPOINTMENT_CANCELED)]

    def compute(self) -> list[Effect]:
        """Build a reschedule task for the cancelled appointment."""
        appointment_id = self.event.target.id
        try:
            appointment = Appointment.objects.select_related("provider", "patient").get(
                id=appointment_id
            )
        except Appointment.DoesNotExist:
            # The event implies the appointment exists; log defensively and bail
            # rather than raising on a record we can no longer read.
            log.warning(
                "RescheduleCancelledAppointment: appointment %s not found",
                appointment_id,
            )
            return []

        # Skip records that were retracted (entered in error).
        if appointment.entered_in_error_id is not None:
            return []

        # Skip cancellations of appointments that have already started/passed —
        # there is nothing to reschedule.
        now = arrow.utcnow().datetime
        if appointment.start_time is None or appointment.start_time <= now:
            return []

        task_kwargs: dict = {
            "patient_id": str(appointment.patient.id) if appointment.patient else None,
            "title": self._task_title(appointment),
            "due": arrow.utcnow().shift(days=RESCHEDULE_DUE_DAYS).datetime,
            "status": TaskStatus.OPEN,
            "labels": [RESCHEDULE_LABEL],
        }

        assignment = self._resolve_assignment(appointment)
        task_kwargs.update(assignment)

        return [AddTask(**task_kwargs).apply()]

    def _resolve_assignment(self, appointment: Appointment) -> dict:
        """Decide who the reschedule task goes to.

        Returns a dict with ``team_id`` (scheduling team), ``assignee_id``
        (appointment provider), or neither (unassigned, last resort).
        """
        team = self._scheduling_team()
        if team is not None:
            return {"team_id": str(team.id)}

        if appointment.provider is not None:
            return {"assignee_id": str(appointment.provider.id)}

        # Appointments always have a provider in practice; this guards against
        # silently dropping the work if that ever isn't true.
        log.warning(
            "RescheduleCancelledAppointment: appointment %s has no scheduling team "
            "or provider; creating an unassigned reschedule task",
            appointment.id,
        )
        return {}

    def _scheduling_team(self) -> Team | None:
        """Look up the configured scheduling team by name, if any."""
        team_name = (self.secrets.get(SCHEDULING_TEAM_NAME_SECRET) or "").strip()
        if not team_name:
            return None

        team = Team.objects.filter(name__iexact=team_name).first()
        if team is None:
            log.warning(
                "RescheduleCancelledAppointment: no team named %r found; "
                "falling back to the appointment provider",
                team_name,
            )
        return team

    @staticmethod
    def _task_title(appointment: Appointment) -> str:
        """Human-readable task title referencing the original appointment time."""
        original = arrow.get(appointment.start_time).format("MMM D, YYYY h:mm A")
        return f"Reschedule cancelled appointment (originally {original} UTC)"
