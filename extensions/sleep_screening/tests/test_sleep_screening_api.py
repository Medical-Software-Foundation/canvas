from unittest.mock import MagicMock, patch

from sleep_screening.handlers import sleep_screening_api as api_mod
from sleep_screening.handlers.sleep_screening_api import SleepScreeningAPI
from sleep_screening.scoring.base import PatientContext


def _api(query=None, body=None, secrets=None):
    api_obj = SleepScreeningAPI.__new__(SleepScreeningAPI)
    api_obj.request = MagicMock()
    api_obj.request.query_params = query or {}
    api_obj.request.json.return_value = body or {}
    api_obj.secrets = secrets or {}
    return api_obj


# --- context ---

def test_context_returns_demographics_json():
    api_obj = _api(query={"patient_id": "p1"})
    with patch("sleep_screening.handlers.sleep_screening_api.build_context",
               return_value=PatientContext(age=66, sex="M", bmi=41.234)):
        resp = api_obj.get_context()
    body = resp[0].content.decode()
    assert '"age": 66' in body
    assert '"bmi": 41.2' in body  # rounded
    assert '"bmi_available": true' in body


def test_context_missing_patient_id_is_bad_request():
    api_obj = _api(query={})
    resp = api_obj.get_context()
    assert resp[0].status_code == 400


# --- app ---

def test_get_app_missing_note_id_bad_request():
    api_obj = _api(query={})
    resp = api_obj.get_app()
    assert resp[0].status_code == 400


def test_get_app_renders_html():
    api_obj = _api(query={"note_id": "n1", "patient_id": "p1"})
    with patch("sleep_screening.handlers.sleep_screening_api.render_to_string",
               return_value="<html>ok</html>") as rts:
        resp = api_obj.get_app()
    assert resp[0].content == b"<html>ok</html>"
    ctx = rts.call_args.args[1]
    assert '"n1"' in ctx["note_id_json"]


# --- commit-instrument ---

def test_commit_instrument_unknown_code_bad_request():
    api_obj = _api(body={"note_id": "n1", "instrument": "NOPE", "responses": {}})
    resp = api_obj.commit_instrument()
    assert resp[0].status_code == 400


def test_commit_instrument_not_installed_404():
    api_obj = _api(body={"note_id": "n1", "instrument": "SLEEP_ESS", "responses": {}})
    with patch("sleep_screening.handlers.sleep_screening_api._committed_instruments", return_value={}), \
         patch("sleep_screening.handlers.sleep_screening_api.Questionnaire") as Q:
        Q.objects.filter.return_value.first.return_value = None
        resp = api_obj.commit_instrument()
    assert resp[0].status_code == 404


def test_commit_instrument_rejects_already_committed():
    api_obj = _api(body={"note_id": "n1", "instrument": "SLEEP_ESS", "responses": {}})
    with patch("sleep_screening.handlers.sleep_screening_api._committed_instruments",
               return_value={"SLEEP_ESS": {"score": 8.0}}):
        resp = api_obj.commit_instrument()
    assert resp[0].status_code == 409


def test_commit_instrument_commits_with_responses():
    api_obj = _api(body={
        "note_id": "n1",
        "instrument": "SLEEP_ESS",
        "responses": {"SLEEP_ESS_Q1": "SLEEP_ESS_Q1_2"},
    })
    # one question with two options; the Q1_2 option should be selected
    opt_a = MagicMock(); opt_a.code = "SLEEP_ESS_Q1_1"
    opt_b = MagicMock(); opt_b.code = "SLEEP_ESS_Q1_2"
    question = MagicMock()
    question.coding = {"code": "SLEEP_ESS_Q1"}
    question.options = [opt_a, opt_b]

    with patch("sleep_screening.handlers.sleep_screening_api._committed_instruments", return_value={}), \
         patch("sleep_screening.handlers.sleep_screening_api.Questionnaire") as Q, \
         patch("sleep_screening.handlers.sleep_screening_api.QuestionnaireCommand") as QC:
        Q.objects.filter.return_value.first.return_value = MagicMock(id="q-1")
        cmd = QC.return_value
        cmd.questions = [question]
        cmd.originate.return_value = "ORIG"
        cmd.edit.return_value = "EDIT"
        cmd.commit.return_value = "COMMIT"
        resp = api_obj.commit_instrument()

    question.add_response.assert_called_once_with(option=opt_b)
    assert resp == ["ORIG", "EDIT", "COMMIT"]


