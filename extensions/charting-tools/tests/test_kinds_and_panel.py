import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.events import EventType

from charting_tools.api.panel_api import PanelAPI
from charting_tools.api.templates_api import match_codes, validate_payload
from charting_tools.diagnoses import clean_sources, matches
from charting_tools.handlers.command_panel import AssessPanel, DiagnosePanel
from charting_tools.kinds import allows_command
from charting_tools.panel import find_icd10
from charting_tools.tokens import sign_token, verify_token
from charting_tools.umls import UmlsError
from tests.conftest import make_template, payload

NOTE_ID = "3f2b8a1c9d4e4f60a7b8c9d0e1f2a3b4"
COMMAND_ID = "9a8b7c6d5e4f40312a1b2c3d4e5f6a7b"


# ── Kinds ────────────────────────────────────────────────────────────


def test_sections_per_kind() -> None:
    assert allows_command("template", "hpi")
    assert allows_command("quickpick", "labOrder") and allows_command("quickpick", "perform")
    assert not allows_command("quickpick", "assess")
    assert allows_command("order_set", "assess") and allows_command("order_set", "refer")
    assert not allows_command("order_set", "hpi")


def _body(**extra: object) -> dict:
    return {"name": "A", "commands": [{"schema_key": "labOrder"}], **extra}


def test_quickpick_is_one_plan_or_procedure_command() -> None:
    fields, error = validate_payload(_body(kind="quickpick", show_in_panel=True))
    assert error is None and fields is not None
    assert fields["kind"] == "quickpick" and fields["show_in_panel"] is True

    _, error = validate_payload(_body(kind="quickpick", commands=[{"schema_key": "plan"}, {"schema_key": "plan"}]))
    assert error == "A quickpick holds exactly one command"

    _, error = validate_payload(_body(kind="quickpick", commands=[{"schema_key": "assess"}]))
    assert error == "Assess can't be added to a quickpick"


def test_order_set_rules_and_template_only_fields() -> None:
    fields, error = validate_payload(
        _body(
            kind="order_set",
            commands=[{"schema_key": "assess"}, {"schema_key": "labOrder", "fields": {"comment": "x", "junk": 1}}],
            note_types=[{"unique_identifier": "u1"}],
            diagnosis_sources=[{"code": "n18", "include_children": True}],
        )
    )
    assert error is None and fields is not None
    assert fields["note_types"] == []  # note-type insertion is for templates
    assert fields["commands"][1]["fields"] == {"comment": "x"}
    assert fields["diagnosis_sources"] == [{"code": "N18", "display": "", "include_children": True}]

    _, error = validate_payload(_body(kind="order_set", show_in_menu=False, show_in_panel=False))
    assert error == 'Turn on at least one place it shows up: the "/" menu, or Assess and Diagnose'


def test_templates_ignore_panel_and_diagnoses() -> None:
    fields, _ = validate_payload(
        {"name": "A", "commands": [{"schema_key": "hpi"}], "show_in_panel": True, "diagnosis_sources": [{"code": "E11"}]}
    )
    assert fields is not None
    assert fields["show_in_panel"] is False and fields["diagnosis_sources"] == []


def test_unknown_kind() -> None:
    assert validate_payload(_body(kind="bundle")) == (None, "Unknown kind 'bundle'")


# ── Diagnoses ────────────────────────────────────────────────────────


def test_clean_sources_dedupes() -> None:
    assert clean_sources([{"code": "e11.9"}, {"code": "E11.9"}, "x", {"code": ""}]) == [
        {"code": "E11.9", "display": "", "include_children": False}
    ]


def test_match_codes_without_umls_for_exact_codes() -> None:
    codes, error = match_codes([{"code": "E11.9", "include_children": False}], {})
    assert (codes, error) == (["E119"], None)


def test_match_codes_expands_headings(mocker: MagicMock) -> None:
    expand = mocker.patch("charting_tools.diagnoses.expand_icd10", return_value=["N18", "N181", "N186"])
    codes, error = match_codes([{"code": "N18", "include_children": True}], {"UMLS_API_KEY": "k"})
    expand.assert_called_once_with("N18", "k")
    assert codes == ["N18", "N181", "N186"] and error is None


def test_match_codes_keeps_stored_when_umls_down_and_unchanged(mocker: MagicMock) -> None:
    mocker.patch("charting_tools.diagnoses.expand_icd10", side_effect=UmlsError("down"))
    sources = [{"code": "N18", "display": "", "include_children": True}]
    assert match_codes(sources, {}, sources, ["N18", "N186"]) == (["N18", "N186"], None)
    assert match_codes(sources, {}, [], []) == (None, "down")


def test_matches_normalizes_charted_code() -> None:
    assert matches(["E119"], "e11.9")
    assert not matches(["E119"], "")
    assert not matches(None, "E11.9")


# ── Panel handler ────────────────────────────────────────────────────


def _command_event(event_type: int, fields: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        type=event_type,
        name=EventType.Name(event_type),
        context={"note": {"uuid": NOTE_ID}, "fields": fields or {}},
        target=SimpleNamespace(id=COMMAND_ID),
    )


SECRETS = {"PANEL_TOKEN_SIGNING_KEY": "secret", "CANVAS_INSTANCE_URL": "https://x.canvasmedical.com/"}


@pytest.fixture
def cache(mocker: MagicMock) -> MagicMock:
    store: dict = {}
    fake = MagicMock()
    fake.get.side_effect = store.get
    fake.set.side_effect = lambda key, value, timeout_seconds=None: store.__setitem__(key, value)
    mocker.patch("charting_tools.handlers.command_panel.get_cache", return_value=fake)
    mocker.patch(
        "charting_tools.handlers.command_panel.build_panel_html",
        side_effect=lambda base, token, kinds: f"{base}|{token}",
    )
    fake.kinds = mocker.patch("charting_tools.handlers.command_panel.panel_kinds", return_value=["quickpick", "order_set"])
    fake.store = store
    return fake


