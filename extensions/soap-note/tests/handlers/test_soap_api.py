from unittest.mock import MagicMock, call, patch

from soap_note.handlers.soap_api import (
    QUESTIONNAIRE_CODE_EXAM,
    QUESTIONNAIRE_CODE_ROS,
    VITALS_FIELD_MAP,
    SoapNoteAPI,
    _originate,
)


MODULE = "soap_note.handlers.soap_api"


def _make_api(query_params=None, body=None):
    """Create a SoapNoteAPI instance with mocked request."""
    handler = SoapNoteAPI.__new__(SoapNoteAPI)
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    handler.request.json.return_value = body
    return handler


# ── _originate helper ─────────────────────────────────────────────────


def test_originate_sets_uuid_and_returns_effect():
    mock_cmd = MagicMock()
    mock_cmd.command_uuid = None
    mock_effect = MagicMock()
    mock_cmd.originate.return_value = mock_effect

    result = _originate(mock_cmd)

    assert mock_cmd.command_uuid is not None
    assert len(mock_cmd.command_uuid) == 36  # UUID format
    assert result is mock_effect
    # originate() called, plus __eq__ from the `is` check above
    assert call.originate() in mock_cmd.mock_calls


# ── get_app ───────────────────────────────────────────────────────────


def test_get_app_missing_note_id():
    handler = _make_api(query_params={"note_id": ""})
    result = handler.get_app()

    assert len(result) == 1
    assert result[0].status_code == 400


def test_get_app_renders_html(mock_note):
    handler = _make_api(query_params={"note_id": "note-uuid-123"})

    with (
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
        patch(f"{MODULE}.render_to_string") as mock_render,
    ):
        mock_note_objects.get.return_value = mock_note
        mock_soap_objects.filter.return_value.first.return_value = None
        mock_render.return_value = "<html>test</html>"

        result = handler.get_app()

        assert mock_note_objects.mock_calls == [call.get(id="note-uuid-123")]
        assert mock_soap_objects.mock_calls == [call.filter(note_id=42), call.filter().first()]
        assert mock_render.mock_calls == [call("templates/soap_note.html", {
            "note_id": "note-uuid-123",
            "note_id_json": '"note-uuid-123"',
            "patient_id_json": mock_render.mock_calls[0][1][1]["patient_id_json"],
            "sections_json": mock_render.mock_calls[0][1][1]["sections_json"],
            "cache_bust": mock_render.mock_calls[0][1][1]["cache_bust"],
        })]
        assert len(result) == 1


# ── _load_questionnaire ──────────────────────────────────────────────


def test_load_questionnaire_not_found():
    handler = _make_api()

    with patch(f"{MODULE}.questionnaire_from_yaml") as mock_yaml:
        mock_yaml.return_value = None

        result = handler._load_questionnaire("test.yml", "CODE", lambda q: q)

        assert mock_yaml.mock_calls == [call("test.yml")]
        assert result[0].status_code == 404


def test_load_questionnaire_success(mock_questionnaire):
    handler = _make_api()

    with (
        patch(f"{MODULE}.questionnaire_from_yaml") as mock_yaml,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
    ):
        mock_yaml.return_value = {"questions": [{"content": "Test", "code": "T1"}]}
        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire

        result = handler._load_questionnaire(
            "test.yml", "CODE", lambda q: {"content": q["content"]}
        )

        assert mock_yaml.mock_calls == [call("test.yml")]
        assert mock_q_objects.mock_calls == [call.filter(code="CODE"), call.filter().first(), call.filter().first().__bool__()]
        content = result[0].content
        assert b"questionnaire_id" in content


# ── ros_questions / exam_questions ────────────────────────────────────


def test_ros_questions_delegates_to_load(mock_ros_config, mock_questionnaire):
    handler = _make_api()

    with (
        patch(f"{MODULE}.questionnaire_from_yaml") as mock_yaml,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
    ):
        mock_yaml.return_value = mock_ros_config
        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire

        result = handler.ros_questions()

        assert mock_yaml.mock_calls == [call("questionnaires/brief_ros.yml")]
        assert mock_q_objects.mock_calls == [
            call.filter(code=QUESTIONNAIRE_CODE_ROS),
            call.filter().first(),
            call.filter().first().__bool__(),
        ]
        content = result[0].content
        assert b"responses" in content
        assert b"Fever" in content


