"""Tests for group_therapy.api.routes."""

from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

from group_therapy.api.routes import GroupTherapyAPI, _parse_body, _provider_name


# ------------------------------------------------------------------ #
#  _parse_body
# ------------------------------------------------------------------ #
def test_parse_body_uses_request_json():
    request = MagicMock()
    request.json.return_value = {"key": "value"}
    assert _parse_body(request) == {"key": "value"}
    assert request.mock_calls == [call.json()]


def test_parse_body_falls_back_to_body_string():
    request = MagicMock()
    request.json.side_effect = Exception("no json")
    request.body = '{"key": "fallback"}'
    assert _parse_body(request) == {"key": "fallback"}


def test_parse_body_falls_back_to_body_bytes():
    request = MagicMock()
    request.json.side_effect = Exception("no json")
    request.body = b'{"key": "bytes"}'
    assert _parse_body(request) == {"key": "bytes"}


def test_parse_body_returns_empty_on_failure():
    request = MagicMock()
    request.json.side_effect = Exception("fail")
    request.body = "not json"
    assert _parse_body(request) == {}


# ------------------------------------------------------------------ #
#  _provider_name
# ------------------------------------------------------------------ #
@patch("group_therapy.api.routes.Staff")
def test_provider_name_resolves(mock_staff):
    staff = MagicMock()
    staff.first_name, staff.last_name = "Dana", "Wang"
    mock_staff.objects.filter.return_value.first.return_value = staff
    assert _provider_name("s1") == "Dana Wang"


@patch("group_therapy.api.routes.Staff")
def test_provider_name_fallback_when_missing(mock_staff):
    mock_staff.objects.filter.return_value.first.return_value = None
    assert _provider_name("s1") == "Provider"


@patch("group_therapy.api.routes.Staff")
def test_provider_name_fallback_on_error(mock_staff):
    mock_staff.objects.filter.side_effect = AttributeError("boom")
    assert _provider_name("s1") == "Provider"


@patch("group_therapy.api.routes.Staff")
def test_provider_name_custom_default_when_missing(mock_staff):
    # default="" lets callers distinguish "unknown" from a real name
    mock_staff.objects.filter.return_value.first.return_value = None
    assert _provider_name("s1", default="") == ""


# ------------------------------------------------------------------ #
#  handler helper
# ------------------------------------------------------------------ #
def _handler(body=None, query=None, headers=None, secrets=None):
    handler = GroupTherapyAPI()
    handler.request = MagicMock()
    handler.request.json.return_value = body or {}
    handler.request.query_params = query or {}
    handler.request.headers = headers or {}
    handler.secrets = secrets or {}
    return handler


# ------------------------------------------------------------------ #
#  serve_ui
# ------------------------------------------------------------------ #
def test_serve_ui_returns_html():
    handler = _handler(headers={"canvas-logged-in-user-id": "s1"}, secrets={"DEMO_MODE": "false"})
    with (
        patch("group_therapy.api.routes._provider_name", return_value="Dr. A"),
        patch("group_therapy.api.routes.build_modal_html", return_value="<html>x</html>") as mock_html,
    ):
        result = handler.serve_ui()
    assert result[0].html == "<html>x</html>"
    assert mock_html.call_args.kwargs["logged_in_name"] == "Dr. A"
    assert mock_html.call_args.kwargs["logged_in_staff_id"] == "s1"


def test_serve_ui_blank_provider_when_unresolved():
    handler = _handler(headers={"canvas-logged-in-user-id": "s1"}, secrets={})
    with (
        patch("group_therapy.api.routes.Staff") as mock_staff,
        patch("group_therapy.api.routes.build_modal_html", return_value="<html>x</html>") as mock_html,
    ):
        mock_staff.objects.filter.return_value.first.return_value = None  # unresolved
        handler.serve_ui()
    assert mock_html.call_args.kwargs["logged_in_name"] == ""


def test_serve_ui_keeps_real_provider_named_provider():
    # a real staff member named "Provider" must NOT be blanked (sentinel collision)
    handler = _handler(headers={"canvas-logged-in-user-id": "s1"}, secrets={})
    staff = MagicMock()
    staff.first_name, staff.last_name = "Provider", ""
    with (
        patch("group_therapy.api.routes.Staff") as mock_staff,
        patch("group_therapy.api.routes.build_modal_html", return_value="<html>x</html>") as mock_html,
    ):
        mock_staff.objects.filter.return_value.first.return_value = staff
        handler.serve_ui()
    assert mock_html.call_args.kwargs["logged_in_name"] == "Provider"


