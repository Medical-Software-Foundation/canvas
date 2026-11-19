from types import SimpleNamespace
from unittest.mock import MagicMock

from canvas_sdk.commands import (
    AssessCommand,
    FollowUpCommand,
    HistoryOfPresentIllnessCommand,
    InstructCommand,
    LabOrderCommand,
    PerformCommand,
    PlanCommand,
    ReasonForVisitCommand,
    TaskCommand,
)
from canvas_sdk.commands.commands.task import AssigneeType
from canvas_sdk.commands.constants import CodeSystems, Coding

from charting_tools.carry_forward import (
    apply_carry_forward,
    find_previous_command,
    supports_carry_forward,
)
from tests.conftest import make_note


def _previous(schema_key: str, data: dict) -> SimpleNamespace:
    return SimpleNamespace(schema_key=schema_key, data=data, id="prev")


def test_supported_commands() -> None:
    assert supports_carry_forward("hpi") is True
    assert supports_carry_forward("labOrder") is True
    assert supports_carry_forward("prescribe") is False
    assert supports_carry_forward("vitals") is False


def test_narrative_commands_copy_narrative() -> None:
    hpi = HistoryOfPresentIllnessCommand(note_uuid="n")
    apply_carry_forward(hpi, _previous("hpi", {"narrative": "Knee pain for 3 weeks"}))
    assert hpi.narrative == "Knee pain for 3 weeks"

    plan = PlanCommand(note_uuid="n")
    apply_carry_forward(plan, _previous("plan", {"narrative": None}))
    assert plan.narrative == ""


def test_task_copies_title_assignee_and_labels() -> None:
    task = TaskCommand(note_uuid="n")
    apply_carry_forward(
        task,
        _previous(
            "task",
            {
                "title": "Call patient",
                "assign_to": {"value": "team-12"},
                "comment": "re: labs",
                "labels": [{"text": "urgent"}, {"text": ""}],
                "due_date": "2026-01-01",
            },
        ),
    )
    assert task.title == "Call patient"
    assert task.assign_to == {"to": AssigneeType.TEAM, "id": 12}
    assert task.comment == "re: labs"
    assert task.labels == ["urgent"]
    assert task.due_date is None


def test_lab_order_maps_provider_by_dbid(mocker: MagicMock) -> None:
    staff_query = mocker.patch("charting_tools.carry_forward.Staff.objects.filter")
    staff_query.return_value.first.return_value = SimpleNamespace(id="staffuuid")
    lab = LabOrderCommand(note_uuid="n")
    apply_carry_forward(
        lab,
        _previous(
            "labOrder",
            {
                "lab_partner": {"value": "partner1"},
                "tests": [{"value": "CBC"}, {"value": "CMP"}],
                "ordering_provider": {"value": 5},
                "diagnosis": [{"value": "E119"}],
                "fasting_status": True,
                "comment": "AM draw",
            },
        ),
    )
    staff_query.assert_called_once_with(dbid=5)
    assert lab.lab_partner == "partner1"
    assert lab.tests_order_codes == ["CBC", "CMP"]
    assert lab.ordering_provider_key == "staffuuid"
    assert lab.diagnosis_codes == ["E119"]
    assert lab.fasting_required is True


def test_assess_skips_condition_entered_in_error(mocker: MagicMock) -> None:
    condition_query = mocker.patch("charting_tools.carry_forward.Condition.objects.filter")
    condition_query.return_value.first.return_value = None
    assess = AssessCommand(note_uuid="n")
    apply_carry_forward(
        assess,
        _previous("assess", {"condition": {"value": 9}, "status": "stable", "narrative": "ok"}),
    )
    condition_query.assert_called_once_with(dbid=9, entered_in_error__isnull=True)
    assert assess.condition_id is None
    assert assess.status == AssessCommand.Status.STABLE
    assert assess.narrative == "ok"


def test_find_previous_command_filters_prior_committed(mocker: MagicMock) -> None:
    command_query = mocker.patch("charting_tools.carry_forward.Command.objects.filter")
    chain = command_query.return_value.exclude.return_value.order_by.return_value
    chain.first.return_value = "found"
    note = make_note()

    assert find_previous_command(note, "hpi") == "found"
    command_query.assert_called_once_with(
        patient_id=note.patient_id,
        schema_key="hpi",
        committer__isnull=False,
        entered_in_error__isnull=True,
        note__datetime_of_service__lt=note.datetime_of_service,
    )
    command_query.return_value.exclude.assert_called_once_with(note_id=note.dbid)
    command_query.return_value.exclude.return_value.order_by.assert_called_once_with(
        "-note__datetime_of_service", "-dbid"
    )


