import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from charting_tools.api.templates_api import NoteTemplatesAPI
from charting_tools.portability import (
    EXPORT_FORMAT,
    EXPORT_VERSION,
    Resolver,
    export_document,
    read_document,
    remap_item,
)
from tests.conftest import make_request, make_template

MODULE = "charting_tools.api.templates_api"
PORT = "charting_tools.portability"

# The source environment's ids, and this environment's.
SRC_OFFICE, HERE_OFFICE = "uid-office-src", "uid-office-here"
SRC_LABCORP, HERE_LABCORP = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def _doc(*items: dict) -> dict:
    return {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "exported_at": "2026-10-12T00:00:00Z", "items": list(items)}


def _item(**overrides: Any) -> dict:
    item = {
        "template_id": "src1", "name": "Annual visit", "kind": "template", "active": True,
        "show_in_menu": True, "show_in_panel": False, "note_types": [], "diagnosis_sources": [],
        "diagnosis_match_codes": [], "tags": [], "rule": None, "commands": [{"schema_key": "plan"}],
    }
    item.update(overrides)
    return item


@pytest.fixture
def here(mocker: MagicMock) -> SimpleNamespace:
    """This environment: its note types, lab partners and tests, staff, and teams."""
    mocker.patch(f"{PORT}.note_type_options", return_value=[{"unique_identifier": HERE_OFFICE, "name": "Office Visit"}])
    labs = mocker.patch(f"{PORT}.LabPartner.objects.filter")
    labs.return_value.values_list.return_value = [(HERE_LABCORP, "LabCorp")]
    tests = mocker.patch(f"{PORT}.LabPartnerTest.objects.filter")
    tests.return_value.values_list.return_value = ["L-CMP", "L-CBC"]
    mocker.patch(f"{PORT}.Staff.objects.filter").return_value.values_list.return_value = [(7, "Alex", "Provider")]
    mocker.patch(f"{PORT}.Team.objects.values_list", return_value=[(3, "Care coordination")])
    return SimpleNamespace(labs=labs, tests=tests)


# ── Export ───────────────────────────────────────────────────────────


def test_export_keeps_expanded_codes_and_full_rules() -> None:
    rule = make_template(template_id="r1", name="CKD", kind="rule", commands=[],
                         rule={"match": "all", "conditions": [{"type": "diagnosis", "sources": [{"code": "N18"}], "match_codes": ["N18", "N186"]}]})
    quickpick = make_template(template_id="q1", name="CMP", kind="quickpick", diagnosis_match_codes=["N186"])
    doc = export_document([rule, quickpick], "2026-10-12T00:00:00Z")
    assert doc["format"] == EXPORT_FORMAT and doc["version"] == EXPORT_VERSION
    by_name = {i["name"]: i for i in doc["items"]}
    assert by_name["CKD"]["rule"]["conditions"][0]["match_codes"] == ["N18", "N186"]
    assert by_name["CMP"]["diagnosis_match_codes"] == ["N186"]
    assert by_name["CMP"]["rule"] is None


