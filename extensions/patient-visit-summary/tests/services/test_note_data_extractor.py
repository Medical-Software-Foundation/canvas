"""Additional targeted tests for NoteDataExtractor to close coverage gaps.

These complement tests/handlers/test_patient_visit_summary.py (which must not
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

        def fake_fetch_commands_fields(schema_key, *fields):
            if schema_key == "followUp":
                return [{"data": follow_up, "id": "fu-uuid-1"}]
            return []

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
            extractor, "_fetch_commands_fields", side_effect=fake_fetch_commands_fields
        ), patch.object(
            extractor, "_get_diagnoses_from_structured_assessments", return_value=[]
        ), patch.object(
            extractor, "_fetch_all_commands_data", return_value=[]
        ), patch.object(
            extractor, "_fetch_refill_decision_commands_data", return_value=[]
        ), patch.object(
            extractor, "_get_note_diagnoses", return_value=[]
        ), patch.object(
            extractor, "_fetch_unknown_command_data", return_value=[]
        ), patch.object(
            extractor, "_attach_command_uuids"
        ), patch.object(
            extractor, "_attach_command_metadata"
        ):
            context = extractor.get_template_context()

        assert len(context["follow_ups"]) == 1
        assert context["follow_ups"][0]["date"] == "2 weeks (around 2026-04-17)"
        assert context["follow_up_date"] == "2 weeks (around 2026-04-17)"
        assert context["follow_up_rfv"] == "Recheck"
        assert context["follow_up_note_type"] == "Office Visit"
        assert context["follow_ups"][0]["_command_uuid"] == "fu-uuid-1"


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
    def _modifier(self, code, display=""):
        m = MagicMock()
        m.code = code
        m.display = display
        return m

    def _diagnosis_coding(self, code, display, system="ICD-10"):
        c = MagicMock()
        c.code = code
        c.display = display
        c.system = system
        return c

    def _assessment(self, codings, entered_in_error_id=None, condition_entered_in_error_id=None):
        # _get_billing_line_items skips assessments/conditions where
        # entered_in_error_id is set (retracted records must NOT leak into
        # the printed billing block's Related Diagnoses cell). MagicMock
        # auto-creates a non-None descendant for any attribute, so we have
        # to explicitly set these to None for the non-retracted case.
        condition = MagicMock()
        condition.codings.all.return_value = codings
        condition.entered_in_error_id = condition_entered_in_error_id
        assess = MagicMock()
        assess.condition = condition
        assess.entered_in_error_id = entered_in_error_id
        return assess

    def _item(self, cpt, description="", units=1, modifiers=(), assessments=()):
        item = MagicMock()
        item.cpt = cpt
        item.description = description
        item.units = units
        item.modifiers.all.return_value = list(modifiers)
        item.assessments.all.return_value = list(assessments)
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
        assert extractor._get_billing_line_items() == [{
            "code": "99213",
            "cpt": "99213",
            "description": "Office visit",
            "units": 1,
            "modifiers": [],
            "diagnoses": [],
        }]

    def test_appends_modifiers_to_code_with_display(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        self._wire(mock_note, [self._item(
            "90686", "Flu vaccine", 1,
            modifiers=[self._modifier("25", "Significant Eval & Mgmt")],
        )])
        result = extractor._get_billing_line_items()
        assert result[0]["code"] == "90686-25"
        assert result[0]["modifiers"] == [
            {"code": "25", "display": "Significant Eval & Mgmt"},
        ]

    def test_skips_blank_cpt_and_blank_modifier(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        self._wire(mock_note, [
            self._item("  ", "no code"),
            self._item(
                "17000", "Lesion", 1,
                modifiers=[self._modifier("", ""), self._modifier("59", "Distinct Service")],
            ),
        ])
        result = extractor._get_billing_line_items()
        assert len(result) == 1
        assert result[0]["code"] == "17000-59"
        assert result[0]["modifiers"] == [
            {"code": "59", "display": "Distinct Service"},
        ]

    def test_attaches_icd10_diagnoses_from_assessments(self, mock_patient, mock_note):
        extractor = _make_extractor(mock_patient, mock_note)
        # One ICD-10 coding plus a non-ICD coding (should be filtered out),
        # and a duplicate ICD-10 across two assessments (should be deduped).
        self._wire(mock_note, [self._item(
            "99213", "Office visit", 1,
            assessments=[
                self._assessment([
                    self._diagnosis_coding(
                        "E11649", "Type 2 diabetes mellitus with hypoglycemia without coma",
                    ),
                    self._diagnosis_coding("250.00", "Old code", system="ICD-9"),
                ]),
                self._assessment([
                    self._diagnosis_coding(
                        "E11649", "Type 2 diabetes mellitus with hypoglycemia without coma",
                    ),
                    self._diagnosis_coding("K635", "Polyp of colon"),
                ]),
            ],
        )])
        result = extractor._get_billing_line_items()
        # Codes are formatted with a dot after the third character.
        assert result[0]["diagnoses"] == [
            {
                "code": "E11.649",
                "display": "Type 2 diabetes mellitus with hypoglycemia without coma",
            },
            {"code": "K63.5", "display": "Polyp of colon"},
        ]

    def test_retracted_assessment_excluded_from_diagnoses(self, mock_patient, mock_note):
        # When an Assessment has been marked entered-in-error after the
        # billing line item was created, its diagnoses MUST be filtered out —
        # otherwise the retracted ICD-10 lands in the printed PDF that's
        # attached to the chart (REVIEW.md / CLAUDE.md 🔴 rule).
        extractor = _make_extractor(mock_patient, mock_note)
        self._wire(mock_note, [self._item("99213", assessments=[
            self._assessment(
                [self._diagnosis_coding("E1165", "Diabetes with hyperglycemia")],
                entered_in_error_id=42,
            ),
            self._assessment(
                [self._diagnosis_coding("K635", "Polyp of colon")],
            ),
        ])])
        result = extractor._get_billing_line_items()
        # Only the non-retracted Assessment's diagnosis surfaces.
        assert result[0]["diagnoses"] == [{"code": "K63.5", "display": "Polyp of colon"}]

    def test_retracted_condition_excluded_from_diagnoses(self, mock_patient, mock_note):
        # Even when the Assessment is fine, a retracted Condition (the
        # diagnosis was corrected) must be skipped.
        extractor = _make_extractor(mock_patient, mock_note)
        self._wire(mock_note, [self._item("99213", assessments=[
            self._assessment(
                [self._diagnosis_coding("E1165", "Diabetes with hyperglycemia")],
                condition_entered_in_error_id=99,
            ),
            self._assessment(
                [self._diagnosis_coding("K635", "Polyp of colon")],
            ),
        ])])
        result = extractor._get_billing_line_items()
        assert result[0]["diagnoses"] == [{"code": "K63.5", "display": "Polyp of colon"}]


# --- _format_prescription_total_quantity ---


class TestFormatPrescriptionTotalQuantity:
    """Mirrors home-app's ``Prescription.pluralized_quantity_qualifier_description``
    (``api/models/prescription.py:421-428``): singular for 1, pluralized otherwise."""

    def _rx(self, qty, qualifier):
        rx = MagicMock()
        rx.potency_quantity = qty
        rx.medication = MagicMock()
        rx.medication.quantity_qualifier_description = qualifier
        return rx

    def test_singular_when_quantity_is_one(self):
        result = NoteDataExtractor._format_prescription_total_quantity(self._rx(1, "Tablet"))
        assert result == "1 Tablet"

    def test_pluralized_when_quantity_is_not_one(self):
        result = NoteDataExtractor._format_prescription_total_quantity(self._rx(30, "Tablet"))
        assert result == "30 Tablets"

    def test_already_plural_not_double_pluralized(self):
        # "Tablets" already ends in s — don't add another.
        result = NoteDataExtractor._format_prescription_total_quantity(self._rx(30, "Tablets"))
        assert result == "30 Tablets"

    def test_float_quantity_renders_as_int_when_whole(self):
        # 30.0 → "30 Tablets", not "30.0 Tablets".
        result = NoteDataExtractor._format_prescription_total_quantity(self._rx(30.0, "Tablet"))
        assert result == "30 Tablets"

    def test_none_quantity_returns_empty(self):
        rx = MagicMock()
        rx.potency_quantity = None
        rx.medication = None
        assert NoteDataExtractor._format_prescription_total_quantity(rx) == ""

    def test_missing_medication_returns_quantity_only(self):
        rx = MagicMock()
        rx.potency_quantity = 5
        rx.medication = None
        assert NoteDataExtractor._format_prescription_total_quantity(rx) == "5"


# --- _format_prescription_pharmacy ---


class TestFormatPrescriptionPharmacy:
    """Mirrors home-app's ``phone_number`` template filter
    (``api/templatetags/custom_template_filters.py:94-103``)."""

    def _rx(self, name, phone):
        rx = MagicMock()
        rx.pharmacy_name = name
        rx.pharmacy_phone_number = phone
        return rx

    def test_10_digit_phone_formatted(self):
        result = NoteDataExtractor._format_prescription_pharmacy(
            self._rx("CVS", "5551234567"),
        )
        assert result == "CVS (555) 123-4567"

    def test_non_10_digit_phone_passes_through(self):
        # Short / international numbers — don't try to reformat, just emit raw.
        result = NoteDataExtractor._format_prescription_pharmacy(self._rx("CVS", "12345"))
        assert result == "CVS 12345"

    def test_empty_pharmacy_name_returns_empty(self):
        # Match home-app's guard: only render the line when both name+phone exist.
        assert NoteDataExtractor._format_prescription_pharmacy(
            self._rx("", "5551234567"),
        ) == ""

    def test_empty_phone_returns_empty(self):
        assert NoteDataExtractor._format_prescription_pharmacy(self._rx("CVS", "")) == ""


# --- _esc (HTML escape used in reference-data HTML stitching) ---


class TestEsc:
    """The plugin sandbox blocks ``django.utils.html`` so we ship a local
    escape helper. Make sure it covers the OWASP-relevant chars."""

    def test_escapes_angle_brackets(self):
        assert NoteDataExtractor._esc("<script>") == "&lt;script&gt;"

    def test_escapes_ampersand(self):
        assert NoteDataExtractor._esc("a & b") == "a &amp; b"

    def test_escapes_double_quote(self):
        assert NoteDataExtractor._esc('a "quoted"') == "a &quot;quoted&quot;"

    def test_escape_order_is_safe(self):
        # & must be escaped first so a `&lt;` isn't double-escaped to `&amp;lt;`.
        assert NoteDataExtractor._esc("<a>&b") == "&lt;a&gt;&amp;b"

    def test_none_returns_empty(self):
        assert NoteDataExtractor._esc(None) == ""

    def test_non_string_coerced(self):
        assert NoteDataExtractor._esc(5) == "5"


# --- _format_lab_reports_html ---


class TestFormatLabReportsHtml:
    """Renders one or more LabReports as a single ``Reference Data:`` block
    with a Name / Reference / Value / Units table."""

    def _value(self, *, value="10", units="mg/dL", reference="-",
               coding_name=None, abnormal_flag="", test_id=None):
        v = MagicMock()
        v.value = value
        v.units = units
        v.reference_range = reference
        v.abnormal_flag = abnormal_flag
        v.test_id = test_id
        coding = MagicMock()
        coding.name = coding_name
        v.codings.all = MagicMock(return_value=[coding] if coding_name else [])
        return v

    def _report(self, values, tests=None, remarks=None):
        report = MagicMock()
        report.values.all = MagicMock(return_value=values)
        report.tests.all = MagicMock(return_value=tests or [])
        remark_mocks = []
        for text in (remarks or []):
            r = MagicMock()
            r.comment = text
            remark_mocks.append(r)
        report.remarks.all = MagicMock(return_value=remark_mocks)
        return report

    def _extractor(self):
        # Bypass __init__ (which hits the DB) and just exercise the helper.
        return NoteDataExtractor.__new__(NoteDataExtractor)

    def test_renders_reference_data_heading_once(self):
        extractor = self._extractor()
        values = [self._value(coding_name="Glucose")]
        html = extractor._format_lab_reports_html([self._report(values)])
        assert html.count("Reference Data:") == 1

    def test_renders_table_columns(self):
        extractor = self._extractor()
        values = [self._value(coding_name="Glucose", reference="70-100", value="120")]
        html = extractor._format_lab_reports_html([self._report(values)])
        assert "<th>Name</th>" in html
        assert "<th>Reference</th>" in html
        assert "<th>Value</th>" in html
        assert "<th>Units</th>" in html
        assert "Glucose" in html
        assert "70-100" in html
        assert "120" in html

    def test_abnormal_flag_appended_to_value(self):
        # `120 H` for a high reading — flag stitched into the Value column.
        extractor = self._extractor()
        values = [self._value(coding_name="Glucose", value="120", abnormal_flag="H")]
        html = extractor._format_lab_reports_html([self._report(values)])
        assert "120 H" in html

    def test_skips_value_with_empty_value(self):
        # No `value` → don't emit a row (matches home-app
        # lab_review_document.html line 54: `{% if value.value %}`).
        extractor = self._extractor()
        values = [self._value(coding_name="Glucose", value="")]
        html = extractor._format_lab_reports_html([self._report(values)])
        assert html == ""

    def test_falls_back_to_lab_test_name_when_no_coding(self):
        # No LabValueCoding → use the linked LabTest.ontology_test_name.
        extractor = self._extractor()
        test = MagicMock()
        test.dbid = 99
        test.ontology_test_name = "Hemoglobin A1c"
        values = [self._value(value="6.5", coding_name=None, test_id=99)]
        report = self._report(values, tests=[test])
        html = extractor._format_lab_reports_html([report])
        assert "Hemoglobin A1c" in html

    def test_escapes_user_content_in_value_cells(self):
        # Verify HTML escaping flows through — a malicious lab value can't
        # inject markup into the pre-rendered Reference Data HTML.
        extractor = self._extractor()
        values = [self._value(coding_name="<x>", value="<b>10</b>")]
        html = extractor._format_lab_reports_html([self._report(values)])
        assert "&lt;x&gt;" in html
        assert "&lt;b&gt;10&lt;/b&gt;" in html

    def test_multiple_reports_share_one_reference_data_heading(self):
        # When a lab review has multiple reports, the user-facing layout is
        # one `Reference Data:` heading + multiple tables stacked below.
        extractor = self._extractor()
        r1 = self._report([self._value(coding_name="A")])
        r2 = self._report([self._value(coding_name="B")])
        html = extractor._format_lab_reports_html([r1, r2])
        assert html.count("Reference Data:") == 1
        assert html.count("<table") == 2

    def test_no_renderable_values_returns_empty(self):
        # If every report has only empty-value rows, return "" so the renderer
        # doesn't emit a stray empty Reference Data block.
        extractor = self._extractor()
        values = [self._value(value="")]
        assert extractor._format_lab_reports_html([self._report(values)]) == ""

    def test_report_level_comment_prepended_above_table(self):
        # canvas-plugins#1749: LabReportRemark comments render as a `Comment:`
        # line above the values table.
        extractor = self._extractor()
        values = [self._value(coding_name="Glucose")]
        report = self._report(values, remarks=["Specimen slightly hemolyzed."])
        html = extractor._format_lab_reports_html([report])
        assert "<strong>Comment:</strong> Specimen slightly hemolyzed." in html
        # Comment appears before the table.
        assert html.index("Comment:") < html.index("<table")

    def test_multiple_remarks_are_concatenated(self):
        extractor = self._extractor()
        values = [self._value(coding_name="Glucose")]
        report = self._report(values, remarks=["First remark.", "Second remark."])
        html = extractor._format_lab_reports_html([report])
        assert "First remark. Second remark." in html

    def test_comment_renders_even_without_value_rows(self):
        # A report with only a remark (no renderable values) still surfaces
        # its comment rather than being dropped entirely.
        extractor = self._extractor()
        report = self._report([self._value(value="")], remarks=["Pending review."])
        html = extractor._format_lab_reports_html([report])
        assert "Reference Data:" in html
        assert "Pending review." in html
        assert "<table" not in html

    def test_comment_is_html_escaped(self):
        extractor = self._extractor()
        report = self._report([self._value(coding_name="A")], remarks=["<b>x</b>"])
        html = extractor._format_lab_reports_html([report])
        assert "&lt;b&gt;x&lt;/b&gt;" in html

    def test_blank_remarks_skipped(self):
        # Empty/whitespace-only remark comments don't produce a Comment line.
        extractor = self._extractor()
        report = self._report([self._value(coding_name="A")], remarks=["", "   "])
        html = extractor._format_lab_reports_html([report])
        assert "Comment:" not in html


# --- _format_imaging_reports_html (canvas-plugins#1748) ---


class TestFormatImagingReportsHtml:
    """Renders one or more ImagingReports' per-field codings as a single
    ``Reference Data:`` block — one ``<display>: <value>`` line per coding."""

    def _coding(self, *, display="Comment", value="No acute findings."):
        c = MagicMock()
        c.display = display
        c.value = value
        return c

    def _report(self, codings):
        report = MagicMock()
        report.codings.all = MagicMock(return_value=codings)
        return report

    def _extractor(self):
        return NoteDataExtractor.__new__(NoteDataExtractor)

    def test_renders_field_label_and_value(self):
        extractor = self._extractor()
        html = extractor._format_imaging_reports_html(
            [self._report([self._coding(display="Interpretation", value="Normal study.")])]
        )
        assert "Reference Data:" in html
        assert "<strong>Interpretation:</strong> Normal study." in html

    def test_skips_codings_with_empty_value(self):
        extractor = self._extractor()
        html = extractor._format_imaging_reports_html(
            [self._report([self._coding(value="")])]
        )
        assert html == ""

    def test_coding_without_display_renders_value_only(self):
        extractor = self._extractor()
        html = extractor._format_imaging_reports_html(
            [self._report([self._coding(display="", value="Bare value.")])]
        )
        assert "Bare value." in html
        assert "<strong>" not in html

    def test_multiple_reports_share_one_heading(self):
        extractor = self._extractor()
        r1 = self._report([self._coding(display="Comment", value="A")])
        r2 = self._report([self._coding(display="Comment", value="B")])
        html = extractor._format_imaging_reports_html([r1, r2])
        assert html.count("Reference Data:") == 1
        assert "A" in html and "B" in html

    def test_escapes_user_content(self):
        extractor = self._extractor()
        html = extractor._format_imaging_reports_html(
            [self._report([self._coding(display="<x>", value="<b>10</b>")])]
        )
        assert "&lt;x&gt;" in html
        assert "&lt;b&gt;10&lt;/b&gt;" in html


class TestAttachImagingReviewReferenceHtml:
    def test_empty_entries_is_a_no_op(self):
        extractor = NoteDataExtractor.__new__(NoteDataExtractor)
        entries: list[dict] = []
        extractor._attach_imaging_review_reference_html(entries)
        assert entries == []

    def test_entries_without_command_uuid_short_circuit(self):
        # No `_command_uuid` → nothing to join against, so no DB hit and no
        # `_reference_html` stamped.
        extractor = NoteDataExtractor.__new__(NoteDataExtractor)
        entries = [{"foo": "bar"}]
        extractor._attach_imaging_review_reference_html(entries)
        assert "_reference_html" not in entries[0]


# --- _attach_poc_value_rows (patient-template helper) ---


class TestAttachPocValueRows:
    """Stamps ``value_rows`` on each POC Lab Test entry so the Django
    patient template can iterate them — Django can't compute the
    ``test_values|<lowercase label>`` key lookups inline. (Underscore-free
    name because Django blocks attribute access on ``_``-leading names.)"""

    def test_stamps_value_rows_in_template_order(self):
        entry = {
            "template": {
                "text": "Urinalysis",
                "extra": {"fields": [
                    {"label": "Status", "units": ""},
                    {"label": "Glucose", "units": "mg/dL"},
                ]},
            },
            "test_values|status": "active",
            "test_values|glucose": "120",
        }
        NoteDataExtractor._attach_poc_value_rows([entry])
        assert entry["value_rows"] == [
            {"label": "Status", "units": "", "value": "active"},
            {"label": "Glucose", "units": "mg/dL", "value": "120"},
        ]

    def test_blank_values_preserved(self):
        # Canvas shows empty rows with their label — the patient template
        # should too, so a blank reading isn't silently dropped.
        entry = {
            "template": {"extra": {"fields": [{"label": "Color", "units": "-"}]}},
            "test_values|color": "",
        }
        NoteDataExtractor._attach_poc_value_rows([entry])
        assert entry["value_rows"] == [{"label": "Color", "units": "-", "value": ""}]

    def test_no_template_fields_does_not_stamp(self):
        entry = {"template": {"text": "X"}}
        NoteDataExtractor._attach_poc_value_rows([entry])
        assert "value_rows" not in entry

    def test_non_dict_entries_skipped(self):
        # Defensive: a stray non-dict in the list shouldn't crash the helper.
        NoteDataExtractor._attach_poc_value_rows([None, "string", 42])  # no raise


# --- _attach_refill_reason_displays (deny refill / deny change patient text) ---


class TestAttachRefillReasonDisplays:
    def test_translates_known_code(self):
        entry = {"reason_code": "AD"}
        NoteDataExtractor._attach_refill_reason_displays([entry])
        assert entry["reason_display"] == "Refill too soon"

    def test_unknown_code_passes_through(self):
        entry = {"reason_code": "ZZ"}
        NoteDataExtractor._attach_refill_reason_displays([entry])
        assert entry["reason_display"] == "ZZ"

    def test_empty_code_does_not_stamp(self):
        # If a deny command somehow has no reason code (it shouldn't — the
        # home-app schema requires reason OR note), don't stamp an empty
        # `reason_display` — let the template's `{% if %}` skip it.
        entry = {"reason_code": ""}
        NoteDataExtractor._attach_refill_reason_displays([entry])
        assert "reason_display" not in entry

    def test_all_14_codes_match_home_app_source(self):
        # Spot-check that the extractor's copy of REASON_CODE_CHOICES stays
        # in sync with the one in command_blocks (lifted from home-app's
        # deny_refill.py:24-40). Drift here would cause the patient HTML and
        # the Customize & Print HTML to translate the same code differently.
        from patient_visit_summary.services import command_blocks as cb
        assert NoteDataExtractor._REFILL_REASON_CODE_DISPLAYS == cb._REFILL_REASON_CODE_DISPLAYS


# --- Patient-template attribute-access constraint ---


class TestPatientTemplateStampsAreUnderscoreFree:
    """Django blocks attribute access on names starting with ``_`` — any
    extractor stamp the patient-facing template needs to read must NOT use
    the ``_``-prefix convention. These tests lock that in so a future
    contributor doesn't accidentally re-introduce ``_total_quantity`` etc."""

    def test_poc_value_rows_stamp_has_no_underscore_prefix(self):
        entry = {
            "template": {"extra": {"fields": [{"label": "Glucose", "units": "mg/dL"}]}},
            "test_values|glucose": "120",
        }
        NoteDataExtractor._attach_poc_value_rows([entry])
        # Affirmative key — must be present, no prefix.
        assert "value_rows" in entry
        # And the underscore form must NOT exist (would regress to invisible).
        assert "_value_rows" not in entry

    def test_refill_reason_display_stamp_has_no_underscore_prefix(self):
        entry = {"reason_code": "AD"}
        NoteDataExtractor._attach_refill_reason_displays([entry])
        assert "reason_display" in entry
        assert "_reason_display" not in entry

    def test_refill_decision_shown_keys_includes_patient_stamps(self):
        # `_blocks_refill_decision` must list every patient-template stamp in
        # its `shown_keys` set so `extra_blocks` doesn't re-emit them as
        # stray fields in Customize & Print. We probe by feeding an entry
        # that includes the stamps and checking they're rendered exactly
        # once (as the structured TOTAL QUANTITY / DIRECTIONS / PHARMACY /
        # REASON rows), not duplicated as auto-generated fields.
        from patient_visit_summary.services import command_blocks as cb
        entry = {
            "prescribe": {"text": "Med"},
            "response_type": "D",
            "reason_code": "AD",
            "total_quantity": "30 Tablets",
            "directions": "Take 1 daily",
            "pharmacy_display": "CVS",
            "reason_display": "Refill too soon",
        }
        result = cb._blocks_refill_decision("Deny Refill", [entry])
        labels = [b.get("label") for b in result if b.get("kind") == "field"]
        # Each value renders exactly once — no duplicated auto-emitted
        # fields like "TOTAL QUANTITY" appearing twice.
        for label in ("TOTAL QUANTITY", "DIRECTIONS", "PHARMACY", "REASON"):
            assert labels.count(label) == 1, f"{label!r} should render exactly once, got {labels.count(label)}"
        # And no auto-generated label derived from the raw key (which would
        # be "PHARMACY DISPLAY" or "REASON DISPLAY" if the key leaked).
        assert "PHARMACY DISPLAY" not in labels
        assert "REASON DISPLAY" not in labels

    def test_poc_lab_test_shown_keys_includes_value_rows(self):
        # Same guard for the POC builder — `value_rows` must be in the
        # `shown_keys` set so extra_blocks doesn't emit a "VALUE ROWS" field
        # with the list repr as the value.
        from patient_visit_summary.services import command_blocks as cb
        entry = {
            "template": {
                "text": "Glucose",
                "extra": {"fields": [{"label": "Glucose", "units": "mg/dL"}]},
            },
            "test_values|glucose": "120",
            "value_rows": [{"label": "Glucose", "units": "mg/dL", "value": "120"}],
        }
        result = cb._blocks_poc_lab_test("POC Lab Test", [entry])
        labels = [b.get("label") for b in result if b.get("kind") == "field"]
        assert "VALUE ROWS" not in labels


