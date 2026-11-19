from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from canvas_sdk.commands import (
    FollowUpCommand,
    ImagingOrderCommand,
    InstructCommand,
    LabOrderCommand,
    PlanCommand,
    PrescribeCommand,
    ReferCommand,
    TaskCommand,
)
from canvas_sdk.commands.commands.task import AssigneeType
from canvas_sdk.commands.constants import ClinicalQuantity, CodeSystems, Coding
from canvas_sdk.v1.data.task import TaskPriority

from charting_tools.command_forms import FORM_SPECS, apply_form, clean_fields

TODAY = date(2026, 10, 1)


def test_every_plan_form_has_an_applier_for_each_field() -> None:
    assert set(FORM_SPECS) == {
        "plan", "instruct", "labOrder", "imagingOrder", "orderDme", "refer", "followUp", "task", "prescribe"
    }


def test_clean_fields_drops_unknown_and_blank() -> None:
    assert clean_fields("plan", {"narrative": "x", "bogus": 1, "other": ""}) == {"narrative": "x"}
    assert clean_fields("labOrder", {"tests": [], "comment": "", "fasting_required": True}) == {
        "fasting_required": True
    }
    assert clean_fields("hpi", {"narrative": "x"}) == {}
    assert clean_fields("plan", "nope") == {}


def test_blank_form_leaves_command_untouched() -> None:
    cmd = PlanCommand(note_uuid="n")
    apply_form(cmd, {}, TODAY)
    assert "narrative" not in cmd.values


def test_plan_and_instruct() -> None:
    plan = PlanCommand(note_uuid="n")
    apply_form(plan, {"narrative": " Recheck in 3 months "}, TODAY)
    assert plan.narrative == "Recheck in 3 months"

    instruct = InstructCommand(note_uuid="n")
    apply_form(instruct, {"instruction": {"concept_id": "123", "display": "Low salt diet"}, "comment": "Handout"}, TODAY)
    assert instruct.coding == Coding(system=CodeSystems.SNOMED, code="123", display="Low salt diet")
    assert instruct.comment == "Handout"


def test_lab_order_caps_comment() -> None:
    lab = LabOrderCommand(note_uuid="n")
    apply_form(
        lab,
        {
            "labs": [{"lab_partner": {"id": "lp1"}, "tests": [{"code": "7600"}, {"code": "1234"}]}],
            "fasting_required": True,
            "comment": "x" * 200,
        },
        TODAY,
    )
    assert lab.lab_partner == "lp1"
    assert lab.tests_order_codes == ["7600", "1234"]
    assert lab.fasting_required is True
    assert len(lab.comment or "") == 127


def test_imaging_order_ignores_unknown_priority() -> None:
    img = ImagingOrderCommand(note_uuid="n")
    apply_form(img, {"image": {"code": "74176"}, "priority": "Urgent", "additional_details": "Contrast ok"}, TODAY)
    assert img.image_code == "74176"
    assert img.priority == ImagingOrderCommand.Priority.URGENT
    assert img.additional_details == "Contrast ok"

    other = ImagingOrderCommand(note_uuid="n")
    apply_form(other, {"priority": "Whenever"}, TODAY)
    assert "priority" not in other.values


def test_refer_builds_service_provider() -> None:
    refer = ReferCommand(note_uuid="n")
    apply_form(
        refer,
        {
            "service_provider": {"first_name": "Ann", "last_name": "Lee", "specialty": "Nephrology", "practice_name": "Kidney Care"},
            "clinical_question": "Diagnostic Uncertainty",
            "priority": "Routine",
            "include_visit_note": True,
        },
        TODAY,
    )
    assert refer.service_provider is not None
    assert refer.service_provider.last_name == "Lee"
    assert refer.clinical_question == ReferCommand.ClinicalQuestion.DIAGNOSTIC_UNCERTAINTY
    assert refer.priority == ReferCommand.Priority.ROUTINE
    assert refer.include_visit_note is True


def test_follow_up_resolves_current_note_type_and_relative_date(mocker: MagicMock) -> None:
    query = mocker.patch("charting_tools.command_forms.NoteType.objects.filter")
    query.return_value.order_by.return_value.first.return_value = SimpleNamespace(id="nt-v3")
    follow = FollowUpCommand(note_uuid="n")
    apply_form(
        follow,
        {"reason_for_visit": "BP check", "note_type": {"unique_identifier": "u1"}, "requested_in_days": "90"},
        TODAY,
    )
    query.assert_called_once_with(unique_identifier="u1", is_active=True, deprecated_at__isnull=True)
    assert follow.note_type_id == "nt-v3"
    assert follow.reason_for_visit == "BP check"
    assert follow.structured is False
    assert follow.requested_date == date(2026, 12, 30)