# ------------------------------------------------------------------ #
#  checkin
# ------------------------------------------------------------------ #
@patch("group_therapy.api.routes.build_checkin_effects")
def test_checkin_checks_in_each_note(mock_checkin):
    mock_checkin.side_effect = lambda nid: ["CI_" + nid]
    handler = _handler(body={"note_ids": ["n1", "n2", ""]})
    result = handler.checkin()
    # one check-in effect per non-empty note id, then a JSON response
    assert result[:2] == ["CI_n1", "CI_n2"]
    assert result[-1].data == {"success": True, "checked_in": 2}


# ------------------------------------------------------------------ #
#  sessions
# ------------------------------------------------------------------ #
def test_sessions_requires_date():
    result = _handler(query={"date": ""}).sessions()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_sessions_invalid_date():
    result = _handler(query={"date": "garbage"}).sessions()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


@patch("group_therapy.api.routes.find_group_sessions")
def test_sessions_returns_sessions(mock_find):
    found = [{"provider_id": "p1", "provider_name": "Dr. A", "start_time": "2026-06-27T10:00:00",
              "patient_count": 2, "roster": []}]
    mock_find.return_value = found
    result = _handler(query={"date": "2026-06-27"}, secrets={}).sessions()
    assert result[0].data == {"sessions": found}
    mock_find.assert_called_once()


# ------------------------------------------------------------------ #
#  patient_conditions
# ------------------------------------------------------------------ #
def test_patient_conditions_requires_patient_id():
    result = _handler(query={"patient_id": ""}).patient_conditions()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


@patch("group_therapy.api.routes.default_condition_id")
@patch("group_therapy.api.routes.active_conditions")
def test_patient_conditions_returns_conditions_and_default(mock_active, mock_default):
    mock_active.return_value = [{"id": "c1", "icd10_code": "F41.1", "display": "GAD"}]
    mock_default.return_value = "c1"
    result = _handler(query={"patient_id": "p1"}).patient_conditions()
    assert result[0].data == {
        "conditions": [{"id": "c1", "icd10_code": "F41.1", "display": "GAD"}],
        "default_id": "c1",
    }


# ------------------------------------------------------------------ #
#  complete_patient
# ------------------------------------------------------------------ #
def test_complete_patient_missing_patient_400():
    handler = _handler(body={"participant": {"id": ""}})
    assert handler.complete_patient()[0].status_code == HTTPStatus.BAD_REQUEST


def test_complete_patient_no_target_note_skipped():
    handler = _handler(body={"participant": {"id": "p1", "status": "present", "target_note_id": ""}})
    result = handler.complete_patient()
    assert result[0].data["action"] == "skipped"


@patch("group_therapy.api.routes.build_no_show_effects")
def test_complete_patient_absent_marks_no_show(mock_no_show):
    mock_no_show.return_value = ["NO_SHOW"]
    handler = _handler(body={
        "participant": {"id": "p1", "status": "absent", "target_note_id": "note-1"},
    })
    result = handler.complete_patient()
    mock_no_show.assert_called_once_with("note-1")
    assert result[0] == "NO_SHOW"
    assert result[1].data["action"] == "no_show"


_DOC = {"billing_mode": "group", "templates": [
    {"name": "Group Therapy", "rfv_codes": ["Group_Therapy"], "cpt_code": "90853", "sections": []},
    {"name": "Group Screening", "rfv_codes": ["GROUP_SCREENING"], "cpt_code": "90832", "sections": []},
]}


@patch("group_therapy.api.routes.load_config", return_value=_DOC)
@patch("group_therapy.api.routes._provider_name")
@patch("group_therapy.api.routes.build_documentation_effects")
def test_complete_patient_documents_into_target(mock_doc, mock_pname, mock_cfg):
    mock_pname.return_value = "Dr. A"
    mock_doc.return_value = ["E1", "E2"]
    handler = _handler(body={
        "provider_id": "prov", "rfv_codes": ["Group_Therapy"], "session_date": "2026-06-27",
        "facilitator": "Dr. A", "duration_minutes": 60, "participant_index": 0,
        "participant": {"id": "p1", "name": "Jo", "status": "present",
                        "target_note_id": "note-9", "condition_id": "cond-1", "needs_checkin": True,
                        "summary_sections": [{"label": "Assessment", "value": "Stable"}],
                        "questionnaires": [{"code": "QUES_0014", "answers": {"q1": "Good"}}]},
    })
    result = handler.complete_patient()
    assert result[:2] == ["E1", "E2"]
    assert result[-1].data["action"] == "documented"
    kwargs = mock_doc.call_args.kwargs
    assert kwargs["target_note_id"] == "note-9"
    assert kwargs["condition_id"] == "cond-1"
    assert kwargs["sign"] is False
    assert kwargs["billing_mode"] == "group"
    assert kwargs["check_in"] is True
    assert kwargs["cpt_code"] == "90853"  # from the matched template
    assert ("Provider", "Dr. A") in kwargs["meta_pairs"]
    assert ("Duration", "60 min") in kwargs["meta_pairs"]
    assert ("Assessment", "Stable") in kwargs["summary_sections"]
    assert kwargs["questionnaire_specs"] == [{"code": "QUES_0014", "answers": {"q1": "Good"}}]