def test_exam_questions_delegates_to_load(mock_exam_config, mock_questionnaire):
    handler = _make_api()

    with (
        patch(f"{MODULE}.questionnaire_from_yaml") as mock_yaml,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
    ):
        mock_yaml.return_value = mock_exam_config
        mock_q_objects.filter.return_value.first.return_value = mock_questionnaire

        result = handler.exam_questions()

        assert mock_yaml.mock_calls == [call("questionnaires/brief_exam.yml")]
        assert mock_q_objects.mock_calls == [
            call.filter(code=QUESTIONNAIRE_CODE_EXAM),
            call.filter().first(),
            call.filter().first().__bool__(),
        ]
        body = result[0].content
        assert b"default_value" in body


# ── save_commands ─────────────────────────────────────────────────────


def test_save_commands_missing_note_uuid():
    handler = _make_api(body={"note_uuid": ""})
    result = handler.save_commands()

    assert result[0].status_code == 400


def test_save_commands_hpi_and_plan(mock_note):
    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "subjective": "Patient has headache",
        "plan": "Take ibuprofen",
    })

    with (
        patch(f"{MODULE}._originate") as mock_orig,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
    ):
        mock_orig.return_value = MagicMock()
        mock_q_objects.filter.return_value = MagicMock(__iter__=lambda s: iter([]))
        mock_note_objects.get.return_value = mock_note

        result = handler.save_commands()

        # HPI + Plan = 2 _originate calls
        assert len(mock_orig.mock_calls) == 2
        assert mock_note_objects.mock_calls == [call.get(id="note-uuid-123")]
        assert mock_soap_objects.mock_calls[0] == call.update_or_create(
            note_id=42,
            defaults={
                "subjective": "Patient has headache",
                "objective": "",
                "assessment": "[]",
                "plan": "Take ibuprofen",
            },
        )

        body = result[0].content
        assert b"commands_created" in body


def test_save_commands_rfv(mock_note):
    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "rfv": "Follow-up visit",
    })

    with (
        patch(f"{MODULE}._originate") as mock_orig,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
    ):
        mock_orig.return_value = MagicMock()
        mock_q_objects.filter.return_value = MagicMock(__iter__=lambda s: iter([]))
        mock_note_objects.get.return_value = mock_note

        result = handler.save_commands()

        # RFV = 1 _originate call
        assert len(mock_orig.mock_calls) == 1
        # Verify it was called with a ReasonForVisitCommand
        cmd_arg = mock_orig.mock_calls[0][1][0]
        assert cmd_arg.comment == "Follow-up visit"


def test_save_commands_vitals(mock_note):
    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "vitals": {"systolic": "120", "diastolic": "80", "pulse": "72", "temperature": "98.6"},
    })

    with (
        patch(f"{MODULE}._originate") as mock_orig,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
    ):
        mock_orig.return_value = MagicMock()
        mock_q_objects.filter.return_value = MagicMock(__iter__=lambda s: iter([]))
        mock_note_objects.get.return_value = mock_note

        result = handler.save_commands()

        assert len(mock_orig.mock_calls) == 1
        cmd_arg = mock_orig.mock_calls[0][1][0]
        assert cmd_arg.blood_pressure_systole == 120
        assert cmd_arg.blood_pressure_diastole == 80
        assert cmd_arg.pulse == 72
        assert cmd_arg.body_temperature == 98.6


def test_save_commands_vitals_invalid_skipped(mock_note):
    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "vitals": {"systolic": "not_a_number"},
    })

    with (
        patch(f"{MODULE}._originate") as mock_orig,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
    ):
        mock_orig.return_value = MagicMock()
        mock_q_objects.filter.return_value = MagicMock(__iter__=lambda s: iter([]))
        mock_note_objects.get.return_value = mock_note

        result = handler.save_commands()

        # Invalid vital skipped, no vitals command
        assert len(mock_orig.mock_calls) == 0


