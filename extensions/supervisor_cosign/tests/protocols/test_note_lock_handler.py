"""Tests for supervisor_cosign.protocols.note_lock_handler."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from supervisor_cosign.protocols.note_lock_handler import NoteLockHandler


MODULE = "supervisor_cosign.protocols.note_lock_handler"


_DEFAULT_CONTEXT = object()
_DEFAULT_DOS = object()


def _make_handler(context=_DEFAULT_CONTEXT, secrets=None, target_id="target-1"):
    handler = NoteLockHandler.__new__(NoteLockHandler)
    handler.event = MagicMock()
    handler.event.context = {"note_id": "note-uuid-1"} if context is _DEFAULT_CONTEXT else context
    handler.event.target.id = target_id
    handler.secrets = secrets or {}
    handler.environment = {}
    return handler


def _mock_note(provider=None, patient=None, datetime_of_service=_DEFAULT_DOS):
    note = MagicMock()
    note.provider = provider
    note.patient = patient
    note.datetime_of_service = (
        datetime(2026, 5, 1, 14, 30, tzinfo=timezone.utc)
        if datetime_of_service is _DEFAULT_DOS
        else datetime_of_service
    )
    return note


def _mock_provider(provider_id="provider-1", first="Sue", last="Smith", supervisor=None):
    p = MagicMock()
    p.id = provider_id
    p.first_name = first
    p.last_name = last
    p.default_supervising_provider = supervisor
    return p


def _mock_patient(patient_id="patient-1", first="Pat", last="Pid"):
    pat = MagicMock()
    pat.id = patient_id
    pat.first_name = first
    pat.last_name = last
    return pat


class TestIsLocked:
    def test_returns_true_when_state_is_locked(self):
        handler = _make_handler(target_id="nsce-1")
        with patch(f"{MODULE}.NoteStateChangeEvent") as mock_nsce, \
             patch(f"{MODULE}.NoteStates") as mock_states:
            mock_states.LOCKED = "LKD"
            mock_nsce.objects.filter.return_value.values_list.return_value.first.return_value = "LKD"
            assert handler._is_locked() is True
            mock_nsce.objects.filter.assert_called_once_with(id="nsce-1")
            mock_nsce.objects.filter.return_value.values_list.assert_called_once_with("state", flat=True)

    def test_returns_false_when_state_is_not_locked(self):
        handler = _make_handler()
        with patch(f"{MODULE}.NoteStateChangeEvent") as mock_nsce, \
             patch(f"{MODULE}.NoteStates") as mock_states:
            mock_states.LOCKED = "LKD"
            mock_nsce.objects.filter.return_value.values_list.return_value.first.return_value = "NEW"
            assert handler._is_locked() is False

    def test_returns_false_when_row_missing(self):
        handler = _make_handler()
        with patch(f"{MODULE}.NoteStateChangeEvent") as mock_nsce, \
             patch(f"{MODULE}.NoteStates") as mock_states:
            mock_states.LOCKED = "LKD"
            mock_nsce.objects.filter.return_value.values_list.return_value.first.return_value = None
            assert handler._is_locked() is False


class TestSamplePercentage:
    def test_default_is_100(self):
        handler = _make_handler(secrets={})
        assert handler._sample_percentage() == 100.0

    def test_parses_numeric_secret(self):
        handler = _make_handler(secrets={"SAMPLE_PERCENTAGE": "25"})
        assert handler._sample_percentage() == 25.0

    def test_invalid_secret_falls_back_to_100(self):
        handler = _make_handler(secrets={"SAMPLE_PERCENTAGE": "not-a-number"})
        assert handler._sample_percentage() == 100.0

    def test_clamps_above_100(self):
        handler = _make_handler(secrets={"SAMPLE_PERCENTAGE": "150"})
        assert handler._sample_percentage() == 100.0

    def test_clamps_below_zero(self):
        handler = _make_handler(secrets={"SAMPLE_PERCENTAGE": "-5"})
        assert handler._sample_percentage() == 0.0


class TestCompute:
    def test_skip_when_not_locked(self):
        handler = _make_handler()
        with patch.object(NoteLockHandler, "_is_locked", return_value=False):
            assert handler.compute() == []

    def test_skip_when_no_note_id_in_context(self):
        handler = _make_handler(context={})
        with patch.object(NoteLockHandler, "_is_locked", return_value=True):
            assert handler.compute() == []

    def test_skip_when_note_has_no_provider(self):
        handler = _make_handler()
        note = _mock_note(provider=None)
        with patch.object(NoteLockHandler, "_is_locked", return_value=True), \
             patch(f"{MODULE}.Note") as mock_note_qs:
            mock_note_qs.objects.select_related.return_value.filter.return_value.first.return_value = note
            assert handler.compute() == []

    def test_skip_when_provider_has_no_supervisor(self):
        handler = _make_handler()
        provider = _mock_provider(supervisor=None)
        note = _mock_note(provider=provider)
        with patch.object(NoteLockHandler, "_is_locked", return_value=True), \
             patch(f"{MODULE}.Note") as mock_note_qs:
            mock_note_qs.objects.select_related.return_value.filter.return_value.first.return_value = note
            assert handler.compute() == []

    def test_skip_when_cosign_record_already_exists(self):
        handler = _make_handler()
        provider = _mock_provider(supervisor=_mock_provider(provider_id="sup-1"))
        note = _mock_note(provider=provider, patient=_mock_patient())
        with patch.object(NoteLockHandler, "_is_locked", return_value=True), \
             patch(f"{MODULE}.Note") as mock_note_qs, \
             patch(f"{MODULE}.CoSignRecord") as mock_record:
            mock_note_qs.objects.select_related.return_value.filter.return_value.first.return_value = note
            mock_record.objects.filter.return_value.exists.return_value = True
            assert handler.compute() == []
            mock_record.objects.filter.assert_called_once_with(note_id="note-uuid-1")

    def test_skip_on_sample_percentage_miss(self):
        handler = _make_handler(secrets={"SAMPLE_PERCENTAGE": "10"})
        provider = _mock_provider(supervisor=_mock_provider(provider_id="sup-1"))
        note = _mock_note(provider=provider, patient=_mock_patient())
        with patch.object(NoteLockHandler, "_is_locked", return_value=True), \
             patch(f"{MODULE}.Note") as mock_note_qs, \
             patch(f"{MODULE}.CoSignRecord") as mock_record, \
             patch(f"{MODULE}.random.uniform", return_value=99.0):
            mock_note_qs.objects.select_related.return_value.filter.return_value.first.return_value = note
            mock_record.objects.filter.return_value.exists.return_value = False
            assert handler.compute() == []

    def test_happy_path_creates_record_and_task(self):
        handler = _make_handler()
        supervisor = _mock_provider(provider_id="sup-uuid", first="Sara", last="Sup")
        provider = _mock_provider(provider_id="sup-uuid-supervisee", supervisor=supervisor)
        patient = _mock_patient(patient_id="pat-uuid")
        note = _mock_note(provider=provider, patient=patient)

        record_instance = MagicMock()
        with patch.object(NoteLockHandler, "_is_locked", return_value=True), \
             patch(f"{MODULE}.Note") as mock_note_qs, \
             patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.random.uniform", return_value=1.0), \
             patch(f"{MODULE}.uuid.uuid4", return_value="generated-task-uuid"), \
             patch(f"{MODULE}.AddTask") as mock_add_task:
            mock_note_qs.objects.select_related.return_value.filter.return_value.first.return_value = note
            mock_record_cls.objects.filter.return_value.exists.return_value = False
            mock_record_cls.return_value = record_instance
            apply_result = MagicMock(name="apply-result")
            mock_add_task.return_value.apply.return_value = apply_result

            result = handler.compute()

            assert result == [apply_result]
            # Persisted record
            kwargs = mock_record_cls.call_args.kwargs
            assert kwargs["note_id"] == "note-uuid-1"
            assert kwargs["supervisee_id"] == "sup-uuid-supervisee"
            assert kwargs["supervisor_id"] == "sup-uuid"
            assert kwargs["task_id"] == "generated-task-uuid"
            assert kwargs["status"] == "pending"
            assert isinstance(kwargs["due_date"], date)
            record_instance.save.assert_called_once()
            # Task wired with assignee=supervisor and the same task_id
            task_kwargs = mock_add_task.call_args.kwargs
            assert task_kwargs["id"] == "generated-task-uuid"
            assert task_kwargs["assignee_id"] == "sup-uuid"
            assert task_kwargs["patient_id"] == "pat-uuid"
            assert task_kwargs["labels"] == ["cosign"]
            assert "Co-sign review" in task_kwargs["title"]

    def test_happy_path_handles_missing_patient(self):
        handler = _make_handler()
        supervisor = _mock_provider(provider_id="sup-uuid")
        provider = _mock_provider(supervisor=supervisor)
        note = _mock_note(provider=provider, patient=None, datetime_of_service=None)

        with patch.object(NoteLockHandler, "_is_locked", return_value=True), \
             patch(f"{MODULE}.Note") as mock_note_qs, \
             patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.random.uniform", return_value=1.0), \
             patch(f"{MODULE}.AddTask") as mock_add_task:
            mock_note_qs.objects.select_related.return_value.filter.return_value.first.return_value = note
            mock_record_cls.objects.filter.return_value.exists.return_value = False
            mock_add_task.return_value.apply.return_value = MagicMock()

            result = handler.compute()

            assert len(result) == 1
            task_kwargs = mock_add_task.call_args.kwargs
            assert task_kwargs["patient_id"] is None
            assert "patient" in task_kwargs["title"]
            assert "unknown date" in task_kwargs["title"]