def test_commit_instrument_skips_unanswered_question():
    api_obj = _api(body={
        "note_id": "n1",
        "instrument": "SLEEP_ESS",
        "responses": {},  # nothing answered
    })
    question = MagicMock()
    question.coding = {"code": "SLEEP_ESS_Q1"}
    question.options = [MagicMock(code="SLEEP_ESS_Q1_1")]
    with patch("sleep_screening.handlers.sleep_screening_api._committed_instruments", return_value={}), \
         patch("sleep_screening.handlers.sleep_screening_api.Questionnaire") as Q, \
         patch("sleep_screening.handlers.sleep_screening_api.QuestionnaireCommand") as QC:
        Q.objects.filter.return_value.first.return_value = MagicMock(id="q-1")
        cmd = QC.return_value
        cmd.questions = [question]
        cmd.originate.return_value = "ORIG"
        cmd.edit.return_value = "EDIT"
        cmd.commit.return_value = "COMMIT"
        resp = api_obj.commit_instrument()
    question.add_response.assert_not_called()
    assert resp == ["ORIG", "EDIT", "COMMIT"]


# --- stage-next-steps ---

def test_stage_next_steps_stages_diagnosis_and_unassigned_task():
    api_obj = _api(body={
        "note_id": "n1",
        "selected_diagnoses": ["G47.30"],
        "study_modality": "HSAT",
        "comment": "at-home",
    })
    dx_effect, task_effect = "DX", "TASK"
    with patch("sleep_screening.handlers.sleep_screening_api.DiagnoseCommand") as DX, \
         patch("sleep_screening.handlers.sleep_screening_api.TaskCommand") as TASK, \
         patch("sleep_screening.handlers.sleep_screening_api.TaskAssigner") as TA, \
         patch("sleep_screening.handlers.sleep_screening_api.AssigneeType") as AT:
        DX.return_value.originate.return_value = dx_effect
        TASK.return_value.originate.return_value = task_effect
        resp = api_obj.stage_next_steps()
    assert dx_effect in resp and task_effect in resp
    DX.return_value.originate.assert_called_once()
    assert not DX.return_value.commit.called  # staged, not committed
    assert "HSAT" in TASK.call_args.kwargs["title"]
    assert TASK.call_args.kwargs["note_uuid"] == "n1"
    TA.assert_called_once_with(to=AT.UNASSIGNED)


def test_stage_next_steps_missing_note_id_bad_request():
    api_obj = _api(body={})
    resp = api_obj.stage_next_steps()
    assert resp[0].status_code == 400


def test_stage_next_steps_no_diagnoses_still_stages_task():
    api_obj = _api(body={"note_id": "n1", "selected_diagnoses": [], "study_modality": "PSG"})
    with patch("sleep_screening.handlers.sleep_screening_api.DiagnoseCommand") as DX, \
         patch("sleep_screening.handlers.sleep_screening_api.TaskCommand") as TASK, \
         patch("sleep_screening.handlers.sleep_screening_api.TaskAssigner"), \
         patch("sleep_screening.handlers.sleep_screening_api.AssigneeType"):
        TASK.return_value.originate.return_value = "TASK"
        resp = api_obj.stage_next_steps()
    assert resp == ["TASK"]
    assert not DX.called


def test_commit_instrument_missing_fields_bad_request():
    api_obj = _api(body={"note_id": "", "instrument": ""})
    resp = api_obj.commit_instrument()
    assert resp[0].status_code == 400


