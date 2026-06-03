"""Additional targeted tests for NoteDataExtractor to close coverage gaps.

These complement tests/protocols/test_patient_visit_summary.py (which must not
be edited). Each test here targets a specific previously-uncovered branch:

  - 81-82:   __init__ DB lookups
  - 192:     _format_questionnaires skips a question with an empty answer
  - 290-310: _get_header_context (appointment present AND absent branches)
  - 345-346: _get_reason_for_visit comment-only branch
  - 423:     follow-up date_str "input (around raw)" branch
  - 551-552: get_commands_by_section lazy import + delegation
"""

from unittest.mock import MagicMock, call, patch

from patient_visit_summary.services.note_data_extractor import (
    NoteDataExtractor,
    _annotate_coded_titles,
)

_NDE = "patient_visit_summary.services.note_data_extractor"


# --- _annotate_coded_titles ---


class TestAnnotateCodedTitles:
    def test_attaches_cpt_cvx_suffix_from_coding_field(self):
        entries = [{
            "coding": {
                "text": "DTaP-Hib vaccine (CPT: 90721)",
                "extra": {"coding": [
                    {"code": "90721", "system": "http://www.ama-assn.org/go/cpt"},
                    {"code": "50", "system": "http://hl7.org/fhir/sid/cvx"},
                ]},
            },
        }]
        _annotate_coded_titles(entries, "coding")
        assert entries[0]["coded_title"] == "DTaP-Hib vaccine (CPT 90721, CVX 50)"

    def test_uses_named_field_key(self):
        entries = [{
            "perform": {
                "text": "Biopsy floor mouth (CPT: 41108)",
                "extra": {"coding": [
                    {"code": "41108", "system": "http://www.ama-assn.org/go/cpt"},
                ]},
            },
        }]
        _annotate_coded_titles(entries, "perform")
        assert entries[0]["coded_title"] == "Biopsy floor mouth (CPT 41108)"

    def test_missing_field_yields_empty_title(self):
        entries = [{"notes": "x"}]
        _annotate_coded_titles(entries, "perform")
        assert entries[0]["coded_title"] == ""

    def test_non_dict_entries_skipped(self):
        entries = ["not a dict", 5]
        _annotate_coded_titles(entries, "coding")
        assert entries == ["not a dict", 5]


def _make_extractor(mock_patient, mock_note):
    """Build a NoteDataExtractor bypassing __init__."""
    extractor = NoteDataExtractor.__new__(NoteDataExtractor)
    extractor.patient = mock_patient
    extractor.note = mock_note
    return extractor


# --- __init__ (lines 81-82) ---


class TestInit:
    def test_init_fetches_patient_and_note(self, mock_patient, mock_note):
        with patch(f"{_NDE}.Patient") as mock_patient_cls, patch(
            f"{_NDE}.Note"
        ) as mock_note_cls:
            mock_patient_cls.objects.get.return_value = mock_patient
            mock_note_cls.objects.get.return_value = mock_note

            extractor = NoteDataExtractor(patient_id="patient-123", note_id="456")

        assert extractor.patient is mock_patient
        assert extractor.note is mock_note
        assert mock_patient_cls.objects.get.mock_calls == [call(id="patient-123")]
        assert mock_note_cls.objects.get.mock_calls == [call(id="456")]


# --- _format_questionnaires: empty answer skipped (line 192) ---