# --- _attach_plugin_command_details (canvas-plugins#1745) ---


class TestAttachPluginCommandDetails:
    """Stamps the registered PluginCommand.label (when the entry has none) and
    _plugin_section on custom-command entries, matching on schema_key or
    command_key."""

    def _extractor(self):
        return NoteDataExtractor.__new__(NoteDataExtractor)

    def _patch_plugin_command(self, rows):
        # Patch PluginCommand.objects.filter(...).values(...) -> rows.
        pc = patch("patient_visit_summary.services.note_data_extractor.PluginCommand")
        mock_pc = pc.start()
        mock_pc.objects.filter.return_value.values.return_value = rows
        return pc

    def test_stamps_label_matched_by_command_key(self):
        extractor = self._extractor()
        entries = [{"_schema_key": "observationSummary"}]
        p = self._patch_plugin_command([
            {"schema_key": "observationSummary_abc123",
             "command_key": "observationSummary",
             "label": "Observation Summary", "section": "objective"},
        ])
        try:
            extractor._attach_plugin_command_details(entries)
        finally:
            p.stop()
        assert entries[0]["label"] == "Observation Summary"

    def test_stamps_label_matched_by_schema_key(self):
        extractor = self._extractor()
        entries = [{"_schema_key": "observationSummary_abc123"}]
        p = self._patch_plugin_command([
            {"schema_key": "observationSummary_abc123",
             "command_key": "observationSummary",
             "label": "Observation Summary", "section": "objective"},
        ])
        try:
            extractor._attach_plugin_command_details(entries)
        finally:
            p.stop()
        assert entries[0]["label"] == "Observation Summary"

    def test_stamps_plugin_section(self):
        extractor = self._extractor()
        entries = [{"_schema_key": "riskAssessment"}]
        p = self._patch_plugin_command([
            {"schema_key": "riskAssessment", "command_key": "riskAssessment",
             "label": "Risk Assessment", "section": "assessment"},
        ])
        try:
            extractor._attach_plugin_command_details(entries)
        finally:
            p.stop()
        assert entries[0]["_plugin_section"] == "assessment"

    def test_stamps_section_even_when_label_present(self):
        # Section routing applies even to entries that carry their own label.
        extractor = self._extractor()
        entries = [{"_schema_key": "observationSummary", "label": "Author Label"}]
        p = self._patch_plugin_command([
            {"schema_key": "observationSummary", "command_key": "observationSummary",
             "label": "Registered Label", "section": "subjective"},
        ])
        try:
            extractor._attach_plugin_command_details(entries)
        finally:
            p.stop()
        # Instance label wins; section is still stamped.
        assert entries[0]["label"] == "Author Label"
        assert entries[0]["_plugin_section"] == "subjective"

    def test_bare_custom_command_is_skipped(self):
        extractor = self._extractor()
        entries = [{"_schema_key": "customCommand"}]
        p = self._patch_plugin_command([])
        try:
            extractor._attach_plugin_command_details(entries)
        finally:
            p.stop()
        assert "label" not in entries[0]
        assert "_plugin_section" not in entries[0]

    def test_no_matching_row_leaves_entry_untouched(self):
        extractor = self._extractor()
        entries = [{"_schema_key": "unknownThing"}]
        p = self._patch_plugin_command([])
        try:
            extractor._attach_plugin_command_details(entries)
        finally:
            p.stop()
        assert "label" not in entries[0]
        assert "_plugin_section" not in entries[0]


