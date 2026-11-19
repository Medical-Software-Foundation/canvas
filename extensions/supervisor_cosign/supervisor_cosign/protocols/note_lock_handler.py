import random
import uuid
from datetime import datetime, timedelta, time, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import Note, NoteStateChangeEvent, NoteStates
from logger import log

from supervisor_cosign.models.cosign_record import CoSignRecord


class NoteLockHandler(BaseHandler):
    RESPONDS_TO = [EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)]

    def compute(self) -> list[Effect]:
        if not self._is_locked():
            return []

        note_id = self.context.get("note_id")
        if not note_id:
            log.info("supervisor_cosign: no note_id in context, skipping")
            return []

        note = (
            Note.objects
            .select_related("provider", "provider__default_supervising_provider", "patient")
            .filter(id=note_id)
            .first()
        )
        if note is None:
            log.info(f"supervisor_cosign: note {note_id} not found, skipping")
            return []
        provider = note.provider
        if not provider:
            log.info(f"supervisor_cosign: note {note_id} has no provider, skipping")
            return []

        provider_name = f"{provider.first_name} {provider.last_name}"
        supervisor = provider.default_supervising_provider
        if not supervisor:
            log.info(
                f"supervisor_cosign: provider {provider_name} (id={provider.id}) "
                f"has no default_supervising_provider set, skipping"
            )
            return []

        log.info(
            f"supervisor_cosign: provider {provider_name} has supervisor "
            f"{supervisor.first_name} {supervisor.last_name} (id={supervisor.id}), creating task"
        )

        # Dedup: only one cosign cycle per note. Re-locks (e.g. after our own addendum
        # unlock+relock, or supervisor edits) must not spawn additional pending records.
        if CoSignRecord.objects.filter(note_id=note_id).exists():
            log.info(f"supervisor_cosign: cosign record already exists for note {note_id}, skipping")
            return []

        percentage = self._sample_percentage()
        if random.uniform(0, 100) > percentage:
            return []

        due_date = (datetime.now(timezone.utc) + timedelta(days=3)).date()
        patient = note.patient
        patient_id = str(patient.id) if patient else None
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else "patient"
        note_date = note.datetime_of_service.strftime("%Y-%m-%d") if note.datetime_of_service else "unknown date"

        task_id = str(uuid.uuid4())
        CoSignRecord(
            note_id=note_id,
            supervisee_id=str(provider.id),
            supervisor_id=str(supervisor.id),
            task_id=task_id,
            status="pending",
            due_date=due_date,
        ).save()

        task = AddTask(
            id=task_id,
            title=f"Co-sign review: note {note_date} for {patient_name}",
            patient_id=patient_id,
            assignee_id=str(supervisor.id),
            due=datetime.combine(due_date, time(0, 0, 0), tzinfo=timezone.utc),
            status=TaskStatus.OPEN,
            labels=["cosign"],
        )
        return [task.apply()]

    def _is_locked(self) -> bool:
        # filter().first() rather than get(): NOTE_STATE_CHANGE_EVENT_CREATED is high-frequency
        # and a missing row (deleted target, replayed event) would otherwise raise DoesNotExist
        # and abort compute() with an unhandled exception.
        state = (
            NoteStateChangeEvent.objects
            .filter(id=self.event.target.id)
            .values_list("state", flat=True)
            .first()
        )
        return state == NoteStates.LOCKED

    def _sample_percentage(self) -> float:
        raw = self.secrets.get("SAMPLE_PERCENTAGE", "100")
        try:
            pct = float(raw)
        except ValueError:
            return 100.0
        return max(0.0, min(100.0, pct))