def test_find_icd10_shapes() -> None:
    assert find_icd10({"condition": {"extra": {"coding": [{"system": "ICD-10", "code": "E11.9"}]}}}) == "E11.9"
    assert find_icd10({"diagnose": {"icd10_code": "N18.6"}}) == "N18.6"
    assert find_icd10({"narrative": "none"}) is None


def test_panel_attached_once_and_code_stored(cache: MagicMock) -> None:
    event = _command_event(EventType.DIAGNOSE_COMMAND__POST_ORIGINATE, {"diagnose": {"icd10_code": "E11.9"}})
    effects = DiagnosePanel(event=event, secrets=SECRETS).compute()
    assert [e.type for e in effects] == [EffectType.SET_COMMAND_CUSTOM_HTML]
    html = payload(effects[0])["data"]["custom_html"]
    base, token = html.split("|", 1)
    assert base == "https://x.canvasmedical.com"
    assert verify_token(token, "secret") == (NOTE_ID, COMMAND_ID)
    assert cache.store[f"charting_tools_icd10:{COMMAND_ID}"] == "E11.9"

    again = DiagnosePanel(event=_command_event(EventType.DIAGNOSE_COMMAND__POST_UPDATE), secrets=SECRETS).compute()
    assert again == []


def test_panel_needs_both_settings(cache: MagicMock) -> None:
    event = _command_event(EventType.ASSESS_COMMAND__POST_ORIGINATE)
    assert AssessPanel(event=event, secrets={"PANEL_TOKEN_SIGNING_KEY": "secret"}).compute() == []
    assert AssessPanel(event=event, secrets={"CANVAS_INSTANCE_URL": "https://x"}).compute() == []


def test_panel_attached_for_quick_adds_without_quickpicks_or_order_sets(cache: MagicMock) -> None:
    cache.kinds.return_value = []
    effects = AssessPanel(event=_command_event(EventType.ASSESS_COMMAND__POST_ORIGINATE), secrets=SECRETS).compute()
    assert [e.type for e in effects] == [EffectType.SET_COMMAND_CUSTOM_HTML]


def test_panel_kinds_lists_only_kinds_with_items(mocker: MagicMock) -> None:
    from charting_tools.panel import panel_kinds

    query = mocker.patch("charting_tools.panel.NoteTemplate.objects.filter")
    query.return_value.values_list.return_value.distinct.return_value = ["order_set"]
    assert panel_kinds() == ["order_set"]
    assert query.call_args.kwargs == {"active": True, "show_in_panel": True, "kind__in": ("quickpick", "order_set")}
    query.return_value.values_list.return_value.distinct.return_value = ["order_set", "quickpick"]
    assert panel_kinds() == ["quickpick", "order_set"]


@pytest.mark.parametrize(
    ("kinds", "tabs"),
    [(["quickpick"], ["quickpick"]), (["order_set"], ["order_set"]), (["quickpick", "order_set"], ["quickpick", "order_set"])],
)
def test_panel_renders_a_tab_per_kind(mocker: MagicMock, kinds: list, tabs: list) -> None:
    import re
    from pathlib import Path

    from django.template import Context, Engine

    from charting_tools.panel import build_panel_html

    source = (Path(__file__).parent.parent / "charting_tools/templates/command_panel.html").read_text()
    mocker.patch("charting_tools.panel.render_to_string", side_effect=lambda path, ctx: Engine().from_string(source).render(Context(ctx)))
    html = build_panel_html("https://x.canvasmedical.com", "tok", kinds)
    assert re.findall(r'class="tab" data-tab="(\w+)"', html) == tabs
    # The quick adds show whatever tabs there are.
    quick = re.findall(r'class="quick" data-command="(\w+)"', html)
    assert quick == ["plan", "refer", "labOrder", "imagingOrder", "orderDme", "prescribe", "instruct", "perform"]
    assert "panel/quick-add" in html.replace("\\u002D", "-").replace("\\u002F", "/")


def test_panel_is_rewritten_with_a_fresh_token_just_before_commit(cache: MagicMock) -> None:
    # Canvas keeps a committed command's custom HTML but won't change it, so the
    # last chance to give the panel a fresh token is while it's still staged.
    first = AssessPanel(event=_command_event(EventType.ASSESS_COMMAND__POST_ORIGINATE), secrets=SECRETS).compute()
    assert len(first) == 1
    again = AssessPanel(event=_command_event(EventType.ASSESS_COMMAND__POST_UPDATE), secrets=SECRETS).compute()
    assert again == []  # already attached
    effects = AssessPanel(event=_command_event(EventType.ASSESS_COMMAND__PRE_COMMIT), secrets=SECRETS).compute()
    assert [e.type for e in effects] == [EffectType.SET_COMMAND_CUSTOM_HTML]
    assert payload(effects[0])["data"]["custom_html"]  # a panel, not cleared


# ── Panel routes ─────────────────────────────────────────────────────


def _patch_panel_note(mocker: MagicMock, note: object) -> None:
    """The panel's note, read with or without its body."""
    query = mocker.patch("charting_tools.api.panel_api.Note.objects.filter")
    query.return_value.first.return_value = note
    mocker.patch("charting_tools.api.panel_api.Note.objects.defer").return_value.filter = query


def _panel_api(mocker: MagicMock, token: str | None, extra: dict | None = None, charted: str = "E11.9") -> PanelAPI:
    api = object.__new__(PanelAPI)
    api.request = MagicMock()
    params = {"token": token} if token else {}
    params.update(extra or {})
    # Every panel call is a POST with the token and parameters in a JSON body.
    api.request.json.return_value = params
    api.request.query_params = {}
    api.secrets = {"PANEL_TOKEN_SIGNING_KEY": "secret"}
    api.environment = {}
    mocker.patch("charting_tools.api.panel_api.get_cache").return_value.get.return_value = charted
    # The command the token was signed for is still being charted, on an open note.
    live = mocker.patch("charting_tools.api.panel_api.Command.objects.filter")
    live.return_value.exclude.return_value.exists.return_value = True
    mocker.patch("charting_tools.api.panel_api.note_is_open", return_value=True)
    # No preferred lab unless a test sets one.
    mocker.patch("charting_tools.api.panel_api.preferred_lab_partner_id", return_value=None)
    # No Assessment behind the panel's command unless a test sets one.
    mocker.patch("charting_tools.api.panel_api.assessment_for", return_value=None)
    mocker.patch("charting_tools.api.panel_api.assessment_ref", return_value=None)
    return api