def test_save_commands_diagnose_new(mock_note):
    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "conditions": [{"icd10_code": "J02.9", "narrative": "acute", "status": "stable"}],
    })

    with (
        patch(f"{MODULE}._originate") as mock_orig,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
    ):
        mock_orig.return_value = MagicMock()
        mock_q_objects.filter.return_value = MagicMock(__iter__=lambda s: iter([]))
        mock_note_objects.get.return_value = mock_note

        result = handler.save_commands()

        assert len(mock_orig.mock_calls) == 1
        cmd_arg = mock_orig.mock_calls[0][1][0]
        assert cmd_arg.icd10_code == "J029"
        assert cmd_arg.today_assessment == "acute"


def test_save_commands_assess_existing(mock_note):
    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "conditions": [{"icd10_code": "N39.0", "narrative": "improving", "condition_id": "cond-123", "status": "improved"}],
    })

    with (
        patch(f"{MODULE}._originate") as mock_orig,
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
    ):
        mock_orig.return_value = MagicMock()
        mock_q_objects.filter.return_value = MagicMock(__iter__=lambda s: iter([]))
        mock_note_objects.get.return_value = mock_note

        result = handler.save_commands()

        assert len(mock_orig.mock_calls) == 1
        cmd_arg = mock_orig.mock_calls[0][1][0]
        assert cmd_arg.condition_id == "cond-123"
        assert cmd_arg.narrative == "improving"


def test_save_commands_ros_selections(mock_note):
    mock_q = MagicMock()
    mock_q.id = "ros-q-uuid"
    mock_q.code = QUESTIONNAIRE_CODE_ROS

    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "ros_selections": {"Constitutional": ["Fever"], "Respiratory": ["Cough"]},
    })

    with (
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
        patch(f"{MODULE}.ReviewOfSystemsCommand") as mock_ros_cls,
    ):
        mock_q_objects.filter.return_value = [mock_q]
        mock_note_objects.get.return_value = mock_note
        mock_ros_instance = MagicMock()
        mock_ros_instance.questions = []
        mock_ros_cls.return_value = mock_ros_instance

        result = handler.save_commands()

        # ROS command was constructed
        assert mock_ros_cls.mock_calls[0] == call(
            note_uuid="note-uuid-123",
            questionnaire_id="ros-q-uuid",
            result="ROS reviewed: Constitutional: Fever, Respiratory: Cough",
        )
        assert b"commands_created" in result[0].content


def test_save_commands_exam_findings(mock_note):
    mock_q = MagicMock()
    mock_q.id = "exam-q-uuid"
    mock_q.code = QUESTIONNAIRE_CODE_EXAM

    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "exam_findings": {"Constitutional": "Alert", "Skin": ""},
    })

    with (
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
        patch(f"{MODULE}.PhysicalExamCommand") as mock_exam_cls,
    ):
        mock_q_objects.filter.return_value = [mock_q]
        mock_note_objects.get.return_value = mock_note
        mock_exam_instance = MagicMock()
        mock_exam_instance.questions = []
        mock_exam_cls.return_value = mock_exam_instance

        result = handler.save_commands()

        # Exam command was constructed (Skin was empty, only Constitutional)
        assert mock_exam_cls.mock_calls[0] == call(
            note_uuid="note-uuid-123",
            questionnaire_id="exam-q-uuid",
            result="Constitutional: Alert",
        )
        assert b"commands_created" in result[0].content


def test_save_commands_exam_all_empty_skipped(mock_note):
    handler = _make_api(body={
        "note_uuid": "note-uuid-123",
        "exam_findings": {"Constitutional": "", "Skin": "  "},
    })

    mock_q = MagicMock()
    mock_q.id = "exam-q-uuid"
    mock_q.code = QUESTIONNAIRE_CODE_EXAM

    with (
        patch(f"{MODULE}.Questionnaire.objects") as mock_q_objects,
        patch(f"{MODULE}.Note.objects") as mock_note_objects,
        patch(f"{MODULE}.SoapNoteData.objects") as mock_soap_objects,
        patch(f"{MODULE}.PhysicalExamCommand") as mock_exam_cls,
    ):
        mock_q_objects.filter.return_value = [mock_q]
        mock_note_objects.get.return_value = mock_note

        result = handler.save_commands()

        # No exam command created since all findings are empty
        assert mock_exam_cls.mock_calls == []


# ── search_conditions ─────────────────────────────────────────────────


