"""Tests for which supervisor NoteLockHandler assigns and for summary page access."""

from unittest.mock import MagicMock, patch

import pytest

from supervisor_cosign.helpers.supervision import supervises_someone
from supervisor_cosign.protocols.note_lock_handler import NoteLockHandler

MODULE = "supervisor_cosign.protocols.note_lock_handler"
SUPERVISION = "supervisor_cosign.helpers.supervision"


def make_handler() -> NoteLockHandler:
    handler = NoteLockHandler.__new__(NoteLockHandler)
    handler.event = MagicMock()
    handler.event.context = {"note_id": "note-uuid-1"}
    handler.secrets = {}
    handler.environment = {}
    return handler


def make_staff(staff_id: str, default_supervisor=None) -> MagicMock:
    staff = MagicMock()
    staff.id = staff_id
    staff.first_name = staff_id
    staff.last_name = "Staff"
    staff.default_supervising_provider = default_supervisor
    return staff


def make_note(provider, supervising_provider) -> MagicMock:
    note = MagicMock()
    note.provider = provider
    note.supervising_provider = supervising_provider
    note.patient.id = "patient-1"
    note.datetime_of_service = None
    return note


def run_compute(note):
    with (
        patch.object(NoteLockHandler, "_is_locked", return_value=True),
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.CoSignRecord") as record_cls,
        patch(f"{MODULE}.random.uniform", return_value=1.0),
        patch(f"{MODULE}.AddTask") as add_task,
        patch(f"{MODULE}.AddTaskComment"),
    ):
        note_model.objects.select_related.return_value.filter.return_value.first.return_value = note
        record_cls.objects.filter.return_value.order_by.return_value.first.return_value = None
        result = make_handler().compute()
    return result, record_cls, add_task, note_model


def test_note_supervising_provider_wins_over_provider_default():
    provider = make_staff("supervisee", default_supervisor=make_staff("profile-default"))
    note = make_note(provider, supervising_provider=make_staff("note-supervisor"))

    _, record_cls, add_task, _ = run_compute(note)

    assert record_cls.call_args.kwargs["supervisor_id"] == "note-supervisor"
    assert record_cls.call_args.kwargs["supervisee_id"] == "supervisee"
    assert add_task.call_args.kwargs["assignee_id"] == "note-supervisor"


def test_falls_back_to_provider_default_when_note_has_none():
    provider = make_staff("supervisee", default_supervisor=make_staff("profile-default"))
    note = make_note(provider, supervising_provider=None)

    _, record_cls, add_task, _ = run_compute(note)

    assert record_cls.call_args.kwargs["supervisor_id"] == "profile-default"
    assert add_task.call_args.kwargs["assignee_id"] == "profile-default"


def test_note_supervisor_used_when_provider_has_no_default():
    provider = make_staff("supervisee", default_supervisor=None)
    note = make_note(provider, supervising_provider=make_staff("note-supervisor"))

    _, record_cls, _, _ = run_compute(note)

    assert record_cls.call_args.kwargs["supervisor_id"] == "note-supervisor"


def test_skips_when_neither_supervisor_is_set():
    provider = make_staff("supervisee", default_supervisor=None)
    note = make_note(provider, supervising_provider=None)

    result, record_cls, add_task, _ = run_compute(note)

    assert result == []
    record_cls.assert_not_called()
    add_task.assert_not_called()


def test_note_query_selects_supervising_provider():
    provider = make_staff("supervisee", default_supervisor=None)
    note = make_note(provider, supervising_provider=make_staff("note-supervisor"))

    _, _, _, note_model = run_compute(note)

    assert "supervising_provider" in note_model.objects.select_related.call_args.args


def test_supervises_someone_true_for_profile_supervisor():
    with patch(f"{SUPERVISION}.Staff") as staff_model, patch(f"{SUPERVISION}.CoSignRecord") as record_model:
        staff_model.objects.filter.return_value.exists.return_value = True
        assert supervises_someone("sup") is True
        record_model.objects.filter.assert_not_called()


def test_supervises_someone_true_for_note_level_supervisor_with_records():
    with patch(f"{SUPERVISION}.Staff") as staff_model, patch(f"{SUPERVISION}.CoSignRecord") as record_model:
        staff_model.objects.filter.return_value.exists.return_value = False
        record_model.objects.filter.return_value.exists.return_value = True
        assert supervises_someone("sup") is True
        record_model.objects.filter.assert_called_once_with(supervisor_id="sup")


def test_supervises_someone_false_without_team_or_records():
    with patch(f"{SUPERVISION}.Staff") as staff_model, patch(f"{SUPERVISION}.CoSignRecord") as record_model:
        staff_model.objects.filter.return_value.exists.return_value = False
        record_model.objects.filter.return_value.exists.return_value = False
        assert supervises_someone("sup") is False


def test_supervises_someone_false_for_blank_id():
    assert supervises_someone("") is False


