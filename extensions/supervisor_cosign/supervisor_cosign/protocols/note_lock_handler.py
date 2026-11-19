import random
import uuid
from datetime import datetime, timedelta, time, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import Note, NoteStateChangeEvent, NoteStates
from logger import log

from supervisor_cosign.helpers.note_links import note_chart_url, summary_note_url
from supervisor_cosign.helpers.note_type_codes import note_type_code_of, note_type_eligible
from supervisor_cosign.models.cosign_record import CoSignRecord


class NoteLockHandler(BaseHandler):
    RESPONDS_TO = [EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)]

    def compute(self) -> list[Effect]:
        if not self._is_locked():
            log.info("supervisor_cosign: note not in LOCKED state, skipping")
            return []

        note_id = self.context.get("note_id")
        if not note_id:
            log.info("supervisor_cosign: no note_id in context, skipping")
            return []

        note = (
            Note.objects
            .select_related(
                "provider",
                "provider__default_supervising_provider",
                "supervising_provider",
                "patient",
                "note_type_version",
            )
            .filter(id=note_id)
            .first()
        )
        if note is None:
            log.info(f"supervisor_cosign: note {note_id} not found, skipping")
            return []

        # Note-type gate first, ahead of the provider and supervisor checks.
        # NOTE_STATE_CHANGE_EVENT_CREATED is high-frequency and every kind of
        # note flows through it, so reasoning about a message note's supervisor
        # only to drop it a moment later fills the log with the wrong lines and
        # buries the one that matters. It is also the cheapest gate here: a
        # string compare against a row select_related already loaded, where
        # dedup below costs a round trip. Unset variable means every type is
        # eligible, so this is a no-op until somebody configures it.
        if not note_type_eligible(note, self.secrets):
            log.info(
                f"supervisor_cosign: note {note_id} type "
                f"{note_type_code_of(note)!r} not in COSIGN_NOTE_TYPE_CODES, skipping"
            )
            return []

        provider = note.provider
        if not provider:
            log.info(f"supervisor_cosign: note {note_id} has no provider, skipping")
            return []

        provider_name = f"{provider.first_name} {provider.last_name}"
        # The supervising provider set on the note wins; the provider's
        # default_supervising_provider is the fallback.
        supervisor = note.supervising_provider
        supervisor_source = "note supervising_provider"
        if not supervisor:
            supervisor = provider.default_supervising_provider
            supervisor_source = "provider default_supervising_provider"
        if not supervisor:
            log.info(
                f"supervisor_cosign: note {note_id} has no supervising_provider and provider "
                f"{provider_name} (id={provider.id}) has no default_supervising_provider set, skipping"
            )
            return []

        log.info(
            f"supervisor_cosign: provider {provider_name} has supervisor "
            f"{supervisor.first_name} {supervisor.last_name} (id={supervisor.id}) "
            f"from {supervisor_source}, creating task"
        )

        # One open cycle per note. A pending record means the co-sign is already owed.
        # With COSIGN_REOPEN_ON_AMEND on, an approved record reopens when the supervisee
        # locks the note again, i.e. amends and re-signs it; re-locks by anyone else (the
        # co-sign chain's own unlock and re-sign, a billing plugin adding a charge) leave
        # it approved. With it off, an approved record is final.
        latest = CoSignRecord.objects.filter(note_id=note_id).order_by("-selected_at").first()
        amended = False
        if latest is not None:
            if (
                latest.status != "approved"
                or not self._reopen_on_amend()
                or not self._locked_by(provider)
            ):
                log.info(f"supervisor_cosign: cosign record already exists for note {note_id}, skipping")
                return []
            amended = True
            log.info(f"supervisor_cosign: note {note_id} re-signed by supervisee after co-sign, reopening")

        # An amended note was already selected once, so it skips the sampling draw.
        if not amended:
            percentage = self._sample_percentage()
            if random.uniform(0, 100) > percentage:
                return []

        due_date = (datetime.now(timezone.utc) + timedelta(days=3)).date()
        patient = note.patient
        patient_id = str(patient.id) if patient else None
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else "patient"
        note_date = note.datetime_of_service.strftime("%Y-%m-%d") if note.datetime_of_service else "unknown date"

        create_tasks = self._create_tasks()
        task_id = str(uuid.uuid4()) if create_tasks else ""
        CoSignRecord(
            note_id=note_id,
            supervisee_id=str(provider.id),
            supervisor_id=str(supervisor.id),
            task_id=task_id,
            status="pending",
            due_date=due_date,
        ).save()

        # Without a task the record alone carries the note onto the encounter
        # list's Co-sign Needed filter and the summary page; approval skips task
        # completion for a record with an empty task_id.
        if not create_tasks:
            log.info(f"supervisor_cosign: COSIGN_CREATE_TASKS is false, recorded note {note_id} without a task")
            return []

        task = AddTask(
            id=task_id,
            title=f"Co-sign review{' (amended)' if amended else ''}: note {note_date} for {patient_name}",
            patient_id=patient_id,
            assignee_id=str(supervisor.id),
            due=datetime.combine(due_date, time(0, 0, 0), tzinfo=timezone.utc),
            status=TaskStatus.OPEN,
            labels=["cosign"],
        )
        effects = [task.apply()]

        # Which note, as something clickable. AddTask has no body field and its
        # linked_object only accepts REFERRAL or IMAGING, so a comment is the
        # only place a URL can go. The comment names task_id, which we minted
        # above rather than letting Canvas assign it, so it can reference a task
        # that does not exist yet -- effects apply in order, and AddTaskComment
        # carries no "task must exist" validation the way TaskMetadata does.
        #
        # The link goes here rather than in the title so the supervisor gets
        # something clickable instead of a bare note UUID.
        comment = self._task_comment(note, note_id, note_date, patient_id)
        if comment:
            effects.append(AddTaskComment(task_id=task_id, body=comment).apply())
        return effects

    def _task_comment(self, note, note_id: str, note_date: str, patient_id: str | None) -> str:
        """The body naming the note and how to reach it.

        Returns "" when there is nothing useful to say, so a note with no
        patient still produces a task -- the comment is an aid, not the job.
        """
        chart_url = note_chart_url(patient_id, getattr(note, "dbid", None))
        lines = []
        note_type = self._note_type_label(note)
        if note_type:
            lines.append(f"Note type: {note_type} - {note_date}")
        else:
            lines.append(f"Note dated {note_date}")
        if chart_url:
            lines.append(f"Open the note: {chart_url}")
        lines.append(f"Co-sign from the summary page: {summary_note_url(note_id)}")
        return "\n".join(lines)

    def _note_type_label(self, note) -> str:
        """What a human calls this note type.

        ``display`` before ``name``: ``name`` is
        the operator-editable slug a note type can carry (``new_patient_eval``)
        while ``display`` is the label the dropdown shows. The code is the last
        resort, and only because a labelled line beats an unlabelled one.
        """
        version = getattr(note, "note_type_version", None)
        for attribute in ("display", "name"):
            value = str(getattr(version, attribute, "") or "").strip()
            if value:
                return value
        return note_type_code_of(note)

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

    def _locked_by(self, staff) -> bool:
        """Whether this LOCKED event's originator is the given staff member."""
        user_id = getattr(staff, "user_id", None)
        if user_id is None:
            return False
        originator_id = (
            NoteStateChangeEvent.objects
            .filter(id=self.event.target.id)
            .values_list("originator_id", flat=True)
            .first()
        )
        return originator_id is not None and originator_id == user_id

    def _create_tasks(self) -> bool:
        """False only when COSIGN_CREATE_TASKS is false, no, off or 0; unset creates tasks."""
        raw = str(self.secrets.get("COSIGN_CREATE_TASKS", "") or "").strip().lower()
        return raw not in ("false", "no", "off", "0")

    def _reopen_on_amend(self) -> bool:
        """True only when COSIGN_REOPEN_ON_AMEND is true, yes, on or 1; unset leaves co-signed notes approved."""
        raw = str(self.secrets.get("COSIGN_REOPEN_ON_AMEND", "") or "").strip().lower()
        return raw in ("true", "yes", "on", "1")

    def _sample_percentage(self) -> float:
        raw = self.secrets.get("SAMPLE_PERCENTAGE", "100")
        try:
            pct = float(raw)
        except ValueError:
            return 100.0
        return max(0.0, min(100.0, pct))