def test_reason_for_visit_structured_when_coding_found(mocker: MagicMock) -> None:
    query = mocker.patch("charting_tools.carry_forward.ReasonForVisitSettingCoding.objects.filter")
    query.return_value.order_by.return_value.last.return_value = SimpleNamespace(id="rfvuuid")
    rfv = ReasonForVisitCommand(note_uuid="n")
    apply_carry_forward(rfv, _previous("reasonForVisit", {"coding": {"value": "R1"}, "comment": "f/u"}))
    query.assert_called_once_with(code="R1")
    assert rfv.structured is True
    assert rfv.coding == "rfvuuid"
    assert rfv.comment == "f/u"


def test_reason_for_visit_unstructured_keeps_comment() -> None:
    rfv = ReasonForVisitCommand(note_uuid="n")
    apply_carry_forward(rfv, _previous("reasonForVisit", {"comment": "Follow-up"}))
    assert rfv.structured is False
    assert rfv.comment == "Follow-up"


def test_instruct_snomed_and_unstructured() -> None:
    snomed = InstructCommand(note_uuid="n")
    apply_carry_forward(
        snomed,
        _previous(
            "instruct",
            {
                "instruct": {"extra": {"coding": [{"system": CodeSystems.SNOMED, "code": 123, "display": "Diet"}]}},
                "narrative": "low sodium",
            },
        ),
    )
    assert snomed.coding == Coding(system=CodeSystems.SNOMED, code="123", display="Diet")
    assert snomed.comment == "low sodium"

    free_text = InstructCommand(note_uuid="n")
    apply_carry_forward(
        free_text,
        _previous(
            "instruct",
            {"instruct": {"extra": {"coding": [{"system": CodeSystems.UNSTRUCTURED, "display": "Rest"}]}}},
        ),
    )
    assert free_text.coding == Coding(system=CodeSystems.UNSTRUCTURED, code="Rest")


def test_perform_copies_cpt_and_notes() -> None:
    perform = PerformCommand(note_uuid="n")
    apply_carry_forward(perform, _previous("perform", {"perform": {"value": "99213"}, "notes": "x"}))
    assert perform.cpt_code == "99213"
    assert perform.notes == "x"


def test_follow_up_keeps_reason_and_note_type_but_not_date(mocker: MagicMock) -> None:
    note_type_query = mocker.patch("charting_tools.carry_forward.NoteType.objects.filter")
    note_type_query.return_value.first.return_value = SimpleNamespace(id="ntuuid")
    follow_up = FollowUpCommand(note_uuid="n")
    apply_carry_forward(
        follow_up,
        _previous(
            "followUp",
            {
                "reason_for_visit": "Recheck BP",
                "note_type": {"value": 3},
                "requested_date": {"date": "2026-01-01"},
                "comment": "2 weeks",
            },
        ),
    )
    note_type_query.assert_called_once_with(dbid=3)
    assert follow_up.structured is False
    assert follow_up.reason_for_visit == "Recheck BP"
    assert follow_up.note_type_id == "ntuuid"
    assert follow_up.requested_date is None
    assert follow_up.comment == "2 weeks"


def test_failed_carry_forward_logs_the_error_type_not_its_text(mocker) -> None:  # type: ignore[no-untyped-def]
    # A validation message can quote the prior note's narrative.
    from types import SimpleNamespace

    from canvas_sdk.commands import PlanCommand

    from charting_tools.insertion import _carry_forward

    mocker.patch("charting_tools.insertion.find_previous_command", return_value=SimpleNamespace(id="c-prior"))
    mocker.patch(
        "charting_tools.insertion.apply_carry_forward",
        side_effect=ValueError("input_value='Patient reports chest pain at night'"),
    )
    log = mocker.patch("charting_tools.insertion.log")
    note = SimpleNamespace(id="a" * 32, dbid=1, patient_id=1)
    command = PlanCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    fresh = _carry_forward(command, PlanCommand, note)
    assert fresh.command_uuid == command.command_uuid
    message = log.warning.call_args.args[0]
    assert "ValueError" in message and "chest pain" not in message


def test_assess_carry_forward_skips_a_condition_held_as_a_code(mocker) -> None:  # type: ignore[no-untyped-def]
    from canvas_sdk.commands import AssessCommand

    from charting_tools import carry_forward

    lookup = mocker.patch("charting_tools.carry_forward.Condition.objects.filter")
    cmd = AssessCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    carry_forward.MAPPERS["assess"](cmd, {"condition": {"value": "R54"}, "narrative": "Stable", "status": "stable"})
    lookup.assert_not_called()
    assert cmd.condition_id is None and cmd.narrative == "Stable"
