import uuid
from datetime import datetime

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.task import TaskLabel
from canvas_sdk.v1.data.team import Team
from logger import log

#: Secret holding the exact name of the Team that reschedule tasks should be
#: assigned to. If unset/blank or no team matches, the task falls back to the
#: appointment's provider.
SCHEDULING_TEAM_NAME_SECRET = "SCHEDULING_TEAM_NAME"

#: Number of days from cancellation until the reschedule task is due.
RESCHEDULE_DUE_DAYS = 1

#: Label added to the reschedule task — but only when a label of this name
#: already exists in the instance. We never create a new label.
RESCHEDULE_LABEL = "Reschedule"

#: Schema key of the Reason For Visit command in a note.
REASON_FOR_VISIT_SCHEMA_KEY = "reasonForVisit"

#: Environment key holding the instance's configured IANA timezone name
#: (e.g. "America/Los_Angeles"), used to display appointment times. Falls back
#: to UTC when unset or invalid.
INSTALLATION_TIME_ZONE_ENV = "INSTALLATION_TIME_ZONE"
DEFAULT_TIMEZONE = "UTC"


class RescheduleCancelledAppointmentHandler(BaseHandler):
    """Create a reschedule task when an appointment is cancelled.

    The task is routed to a scheduling team (configured by name via the
    ``SCHEDULING_TEAM_NAME`` secret) when one is found, otherwise to the
    appointment's provider. A comment summarising the original appointment
    (reason for visit, provider, date/time, location, note type) is attached.
    """

    RESPONDS_TO = [EventType.Name(EventType.APPOINTMENT_CANCELED)]

    def compute(self) -> list[Effect]:
        """Build a reschedule task (and summary comment) for the cancellation."""
        appointment_id = self.event.target.id
        try:
            appointment = Appointment.objects.select_related(
                "provider", "patient", "location", "note_type"
            ).get(id=appointment_id)
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

        tz = self._timezone()
        task_id = str(uuid.uuid4())
        task_kwargs: dict = {
            "id": task_id,
            "patient_id": str(appointment.patient.id) if appointment.patient else None,
            "title": self._task_title(appointment, tz),
            "due": arrow.utcnow().shift(days=RESCHEDULE_DUE_DAYS).datetime,
            "status": TaskStatus.OPEN,
            "labels": self._labels(appointment),
        }
        task_kwargs.update(self._resolve_assignment(appointment))

        comment = AddTaskComment(
            task_id=task_id, body=self._comment_body(appointment, tz)
        )

        return [AddTask(**task_kwargs).apply(), comment.apply()]

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
    def _labels(appointment: Appointment) -> list[str]:
        """Labels for the reschedule task.

        Inherits the cancelled appointment's existing (active) labels and adds
        the ``Reschedule`` label only when a label of that name already exists
        in the instance — we never create a new label.
        """
        labels: list[str] = list(
            appointment.labels.filter(active=True).values_list("name", flat=True)
        )

        already_present = {name.casefold() for name in labels}
        if (
            RESCHEDULE_LABEL.casefold() not in already_present
            and TaskLabel.objects.filter(
                name__iexact=RESCHEDULE_LABEL, active=True
            ).exists()
        ):
            labels.append(RESCHEDULE_LABEL)

        return labels

    def _comment_body(self, appointment: Appointment, tz: str) -> str:
        """A summary of the original appointment for the reschedule task."""
        provider = appointment.provider.full_name if appointment.provider else "Unknown"
        when = self._format_local(appointment.start_time, tz)
        location = (
            appointment.location.full_name if appointment.location else "Not specified"
        )
        note_type = (
            appointment.note_type.name if appointment.note_type else "Not specified"
        )

        return (
            "Appointment cancelled — reschedule needed.\n"
            f"Reason for visit: {self._reason_for_visit(appointment)}\n"
            f"Provider: {provider}\n"
            f"Date/time: {when}\n"
            f"Location: {location}\n"
            f"Note type: {note_type}"
        )

    @classmethod
    def _reason_for_visit(cls, appointment: Appointment) -> str:
        """Best-effort reason for visit for the cancelled appointment.

        Prefers the Reason For Visit command on the appointment's
        note, then the appointment's free-text comment, then a placeholder.
        """
        if appointment.note_id is not None:
            data = (
                Command.objects.filter(
                    note_id=appointment.note_id,
                    schema_key=REASON_FOR_VISIT_SCHEMA_KEY,
                    entered_in_error__isnull=True,
                    state="staged",
                )
                .order_by("-dbid")
                .values_list("data", flat=True)
                .first()
            )
            text = cls._rfv_text(data) if data else ""
            if text:
                return text

        comment = str(appointment.comment or "").strip()
        if comment:
            return comment

        return "Not documented"

    @staticmethod
    def _rfv_text(data: dict) -> str:
        """Extract the reason text from a Reason For Visit command's data."""
        coding = data.get("coding")
        if isinstance(coding, dict) and coding.get("text"):
            return str(coding["text"]).strip()

        comment = data.get("comment")
        if comment:
            return str(comment).strip()

        return ""

    def _task_title(self, appointment: Appointment, tz: str) -> str:
        """Human-readable task title referencing the original appointment time."""
        original = self._format_local(appointment.start_time, tz)
        return f"Reschedule cancelled appointment (originally {original})"

    def _timezone(self) -> str:
        """The instance timezone (IANA name) from the environment, or UTC.

        Validated via arrow; an unknown/malformed name raises a subclass of
        ``ValueError`` (``arrow.parser.ParserError``) or ``KeyError``
        (``zoneinfo.ZoneInfoNotFoundError``), which we treat as "use UTC".
        """
        tz_name = (
            self.environment.get(INSTALLATION_TIME_ZONE_ENV) or ""
        ).strip() or DEFAULT_TIMEZONE
        try:
            arrow.utcnow().to(tz_name)
        except (ValueError, KeyError):
            log.warning(
                "RescheduleCancelledAppointment: invalid timezone %r; using %s",
                tz_name,
                DEFAULT_TIMEZONE,
            )
            return DEFAULT_TIMEZONE
        return tz_name

    @staticmethod
    def _format_local(dt: datetime, tz: str) -> str:
        """Format a datetime in the given IANA timezone, with its abbreviation."""
        return arrow.get(dt).to(tz).format("MMM D, YYYY h:mm A ZZZ")