def run_compute_with_secrets(note, secrets: dict):
    handler = make_handler()
    handler.secrets = secrets
    with (
        patch.object(NoteLockHandler, "_is_locked", return_value=True),
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.CoSignRecord") as record_cls,
        patch(f"{MODULE}.random.uniform", return_value=1.0),
        patch(f"{MODULE}.AddTask") as add_task,
        patch(f"{MODULE}.AddTaskComment") as add_comment,
    ):
        note_model.objects.select_related.return_value.filter.return_value.first.return_value = note
        record_cls.objects.filter.return_value.order_by.return_value.first.return_value = None
        result = handler.compute()
    return result, record_cls, add_task, add_comment


@pytest.mark.parametrize("value", ["false", "False", " no ", "off", "0"])
def test_create_tasks_off_records_the_note_without_a_task(value):
    provider = make_staff("supervisee", default_supervisor=make_staff("profile-default"))
    note = make_note(provider, supervising_provider=None)

    result, record_cls, add_task, add_comment = run_compute_with_secrets(note, {"COSIGN_CREATE_TASKS": value})

    assert result == []
    record_cls.return_value.save.assert_called_once()
    assert record_cls.call_args.kwargs["status"] == "pending"
    assert record_cls.call_args.kwargs["supervisor_id"] == "profile-default"
    assert record_cls.call_args.kwargs["task_id"] == ""
    add_task.assert_not_called()
    add_comment.assert_not_called()


@pytest.mark.parametrize("secrets", [{}, {"COSIGN_CREATE_TASKS": ""}, {"COSIGN_CREATE_TASKS": "true"}])
def test_create_tasks_unset_or_true_creates_the_task(secrets):
    provider = make_staff("supervisee", default_supervisor=make_staff("profile-default"))
    note = make_note(provider, supervising_provider=None)

    result, record_cls, add_task, _ = run_compute_with_secrets(note, secrets)

    add_task.assert_called_once()
    assert record_cls.call_args.kwargs["task_id"] == add_task.call_args.kwargs["id"]
    assert record_cls.call_args.kwargs["task_id"] != ""
    assert len(result) == 2


# Reopening after an amend


def run_relock(latest_status: str | None, originator_is_supervisee: bool, reopen: str | None = "true"):
    provider = make_staff("supervisee", default_supervisor=make_staff("profile-default"))
    provider.user_id = 501
    note = make_note(provider, supervising_provider=None)
    latest = None
    if latest_status:
        latest = MagicMock()
        latest.status = latest_status
    with (
        patch.object(NoteLockHandler, "_is_locked", return_value=True),
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.NoteStateChangeEvent") as event_model,
        patch(f"{MODULE}.CoSignRecord") as record_cls,
        patch(f"{MODULE}.random.uniform", return_value=100.0) as draw,
        patch(f"{MODULE}.AddTask") as add_task,
        patch(f"{MODULE}.AddTaskComment"),
    ):
        note_model.objects.select_related.return_value.filter.return_value.first.return_value = note
        event_model.objects.filter.return_value.values_list.return_value.first.return_value = (
            501 if originator_is_supervisee else 92
        )
        record_cls.objects.filter.return_value.order_by.return_value.first.return_value = latest
        handler = make_handler()
        handler.secrets = {"SAMPLE_PERCENTAGE": "0"}
        if reopen is not None:
            handler.secrets["COSIGN_REOPEN_ON_AMEND"] = reopen
        result = handler.compute()
    return result, record_cls, add_task, draw


def test_supervisee_resigning_a_cosigned_note_reopens_it_without_sampling():
    result, record_cls, add_task, draw = run_relock("approved", originator_is_supervisee=True)

    record_cls.return_value.save.assert_called_once()
    assert record_cls.call_args.kwargs["status"] == "pending"
    assert record_cls.call_args.kwargs["supervisor_id"] == "profile-default"
    assert add_task.call_args.kwargs["title"].startswith("Co-sign review (amended):")
    draw.assert_not_called()


def test_relock_by_someone_else_leaves_a_cosigned_note_approved():
    result, record_cls, add_task, _ = run_relock("approved", originator_is_supervisee=False)

    assert result == []
    record_cls.return_value.save.assert_not_called()
    add_task.assert_not_called()


def test_relock_while_pending_does_not_add_a_second_record():
    result, record_cls, _, _ = run_relock("pending", originator_is_supervisee=True)

    assert result == []
    record_cls.return_value.save.assert_not_called()


def test_first_lock_still_goes_through_sampling():
    result, record_cls, _, draw = run_relock(None, originator_is_supervisee=True)

    draw.assert_called_once()
    record_cls.return_value.save.assert_not_called()


@pytest.mark.parametrize("reopen", [None, "", "false", "no", "maybe"])
def test_reopen_is_off_unless_turned_on(reopen):
    result, record_cls, add_task, _ = run_relock("approved", originator_is_supervisee=True, reopen=reopen)

    assert result == []
    record_cls.return_value.save.assert_not_called()
    add_task.assert_not_called()


@pytest.mark.parametrize("reopen", ["true", "Yes", " on ", "1"])
def test_reopen_accepts_truthy_values(reopen):
    _, record_cls, _, _ = run_relock("approved", originator_is_supervisee=True, reopen=reopen)

    record_cls.return_value.save.assert_called_once()