# --- _route_custom_commands_to_sections (section-aware printing) ---


class TestRouteCustomCommandsToSections:
    def _extractor(self):
        return NoteDataExtractor.__new__(NoteDataExtractor)

    def test_routes_each_entry_to_its_section_bucket(self):
        extractor = self._extractor()
        subj = {"_schema_key": "a", "_plugin_section": "subjective"}
        obj = {"_schema_key": "b", "_plugin_section": "objective"}
        plan = {"_schema_key": "c", "_plugin_section": "plan"}
        context = {"custom_commands_data": [subj, obj, plan]}
        extractor._route_custom_commands_to_sections(context)
        assert context["custom_commands_subjective"] == [subj]
        assert context["custom_commands_objective"] == [obj]
        assert context["custom_commands_plan"] == [plan]
        # All routed → fallback bucket is now empty.
        assert context["custom_commands_data"] == []

    def test_unknown_and_internal_fall_back(self):
        extractor = self._extractor()
        internal = {"_schema_key": "a", "_plugin_section": "internal"}
        none_section = {"_schema_key": "b"}
        context = {"custom_commands_data": [internal, none_section]}
        extractor._route_custom_commands_to_sections(context)
        assert context["custom_commands_data"] == [internal, none_section]
        # Section buckets exist but are empty.
        assert context["custom_commands_assessment"] == []

    def test_preserves_stamped_uuid_and_metadata(self):
        # Routing redistributes the same dict objects, so any _command_uuid /
        # _metadata already attached upstream survives.
        extractor = self._extractor()
        entry = {
            "_schema_key": "a", "_plugin_section": "history",
            "_command_uuid": "uuid-1", "_metadata": [{"key": "k", "value": "v"}],
        }
        context = {"custom_commands_data": [entry]}
        extractor._route_custom_commands_to_sections(context)
        routed = context["custom_commands_history"][0]
        assert routed is entry
        assert routed["_command_uuid"] == "uuid-1"
        assert routed["_metadata"] == [{"key": "k", "value": "v"}]

    def test_no_custom_commands_key_is_a_no_op(self):
        extractor = self._extractor()
        context: dict = {}
        extractor._route_custom_commands_to_sections(context)
        assert context == {}