@pytest.mark.parametrize(
    ("raw", "message"),
    [({"format": "other"}, "isn't a Charting Admin export"),
     ({"format": EXPORT_FORMAT, "version": 99, "items": []}, "version 99"),
     ({"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "items": [{"kind": "nope"}]}, "Item 1")],
)
def test_bad_files_are_refused(raw: dict, message: str) -> None:
    items, error = read_document(raw)
    assert items is None and error and message in error


# ── Matching references ──────────────────────────────────────────────


def test_note_types_match_by_name_when_ids_differ(here: SimpleNamespace) -> None:
    body, problems, _ = remap_item(_item(note_types=[{"unique_identifier": SRC_OFFICE, "name": "office visit"}]), Resolver())
    assert problems == []
    assert body["note_types"] == [{"unique_identifier": HERE_OFFICE, "name": "Office Visit"}]


def test_unknown_note_type_is_a_problem(here: SimpleNamespace) -> None:
    _, problems, _ = remap_item(_item(note_types=[{"unique_identifier": "x", "name": "Telehealth"}]), Resolver())
    assert problems == ["Note type 'Telehealth' doesn't exist here"]


def _lab_item(tests: list[str], display: str = "LabCorp") -> dict:
    return _item(kind="quickpick", commands=[{"schema_key": "labOrder", "fields": {"labs": [
        {"lab_partner": {"id": SRC_LABCORP, "display": display}, "tests": [{"code": c, "display": c} for c in tests]}]}}])


def test_lab_partners_match_by_name_and_tests_must_exist(here: SimpleNamespace) -> None:
    body, problems, _ = remap_item(_lab_item(["L-CMP"]), Resolver())
    assert problems == []
    assert body["commands"][0]["fields"]["labs"][0]["lab_partner"] == {"id": HERE_LABCORP, "display": "LabCorp"}

    _, problems, _ = remap_item(_lab_item(["L-CMP", "L-XYZ"]), Resolver())
    assert problems == ["Command 1: LabCorp doesn't offer test(s) L-XYZ"]

    _, problems, _ = remap_item(_lab_item(["Q-CMP"], display="Quest"), Resolver())
    assert problems == ["Command 1: lab 'Quest' doesn't exist here"]


def test_task_assignee_matches_by_name_or_is_left_unset(here: SimpleNamespace) -> None:
    def task(assignee: dict) -> dict:
        return _item(commands=[{"schema_key": "task", "fields": {"title": "Call", "assignee": assignee}}])

    body, problems, warnings = remap_item(task({"to": "team", "id": 99, "display": "Team: Care coordination"}), Resolver())
    assert problems == [] and warnings == []
    assert body["commands"][0]["fields"]["assignee"] == {"to": "team", "id": 3, "display": "Team: Care coordination"}

    body, problems, warnings = remap_item(task({"to": "staff", "id": 7, "display": "Someone Else"}), Resolver())
    assert problems == [] and "assignee" not in body["commands"][0]["fields"]
    assert warnings == ["Command 1: assignee 'Someone Else' isn't here, so it's left unset"]


def test_rule_commands_and_note_type_conditions_are_matched(here: SimpleNamespace) -> None:
    rule = {"match": "all",
            "conditions": [{"type": "note_type", "note_types": [{"unique_identifier": SRC_OFFICE, "name": "Office Visit"}]}],
            "actions": [{"type": "add", "mode": "insert", "commands": [{"schema_key": "labOrder", "fields": {"labs": [
                {"lab_partner": {"id": SRC_LABCORP, "display": "LabCorp"}, "tests": [{"code": "L-CBC", "display": "CBC"}]}]}}]}]}
    body, problems, _ = remap_item(_item(kind="rule", commands=[], rule=rule), Resolver())
    assert problems == []
    assert body["rule"]["conditions"][0]["note_types"][0]["unique_identifier"] == HERE_OFFICE
    assert body["rule"]["actions"][0]["commands"][0]["fields"]["labs"][0]["lab_partner"]["id"] == HERE_LABCORP


# ── Upload ───────────────────────────────────────────────────────────


@pytest.fixture
def upload(mocker: MagicMock, here: SimpleNamespace) -> SimpleNamespace:
    mocker.patch(f"{MODULE}.staff_can_manage_templates", return_value=True)
    mocker.patch(f"{MODULE}.missing_questionnaires", return_value=None)
    mocker.patch(f"{MODULE}.note_type_problem", return_value=None)
    existing = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
    existing.return_value.first.return_value = None
    created = mocker.patch(f"{MODULE}.NoteTemplate.save", autospec=True)
    umls = mocker.patch(f"{MODULE}.expand_sources")
    return SimpleNamespace(existing=existing, created=created, umls=umls)


def _run(doc: dict, apply: bool) -> dict:
    api = object.__new__(NoteTemplatesAPI)
    api.request = make_request({"export": doc, "apply": apply})
    api.secrets = {}
    api.environment = {}
    [response] = api.import_all()
    assert response.status_code == HTTPStatus.OK
    return json.loads(response.content)


def test_preview_saves_nothing(upload: SimpleNamespace) -> None:
    result = _run(_doc(_item()), apply=False)
    assert result["applied"] is False
    assert result["counts"] == {"create": 1, "update": 0, "skip": 0}
    upload.created.assert_not_called()


def test_upload_creates_new_items_and_updates_by_name_and_kind(upload: SimpleNamespace) -> None:
    current = make_template(template_id="here1", name="Annual Visit", kind="template", commands=[])
    current.save = MagicMock()
    upload.existing.return_value.first.side_effect = [current, None]
    result = _run(_doc(_item(), _item(template_id="src2", name="Diabetes follow-up", active=False)), apply=True)
    assert [r["action"] for r in result["items"]] == ["update", "create"]
    current.save.assert_called_once()
    assert [c["schema_key"] for c in current.commands] == ["plan"]  # replaced: it had none
    assert current.name == "Annual visit" and current.template_id == "here1"  # same row, renamed to the file's spelling
    [(saved,), _] = upload.created.call_args_list[0]
    assert saved.name == "Diabetes follow-up" and saved.active is False  # keeps its on/off state


def test_expanded_codes_come_from_the_file_without_umls(upload: SimpleNamespace) -> None:
    item = _item(kind="quickpick", show_in_panel=True,
                 diagnosis_sources=[{"code": "N18", "display": "CKD", "include_children": True}],
                 diagnosis_match_codes=["N18", "N186"])
    _run(_doc(item), apply=True)
    upload.umls.assert_not_called()
    [(saved,), _] = upload.created.call_args_list[0]
    assert saved.diagnosis_match_codes == ["N18", "N186"]


def test_problems_skip_the_item_and_the_rest_upload(upload: SimpleNamespace) -> None:
    clash = make_template(template_id="here9", name="CMP", kind="order_set")
    upload.existing.return_value.first.side_effect = [clash, None, None]
    result = _run(_doc(
        _item(name="CMP", kind="quickpick"),
        _item(name="Telehealth", note_types=[{"unique_identifier": "x", "name": "Telehealth"}]),
        _item(name="Plan only"),
    ), apply=True)
    by_name = {r["name"]: r for r in result["items"]}
    assert by_name["CMP"]["action"] == "skip" and "already used here by a order set" in by_name["CMP"]["problems"][0]
    assert by_name["Telehealth"]["action"] == "skip"
    assert by_name["Plan only"]["action"] == "create"
    assert upload.created.call_count == 1


def test_the_same_name_twice_in_one_file_is_a_problem(upload: SimpleNamespace) -> None:
    result = _run(_doc(_item(), _item(template_id="src2")), apply=False)
    assert [r["action"] for r in result["items"]] == ["create", "skip"]
    assert result["items"][1]["problems"] == ["The file has this name more than once"]


def test_upload_needs_an_admin_and_json(mocker: MagicMock) -> None:
    mocker.patch(f"{MODULE}.staff_can_manage_templates", return_value=False)
    api = object.__new__(NoteTemplatesAPI)
    api.request = make_request({"export": _doc(), "apply": True})
    api.secrets, api.environment = {}, {}
    [response] = api.import_all()
    assert response.status_code == HTTPStatus.FORBIDDEN


def _dme_item(ref: dict) -> dict:
    return _item(kind="quickpick", commands=[{"schema_key": "orderDme", "fields": {"item": {"product": ref}}}])


def test_dme_products_match_by_code_when_ids_differ(mocker: MagicMock) -> None:
    here_walker = SimpleNamespace(id="99999999-9999-4999-8999-999999999999", code="E0143", code_system="HCPCS",
                                  name="Walker, folding, wheeled")
    products = mocker.patch(f"{PORT}.DmeProduct.objects.filter")
    products.return_value.filter.side_effect = lambda **kw: MagicMock(
        first=MagicMock(return_value=here_walker if kw.get("code") == "E0143" else None))
    src = {"id": "11111111-1111-4111-8111-111111111111", "code": "E0143", "code_system": "HCPCS", "display": "Walker"}
    body, problems, _ = remap_item(_dme_item(src), Resolver())
    assert problems == []
    assert body["commands"][0]["fields"]["item"]["product"]["id"] == here_walker.id

    _, problems, _ = remap_item(_dme_item({**src, "code": "E9999", "display": "Hoyer lift"}), Resolver())
    assert problems == ["Command 1: DME product 'Hoyer lift' isn't on this formulary"]


def test_dme_products_are_looked_up_once_per_upload(mocker: MagicMock) -> None:
    walker = SimpleNamespace(id="99999999-9999-4999-8999-999999999999", code="E0143", code_system="HCPCS",
                             name="Walker, folding, wheeled")
    products = mocker.patch(f"{PORT}.DmeProduct.objects.filter")
    products.return_value.filter.return_value.first.return_value = walker
    ref = {"id": walker.id, "code": "E0143", "code_system": "HCPCS", "display": "Walker"}
    resolver = Resolver()
    for _ in range(3):
        _, problems, _ = remap_item(_dme_item(ref), resolver)
        assert problems == []
    assert products.call_count == 1