def _body_of(response: object) -> dict:
    return json.loads(response.content)  # type: ignore[attr-defined]


def test_panel_rejects_bad_token(mocker: MagicMock) -> None:
    [response] = _panel_api(mocker, "forged.token").catalog()
    assert response.status_code == 401
    [response] = _panel_api(mocker, None).apply()
    assert response.status_code == 401


def _note() -> SimpleNamespace:
    return SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None)


def _patch_panel_rows(mocker: MagicMock, rows: list) -> MagicMock:
    query = mocker.patch("charting_tools.api.panel_api.NoteTemplate.objects.filter")
    query.return_value = rows
    query.return_value_order = query.return_value
    return query


def test_catalog_lists_conditions_groups_and_added(mocker: MagicMock) -> None:
    _patch_panel_note(mocker, _note())
    mocker.patch(
        "charting_tools.api.panel_api.note_diagnoses",
        return_value=[{"code": "N186", "label": "ESRD"}, {"code": "I509", "label": "Heart failure"}],
    )
    mocker.patch("charting_tools.api.panel_api.added_quickpicks", return_value={"q2"})
    query = mocker.patch("charting_tools.api.panel_api.NoteTemplate.objects.filter")
    query.return_value.order_by.return_value = [
        make_template(template_id="q1", kind="quickpick", name="CMP", diagnosis_match_codes=["E119", "N186"],
                      diagnosis_sources=[{"code": "N18", "include_children": True}], commands=[{"schema_key": "labOrder"}]),
        make_template(template_id="q2", kind="quickpick", name="Nephrology", diagnosis_match_codes=["N186"],
                      commands=[{"schema_key": "refer"}], tags=["Nephrology clinic"]),
        make_template(template_id="o1", kind="order_set", name="CKD", commands=[{}, {}]),
        make_template(template_id="t1", kind="template", name="Annual"),
    ]
    [response] = _panel_api(mocker, sign_token(NOTE_ID, "cmd1", "secret")).catalog()
    body = _body_of(response)
    # The charted code isn't on the note yet, so it leads the conditions.
    assert [c["code"] for c in body["conditions"]] == ["E119", "N186", "I509"]
    by_id = {i["id"]: i for i in body["items"]}
    assert set(by_id) == {"q1", "q2", "o1"}
    assert by_id["q1"]["group"] == "labs" and by_id["q1"]["conditions"] == ["E119", "N186"]
    assert by_id["q1"]["diagnoses"] == ["N18 (all)"] and by_id["q1"]["added"] is False
    assert by_id["q2"]["group"] == "referrals" and by_id["q2"]["added"] is True
    assert by_id["q2"]["tags"] == ["Nephrology clinic"] and by_id["q1"]["tags"] == []
    assert by_id["o1"]["group"] == ""
    assert by_id["q1"]["lab_partners"] == [] and by_id["o1"]["lab_partners"] == []


def _lab(template_id: str, test_code: str, fasting: bool = False, comment: str = "") -> SimpleNamespace:
    fields = {"lab_partner": {"id": "lp1"}, "tests": [{"code": test_code}]}
    if fasting:
        fields["fasting_required"] = True
    if comment:
        fields["comment"] = comment
    return make_template(template_id=template_id, kind="quickpick", diagnosis_match_codes=["E119", "N186"],
                         commands=[{"schema_key": "labOrder", "fields": fields}])


class _Tests(list):
    """Stands in for LabPartnerTest rows: every requested code exists."""

    def count(self) -> int:
        return len(self)


def _stub_lab_catalog(mocker: MagicMock) -> None:
    module = "canvas_sdk.commands.commands.lab_order"
    mocker.patch(f"{module}.LabPartner.objects.filter").return_value.values.return_value.first.return_value = {
        "id": "lp1", "dbid": 1, "electronic_ordering_enabled": False
    }

    def tests(*args: object, **kwargs: object) -> MagicMock:
        q = args[0]
        codes = [v for child in q.children for k, v in [child] if k == "order_code__in"][0]
        chain = MagicMock()
        chain.values_list.return_value = _Tests((f"id-{c}", c) for c in codes)
        return chain

    mocker.patch(f"{module}.LabPartnerTest.objects.filter", side_effect=tests)


def _apply(mocker: MagicMock, rows: list, ids: str, conditions: str = "", added: set | None = None) -> list:
    _stub_lab_catalog(mocker)
    mocker.patch("charting_tools.api.panel_api.NoteTemplate.objects.filter", return_value=rows)
    _patch_panel_note(mocker, _note())
    mocker.patch("charting_tools.api.panel_api.added_quickpicks", return_value=added or set())
    mocker.patch("charting_tools.insertion.resolve", return_value={})
    extra = {"ids": ids}
    if conditions:
        extra["conditions"] = conditions
    return _panel_api(mocker, sign_token(NOTE_ID, "cmd1", "secret"), extra).apply()