# --- get_context bmi none branch ---

def test_context_bmi_none_reports_unavailable():
    api_obj = _api(query={"patient_id": "p1"})
    with patch("sleep_screening.handlers.sleep_screening_api.build_context",
               return_value=PatientContext(age=40, sex="F", bmi=None)):
        resp = api_obj.get_context()
    body = resp[0].content.decode()
    assert '"bmi": null' in body
    assert '"bmi_available": false' in body


# --- _instrument_structure + instruments endpoint ---

def _structure_first(Q):
    """Return the chained .first() mock for the prefetch chain used by
    _instrument_structure: filter(...).prefetch_related(...).first()."""
    return Q.objects.filter.return_value.prefetch_related.return_value.first


def test_instrument_structure_none_when_not_installed():
    with patch("sleep_screening.handlers.sleep_screening_api.Questionnaire") as Q:
        _structure_first(Q).return_value = None
        assert api_mod._instrument_structure("SLEEP_ESS") is None


def test_instrument_structure_reads_questions_and_options():
    opt = MagicMock(name="opt")
    opt.name = "Slight"
    opt.code = "SLEEP_ESS_Q1_1"
    opt.value = "1"
    question = MagicMock()
    question.code = "SLEEP_ESS_Q1"
    question.name = "Sitting and reading"
    question.response_option_set.options.all.return_value = [opt]
    qn = MagicMock()
    qn.name = "Epworth"
    qn.questions.all.return_value = [question]
    with patch("sleep_screening.handlers.sleep_screening_api.Questionnaire") as Q:
        _structure_first(Q).return_value = qn
        struct = api_mod._instrument_structure("SLEEP_ESS")
    assert struct["code"] == "SLEEP_ESS"
    assert struct["questions"][0]["code"] == "SLEEP_ESS_Q1"
    assert struct["questions"][0]["options"][0]["value"] == "1"


def test_instrument_structure_handles_question_without_option_set():
    question = MagicMock()
    question.code = "SLEEP_ESS_Q1"
    question.name = "Q"
    question.response_option_set = None
    qn = MagicMock()
    qn.name = "Epworth"
    qn.questions.all.return_value = [question]
    with patch("sleep_screening.handlers.sleep_screening_api.Questionnaire") as Q:
        _structure_first(Q).return_value = qn
        struct = api_mod._instrument_structure("SLEEP_ESS")
    assert struct["questions"][0]["options"] == []


def test_instruments_endpoint_returns_installed_and_codes():
    api_obj = _api()
    with patch("sleep_screening.handlers.sleep_screening_api._instrument_structure",
               side_effect=lambda code: {"code": code, "questions": []}), \
         patch("sleep_screening.handlers.sleep_screening_api._committed_instruments", return_value={}), \
         patch("sleep_screening.handlers.sleep_screening_api.load_codes",
               return_value=[{"code": "G47.30", "display": "x"}]):
        resp = api_obj.instruments()
    body = resp[0].content.decode()
    assert "SLEEP_STOPBANG" in body
    assert "preselect_dx" in body
    assert "G47.30" in body


def test_instruments_endpoint_skips_uninstalled():
    api_obj = _api()
    with patch("sleep_screening.handlers.sleep_screening_api._instrument_structure",
               return_value=None), \
         patch("sleep_screening.handlers.sleep_screening_api._committed_instruments", return_value={}), \
         patch("sleep_screening.handlers.sleep_screening_api.load_codes", return_value=[]):
        resp = api_obj.instruments()
    body = resp[0].content.decode()
    assert '"instruments": []' in body


