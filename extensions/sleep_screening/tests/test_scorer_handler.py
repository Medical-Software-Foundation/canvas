from unittest.mock import MagicMock, patch

from sleep_screening.handlers.scorer_handler import InstrumentScorer


def _handler(command_id="cmd-1"):
    h = InstrumentScorer.__new__(InstrumentScorer)
    h.event = MagicMock()
    h.event.target.id = command_id
    return h


def _interview(code, patient_id="p1", committed=True):
    interview = MagicMock()
    interview.id = "iv-1"
    interview.committer = MagicMock() if committed else None
    interview.questionnaires.first.return_value = MagicMock(code=code) if code else None
    interview.patient = MagicMock(id=patient_id) if patient_id else None
    return interview


def _command_returning(interview):
    command = MagicMock()
    command.anchor_object = interview
    return command


def test_command_not_found_returns_empty():
    h = _handler()
    with patch("sleep_screening.handlers.scorer_handler.Command") as Cmd:
        Cmd.DoesNotExist = Exception
        Cmd.objects.get.side_effect = Cmd.DoesNotExist
        assert h.compute() == []


def test_no_anchor_returns_empty():
    h = _handler()
    with patch("sleep_screening.handlers.scorer_handler.Command") as Cmd:
        Cmd.objects.get.return_value = _command_returning(None)
        assert h.compute() == []


def test_foreign_questionnaire_returns_empty_without_scoring():
    h = _handler()
    interview = _interview("OTHER_CODE")
    with patch("sleep_screening.handlers.scorer_handler.Command") as Cmd, \
         patch("sleep_screening.handlers.scorer_handler.build_context") as bc:
        Cmd.objects.get.return_value = _command_returning(interview)
        assert h.compute() == []
        # cheap gate: never builds patient context for a foreign questionnaire
        bc.assert_not_called()


def test_no_questionnaire_on_interview_returns_empty():
    h = _handler()
    interview = _interview(None)
    with patch("sleep_screening.handlers.scorer_handler.Command") as Cmd:
        Cmd.objects.get.return_value = _command_returning(interview)
        assert h.compute() == []


def test_our_questionnaire_emits_result_with_score_and_abnormal():
    h = _handler()
    interview = _interview("SLEEP_ESS")
    responses = {"SLEEP_ESS_Q" + str(i): 2.0 for i in range(1, 9)}  # total 16 -> abnormal
    fake_effect = MagicMock()
    with patch("sleep_screening.handlers.scorer_handler.Command") as Cmd, \
         patch.object(InstrumentScorer, "_responses", return_value=responses), \
         patch("sleep_screening.handlers.scorer_handler.build_context", return_value=MagicMock()), \
         patch("sleep_screening.handlers.scorer_handler.CreateQuestionnaireResult") as CQR:
        Cmd.objects.get.return_value = _command_returning(interview)
        CQR.return_value.apply.return_value = fake_effect
        effects = h.compute()
    assert effects == [fake_effect]
    kwargs = CQR.call_args.kwargs
    assert kwargs["interview_id"] == "iv-1"
    assert kwargs["score"] == 16.0
    assert kwargs["abnormal"] is True
    assert kwargs["code"] == "SLEEP_ESS_SCORE"
    assert kwargs["code_system"] == "INTERNAL"


def test_scores_with_no_patient_uses_empty_patient_id():
    h = _handler()
    interview = _interview("SLEEP_ISI", patient_id=None)
    with patch("sleep_screening.handlers.scorer_handler.Command") as Cmd, \
         patch.object(InstrumentScorer, "_responses", return_value={}), \
         patch("sleep_screening.handlers.scorer_handler.build_context", return_value=MagicMock()) as bc, \
         patch("sleep_screening.handlers.scorer_handler.CreateQuestionnaireResult"):
        Cmd.objects.get.return_value = _command_returning(interview)
        h.compute()
        assert bc.call_args.args[0] == ""


def test_responses_extracts_question_code_to_value():
    h = _handler()
    interview = MagicMock()
    resp = MagicMock()
    resp.response_option.value = "3"
    resp.question.code = "SLEEP_ISI_Q1"
    interview.interview_responses.all.return_value = [resp]
    assert h._responses(interview) == {"SLEEP_ISI_Q1": 3.0}


def test_responses_skips_rows_with_missing_option_or_question():
    h = _handler()
    interview = MagicMock()
    bad = MagicMock()
    bad.response_option = None
    interview.interview_responses.all.return_value = [bad]
    assert h._responses(interview) == {}


def test_responses_skips_non_numeric_value():
    h = _handler()
    interview = MagicMock()
    resp = MagicMock()
    resp.response_option.value = "not-a-number"
    resp.question.code = "SLEEP_ESS_Q1"
    interview.interview_responses.all.return_value = [resp]
    assert h._responses(interview) == {}