def test_selected_labs_merge_into_one_order(mocker: MagicMock) -> None:
    rows = [_lab("q1", "CMP", comment="AM"), _lab("q2", "A1C", fasting=True, comment="fasting"),
            make_template(template_id="q3", kind="quickpick", diagnosis_match_codes=["N186"],
                          commands=[{"schema_key": "refer"}])]
    effects = _apply(mocker, rows, "q1,q2,q3", conditions="N18.6")

    batch = payload(effects[0])["data"]
    assert [c["type"] for c in batch["commands"]] == ["ORIGINATE_LAB_ORDER_COMMAND", "ORIGINATE_REFER_COMMAND"]
    lab = batch["commands"][0]["data"]
    assert lab["tests_order_codes"] == ["CMP", "A1C"]
    assert lab["fasting_required"] is True
    assert lab["comment"] == "AM; fasting"
    assert lab["diagnosis_codes"] == ["N186"]  # the chosen condition it matches
    markers = sorted(payload(e)["data"]["key"] for e in effects[1:-1])
    assert markers == ["charting_tools:quickpick:q1", "charting_tools:quickpick:q2", "charting_tools:quickpick:q3"]
    assert _body_of(effects[-1])["added"] == ["q1", "q2", "q3"]


def test_lab_partner_choice_picks_each_quickpicks_tests(mocker: MagicMock) -> None:
    def two_lab(template_id: str, quest: str, labcorp: str) -> SimpleNamespace:
        fields = {"labs": [{"lab_partner": {"id": "lp1", "display": "Quest"}, "tests": [{"code": quest}]},
                           {"lab_partner": {"id": "lp2", "display": "LabCorp"}, "tests": [{"code": labcorp}]}]}
        return make_template(template_id=template_id, kind="quickpick", commands=[{"schema_key": "labOrder", "fields": fields}])

    rows = [two_lab("q1", "Q-CMP", "L-CMP"), two_lab("q2", "Q-A1C", "L-A1C")]
    _stub_lab_catalog(mocker)
    mocker.patch("charting_tools.api.panel_api.NoteTemplate.objects.filter", return_value=rows)
    _patch_panel_note(mocker, _note())
    mocker.patch("charting_tools.api.panel_api.added_quickpicks", return_value=set())
    mocker.patch("charting_tools.insertion.resolve", return_value={})
    effects = _panel_api(mocker, sign_token(NOTE_ID, "cmd1", "secret"), {"ids": "q1,q2", "lab_partner": "lp2"}).apply()
    [lab] = payload(effects[0])["data"]["commands"]
    assert lab["data"]["lab_partner"] == "lp2"
    assert lab["data"]["tests_order_codes"] == ["L-CMP", "L-A1C"]


def test_unmatched_quickpick_uses_charted_code(mocker: MagicMock) -> None:
    rows = [make_template(template_id="q1", kind="quickpick", commands=[{"schema_key": "refer"}])]
    effects = _apply(mocker, rows, "q1", conditions="I50.9")
    assert payload(effects[0])["data"]["commands"][0]["data"]["diagnosis_codes"] == ["E119"]


def test_already_added_quickpicks_are_skipped(mocker: MagicMock) -> None:
    rows = [_lab("q1", "CMP"), _lab("q2", "A1C")]
    effects = _apply(mocker, rows, "q1,q2", added={"q1"})
    assert payload(effects[0])["data"]["commands"][0]["data"]["tests_order_codes"] == ["A1C"]

    [response] = _apply(mocker, rows, "q1,q2", added={"q1", "q2"})
    assert response.status_code == 409


def test_order_set_applies_alone_without_assessment(mocker: MagicMock) -> None:
    order_set = make_template(template_id="o1", kind="order_set",
                              commands=[{"schema_key": "assess"}, {"schema_key": "labOrder"}])
    effects = _apply(mocker, [order_set], "o1")
    batch = payload(effects[0])["data"]
    assert [c["type"] for c in batch["commands"]] == ["ORIGINATE_LAB_ORDER_COMMAND"]
    assert batch["commands"][0]["data"]["diagnosis_codes"] == ["E119"]

    [response] = _apply(mocker, [order_set, _lab("q1", "CMP")], "o1,q1")
    assert response.status_code == 400


def test_apply_ignores_templates(mocker: MagicMock) -> None:
    [response] = _apply(mocker, [make_template(template_id="t1")], "t1")
    assert response.status_code == 409


def test_carry_forward_is_dropped_outside_templates() -> None:
    for kind in ("quickpick", "order_set"):
        fields, _ = validate_payload(_body(kind=kind, commands=[{"schema_key": "plan", "carry_forward": True}]))
        assert fields is not None and fields["commands"][0]["carry_forward"] is False
    fields, _ = validate_payload(_body(commands=[{"schema_key": "plan", "carry_forward": True}]))
    assert fields is not None and fields["commands"][0]["carry_forward"] is True


def test_quickpick_from_the_menu_is_marked_as_added() -> None:
    from charting_tools.insertion import QUICKPICK_MARKER_PREFIX, template_effects

    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None)
    keys = lambda effects: [payload(e)["data"]["key"] for e in effects[1:]]  # noqa: E731
    quickpick = make_template(template_id="q1", kind="quickpick", commands=[{"schema_key": "plan"}])
    assert keys(template_effects(quickpick, note, {}, replace_line=True)) == [f"{QUICKPICK_MARKER_PREFIX}q1"]
    order_set = make_template(template_id="o1", kind="order_set", commands=[{"schema_key": "plan"}])
    assert keys(template_effects(order_set, note, {}, replace_line=True)) == []


def test_insert_ignores_saved_carry_forward_on_order_sets(mocker: MagicMock) -> None:
    from charting_tools.insertion import template_effects

    find = mocker.patch("charting_tools.insertion.find_previous_command")
    mocker.patch("charting_tools.insertion.resolve", return_value={})
    template = make_template(kind="order_set", commands=[{"schema_key": "plan", "carry_forward": True}])
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=1, datetime_of_service=None)
    template_effects(template, note, {}, replace_line=True)
    find.assert_not_called()


# ── Quick add ────────────────────────────────────────────────────────

ORIGIN_DASHED = "9a8b7c6d-5e4f-4031-2a1b-2c3d4e5f6a7b"