@patch("group_therapy.api.routes.load_config", return_value=_DOC)
@patch("group_therapy.api.routes._provider_name")
@patch("group_therapy.api.routes.build_documentation_effects")
def test_complete_patient_screening_bills_90832(mock_doc, mock_pname, mock_cfg):
    mock_pname.return_value = "Dr. A"
    mock_doc.return_value = ["E1"]
    handler = _handler(body={
        "provider_id": "prov", "rfv_codes": ["GROUP_SCREENING"], "participant_index": 0,
        "participant": {"id": "p1", "name": "Jo", "status": "present", "target_note_id": "note-9",
                        "summary_sections": [{"label": "Active medications", "value": "Sertraline 50 mg"}],
                        "questionnaires": []},
    })
    handler.complete_patient()
    kwargs = mock_doc.call_args.kwargs
    assert kwargs["cpt_code"] == "90832"
    assert ("Active medications", "Sertraline 50 mg") in kwargs["summary_sections"]


@patch("group_therapy.api.routes.question_schema", return_value=[{"name": "q1", "type": "RAD", "options": []}])
@patch("group_therapy.api.routes.load_config")
def test_template_resolves_and_attaches_schema(mock_cfg, mock_schema):
    mock_cfg.return_value = {"billing_mode": "group", "templates": [
        {"name": "Group Note", "rfv_codes": ["Group_Therapy"], "cpt_code": "90853",
         "sections": [{"label": "MSE", "type": "questionnaire", "code": "QUES_0014"},
                      {"label": "Notes", "type": "free_text"}]},
    ]}
    handler = _handler(query={"rfv": "Group_Therapy"})
    data = handler.template()[0].data
    assert data["template"]["cpt_code"] == "90853"
    assert data["template"]["sections"][0]["schema"] == [{"name": "q1", "type": "RAD", "options": []}]
    assert "schema" not in data["template"]["sections"][1]  # free_text untouched


@patch("group_therapy.api.routes.load_config", return_value=_DOC)
def test_template_returns_none_for_unknown_rfv(mock_cfg):
    assert _handler(query={"rfv": "nope"}).template()[0].data["template"] is None


# ------------------------------------------------------------------ #
#  admin endpoints (gated by the ADMIN_STAFF_KEYS plugin variable)
# ------------------------------------------------------------------ #
_ADMIN_SECRETS = {"ADMIN_STAFF_KEYS": "staff-1,staff-2"}
_ADMIN_HEADERS = {"canvas-logged-in-user-id": "staff-1"}


def _admin_handler(**kw):
    kw.setdefault("secrets", _ADMIN_SECRETS)
    kw.setdefault("headers", _ADMIN_HEADERS)
    return _handler(**kw)


def test_serve_admin_returns_html():
    with patch("group_therapy.api.routes.build_admin_html", return_value="<html>admin</html>"):
        result = _admin_handler().serve_admin()
    assert result[0].html == "<html>admin</html>"


@patch("group_therapy.api.routes.load_config", return_value=_DOC)
def test_get_config_returns_document(mock_cfg):
    assert _admin_handler().get_config()[0].data == {"config": _DOC}


@patch("group_therapy.api.routes.save_config")
def test_put_config_saves_valid_document(mock_save):
    cfg = {"billing_mode": "group", "templates": [{"name": "T", "rfv_codes": [], "cpt_code": "", "sections": []}]}
    result = _admin_handler(body={"config": cfg}).put_config()
    mock_save.assert_called_once_with(cfg)
    assert result[0].data == {"success": True}