# --- _attach_chart_section_review_content (canvas-plugins#1744) ---


class TestAttachChartSectionReviewContent:
    def _extractor(self):
        return NoteDataExtractor.__new__(NoteDataExtractor)

    def test_splits_content_into_section_content_list(self):
        extractor = self._extractor()
        entries = [{"_command_uuid": "uuid1", "section": "conditions"}]
        with patch(f"{_NDE}.Command") as mc, patch(f"{_NDE}.ChartSectionReview") as mcsr:
            mc.objects.filter.return_value.values.return_value = [
                {"id": "uuid1", "anchor_object_dbid": 10},
            ]
            mcsr.objects.filter.return_value.values.return_value = [
                {"dbid": 10, "content": "Hypertension\nType 2 diabetes\n"},
            ]
            extractor._attach_chart_section_review_content(entries)
        assert entries[0]["section_content"] == ["Hypertension", "Type 2 diabetes"]
        # Humanized label stamped for the heading / patient template.
        assert entries[0]["section_label"] == "Conditions"

    def test_section_label_stamped_even_without_content(self):
        # section_label is derived from the raw enum and needs no DB content,
        # so it's present even when the anchor review can't be resolved.
        extractor = self._extractor()
        entries = [{"section": "family_histories"}]
        extractor._attach_chart_section_review_content(entries)
        assert entries[0]["section_label"] == "Family History"

    def test_empty_content_leaves_entry_untouched(self):
        extractor = self._extractor()
        entries = [{"_command_uuid": "uuid1"}]
        with patch(f"{_NDE}.Command") as mc, patch(f"{_NDE}.ChartSectionReview") as mcsr:
            mc.objects.filter.return_value.values.return_value = [
                {"id": "uuid1", "anchor_object_dbid": 10},
            ]
            mcsr.objects.filter.return_value.values.return_value = [
                {"dbid": 10, "content": ""},
            ]
            extractor._attach_chart_section_review_content(entries)
        assert "section_content" not in entries[0]

    def test_no_command_uuid_short_circuits(self):
        extractor = self._extractor()
        entries = [{"section": "conditions"}]
        extractor._attach_chart_section_review_content(entries)
        assert "section_content" not in entries[0]