def _note_with_body() -> SimpleNamespace:
    return SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=7, body=[
        {"type": "text", "value": ""},
        {"type": "command", "value": "hpi", "data": {"command_uuid": "other"}},
        {"type": "text", "value": ""},
        {"type": "command", "value": "assess", "data": {"command_uuid": COMMAND_ID}},
        {"type": "text", "value": ""},
    ])


@pytest.mark.parametrize(
    ("command", "indications_key"),
    [("labOrder", "diagnosis_codes"), ("refer", "diagnosis_codes"), ("imagingOrder", "diagnosis_codes"),
     ("orderDme", "diagnosis_codes"), ("prescribe", "icd10_codes"), ("plan", None), ("instruct", None), ("perform", None)],
)
def test_quick_add_goes_below_the_command_with_its_diagnosis(mocker: MagicMock, command: str, indications_key: str | None) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": command}, charted="N186")
    _patch_panel_note(mocker, _note_with_body())
    effect, response = api.quick_add()
    body = payload(effect)
    assert body["line_number"] == 4  # the line after the Assess
    if indications_key:
        assert body["data"][indications_key] == ["N186"]
    assert response.status_code == 200


def test_quick_add_appends_when_the_command_is_not_in_the_body(mocker: MagicMock) -> None:
    from charting_tools.api.panel_api import line_below

    assert line_below(SimpleNamespace(body=[{"type": "text", "value": ""}]), COMMAND_ID) == -1


def test_quick_add_rejects_other_commands_and_bad_tokens(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    [response] = _panel_api(mocker, token, {"command": "hpi"}).quick_add()
    assert response.status_code == 400
    [response] = _panel_api(mocker, "bad", {"command": "plan"}).quick_add()
    assert response.status_code == 401


# ── Linking to the assessment ───────────────────────────────────────

ASSESSMENT_ID = "5c1f0e2a-6b7d-4e8f-9a0b-1c2d3e4f5a6b"


# Every quick add links to the assessment: Plan, Instruct, and Perform always
# could, and SDK 0.247.0 (KOALA-7603) added orders and prescriptions.
@pytest.mark.parametrize("command", ["plan", "instruct", "perform", "labOrder", "refer", "imagingOrder", "prescribe"])
def test_quick_add_links_to_the_assessment(mocker: MagicMock, command: str) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": command}, charted="N186")
    mocker.patch("charting_tools.api.panel_api.assessment_ref", return_value=(ASSESSMENT_ID, 41))
    _patch_panel_note(mocker, _note_with_body())
    # The SDK checks the Assessment was made in this note.
    mocker.patch("canvas_sdk.commands.commands.assessment_link.Assessment.objects.filter").return_value.exists.return_value = True
    mocker.patch.object(type(api), "_charted", return_value="N186")
    effect, _ = api.quick_add()
    data = payload(effect)["data"]
    assert data.get("assessment_id") == ASSESSMENT_ID


def test_quickpicks_link_to_the_assessment(mocker: MagicMock) -> None:
    rows = [make_template(template_id="q1", kind="quickpick", commands=[{"schema_key": "plan", "fields": {"narrative": "Low salt"}}]),
            _lab("q2", "CMP")]
    mocker.patch("canvas_sdk.commands.commands.assessment_link.Assessment.objects.filter").return_value.exists.return_value = True
    _stub_lab_catalog(mocker)
    mocker.patch("charting_tools.api.panel_api.NoteTemplate.objects.filter", return_value=rows)
    _patch_panel_note(mocker, _note())
    mocker.patch("charting_tools.api.panel_api.added_quickpicks", return_value=set())
    mocker.patch("charting_tools.insertion.resolve", return_value={})
    api = _panel_api(mocker, sign_token(NOTE_ID, "cmd1", "secret"), {"ids": "q1,q2"})
    mocker.patch("charting_tools.api.panel_api.assessment_for", return_value=ASSESSMENT_ID)
    commands = payload(api.apply()[0])["data"]["commands"]
    by_type = {c["type"]: c["data"] for c in commands}
    assert by_type["ORIGINATE_PLAN_COMMAND"]["assessment_id"] == ASSESSMENT_ID
    assert by_type["ORIGINATE_LAB_ORDER_COMMAND"]["assessment_id"] == ASSESSMENT_ID


def test_assessment_for_assess_and_diagnose(mocker: MagicMock) -> None:
    from charting_tools.api.panel_api import assessment_for

    note = SimpleNamespace(dbid=9)
    commands = mocker.patch("charting_tools.api.panel_api.Command.objects.filter")
    assessments = mocker.patch("charting_tools.api.panel_api.Assessment.objects.filter")
    live = assessments.return_value

    # Assess: anchored straight to its Assessment.
    commands.return_value.values_list.return_value.first.return_value = ("assessment", 41)
    live.filter.return_value.values_list.return_value.first.return_value = (ASSESSMENT_ID, 41)
    assert assessment_for(note, COMMAND_ID) == ASSESSMENT_ID
    assert live.filter.call_args.kwargs == {"dbid": 41}

    # Diagnose: anchored to its Condition, whose Assessment in this note is used.
    commands.return_value.values_list.return_value.first.return_value = ("condition", 77)
    live.filter.return_value.order_by.return_value.values_list.return_value.first.return_value = (ASSESSMENT_ID, 88)
    assert assessment_for(note, COMMAND_ID) == ASSESSMENT_ID
    assert live.filter.call_args.kwargs == {"condition_id": 77}
    assert assessments.call_args.kwargs == {"note_id": 9, "entered_in_error__isnull": True, "deleted": False}

    # Not saved yet, or anchored to something else: no link.
    commands.return_value.values_list.return_value.first.return_value = None
    assert assessment_for(note, COMMAND_ID) is None


# ── Panel token and note state ──────────────────────────────────────


def test_token_in_the_url_is_ignored(mocker: MagicMock) -> None:
    api = _panel_api(mocker, None, {"command": "plan"})
    api.request.query_params = {"token": sign_token(NOTE_ID, COMMAND_ID, "secret", 600)}
    [response] = api.quick_add()
    assert response.status_code == 401


def test_token_keeps_working_after_commit_but_not_once_entered_in_error(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "plan"})
    live = mocker.patch("charting_tools.api.panel_api.Command.objects.filter")
    live.return_value.exclude.return_value.exists.return_value = False  # entered in error, or gone
    [response] = api.quick_add()
    assert response.status_code == 401
    kwargs = live.call_args.kwargs
    assert kwargs == {"id": COMMAND_ID, "note__id": NOTE_ID, "entered_in_error__isnull": True}
    assert "state" not in kwargs  # committed is fine; the note being open is what counts