@patch("group_therapy.api.routes.save_config")
def test_put_config_rejects_invalid_document(mock_save):
    result = _admin_handler(body={"config": {"no": "templates"}}).put_config()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST
    mock_save.assert_not_called()


@patch("group_therapy.api.routes.save_config", return_value=False)
def test_put_config_reports_failure_when_save_unavailable(mock_save):
    cfg = {"templates": []}
    data = _admin_handler(body={"config": cfg}).put_config()[0].data
    assert data["success"] is False
    assert "custom data" in data["error"].lower()


@patch("group_therapy.api.routes.list_questionnaires")
def test_admin_questionnaires_lists(mock_list):
    mock_list.return_value = [{"name": "MSE", "code": "QUES_0014", "use_case": "EXAM"}]
    result = _admin_handler().admin_questionnaires()
    assert result[0].data == {"questionnaires": [{"name": "MSE", "code": "QUES_0014", "use_case": "EXAM"}]}


# ---- admin access gating (ADMIN_STAFF_KEYS variable, fail closed) ----
def test_serve_admin_denied_when_key_unset():
    # fail closed: no ADMIN_STAFF_KEYS -> nobody can open Setup
    with patch("group_therapy.api.routes.build_admin_html", return_value="<html>builder</html>"):
        result = _handler(headers=_ADMIN_HEADERS, secrets={}).serve_admin()
    assert "Access restricted" in result[0].html


def test_serve_admin_denied_for_unlisted_staff():
    with patch("group_therapy.api.routes.build_admin_html", return_value="<html>builder</html>"):
        result = _handler(headers={"canvas-logged-in-user-id": "intruder"}, secrets=_ADMIN_SECRETS).serve_admin()
    assert "Access restricted" in result[0].html  # denied page, not the builder


def test_serve_admin_allowed_for_listed_staff():
    with patch("group_therapy.api.routes.build_admin_html", return_value="<html>builder</html>"):
        result = _admin_handler().serve_admin()
    assert result[0].html == "<html>builder</html>"


_ROOT_KEY = "4150cd20de8a470aa570a852859ac87e"


def test_serve_admin_allows_root_even_when_key_unset():
    # break-glass: the Canvas root staff key is always allowed, ADMIN_STAFF_KEYS unset
    with patch("group_therapy.api.routes.build_admin_html", return_value="<html>builder</html>"):
        result = _handler(headers={"canvas-logged-in-user-id": _ROOT_KEY}, secrets={}).serve_admin()
    assert result[0].html == "<html>builder</html>"


def test_serve_admin_allows_root_when_not_in_admin_keys():
    # root is allowed even if a (non-empty) ADMIN_STAFF_KEYS list omits it
    with patch("group_therapy.api.routes.build_admin_html", return_value="<html>builder</html>"):
        result = _handler(headers={"canvas-logged-in-user-id": _ROOT_KEY},
                          secrets={"ADMIN_STAFF_KEYS": "someone-else"}).serve_admin()
    assert result[0].html == "<html>builder</html>"


def test_get_config_forbidden_for_unlisted_staff():
    result = _handler(headers={"canvas-logged-in-user-id": "intruder"}, secrets=_ADMIN_SECRETS).get_config()
    assert result[0].status_code == HTTPStatus.FORBIDDEN


@patch("group_therapy.api.routes.save_config")
def test_put_config_forbidden_for_unlisted_staff(mock_save):
    result = _handler(headers={"canvas-logged-in-user-id": "intruder"}, secrets=_ADMIN_SECRETS,
                      body={"config": {"templates": []}}).put_config()
    assert result[0].status_code == HTTPStatus.FORBIDDEN
    mock_save.assert_not_called()


@patch("group_therapy.api.routes.list_questionnaires")
def test_admin_questionnaires_forbidden_for_unlisted_staff(mock_list):
    result = _handler(headers={"canvas-logged-in-user-id": "intruder"}, secrets=_ADMIN_SECRETS).admin_questionnaires()
    assert result[0].status_code == HTTPStatus.FORBIDDEN
    mock_list.assert_not_called()


def test_patient_medications_requires_patient_id():
    from http import HTTPStatus
    result = _handler(query={"patient_id": ""}).patient_medications()
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


@patch("group_therapy.api.routes.active_medications")
def test_patient_medications_returns_list(mock_meds):
    mock_meds.return_value = ["Sertraline 50 mg"]
    result = _handler(query={"patient_id": "p1"}).patient_medications()
    assert result[0].data == {"medications": ["Sertraline 50 mg"]}