def test_search_conditions_too_short():
    handler = _make_api(query_params={"q": "a"})
    result = handler.search_conditions()

    assert b"[]" in result[0].content


def test_search_conditions_success():
    handler = _make_api(query_params={"q": "diabetes"})

    with patch(f"{MODULE}.ontologies_http") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"icd10_code": "E119", "icd10_text": "Type 2 diabetes"},
                {"icd10_code": "E109", "icd10_text": "Type 1 diabetes"},
            ]
        }
        mock_http.get_json.return_value = mock_resp

        result = handler.search_conditions()

        assert mock_http.mock_calls == [call.get_json("/icd/condition?search=diabetes"), call.get_json().json()]
        assert b"E119" in result[0].content


def test_search_conditions_api_error():
    handler = _make_api(query_params={"q": "diabetes"})

    with patch(f"{MODULE}.ontologies_http") as mock_http:
        mock_http.get_json.side_effect = RuntimeError("API down")

        result = handler.search_conditions()

        assert b"[]" in result[0].content


# ── patient_conditions ────────────────────────────────────────────────


def test_patient_conditions_no_patient_id():
    handler = _make_api(query_params={"patient_id": ""})
    result = handler.patient_conditions()

    assert b"[]" in result[0].content


def test_patient_conditions_returns_icd10(mock_questionnaire):
    handler = _make_api(query_params={"patient_id": "patient-uuid-456"})

    mock_coding = MagicMock()
    mock_coding.system = "http://hl7.org/fhir/sid/icd-10-cm"
    mock_coding.code = "N390"
    mock_coding.display = "Urinary tract infection"

    mock_cond = MagicMock()
    mock_cond.id = "cond-uuid-111"
    mock_cond.clinical_status = "active"
    mock_cond.codings.all.return_value = [mock_coding]

    with (
        patch(f"{MODULE}.Condition.objects") as mock_cond_objects,
        patch(f"{MODULE}.CodeConstants") as mock_constants,
    ):
        mock_constants.URL_ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
        mock_cond_objects.for_patient.return_value.committed.return_value.prefetch_related.return_value = [mock_cond]

        result = handler.patient_conditions()

        assert mock_cond_objects.mock_calls == [
            call.for_patient("patient-uuid-456"),
            call.for_patient().committed(),
            call.for_patient().committed().prefetch_related("codings"),
        ]
        assert b"N390" in result[0].content
        assert b"cond-uuid-111" in result[0].content


# ── originate_order ───────────────────────────────────────────────────


def test_originate_order_invalid_type():
    handler = _make_api(body={"note_uuid": "note-123", "order_type": "invalid"})
    result = handler.originate_order()

    assert result[0].status_code == 400


def test_originate_order_missing_note_uuid():
    handler = _make_api(body={"note_uuid": "", "order_type": "lab"})
    result = handler.originate_order()

    assert result[0].status_code == 400


def test_originate_order_lab():
    handler = _make_api(body={"note_uuid": "note-123", "order_type": "lab"})

    with patch(f"{MODULE}._originate") as mock_orig:
        mock_orig.return_value = MagicMock()

        result = handler.originate_order()

        assert len(mock_orig.mock_calls) == 1
        assert b"order_created" in result[0].content
        assert b"lab" in result[0].content


def test_originate_order_all_types():
    for order_type in ["lab", "imaging", "refer", "prescribe"]:
        handler = _make_api(body={"note_uuid": "note-123", "order_type": order_type})

        with patch(f"{MODULE}._originate") as mock_orig:
            mock_orig.return_value = MagicMock()
            result = handler.originate_order()

            assert len(mock_orig.mock_calls) == 1
            assert order_type.encode() in result[0].content


# ── Constants ─────────────────────────────────────────────────────────


def test_vitals_field_map_has_all_fields():
    expected_keys = {"systolic", "diastolic", "pulse", "temperature", "respiration", "oxygen", "height", "weight"}
    assert set(VITALS_FIELD_MAP.keys()) == expected_keys


def test_questionnaire_codes_are_strings():
    assert isinstance(QUESTIONNAIRE_CODE_ROS, str)
    assert isinstance(QUESTIONNAIRE_CODE_EXAM, str)