def test_catalog_refuses_a_closed_note(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token)
    _patch_panel_note(mocker, _note())
    mocker.patch("charting_tools.api.panel_api.note_is_open", return_value=False)
    [response] = api.catalog()
    assert response.status_code == 409


@pytest.mark.parametrize("route", ["quick_add", "apply"])
def test_closed_notes_get_nothing_added(mocker: MagicMock, route: str) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "plan", "ids": "q1"})
    _patch_panel_note(mocker, _note_with_body())
    mocker.patch("charting_tools.api.panel_api.note_is_open", return_value=False)
    [response] = getattr(api, route)()
    assert response.status_code == 409


def test_panel_token_lasts_four_hours_and_is_refreshed_before(cache: MagicMock) -> None:
    from charting_tools.handlers import command_panel

    assert command_panel.TOKEN_TTL_SECONDS == 4 * 3600
    assert command_panel.PANEL_REFRESH_SECONDS < command_panel.TOKEN_TTL_SECONDS
    effects = DiagnosePanel(event=_command_event(EventType.DIAGNOSE_COMMAND__POST_ORIGINATE), secrets=SECRETS).compute()
    token = payload(effects[0])["data"]["custom_html"].split("|", 1)[1]
    expiry = int(token.rsplit(".", 1)[0].rsplit("|", 1)[1])
    import time

    assert 4 * 3600 - 60 <= expiry - time.time() <= 4 * 3600


# ── Preferred lab ────────────────────────────────────────────────────

LAB_ITEMS = [
    {"id": "q1", "lab_partners": [{"id": "lp-quest", "display": "Quest Diagnostics"}]},
    {"id": "q2", "lab_partners": [{"id": "lp-labcorp", "display": "LabCorp"}]},
    {"id": "q3", "lab_partners": []},
]


LAB_PARTNERS = [("lp-quest", "Quest Diagnostics"), ("lp-labcorp", "LabCorp"), ("lp-bio", "BioReference")]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("LabCorp", "lp-labcorp"), ("  labcorp ", "lp-labcorp"), ("QUEST DIAGNOSTICS", "lp-quest"),
     ("Sonic", None), ("", None), (None, None)],
)
def test_preferred_lab_matches_an_active_lab_partner_by_name(mocker: MagicMock, value: str | None, expected: str | None) -> None:
    from charting_tools.labs import preferred_lab_partner_id

    query = mocker.patch("charting_tools.labs.PatientMetadata.objects.filter")
    query.return_value.values_list.return_value.first.return_value = value
    partners = mocker.patch("charting_tools.labs.LabPartner.objects.filter")
    partners.return_value.values_list.return_value = LAB_PARTNERS
    assert preferred_lab_partner_id(7) == expected
    assert query.call_args.kwargs == {"patient_id": 7, "key": "preferred_lab"}


def test_panel_preselects_the_preferred_lab_only_when_offered(mocker: MagicMock) -> None:
    from charting_tools.api.panel_api import preferred_lab_partner

    lookup = mocker.patch("charting_tools.api.panel_api.preferred_lab_partner_id", return_value="lp-labcorp")
    assert preferred_lab_partner(SimpleNamespace(patient_id=7), LAB_ITEMS) == "lp-labcorp"
    lookup.return_value = "lp-bio"  # a real lab, but no quickpick has tests for it
    assert preferred_lab_partner(SimpleNamespace(patient_id=7), LAB_ITEMS) is None


def test_preferred_lab_needs_a_patient(mocker: MagicMock) -> None:
    from charting_tools.labs import preferred_lab_partner_id

    query = mocker.patch("charting_tools.labs.PatientMetadata.objects.filter")
    assert preferred_lab_partner_id(None) is None
    query.assert_not_called()


# ── Lab orders created with the lab set ─────────────────────────────


def test_quick_add_lab_is_created_with_the_preferred_lab(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    # A lab chosen in the panel's Lab filter doesn't apply to + Lab.
    api = _panel_api(mocker, token, {"command": "labOrder", "lab_partner": QUEST_ID}, charted="N186")
    _patch_panel_note(mocker, _note_with_body())
    lookup = mocker.patch("charting_tools.api.panel_api.preferred_lab_partner_id", return_value=LABCORP_ID)
    mocker.patch("canvas_sdk.commands.commands.lab_order.LabPartner.objects.filter").return_value.values.return_value.first.return_value = {
        "id": LABCORP_ID, "dbid": 2, "electronic_ordering_enabled": True}
    effect, _ = api.quick_add()
    assert payload(effect)["data"]["lab_partner"] == LABCORP_ID
    lookup.assert_called_once_with(7)


def test_quick_add_lab_without_a_preferred_lab_has_no_lab(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "labOrder"}, charted="N186")
    _patch_panel_note(mocker, _note_with_body())
    effect, _ = api.quick_add()
    assert payload(effect)["data"].get("lab_partner") in (None, "")


def test_other_quick_adds_dont_look_up_a_lab(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "plan"}, charted="N186")
    _patch_panel_note(mocker, _note_with_body())
    lookup = mocker.patch("charting_tools.api.panel_api.preferred_lab_partner_id")
    api.quick_add()
    lookup.assert_not_called()