def test_task_assignee_priority_due_and_labels() -> None:
    task = TaskCommand(note_uuid="n")
    apply_form(
        task,
        {
            "title": "Call with results",
            "assignee": {"to": "team", "id": 3},
            "priority": "urgent",
            "due_in_days": 7,
            "labels": "labs, follow-up ,",
        },
        TODAY,
    )
    assert task.assign_to == {"to": AssigneeType.TEAM, "id": 3}
    assert task.priority == TaskPriority.URGENT
    assert task.due_date == date(2026, 10, 8)
    assert task.labels == ["labs", "follow-up"]

    unassigned = TaskCommand(note_uuid="n")
    apply_form(unassigned, {"assignee": {"to": "unassigned"}}, TODAY)
    assert unassigned.assign_to == {"to": AssigneeType.UNASSIGNED}


def test_prescribe_parses_numbers_and_leaves_pharmacy_unset() -> None:
    rx = PrescribeCommand(note_uuid="n")
    apply_form(
        rx,
        {
            "medication": {"fdb_code": "123"},
            "type_to_dispense": {"representative_ndc": "000", "ncpdp_quantity_qualifier_code": "C48542"},
            "sig": "1 tab daily",
            "days_supply": "30",
            "quantity_to_dispense": "30.5",
            "refills": "two",
            "substitutions": "not_allowed",
        },
        TODAY,
    )
    assert rx.fdb_code == "123"
    assert rx.type_to_dispense == ClinicalQuantity(representative_ndc="000", ncpdp_quantity_qualifier_code="C48542")
    assert rx.days_supply == 30
    assert rx.quantity_to_dispense == Decimal("30.5")
    assert "refills" not in rx.values  # "two" isn't a number
    assert rx.substitutions == PrescribeCommand.Substitutions.NOT_ALLOWED
    assert "pharmacy" not in rx.values


# ── Lab partners and their tests ─────────────────────────────────────

from charting_tools.command_forms import lab_variants  # noqa: E402

QUEST = {"id": "lp-quest", "display": "Quest"}
LABCORP = {"id": "lp-labcorp", "display": "LabCorp"}


def test_saved_single_partner_lab_reads_as_one_entry() -> None:
    legacy = {"lab_partner": QUEST, "tests": [{"code": "CMP1", "display": "CMP"}]}
    assert lab_variants(legacy) == [{"lab_partner": QUEST, "tests": [{"code": "CMP1", "display": "CMP"}]}]
    assert clean_fields("labOrder", legacy) == {"labs": [{"lab_partner": QUEST, "tests": [{"code": "CMP1", "display": "CMP"}]}]}


def test_lab_entries_dedupe_and_limit() -> None:
    raw = {"labs": [
        {"lab_partner": QUEST, "tests": [{"code": "A"}]},
        {"lab_partner": QUEST, "tests": [{"code": "B"}]},
        {"lab_partner": LABCORP, "tests": [{"code": "C"}, {"code": ""}]},
        {"lab_partner": None, "tests": []},
    ]}
    assert [v["lab_partner"]["id"] for v in clean_fields("labOrder", raw)["labs"]] == ["lp-quest", "lp-labcorp"]
    assert len(clean_fields("labOrder", raw, max_lab_partners=1)["labs"]) == 1


def test_lab_order_uses_chosen_partner_else_first() -> None:
    fields = {"labs": [{"lab_partner": QUEST, "tests": [{"code": "Q-CMP"}]},
                       {"lab_partner": LABCORP, "tests": [{"code": "L-CMP"}]}], "fasting_required": True}
    chosen = LabOrderCommand(note_uuid="n")
    apply_form(chosen, fields, TODAY, "lp-labcorp")
    assert chosen.lab_partner == "lp-labcorp" and chosen.tests_order_codes == ["L-CMP"]
    assert chosen.fasting_required is True

    default = LabOrderCommand(note_uuid="n")
    apply_form(default, fields, TODAY, "lp-unknown")
    assert default.lab_partner == "lp-quest" and default.tests_order_codes == ["Q-CMP"]


