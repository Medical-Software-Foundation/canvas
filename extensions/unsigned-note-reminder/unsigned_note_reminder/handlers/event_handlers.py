import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.task import Task
from logger import log

DEFAULT_THRESHOLD_HOURS = 48
DEFAULT_CRON_SCHEDULE = "0 18 * * *"


class UnsignedNoteReminderTask(CronTask):
    """Creates follow-up tasks for notes that remain unsigned past a configurable threshold."""

    SCHEDULE = DEFAULT_CRON_SCHEDULE

    def execute(self) -> list[Effect]:
        threshold_hours = int(self.secrets.get("THRESHOLD_HOURS", DEFAULT_THRESHOLD_HOURS))
        note_types_raw = self.secrets.get("NOTE_TYPES", "")

        cutoff = arrow.utcnow().shift(hours=-threshold_hours).datetime

        # Find notes that are NOT locked (i.e., unsigned) and older than the threshold
        locked_note_ids = CurrentNoteStateEvent.objects.filter(
            state=NoteStates.LOCKED,
        ).values_list("note_id", flat=True)

        unsigned_notes = Note.objects.filter(
            datetime_of_service__lte=cutoff,
        ).exclude(
            dbid__in=locked_note_ids,
        ).select_related("patient", "provider")

        if note_types_raw.strip():
            allowed_types = [t.strip() for t in note_types_raw.split(",") if t.strip()]
            unsigned_notes = unsigned_notes.filter(
                note_type_version__name__in=allowed_types,
            )

        # Filter to notes with an active provider
        unsigned_notes = unsigned_notes.exclude(provider__isnull=True)

        effects: list[Effect] = []

        for note in unsigned_notes:
            if self._reminder_exists(note):
                continue

            patient_name = f"{note.patient.first_name} {note.patient.last_name}"
            note_date = note.datetime_of_service.strftime("%Y-%m-%d")

            task = AddTask(
                assignee_id=str(note.provider.id),
                patient_id=str(note.patient.id),
                title=f"Sign note for {patient_name} from {note_date}",
                due=arrow.utcnow().datetime,
                status=TaskStatus.OPEN,
                labels=["unsigned-note-reminder"],
            )
            effects.append(task.apply())

        log.info(
            f"[UnsignedNoteReminderTask] Found {unsigned_notes.count()} unsigned notes, "
            f"created {len(effects)} reminder tasks"
        )

        return effects

    def _reminder_exists(self, note: Note) -> bool:
        """Check if an open reminder task already exists for this note's patient + provider combo."""
        return bool(Task.objects.filter(
            patient=note.patient,
            assignee=note.provider,
            status=TaskStatus.OPEN,
            title__startswith=f"Sign note for {note.patient.first_name} {note.patient.last_name} from {note.datetime_of_service.strftime('%Y-%m-%d')}",
        ).exists())