def test_panel_quickpicks_dont_fall_back_to_the_preferred_lab(mocker: MagicMock) -> None:
    rows = [make_template(template_id="q1", kind="quickpick", commands=[{"schema_key": "labOrder"}])]
    lookup = mocker.patch("charting_tools.insertion.preferred_lab_partner_id", return_value=LABCORP_ID)
    _apply(mocker, rows, "q1")
    lookup.assert_not_called()


LABCORP_ID = "4b0e2c1a-3d5f-4a6b-8c9d-0e1f2a3b4c5d"
QUEST_ID = "6d2f4e3c-5b7a-4c8d-9e0f-1a2b3c4d5e6f"


def _lab_template(fields: dict) -> SimpleNamespace:
    return make_template(template_id="t1", commands=[{"schema_key": "labOrder", "fields": fields}])


def test_template_lab_order_without_a_lab_gets_the_preferred_lab(mocker: MagicMock) -> None:
    from charting_tools.insertion import build_commands

    mocker.patch("charting_tools.insertion.resolve", return_value={})
    lookup = mocker.patch("charting_tools.insertion.preferred_lab_partner_id", return_value=LABCORP_ID)
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=7, datetime_of_service=None)
    [built] = build_commands(_lab_template({}), note)
    assert str(built.command.lab_partner) == LABCORP_ID
    lookup.assert_called_once_with(7)


def test_template_lab_order_uses_the_preferred_labs_tests(mocker: MagicMock) -> None:
    from charting_tools.insertion import build_commands

    mocker.patch("charting_tools.insertion.resolve", return_value={})
    mocker.patch("charting_tools.insertion.preferred_lab_partner_id", return_value=LABCORP_ID)
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=7, datetime_of_service=None)
    fields = {"labs": [
        {"lab_partner": {"id": QUEST_ID, "display": "Quest"}, "tests": [{"code": "Q-CMP", "display": "CMP"}]},
        {"lab_partner": {"id": LABCORP_ID, "display": "LabCorp"}, "tests": [{"code": "L-CMP", "display": "CMP"}]},
    ]}
    [built] = build_commands(_lab_template(fields), note)
    assert str(built.command.lab_partner) == LABCORP_ID
    assert built.command.tests_order_codes == ["L-CMP"]


def test_lab_chosen_in_the_panel_wins_over_the_preferred_lab(mocker: MagicMock) -> None:
    from charting_tools.insertion import build_commands

    mocker.patch("charting_tools.insertion.resolve", return_value={})
    lookup = mocker.patch("charting_tools.insertion.preferred_lab_partner_id", return_value=LABCORP_ID)
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=7, datetime_of_service=None)
    [built] = build_commands(_lab_template({}), note, lab_partner_id=QUEST_ID)
    assert str(built.command.lab_partner) == QUEST_ID
    lookup.assert_not_called()


def test_no_lab_lookup_without_a_lab_order(mocker: MagicMock) -> None:
    from charting_tools.insertion import build_commands

    mocker.patch("charting_tools.insertion.resolve", return_value={})
    lookup = mocker.patch("charting_tools.insertion.preferred_lab_partner_id")
    note = SimpleNamespace(id=NOTE_ID, dbid=1, patient_id=7, datetime_of_service=None)
    build_commands(make_template(commands=[{"schema_key": "plan"}]), note)
    lookup.assert_not_called()


# ── The code an Assess is charting ──────────────────────────────────


def _command_row(mocker: MagicMock, schema_key: str, data: dict) -> MagicMock:
    query = mocker.patch("charting_tools.note_conditions.Command.objects.filter")
    query.return_value.values_list.return_value.first.return_value = (schema_key, data)
    return query


def test_assess_code_comes_from_its_condition(mocker: MagicMock) -> None:
    from charting_tools.note_conditions import command_icd10

    _command_row(mocker, "assess", {"condition": {"value": 1955, "text": "CKD stage 5"}})
    condition = SimpleNamespace(codings=MagicMock())
    condition.codings.all.return_value = [
        SimpleNamespace(system="http://snomed.info/sct", code="433146000"),
        SimpleNamespace(system="ICD-10", code="N18.5"),
    ]
    conditions = mocker.patch("charting_tools.note_conditions.Condition.objects.filter")
    conditions.return_value.prefetch_related.return_value.first.return_value = condition
    assert command_icd10(COMMAND_ID) == "N185"
    assert conditions.call_args.kwargs == {"dbid": 1955, "entered_in_error__isnull": True}


def test_diagnose_code_comes_from_the_command(mocker: MagicMock) -> None:
    from charting_tools.note_conditions import command_icd10

    _command_row(mocker, "diagnose", {"diagnose": {"value": "Z99.2", "text": "Dialysis"}})
    assert command_icd10(COMMAND_ID) == "Z992"




def test_quick_add_from_an_assess_gets_its_condition_as_indication(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "labOrder"}, charted="")  # nothing cached
    lookup = mocker.patch("charting_tools.api.panel_api.command_icd10", return_value="Z992")
    _patch_panel_note(mocker, _note_with_body())
    effect, _ = api.quick_add()
    assert payload(effect)["data"]["diagnosis_codes"] == ["Z992"]
    lookup.assert_called_once_with(COMMAND_ID)


def test_assess_diagnosing_a_new_condition_charts_its_code(mocker: MagicMock) -> None:
    from charting_tools.note_conditions import command_icd10

    _command_row(mocker, "assess", {"condition": {"value": "R54", "text": "Frailty"}})
    conditions = mocker.patch("charting_tools.note_conditions.Condition.objects.filter")
    assert command_icd10(COMMAND_ID) == "R54"
    conditions.assert_not_called()


def test_quick_add_dme_gets_its_indication_but_no_assessment_link(mocker: MagicMock) -> None:
    # SDK 0.254.0's Order DME takes indications but no assessment link.
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "orderDme"}, charted="N186")
    mocker.patch("charting_tools.api.panel_api.assessment_ref", return_value=(ASSESSMENT_ID, 41))
    _patch_panel_note(mocker, _note_with_body())
    effect, _ = api.quick_add()
    assert effect.type == EffectType.ORIGINATE_ORDER_DME_COMMAND
    data = payload(effect)["data"]
    assert data["diagnosis_codes"] == ["N186"]
    assert "assessment_id" not in data and "assessment" not in data