class TestFormatQuestionnairesEmptyAnswer:
    def test_question_with_empty_answer_is_skipped(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        # A MULT question with nothing selected yields answer="" -> skipped (192).
        # A TXT question with a real answer is kept, proving only the empty one drops.
        questions = [
            {
                "label": "Symptoms",
                "name": "q_empty",
                "type": "MULT",
                "coding": {"code": "SYM-1"},
            },
            {
                "label": "Notes",
                "name": "q_kept",
                "type": "TXT",
                "coding": {"code": "NOTE-1"},
            },
        ]
        raw_data = [
            {
                "modified": "2025-01-15T10:00:00Z",
                "data": {
                    "questionnaire": {
                        "text": "Q",
                        "extra": {"questions": questions},
                    },
                    "q_empty": [{"text": "Cough", "selected": False}],
                    "q_kept": "Has a real answer",
                },
            }
        ]

        with patch.object(extractor, "_fetch_commands_fields", return_value=raw_data):
            result = extractor._format_questionnaires()

        qa = result[0]["questions_and_answers"]
        assert len(qa) == 1
        assert qa[0]["label"] == "Notes"
        assert qa[0]["answer"] == "Has a real answer"


# --- _get_header_context (lines 290-310) ---


class TestGetHeaderContext:
    def test_with_appointment(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        appt = MagicMock()
        appt.start_time = "2025-01-15T10:00:00Z"
        provider = MagicMock()
        appt.provider = provider
        top_role = MagicMock()
        provider.roles.filter.return_value.order_by.return_value.first.return_value = top_role

        with patch(f"{_NDE}.Appointment") as mock_appt_cls, patch(
            f"{_NDE}.StaffRole"
        ) as mock_staffrole:
            mock_appt_cls.objects.filter.return_value.order_by.return_value.only.return_value.first.return_value = appt
            mock_staffrole.RoleDomain.clinical_domains.return_value = ["clinical"]

            result = extractor._get_header_context()

        assert result["provider"] is provider
        assert result["provider_top_role"] is top_role
        assert result["appointment_date"] == "January 15, 2025"
        assert mock_appt_cls.objects.filter.mock_calls[0] == call(note=mock_note)
        provider.roles.filter.assert_called_once_with(domain__in=["clinical"])

    def test_without_appointment_falls_back_to_note(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        mock_note.datetime_of_service = "2025-02-20T08:00:00Z"
        provider = MagicMock()
        mock_note.provider = provider
        top_role = MagicMock()
        provider.roles.filter.return_value.order_by.return_value.first.return_value = top_role

        with patch(f"{_NDE}.Appointment") as mock_appt_cls, patch(
            f"{_NDE}.StaffRole"
        ) as mock_staffrole:
            mock_appt_cls.objects.filter.return_value.order_by.return_value.only.return_value.first.return_value = None
            mock_staffrole.RoleDomain.clinical_domains.return_value = ["clinical"]

            result = extractor._get_header_context()

        assert result["provider"] is provider
        assert result["provider_top_role"] is top_role
        assert result["appointment_date"] == "February 20, 2025"


# --- _get_reason_for_visit: comment-only branch (lines 345-346) ---


class TestGetReasonForVisitCommentOnly:
    def test_comment_only_rfv(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        # _get_reasons_for_visit returns an entry with only a comment, no text.
        with patch.object(
            extractor,
            "_get_reasons_for_visit",
            return_value=[{"text": "", "comment": "Just a comment"}],
        ):
            result = extractor._get_reason_for_visit()

        assert result == "Just a comment"


# --- follow-up date_str "input (around raw)" branch (line 423) ---


class TestFollowUpDateAroundBranch:
    def test_follow_up_input_differs_from_raw_date(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        follow_up = {
            "requested_date": {"date": "2026-04-17", "input": "2 weeks"},
            "coding": {"text": "Recheck"},
            "note_type": {"text": "Office Visit"},
            "comment": "see you then",
        }

        # Drive the real get_template_context but stub everything except followUp.
        def fake_fetch_all(schema_key):
            return [follow_up] if schema_key == "followUp" else []

        with patch.object(extractor, "_get_header_context", return_value={
            "provider": MagicMock(),
            "provider_top_role": MagicMock(),
            "appointment_date": "January 1, 2025",
        }), patch.object(extractor, "_get_reasons_for_visit", return_value=[]), patch.object(
            extractor, "_get_reason_for_visit", return_value=""
        ), patch.object(
            extractor, "_format_ros_or_exam", return_value=[]
        ), patch.object(
            extractor, "_format_questionnaires", return_value=[]
        ), patch.object(
            extractor, "_fetch_commands_fields", return_value=[]
        ), patch.object(
            extractor, "_get_diagnoses_from_structured_assessments", return_value=[]
        ), patch.object(
            extractor, "_fetch_all_commands_data", side_effect=fake_fetch_all
        ):
            context = extractor.get_template_context()

        assert len(context["follow_ups"]) == 1
        assert context["follow_ups"][0]["date"] == "2 weeks (around 2026-04-17)"
        assert context["follow_up_date"] == "2 weeks (around 2026-04-17)"
        assert context["follow_up_rfv"] == "Recheck"
        assert context["follow_up_note_type"] == "Office Visit"


# --- get_commands_by_section lazy import + delegation (lines 551-552) ---


class TestGetCommandsBySection:
    def test_delegates_to_enumerate_sections(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)

        fake_context = {"patient": mock_patient}
        sections = [{"title": "Subjective"}]
        sentinel_result = [{"section": "Subjective", "entries": []}]

        with patch.object(
            extractor, "get_template_context", return_value=fake_context
        ) as mock_ctx, patch(
            "patient_visit_summary.services.command_blocks.enumerate_sections",
            return_value=sentinel_result,
        ) as mock_enumerate:
            result = extractor.get_commands_by_section(sections=sections)

        assert result is sentinel_result
        mock_ctx.assert_called_once_with()
        mock_enumerate.assert_called_once_with(fake_context, sections=sections)


# --- _get_billing_line_items ---


class TestGetBillingLineItems:
    def _item(self, cpt, description="", units=1, modifier_codes=()):
        item = MagicMock()
        item.cpt = cpt
        item.description = description
        item.units = units
        item.modifiers.all.return_value = [MagicMock(code=c) for c in modifier_codes]
        return item

    def _wire(self, mock_note, items):
        qs = (
            mock_note.billing_line_items.filter.return_value
            .order_by.return_value.prefetch_related.return_value
        )
        qs.__iter__ = MagicMock(return_value=iter(items))

    def test_maps_code_description_units(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        self._wire(mock_note, [self._item("99213", "Office visit", 1)])
        assert extractor._get_billing_line_items() == [
            {"code": "99213", "description": "Office visit", "units": 1},
        ]

    def test_appends_modifiers_to_code(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        self._wire(mock_note, [self._item("90686", "Flu vaccine", 1, modifier_codes=["25"])])
        result = extractor._get_billing_line_items()
        assert result[0]["code"] == "90686-25"

    def test_skips_blank_cpt_and_blank_modifier(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        self._wire(mock_note, [
            self._item("  ", "no code"),
            self._item("17000", "Lesion", 1, modifier_codes=["", "59"]),
        ])
        result = extractor._get_billing_line_items()
        assert result == [{"code": "17000-59", "description": "Lesion", "units": 1}]