def test_instruments_endpoint_marks_committed():
    api_obj = _api(query={"note_id": "note-uuid"})
    committed = {"SLEEP_ESS": {"score": 8.0, "band": "Normal",
                               "narrative": "Epworth total 8 (Normal).", "abnormal": False}}
    with patch("sleep_screening.handlers.sleep_screening_api._instrument_structure",
               side_effect=lambda code: {"code": code, "questions": []}), \
         patch("sleep_screening.handlers.sleep_screening_api._committed_instruments", return_value=committed), \
         patch("sleep_screening.handlers.sleep_screening_api.load_codes", return_value=[]):
        resp = api_obj.instruments()
    body = resp[0].content.decode()
    # ESS carries a committed block; a non-committed one is null
    assert '"Epworth total 8 (Normal)."' in body
    assert '"committed": null' in body


def test_committed_instruments_no_note_returns_empty():
    with patch("sleep_screening.handlers.sleep_screening_api.Note") as N:
        N.DoesNotExist = Exception
        N.objects.get.side_effect = N.DoesNotExist
        assert api_mod._committed_instruments("missing-uuid") == {}


def test_committed_instruments_blank_uuid_returns_empty():
    assert api_mod._committed_instruments("") == {}


def test_committed_instruments_scores_committed_interview():
    # one committed ESS interview with all-2 answers -> total 16
    resp_objs = []
    for i in range(1, 9):
        r = MagicMock()
        r.response_option.value = "2"
        r.question.code = "SLEEP_ESS_Q" + str(i)
        resp_objs.append(r)
    interview = MagicMock()
    interview.questionnaires.first.return_value = MagicMock(code="SLEEP_ESS")
    interview.patient = MagicMock(id="p1")
    interview.interview_responses.all.return_value = resp_objs

    note = MagicMock(); note.dbid = 55
    qs = MagicMock()
    qs.prefetch_related.return_value = [interview]
    with patch("sleep_screening.handlers.sleep_screening_api.Note") as N, \
         patch("sleep_screening.handlers.sleep_screening_api.Interview") as Iv, \
         patch("sleep_screening.handlers.sleep_screening_api.build_context", return_value=MagicMock()):
        N.objects.get.return_value = note
        Iv.objects.filter.return_value = qs
        out = api_mod._committed_instruments("note-uuid")
    assert "SLEEP_ESS" in out
    assert out["SLEEP_ESS"]["score"] == 16.0
    assert out["SLEEP_ESS"]["abnormal"] is True


def test_committed_instruments_skips_bad_response_rows():
    good = MagicMock()
    good.response_option.value = "1"
    good.question.code = "SLEEP_ESS_Q1"
    none_option = MagicMock()
    none_option.response_option = None
    non_numeric = MagicMock()
    non_numeric.response_option.value = "x"
    non_numeric.question.code = "SLEEP_ESS_Q2"
    interview = MagicMock()
    interview.questionnaires.first.return_value = MagicMock(code="SLEEP_ESS")
    interview.patient = MagicMock(id="p1")
    interview.interview_responses.all.return_value = [good, none_option, non_numeric]

    note = MagicMock(); note.dbid = 55
    qs = MagicMock()
    qs.prefetch_related.return_value = [interview]
    with patch("sleep_screening.handlers.sleep_screening_api.Note") as N, \
         patch("sleep_screening.handlers.sleep_screening_api.Interview") as Iv, \
         patch("sleep_screening.handlers.sleep_screening_api.build_context", return_value=MagicMock()):
        N.objects.get.return_value = note
        Iv.objects.filter.return_value = qs
        out = api_mod._committed_instruments("note-uuid")
    # only the one good answer counted -> ESS total 1
    assert out["SLEEP_ESS"]["score"] == 1.0


def test_committed_instruments_dedupes_and_skips_foreign():
    foreign = MagicMock()
    foreign.questionnaires.first.return_value = MagicMock(code="OTHER")
    note = MagicMock(); note.dbid = 55
    qs = MagicMock()
    qs.prefetch_related.return_value = [foreign]
    with patch("sleep_screening.handlers.sleep_screening_api.Note") as N, \
         patch("sleep_screening.handlers.sleep_screening_api.Interview") as Iv:
        N.objects.get.return_value = note
        Iv.objects.filter.return_value = qs
        assert api_mod._committed_instruments("note-uuid") == {}