# ── Ordering provider / prescriber from the note ────────────────────

NOTE_PROVIDER = SimpleNamespace(id="e110d34f-e9a3-4878-a052-650eb5f54681")


@pytest.mark.parametrize(("command", "field"), [
    ("labOrder", "ordering_provider_key"), ("imagingOrder", "ordering_provider_key"),
    ("orderDme", "ordering_provider_key"), ("prescribe", "prescriber_id"),
])
def test_quick_add_orders_from_the_notes_provider(mocker: MagicMock, command: str, field: str) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": command}, charted="N186")
    note = _note_with_body()
    note.provider = NOTE_PROVIDER
    _patch_panel_note(mocker, note)
    effect, _ = api.quick_add()
    data = payload(effect)["data"]
    assert data[field] == NOTE_PROVIDER.id


def test_template_orders_take_the_notes_provider_unless_set(mocker: MagicMock) -> None:
    from canvas_sdk.commands import LabOrderCommand

    from charting_tools.insertion import set_note_provider

    note = SimpleNamespace(provider=NOTE_PROVIDER)
    lab = LabOrderCommand(note_uuid="a" * 32, command_uuid="b" * 32)
    set_note_provider(lab, note)
    assert lab.ordering_provider_key == NOTE_PROVIDER.id

    chosen = LabOrderCommand(note_uuid="a" * 32, command_uuid="c" * 32, ordering_provider_key="someone-else")
    set_note_provider(chosen, note)
    assert chosen.ordering_provider_key == "someone-else"

    orphan = LabOrderCommand(note_uuid="a" * 32, command_uuid="d" * 32)
    set_note_provider(orphan, SimpleNamespace(provider=None))
    assert orphan.ordering_provider_key is None


# ── + Plan: carry forward the last plan for the diagnosis ───────────


def _plans(mocker: MagicMock, plans: list, assessments: dict, codings: list) -> None:
    query = mocker.patch("charting_tools.api.panel_api.Command.objects.filter")
    query.return_value.exclude.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = plans
    mocker.patch("charting_tools.api.panel_api.Assessment.objects.filter").return_value.values_list.return_value = list(assessments.items())
    mocker.patch("charting_tools.api.panel_api.ConditionCoding.objects.filter").return_value.values_list.return_value = codings


def test_last_plan_for_the_diagnosis(mocker: MagicMock) -> None:
    from charting_tools.api.panel_api import last_plan_for

    _plans(mocker,
           plans=[  # newest first
               {"narrative": "BP plan", "assessment": {"value": 11}},
               {"narrative": "Unlinked plan"},
               {"narrative": "Dialysis 3x weekly; recheck labs", "assessment": {"value": 12}},
               {"narrative": "Older CKD plan", "assessment": {"value": 13}},
           ],
           assessments={11: 101, 12: 102, 13: 102},
           codings=[(101, "ICD-10", "I10"), (102, "http://hl7.org/fhir/sid/icd-10-cm", "N18.6"),
                    (102, "http://snomed.info/sct", "433146000")])
    note = SimpleNamespace(dbid=1, patient_id=7)
    assert last_plan_for(note, "N186") == "Dialysis 3x weekly; recheck labs"
    assert last_plan_for(note, "E119") is None
    assert last_plan_for(note, "") is None


def test_plan_caret_adds_the_last_plan_or_says_there_is_none(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "plan", "carry_forward": True}, charted="N186")
    _patch_panel_note(mocker, _note_with_body())
    lookup = mocker.patch("charting_tools.api.panel_api.last_plan_for", return_value="Dialysis 3x weekly")
    effect, _ = api.quick_add()
    assert payload(effect)["data"]["narrative"] == "Dialysis 3x weekly"
    assert lookup.call_args.args[1] == "N186"

    lookup.return_value = None
    [response] = api.quick_add()
    assert response.status_code == 404


def test_carry_forward_fills_a_blank_plan_linked_to_the_assessment(mocker: MagicMock) -> None:
    token = sign_token(NOTE_ID, COMMAND_ID, "secret", 600)
    api = _panel_api(mocker, token, {"command": "plan", "carry_forward": True}, charted="N186")
    _patch_panel_note(mocker, _note_with_body())
    mocker.patch("charting_tools.api.panel_api.last_plan_for", return_value="Dialysis 3x weekly")
    mocker.patch("charting_tools.api.panel_api.assessment_ref", return_value=(ASSESSMENT_ID, 41))
    blank = "f" * 32
    mocker.patch("charting_tools.api.panel_api.blank_linked_plan", return_value=blank)
    effect, response = api.quick_add()
    assert effect.type == EffectType.EDIT_PLAN_COMMAND
    assert payload(effect)["command"] == blank
    assert payload(effect)["data"]["narrative"] == "Dialysis 3x weekly"
    assert json.loads(response.content)["status"] == "updated"


def test_blank_linked_plan_finds_only_an_empty_plan_on_that_assessment(mocker: MagicMock) -> None:
    from charting_tools.api.panel_api import blank_linked_plan

    rows = [
        ("a" * 32, {"narrative": "Already written", "assessment": {"value": 41}}),
        ("b" * 32, {"narrative": "", "assessment": {"value": 99}}),  # another assessment
        ("c" * 32, {"narrative": "  ", "assessment": {"value": 41}}),
    ]
    query = mocker.patch("charting_tools.api.panel_api.Command.objects.filter")
    query.return_value.order_by.return_value.values_list.return_value = rows
    note = SimpleNamespace(dbid=1)
    assert blank_linked_plan(note, 41) == "c" * 32
    assert query.call_args.kwargs["state"] == "staged" and query.call_args.kwargs["committer__isnull"] is True
    assert blank_linked_plan(note, 7) is None
