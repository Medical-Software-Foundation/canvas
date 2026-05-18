import arrow
from django.db.models import QuerySet

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.v1.data.task import Task
from logger import log

DEFAULT_THRESHOLD_HOURS = 48
DEFAULT_MAX_BATCH_SIZE = 100
DEFAULT_CRON_SCHEDULE = "0 18 * * *"


class UnsignedNoteReminderTask(CronTask):
    """Creates follow-up tasks for notes that remain unsigned past a configurable threshold."""

    SCHEDULE = DEFAULT_CRON_SCHEDULE

    def execute(self) -> list[Effect]:
        threshold_hours = int(self.secrets.get("THRESHOLD_HOURS", DEFAULT_THRESHOLD_HOURS))
        max_batch = int(self.secrets.get("MAX_BATCH_SIZE", DEFAULT_MAX_BATCH_SIZE))
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
        ).exclude(
            provider__isnull=True,
        ).select_related("patient", "provider").order_by("datetime_of_service")

        if note_types_raw.strip():
            allowed_types = [t.strip() for t in note_types_raw.split(",") if t.strip()]
            unsigned_notes = unsigned_notes.filter(
                note_type_version__name__in=allowed_types,
            )

        total_eligible = unsigned_notes.count()

        # Cap to batch size — process oldest first
        batch = unsigned_notes[:max_batch]
        batch_list = list(batch)

        # Bulk check for existing open reminders to avoid N+1
        existing_titles = self._get_existing_reminder_titles(batch_list)

        effects: list[Effect] = []

        for note in batch_list:
            title = self._build_title(note)
            if title in existing_titles:
                continue

            task = AddTask(
                assignee_id=str(note.provider.id),
                patient_id=str(note.patient.id),
                title=title,
                due=arrow.utcnow().datetime,
                status=TaskStatus.OPEN,
                labels=["unsigned-note-reminder"],
            )
            effects.append(task.apply())

        log.info(
            f"[UnsignedNoteReminderTask] "
            f"{total_eligible} eligible unsigned notes, "
            f"processed batch of {len(batch_list)}, "
            f"created {len(effects)} reminder tasks"
        )

        return effects

    def _build_title(self, note: Note) -> str:
        patient_name = f"{note.patient.first_name} {note.patient.last_name}"
        note_date = note.datetime_of_service.strftime("%Y-%m-%d")
        return f"Sign note for {patient_name} from {note_date}"

    def _get_existing_reminder_titles(self, notes: list[Note]) -> set[str]:
        """Bulk-fetch existing open reminder task titles for the given notes."""
        if not notes:
            return set()

        # Collect all (patient, provider) pairs from the batch
        patient_ids = {note.patient.dbid for note in notes}
        provider_ids = {note.provider.dbid for note in notes}

        existing_tasks: QuerySet[Task] = Task.objects.filter(
            patient__dbid__in=patient_ids,
            assignee__dbid__in=provider_ids,
            status=TaskStatus.OPEN,
            title__startswith="Sign note for",
        ).values_list("title", flat=True)

        return set(existing_tasks)