# --- _attach_visual_exam_finding_image (canvas-plugins#1747) ---


class TestAttachVisualExamFindingImage:
    def _extractor(self):
        return NoteDataExtractor.__new__(NoteDataExtractor)

    def test_stamps_presigned_image_url(self):
        extractor = self._extractor()
        entries = [{"_command_uuid": "uuid1", "title": "Forearm"}]
        finding = MagicMock()
        finding.dbid = 20
        finding.image_url = "https://s3.example.com/y.png?a=1&b=2"
        with patch(f"{_NDE}.Command") as mc, patch(f"{_NDE}.VisualExamFinding") as mvef:
            mc.objects.filter.return_value.values.return_value = [
                {"id": "uuid1", "anchor_object_dbid": 20},
            ]
            mvef.objects.filter.return_value = [finding]
            extractor._attach_visual_exam_finding_image(entries)
        assert entries[0]["image_url"] == "https://s3.example.com/y.png?a=1&b=2"

    def test_no_image_url_leaves_entry_untouched(self):
        extractor = self._extractor()
        entries = [{"_command_uuid": "uuid1"}]
        finding = MagicMock()
        finding.dbid = 20
        finding.image_url = None
        with patch(f"{_NDE}.Command") as mc, patch(f"{_NDE}.VisualExamFinding") as mvef:
            mc.objects.filter.return_value.values.return_value = [
                {"id": "uuid1", "anchor_object_dbid": 20},
            ]
            mvef.objects.filter.return_value = [finding]
            extractor._attach_visual_exam_finding_image(entries)
        assert "image_url" not in entries[0]

    def test_no_command_uuid_short_circuits(self):
        extractor = self._extractor()
        entries = [{"title": "Forearm"}]
        extractor._attach_visual_exam_finding_image(entries)
        assert "image_url" not in entries[0]