def test_quickpick_drops_labs_without_tests_but_single_partner_keeps_choice() -> None:
    raw = {"labs": [{"lab_partner": QUEST, "tests": []}, {"lab_partner": LABCORP, "tests": [{"code": "CBC"}]}]}
    assert [v["lab_partner"]["id"] for v in clean_fields("labOrder", raw, max_lab_partners=20)["labs"]] == ["lp-labcorp"]
    # One partner (templates, order sets): a lab with no tests yet is still a valid choice.
    single = {"labs": [{"lab_partner": QUEST, "tests": []}]}
    assert clean_fields("labOrder", single, max_lab_partners=1)["labs"][0]["lab_partner"]["id"] == "lp-quest"


def test_panel_offers_only_labs_with_tests() -> None:
    from types import SimpleNamespace

    from charting_tools.insertion import lab_partners_of

    template = SimpleNamespace(commands=[{"schema_key": "labOrder", "fields": {"labs": [
        {"lab_partner": QUEST, "tests": []}, {"lab_partner": LABCORP, "tests": [{"code": "CBC"}]}]}}])
    assert lab_partners_of(template) == [{"id": "lp-labcorp", "display": "LabCorp"}]


def test_dme_form_fills_item_quantity_length_and_send_to() -> None:
    from datetime import date

    from canvas_sdk.commands import OrderDmeCommand

    from charting_tools.command_forms import apply_form

    cmd = OrderDmeCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    apply_form(cmd, {
        "item": {"free_text": "  Standard walker "}, "quantity": "2", "length_of_need": "99 months",
        "service_provider": {"first_name": "", "last_name": "", "practice_name": "Acme Medical Supply",
                             "business_fax": "555-0100"},
    }, date(2026, 10, 18))
    assert cmd.free_text_item == "Standard walker"
    assert cmd.quantity == 2
    assert cmd.length_of_need == "99 months"
    assert cmd.service_provider is not None and cmd.service_provider.practice_name == "Acme Medical Supply"


def test_dme_form_skips_a_quantity_below_one() -> None:
    from datetime import date

    from canvas_sdk.commands import OrderDmeCommand

    from charting_tools.command_forms import apply_form

    cmd = OrderDmeCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    apply_form(cmd, {"item": {"free_text": "Cane"}, "quantity": "0"}, date(2026, 10, 18))
    assert cmd.quantity is None and cmd.free_text_item == "Cane"


PRODUCT = {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "code": "E0143", "code_system": "HCPCS",
           "name": "Walker, folding, wheeled", "display": "Walker, folding, wheeled (E0143)"}


def test_dme_form_uses_an_active_formulary_product(mocker) -> None:  # type: ignore[no-untyped-def]
    from datetime import date

    from canvas_sdk.commands import OrderDmeCommand

    from charting_tools.command_forms import apply_form

    active = mocker.patch("charting_tools.command_forms.DmeProduct.objects.filter")
    active.return_value.exists.return_value = True
    cmd = OrderDmeCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    apply_form(cmd, {"item": {"product": PRODUCT}}, date(2026, 10, 18))
    assert cmd.dme_product_id == PRODUCT["id"] and cmd.free_text_item is None
    assert active.call_args.kwargs == {"id": PRODUCT["id"], "active": True}

    active.return_value.exists.return_value = False  # since taken off the formulary
    cmd = OrderDmeCommand(note_uuid="a" * 32, command_uuid="c" * 32)
    apply_form(cmd, {"item": {"product": PRODUCT}}, date(2026, 10, 18))
    assert cmd.dme_product_id is None


def test_dme_item_is_kept_to_one_shape() -> None:
    from charting_tools.command_forms import clean_fields

    both = clean_fields("orderDme", {"item": {"product": {**PRODUCT, "extra": "x"}, "free_text": "Cane"}})
    assert both["item"] == {"product": {k: PRODUCT[k] for k in ("id", "code", "code_system", "name", "display")}}
    assert clean_fields("orderDme", {"item": {"free_text": "Cane"}}) == {"item": {"free_text": "Cane"}}
    assert "item" not in clean_fields("orderDme", {"item": "not an object"})


def test_older_flat_free_text_item_still_applies() -> None:
    from datetime import date

    from canvas_sdk.commands import OrderDmeCommand

    from charting_tools.command_forms import apply_form

    cmd = OrderDmeCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    apply_form(cmd, {"free_text_item": "Shower chair"}, date(2026, 10, 18))
    assert cmd.free_text_item == "Shower chair"
