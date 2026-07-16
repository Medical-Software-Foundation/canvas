"""Tests for consent_capture/handlers/consent_api.py."""

import base64
import json
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch

from consent_capture.handlers.consent_api import (
    ConsentAdminApi,
    ConsentApi,
    _clean_document_pdf,
    _is_trusted_fhir_host,
    _clean_method,
    _clean_text,
    _clean_time,
    _clean_tz,
    _consented_by,
    _full_name,
    _representative_name,
    _resolve_patient,
    _resolve_staff,
    render_admin_page,
    serialize_coding,
    serialize_definition,
)

MODULE = "consent_capture.handlers.consent_api"

# A minimal valid PDF (magic header) as base64, for the Written-document path.
_PDF_BYTES = b"%PDF-1.4\n%%EOF\n"
_PDF_B64 = base64.b64encode(_PDF_BYTES).decode("ascii")


class TestCleanTime:
    def test_empty_returns_empty(self):
        assert _clean_time("") == ""

    def test_none_returns_empty(self):
        assert _clean_time(None) == ""

    def test_strips_disallowed_characters(self):
        assert _clean_time("2:32 PM<script>") == "2:32 PMp"

    def test_truncates_to_twelve_chars(self):
        assert _clean_time("12:34:56 PM AM") == "12:34:56 PM "

    def test_keeps_valid_time(self):
        assert _clean_time("2:32 PM") == "2:32 PM"


class TestCleanText:
    def test_empty_returns_empty(self):
        assert _clean_text("") == ""

    def test_none_returns_empty(self):
        assert _clean_text(None) == ""

    def test_removes_control_characters(self):
        assert _clean_text("Jane\x00\x07 Doe") == "Jane Doe"

    def test_coerces_non_string(self):
        assert _clean_text(12345) == "12345"

    def test_trims_and_limits(self):
        assert _clean_text("  padded  ") == "padded"
        assert _clean_text("x" * 100) == "x" * 80

    def test_custom_limit(self):
        assert _clean_text("x" * 100, limit=60) == "x" * 60


class TestCleanTz:
    def test_empty(self):
        assert _clean_tz("") == ""
        assert _clean_tz(None) == ""

    def test_keeps_common_labels(self):
        assert _clean_tz("PDT") == "PDT"
        assert _clean_tz("GMT+2") == "GMT+2"
        assert _clean_tz("America/Los_Angeles") == "America/Los_Ange"  # truncated to 16

    def test_strips_disallowed_and_truncates(self):
        assert _clean_tz("PDT<script>") == "PDTscript"
        assert len(_clean_tz("X" * 40)) == 16


class TestCleanMethod:
    ALLOWED = ["Verbal", "Electronic Form"]

    def test_valid_options(self):
        assert _clean_method("Verbal", self.ALLOWED) == "Verbal"
        assert _clean_method("Electronic Form", self.ALLOWED) == "Electronic Form"

    def test_invalid_returns_empty(self):
        assert _clean_method("Telepathy", self.ALLOWED) == ""
        assert _clean_method("", self.ALLOWED) == ""
        assert _clean_method(None, self.ALLOWED) == ""


class TestCleanDocumentPdf:
    def test_valid_pdf_round_trips(self):
        clean, err = _clean_document_pdf(_PDF_B64)
        assert err is None
        assert base64.b64decode(clean).startswith(b"%PDF-")

    def test_strips_data_url_prefix(self):
        clean, err = _clean_document_pdf("data:application/pdf;base64," + _PDF_B64)
        assert err is None and clean == _PDF_B64

    def test_missing_returns_error(self):
        for bad in ("", None, 123):
            clean, err = _clean_document_pdf(bad)
            assert clean == "" and "document" in err.lower()

    def test_undecodable_returns_error(self):
        clean, err = _clean_document_pdf("!!!not base64!!!")
        assert clean == "" and err

    def test_non_pdf_rejected(self):
        clean, err = _clean_document_pdf(base64.b64encode(b"\x89PNG\r\n").decode())
        assert clean == "" and "PDF" in err

    def test_oversize_rejected(self):
        from consent_capture.constants import MAX_DOCUMENT_BYTES
        big = b"%PDF-" + b"0" * (MAX_DOCUMENT_BYTES + 1)
        clean, err = _clean_document_pdf(base64.b64encode(big).decode())
        assert clean == "" and "large" in err.lower()
        assert _clean_method("Verbal", []) == ""


class TestRepresentativeName:
    def test_returns_cleaned_name(self):
        assert _representative_name({"representative_name": "  John Roe "}) == "John Roe"

    def test_missing_returns_empty(self):
        assert _representative_name({}) == ""


class TestConsentedBy:
    def test_defaults_to_patient(self):
        assert _consented_by({}) == ("Patient", None)

    def test_explicit_patient(self):
        assert _consented_by({"consent_by": "patient"}) == ("Patient", None)

    def test_representative_with_name_and_relationship(self):
        label, error = _consented_by(
            {
                "consent_by": "representative",
                "representative_name": "John Doe",
                "representative_relationship": "Son",
            }
        )
        assert label == "John Doe (Son)"
        assert error is None

    def test_representative_with_name_only(self):
        label, error = _consented_by(
            {"consent_by": "representative", "representative_name": "John Doe"}
        )
        assert label == "John Doe"
        assert error is None

    def test_representative_missing_name_returns_error(self):
        label, error = _consented_by(
            {"consent_by": "representative", "representative_name": ""}
        )
        assert label is None
        assert error == "Please enter the representative's name."


class TestFullName:
    def test_combines_first_and_last(self):
        assert _full_name("Jane", "Doe", "fallback") == "Jane Doe"

    def test_first_only(self):
        assert _full_name("Jane", "", "fallback") == "Jane"

    def test_empty_uses_fallback(self):
        assert _full_name("", "", "fallback") == "fallback"

    def test_none_uses_fallback(self):
        assert _full_name(None, None, "fallback") == "fallback"


class TestResolvePatient:
    def test_no_row_returns_none(self):
        with patch(f"{MODULE}.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                None
            )
            assert _resolve_patient("patient-1") is None

    def test_row_with_dob(self):
        dob = MagicMock()
        dob.isoformat.return_value = "1990-01-01"
        with patch(f"{MODULE}.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                "Jane",
                "Doe",
                dob,
            )
            assert _resolve_patient("patient-1") == ("Jane Doe", "1990-01-01")

    def test_row_without_dob_uses_empty_string(self):
        with patch(f"{MODULE}.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                "Jane",
                "Doe",
                None,
            )
            assert _resolve_patient("patient-1") == ("Jane Doe", "")

    def test_row_missing_name_uses_fallback(self):
        with patch(f"{MODULE}.Patient") as mock_patient:
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                "",
                "",
                None,
            )
            assert _resolve_patient("patient-1") == ("(name unavailable)", "")


class TestResolveStaff:
    def test_no_staff_id_returns_unknown(self):
        assert _resolve_staff("") == "Unknown"

    def test_no_row_returns_unknown(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = (
                None
            )
            assert _resolve_staff("staff-1") == "Unknown"

    def test_row_returns_full_name(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = (
                "Dr.",
                "Smith",
            )
            assert _resolve_staff("staff-1") == "Dr. Smith"


def _defn(**over):
    d = MagicMock()
    d.code = over.get("code", "universal")
    d.system = over.get("system", "http://loinc.org")
    d.display = over.get("display", "Universal Consent")
    d.verbiage = over.get("verbiage", "Line one.")
    d.method_enabled = over.get("method_enabled", True)
    d.obtained_by_enabled = over.get("obtained_by_enabled", True)
    d.capacity_enabled = over.get("capacity_enabled", True)
    d.capacity_patient_template = over.get(
        "capacity_patient_template", "[Patient name] has the capacity for decision-making."
    )
    d.capacity_representative_template = over.get(
        "capacity_representative_template", "Consent obtained by [Name], who has authority."
    )
    d.questions = over.get("questions", [])
    d.method_options = over.get("method_options", [])
    d.satisfied_by = over.get("satisfied_by", [])
    d.required = over.get("required", False)
    return d


def _make_api(body, staff_id="staff-9", secrets=None):
    """Build a ConsentApi with a mocked request and dict secrets."""
    api = ConsentApi()
    api.request = MagicMock()
    # The modal always sends capacity_confirmed with the capture; default it to True
    # here so success-path tests (whose _defn has capacity_enabled) don't each need to.
    # Capacity-specific tests pass it explicitly (including False) and are respected.
    if isinstance(body, dict):
        body.setdefault("capacity_confirmed", True)
    api.request.json.return_value = body
    api.request.headers.get.return_value = staff_id
    api.secrets = secrets if secrets is not None else {
        "CONSENT_SYSTEM": "http://loinc.org",
        "CANVAS_FHIR_CLIENT_ID": "client-id",
        "CANVAS_FHIR_CLIENT_SECRET": "client-secret",
    }
    return api


class TestCollectValidationErrors:
    def test_missing_patient_id(self):
        api = _make_api({"patient_id": ""})
        result = api.collect()
        assert result[0].content == {
            "ok": False,
            "error": "No patient was identified for this consent.",
        }

    def test_missing_consent_code(self):
        api = _make_api({"patient_id": "patient-1", "consent_code": ""})
        result = api.collect()
        assert result[0].content == {"ok": False, "error": "No consent was selected."}

    def test_unknown_definition(self):
        api = _make_api({"patient_id": "patient-1", "consent_code": "nope"})
        with patch(f"{MODULE}.definition_by_code", return_value=None):
            result = api.collect()
        assert result[0].content["ok"] is False
        assert "isn't configured" in result[0].content["error"]

    def test_missing_fhir_credentials(self):
        api = _make_api(
            {"patient_id": "patient-1", "consent_code": "universal"},
            secrets={"CANVAS_FHIR_CLIENT_ID": "", "CANVAS_FHIR_CLIENT_SECRET": ""},
        )
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()):
            result = api.collect()
        assert result[0].content["ok"] is False
        assert "FHIR" in result[0].content["error"]

    def test_patient_not_found(self):
        api = _make_api({"patient_id": "patient-1", "consent_code": "universal"})
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), patch(
            f"{MODULE}._resolve_patient", return_value=None
        ):
            result = api.collect()
        assert result[0].content == {
            "ok": False,
            "error": "We couldn't find this patient's record.",
        }

    def test_representative_without_name(self):
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "consent_by": "representative",
            }
        )
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"):
            result = api.collect()
        assert result[0].content == {
            "ok": False,
            "error": "Please enter the representative's name.",
        }

    def test_method_required_when_enabled(self):
        api = _make_api(
            {"patient_id": "patient-1", "consent_code": "universal", "method": ""}
        )
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"):
            result = api.collect()
        assert result[0].content["ok"] is False
        assert "how the consent was obtained" in result[0].content["error"]


class TestCollectSuccess:
    def _patches(self):
        return (
            patch(f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")),
            patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"),
            patch(f"{MODULE}.generate_consent_pdf_base64", return_value="PDF64"),
            patch(f"{MODULE}.build_consent_payload", return_value={"resourceType": "Consent"}),
            patch(f"{MODULE}.parse_statement", return_value=["Line one."]),
        )

    def test_patient_success_builds_pdf_and_payload(self):
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Verbal",
                "local_date": "2026-07-07",
                "local_time": "2:32 PM",
            }
        )
        defn = _defn()
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=defn), p1, p2, p3 as mock_pdf, p4 as mock_payload, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.return_value = {"id": "consent-1"}
            result = api.collect()

            kwargs = mock_pdf.mock_calls[0].kwargs
            assert kwargs["title"] == "Universal Consent"
            assert kwargs["method"] == "Verbal"
            assert kwargs["date"] == "2026-07-07"
            assert kwargs["consented_by"] == "Patient"
            # capacity rendered from the patient template with the patient's name
            assert kwargs["capacity_statement"] == "Jane Doe has the capacity for decision-making."
            assert kwargs["time"] == "2:32 PM"  # no timezone sent in this body

            assert mock_payload.mock_calls == [
                call(
                    system="http://loinc.org",
                    code="universal",
                    display="Universal Consent",
                    patient_id="patient-1",
                    pdf_base64="PDF64",
                    today="2026-07-07",
                )
            ]
            assert mock_fhir.mock_calls == [
                call("client-id", "client-secret"),
                call().create("Consent", {"resourceType": "Consent"}),
            ]

        content = result[0].content
        assert content["ok"] is True
        assert content["preview"]["code"] == "universal"
        assert content["preview"]["method"] == "Verbal"
        assert content["preview"]["consented_by"] == "Patient"
        # The preview carries the capture detail so the picker can show it under On
        # File immediately (optimistic update), matching a close/reopen.
        assert content["preview"]["collected_by"] == "Dr. Smith"
        assert content["preview"]["capacity_statement"] == "Jane Doe has the capacity for decision-making."
        # A non-written method generates and attaches a PDF.
        assert content["preview"]["pdf"] is True

    def test_success_appends_button_reload(self):
        # On success the response is followed by a ReloadPatientActionButtonsEffect so
        # the chart-header button recolors (red -> neutral gray) without a reload.
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Verbal",
                "local_date": "2026-07-07",
            }
        )
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), p1, p2, p3, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(f"{MODULE}.ReloadPatientActionButtonsEffect") as mock_reload:
            mock_fhir.return_value.create.return_value = {}
            mock_reload.return_value.apply.return_value = "RELOAD_EFFECT"
            result = api.collect()
            assert mock_reload.mock_calls[0] == call(id="patient-1")
        assert result[0].content["ok"] is True
        assert "RELOAD_EFFECT" in result

    def test_button_reload_failure_does_not_fail_capture(self):
        # The consent is already recorded before the reload, so a reload failure must
        # be swallowed and the capture must still report success.
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Verbal",
                "local_date": "2026-07-07",
            }
        )
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), p1, p2, p3, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(
            f"{MODULE}.ReloadPatientActionButtonsEffect",
            side_effect=RuntimeError("boom"),
        ):
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
        assert result[0].content["ok"] is True
        assert result == [result[0]]  # only the response; the failed reload is dropped

    def test_timezone_appended_to_time(self):
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Verbal",
                "local_date": "2026-07-07",
                "local_time": "2:32 PM",
                "local_tz": "PDT",
            }
        )
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), p1, p2, p3 as mock_pdf, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            assert mock_pdf.mock_calls[0].kwargs["time"] == "2:32 PM PDT"
        assert result[0].content["ok"] is True
        assert result[0].content["preview"]["time"] == "2:32 PM PDT"

    def test_representative_capacity_uses_representative_template(self):
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Electronic",
                "consent_by": "representative",
                "representative_name": "John Roe",
                "representative_relationship": "Son",
                "local_date": "2026-07-07",
            }
        )
        defn = _defn()
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=defn), p1, p2, p3 as mock_pdf, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            kwargs = mock_pdf.mock_calls[0].kwargs
            assert kwargs["consented_by"] == "John Roe (Son)"
            assert kwargs["capacity_statement"] == "Consent obtained by John Roe, who has authority."
        assert result[0].content["ok"] is True

    def test_method_skipped_when_disabled(self):
        api = _make_api({"patient_id": "patient-1", "consent_code": "x"})
        defn = _defn(method_enabled=False, capacity_enabled=False)
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=defn), p1, p2, p3 as mock_pdf, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            api.collect()
            kwargs = mock_pdf.mock_calls[0].kwargs
            assert kwargs["method"] == ""
            assert kwargs["capacity_statement"] == ""

    def test_invalid_local_date_falls_back_to_utc(self):
        api = _make_api(
            {"patient_id": "patient-1", "consent_code": "x", "method": "Verbal", "local_date": "nope"}
        )
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), p1, p2, p3 as mock_pdf, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ), patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value.isoformat.return_value = "2026-07-07"
            api.collect()
            assert mock_pdf.mock_calls[0].kwargs["date"] == "2026-07-07"

    def test_stores_capture_detail(self):
        # After a successful create, the obtainer + capture detail is persisted under
        # the natural key so it can be shown under On File (Canvas has no such field).
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Verbal",
                "local_date": "2026-07-07",
            }
        )
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), p1, p2, p3, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(f"{MODULE}.ConsentCaptureDetail") as mock_ccd:
            mock_fhir.return_value.create.return_value = {}
            mock_ccd.objects.filter.return_value.update.return_value = 0  # none existing -> create
            api.collect()
            ckwargs = mock_ccd.objects.create.mock_calls[0].kwargs
            assert ckwargs["patient_id"] == "patient-1"
            assert ckwargs["system"] == "http://loinc.org"
            assert ckwargs["code"] == "universal"
            assert ckwargs["effective_date"] == "2026-07-07"
            assert ckwargs["obtained_by_id"] == "staff-9"      # from the session header
            assert ckwargs["obtained_by_name"] == "Dr. Smith"  # server-resolved
            assert ckwargs["method"] == "Verbal"
            assert ckwargs["consented_by"] == "Patient"
            assert ckwargs["capacity_statement"] == "Jane Doe has the capacity for decision-making."
            assert "pages" in ckwargs  # page count of the attached PDF (0 when unreadable)

    def test_capture_detail_store_failure_does_not_fail_capture(self):
        api = _make_api(
            {"patient_id": "patient-1", "consent_code": "universal", "method": "Verbal", "local_date": "2026-07-07"}
        )
        p1, p2, p3, p4, p5 = self._patches()
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), p1, p2, p3, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(f"{MODULE}.ConsentCaptureDetail") as mock_ccd, patch(f"{MODULE}.log"):
            mock_fhir.return_value.create.return_value = {}
            mock_ccd.objects.filter.side_effect = Exception("db down")
            result = api.collect()
            assert result[0].content["ok"] is True  # consent still recorded


AFFIRM_Q = {"id": "a", "prompt": "Agree?", "type": "yes_no", "required": True, "affirm": True}


class TestCollectQuestions:
    def test_declined_affirmation_blocks_without_fhir_call(self):
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Verbal",
                "answers": {"a": "No"},
                "local_date": "2026-07-07",
            }
        )
        defn = _defn(questions=[AFFIRM_Q], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64"
        ) as mock_pdf, patch(f"{MODULE}.CanvasFhir") as mock_fhir, patch(f"{MODULE}.log"):
            result = api.collect()
            # Blocked before any PDF build or FHIR write.
            assert mock_pdf.mock_calls == []
            assert mock_fhir.mock_calls == []
        assert result[0].content["ok"] is False
        assert "Consent was not granted" in result[0].content["error"]

    def test_required_missing_blocks(self):
        api = _make_api(
            {"patient_id": "patient-1", "consent_code": "universal", "method": "Verbal", "answers": {}}
        )
        defn = _defn(questions=[AFFIRM_Q], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(f"{MODULE}.log"):
            result = api.collect()
        assert result[0].content["ok"] is False
        assert "Please answer" in result[0].content["error"]

    def test_affirmed_passes_responses_to_pdf(self):
        api = _make_api(
            {
                "patient_id": "patient-1",
                "consent_code": "universal",
                "method": "Verbal",
                "answers": {"a": "Yes"},
                "local_date": "2026-07-07",
            }
        )
        defn = _defn(questions=[AFFIRM_Q], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"
        ) as mock_pdf, patch(f"{MODULE}.build_consent_payload", return_value={}), patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            assert mock_pdf.mock_calls[0].kwargs["responses"] == [("Agree?", "Yes")]
        assert result[0].content["ok"] is True


class TestCollectCapacity:
    def test_unconfirmed_capacity_blocks_before_fhir(self):
        # When capacity is enabled it must be affirmed (Yes) in the modal; without the
        # flag the capture is rejected before any PDF build or FHIR write.
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "universal", "method": "Verbal",
            "local_date": "2026-07-08", "capacity_confirmed": False,
        })
        with patch(f"{MODULE}.definition_by_code", return_value=_defn()), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64"
        ) as mock_pdf, patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            result = api.collect()
            assert mock_pdf.mock_calls == []
            assert mock_fhir.mock_calls == []  # never reached FHIR
        assert result[0].content["ok"] is False
        assert "capacity" in result[0].content["error"].lower()

    def test_capacity_required_even_with_blank_template(self):
        # The gate keys on the capacity toggle, not the recorded statement: a blank
        # template still requires confirmation (the modal shows the generic attestation).
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "universal", "method": "Verbal",
            "local_date": "2026-07-08", "capacity_confirmed": False,
        })
        defn = _defn(capacity_patient_template="", capacity_representative_template="")
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64"
        ) as mock_pdf, patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            result = api.collect()
            assert mock_pdf.mock_calls == []
            assert mock_fhir.mock_calls == []
        assert result[0].content["ok"] is False

    def test_confirmed_blank_template_records_empty_statement(self):
        # Once confirmed, a blank template records with an empty capacity statement
        # (the template drives the PDF wording, not the affirmation gate).
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "universal", "method": "Verbal",
            "local_date": "2026-07-08", "capacity_confirmed": True,
        })
        defn = _defn(capacity_patient_template="", capacity_representative_template="")
        p1, p2, p3, p4, p5 = (
            patch(f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")),
            patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"),
            patch(f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"),
            patch(f"{MODULE}.build_consent_payload", return_value={}),
            patch(f"{MODULE}.parse_statement", return_value=[]),
        )
        with patch(f"{MODULE}.definition_by_code", return_value=defn), p1, p2, p3 as mock_pdf, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            assert mock_pdf.mock_calls[0].kwargs["capacity_statement"] == ""
        assert result[0].content["ok"] is True

    def test_capacity_not_required_when_disabled(self):
        # capacity_enabled False: no confirmation needed even without the flag.
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "universal", "method": "Verbal",
            "local_date": "2026-07-08", "capacity_confirmed": False,
        })
        defn = _defn(capacity_enabled=False)
        p1, p2, p3, p4, p5 = (
            patch(f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")),
            patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"),
            patch(f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"),
            patch(f"{MODULE}.build_consent_payload", return_value={}),
            patch(f"{MODULE}.parse_statement", return_value=[]),
        )
        with patch(f"{MODULE}.definition_by_code", return_value=defn), p1, p2, p3 as mock_pdf, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            assert mock_pdf.mock_calls[0].kwargs["capacity_statement"] == ""
        assert result[0].content["ok"] is True


class TestCollectMethodOptions:
    def test_method_validated_against_consent_options(self):
        # A consent that only supports "Electronic" rejects "Verbal".
        api = _make_api({"patient_id": "patient-1", "consent_code": "x", "method": "Verbal"})
        defn = _defn(method_options=["Electronic"], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(f"{MODULE}.log"):
            result = api.collect()
        assert result[0].content["ok"] is False
        assert "how the consent was obtained" in result[0].content["error"]

    def test_supported_method_accepted(self):
        api = _make_api({"patient_id": "patient-1", "consent_code": "x", "method": "Electronic", "local_date": "2026-07-08"})
        defn = _defn(method_options=["Electronic"], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"
        ) as mock_pdf, patch(f"{MODULE}.build_consent_payload", return_value={}), patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            assert mock_pdf.mock_calls[0].kwargs["method"] == "Electronic"
        assert result[0].content["ok"] is True

    def test_legacy_electronic_form_option_accepts_electronic(self):
        # An older config stored "Electronic Form"; it normalizes to "Electronic".
        api = _make_api({"patient_id": "patient-1", "consent_code": "x", "method": "Electronic", "local_date": "2026-07-08"})
        defn = _defn(method_options=["Electronic Form"], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"
        ), patch(f"{MODULE}.build_consent_payload", return_value={}), patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
        assert result[0].content["ok"] is True

    def test_written_attaches_uploaded_document_no_generated_pdf(self):
        # A "Written" consent attaches the provider-supplied document; no PDF is
        # generated. The cleaned base64 is passed to build_consent_payload.
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "x", "method": "Written",
            "local_date": "2026-07-08", "document_pdf": _PDF_B64,
        })
        defn = _defn(method_options=["Written"], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64", return_value="GEN"
        ) as mock_pdf, patch(f"{MODULE}.build_consent_payload", return_value={}) as mock_payload, patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            assert mock_pdf.mock_calls == []  # nothing generated
            assert mock_payload.mock_calls[0].kwargs["pdf_base64"] == _PDF_B64
        content = result[0].content
        assert content["ok"] is True
        assert content["preview"]["pdf"] is True

    def test_written_ignores_questions_and_records(self):
        # Written consents don't surface the questions (the signed document is the
        # record), so they aren't evaluated: an unaffirmed/absent required question no
        # longer blocks a Written consent — it records and attaches the document.
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "x", "method": "Written",
            "local_date": "2026-07-08", "document_pdf": _PDF_B64, "answers": {"a": "No"},
        })
        defn = _defn(method_options=["Written"], capacity_enabled=False, questions=[AFFIRM_Q])
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.build_consent_payload", return_value={}
        ) as mock_payload, patch(f"{MODULE}.parse_statement", return_value=[]), patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(f"{MODULE}.log"):
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
            assert mock_payload.mock_calls[0].kwargs["pdf_base64"] == _PDF_B64
        assert result[0].content["ok"] is True

    def test_written_records_with_no_answers_despite_required_question(self):
        # Even with a required question configured, a Written consent records when the
        # modal sends no answers (they aren't asked for Written).
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "x", "method": "Written",
            "local_date": "2026-07-08", "document_pdf": _PDF_B64, "answers": {},
        })
        defn = _defn(method_options=["Written"], capacity_enabled=False, questions=[AFFIRM_Q])
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.build_consent_payload", return_value={}
        ), patch(f"{MODULE}.parse_statement", return_value=[]), patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(f"{MODULE}.log"):
            mock_fhir.return_value.create.return_value = {}
            result = api.collect()
        assert result[0].content["ok"] is True

    def test_written_without_document_errors_before_fhir(self):
        api = _make_api({"patient_id": "patient-1", "consent_code": "x", "method": "Written", "local_date": "2026-07-08"})
        defn = _defn(method_options=["Written"], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64"
        ) as mock_pdf, patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            result = api.collect()
            assert mock_pdf.mock_calls == []
            assert mock_fhir.mock_calls == []  # never reached FHIR
        assert result[0].content["ok"] is False
        assert "document" in result[0].content["error"].lower()

    def test_written_with_invalid_document_errors(self):
        api = _make_api({
            "patient_id": "patient-1", "consent_code": "x", "method": "Written",
            "local_date": "2026-07-08", "document_pdf": base64.b64encode(b"not a pdf").decode(),
        })
        defn = _defn(method_options=["Written"], capacity_enabled=False)
        with patch(f"{MODULE}.definition_by_code", return_value=defn), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(f"{MODULE}.CanvasFhir") as mock_fhir:
            result = api.collect()
            assert mock_fhir.mock_calls == []
        assert result[0].content["ok"] is False
        assert "PDF" in result[0].content["error"]


def _make_doc_api(params, secrets=None):
    api = ConsentApi()
    api.request = MagicMock()
    api.request.query_params = params
    api.secrets = secrets if secrets is not None else {
        "CANVAS_FHIR_CLIENT_ID": "cid", "CANVAS_FHIR_CLIENT_SECRET": "sec",
    }
    return api


class TestTrustedFhirHost:
    def test_exact_instance_hosts_when_customer_known(self):
        assert _is_trusted_fhir_host("https://inst.canvasmedical.com/x", "inst") is True
        assert _is_trusted_fhir_host("https://fumage-inst.canvasmedical.com/x", "inst") is True

    def test_other_tenant_refused_when_customer_known(self):
        assert _is_trusted_fhir_host("https://fumage-other.canvasmedical.com/x", "inst") is False

    def test_attacker_host_always_refused(self):
        assert _is_trusted_fhir_host("https://fumage-evil.attacker.com/x", "inst") is False
        assert _is_trusted_fhir_host("https://fumage-evil.attacker.com/x", "") is False

    def test_fallback_allows_canvas_host_without_customer(self):
        assert _is_trusted_fhir_host("https://fumage-inst.canvasmedical.com/x", "") is True

    def test_unparseable_is_refused(self):
        assert _is_trusted_fhir_host("", "inst") is False
        assert _is_trusted_fhir_host("not-a-url", "inst") is False


def _stub_consent_id(mock_pc, consent_id):
    (
        mock_pc.objects.filter.return_value.order_by.return_value.values_list.return_value.first.return_value
    ) = consent_id


class TestConsentDocument:
    def test_missing_params(self):
        assert _make_doc_api({"patient_id": "p1"}).document()[0].content["ok"] is False
        assert _make_doc_api({"code": "x"}).document()[0].content["ok"] is False

    def test_no_consent_found(self):
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        with patch(f"{MODULE}.PatientConsent") as mpc:
            _stub_consent_id(mpc, None)
            res = api.document()
        assert res[0].content["ok"] is False
        assert "No recorded consent" in res[0].content["error"]

    def test_returns_pdf_from_attachment(self):
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir:
            _stub_consent_id(mpc, "cid-1")
            mfhir.return_value.read.return_value = {"sourceAttachment": {"data": "B64PDF", "title": "consent.pdf"}}
            res = api.document()
            mfhir.return_value.read.assert_called_once_with("Consent", "cid-1")
        content = res[0].content
        assert content["ok"] is True
        assert content["pdf_base64"] == "B64PDF"
        assert content["filename"] == "consent.pdf"

    def test_no_attachment_returns_error(self):
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir, patch(f"{MODULE}.log"):
            _stub_consent_id(mpc, "cid-1")
            mfhir.return_value.read.return_value = {}
            res = api.document()
        assert res[0].content["ok"] is False
        assert "attached document" in res[0].content["error"]

    def test_fetches_document_from_binary_reference(self):
        # sourceAttachment.url points to a FHIR Binary -> read it via the public client.
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir:
            _stub_consent_id(mpc, "cid-1")
            reads = {("Consent", "cid-1"): {"sourceAttachment": {"url": "https://fumage/Binary/bin-9", "title": "c.pdf"}},
                     ("Binary", "bin-9"): {"resourceType": "Binary", "data": "B64PDF"}}
            mfhir.return_value.read.side_effect = lambda rt, rid: reads[(rt, rid)]
            res = api.document()
            mfhir.return_value.read.assert_any_call("Binary", "bin-9")
        content = res[0].content
        assert content["ok"] is True
        assert content["pdf_base64"] == "B64PDF"
        assert content["filename"] == "c.pdf"

    def test_fetches_document_from_authed_url(self):
        # A Canvas-hosted sourceAttachment URL: mint a bearer, then GET the bytes.
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        url = "https://fumage-inst.canvasmedical.com/Consent/cid-1/files/sourceAttachment"
        tokresp = MagicMock(); tokresp.raise_for_status.return_value = None
        tokresp.json.return_value = {"access_token": "TOK"}
        binresp = MagicMock(); binresp.raise_for_status.return_value = None; binresp.content = b"%PDF-1.4 bytes"
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir, patch(f"{MODULE}.Http") as mhttp:
            _stub_consent_id(mpc, "cid-1")
            mfhir.return_value.read.return_value = {"sourceAttachment": {"url": url, "title": "c.pdf"}}
            mhttp.return_value.post.return_value = tokresp
            mhttp.return_value.get.return_value = binresp
            res = api.document()
            # token minted against the app host (fumage- stripped)
            assert mhttp.return_value.post.call_args[0][0] == "https://inst.canvasmedical.com/auth/token/"
            mhttp.return_value.get.assert_called_once_with(url, headers={"Authorization": "Bearer TOK"})
        content = res[0].content
        assert content["ok"] is True
        assert content["pdf_base64"] == base64.b64encode(b"%PDF-1.4 bytes").decode()
        assert content["filename"] == "c.pdf"

    def test_refuses_off_instance_attachment_url(self):
        # A tampered Consent whose sourceAttachment.url is on an attacker host must
        # not cause a token mint or fetch (would leak FHIR client credentials).
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir, \
             patch(f"{MODULE}.Http") as mhttp, patch(f"{MODULE}.log"):
            _stub_consent_id(mpc, "cid-1")
            mfhir.return_value.read.return_value = {
                "sourceAttachment": {"url": "https://fumage-evil.attacker.com/Consent/cid-1/files/x"}
            }
            res = api.document()
            mhttp.return_value.post.assert_not_called()  # no token minted
            mhttp.return_value.get.assert_not_called()   # no fetch attempted
        assert res[0].content["ok"] is False
        assert "attached document" in res[0].content["error"]

    def test_refuses_other_tenant_url_when_customer_known(self):
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        api.environment = {"CUSTOMER_IDENTIFIER": "inst"}
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir, \
             patch(f"{MODULE}.Http") as mhttp, patch(f"{MODULE}.log"):
            _stub_consent_id(mpc, "cid-1")
            mfhir.return_value.read.return_value = {
                "sourceAttachment": {"url": "https://fumage-other.canvasmedical.com/Consent/cid-1/files/x"}
            }
            res = api.document()
            mhttp.return_value.post.assert_not_called()
        assert res[0].content["ok"] is False

    def test_fhir_error_returns_friendly_message(self):
        api = _make_doc_api({"patient_id": "p1", "code": "x"})
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir, patch(f"{MODULE}.log"):
            _stub_consent_id(mpc, "cid-1")
            mfhir.return_value.read.side_effect = Exception("boom")
            res = api.document()
        assert res[0].content["ok"] is False
        assert "couldn't load" in res[0].content["error"].lower()

    def test_missing_credentials(self):
        api = _make_doc_api({"patient_id": "p1", "code": "x"}, secrets={})
        with patch(f"{MODULE}.PatientConsent") as mpc:
            _stub_consent_id(mpc, "cid-1")
            res = api.document()
        assert res[0].content["ok"] is False

    def test_specific_record_id_loads_that_exact_record(self):
        # An On File history row passes consent_id: load that record (scoped to the
        # patient), not the coding's most recent.
        api = _make_doc_api({"patient_id": "p1", "consent_id": "cid-9", "code": "x"})
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir:
            mpc.objects.filter.return_value.values_list.return_value.first.return_value = "cid-9"
            mfhir.return_value.read.return_value = {"sourceAttachment": {"data": "B64", "title": "c.pdf"}}
            res = api.document()
            assert mpc.objects.filter.mock_calls[0] == call(
                id="cid-9", patient__id="p1",
                state__in=("accepted", "accepted_via_patient_portal"),
            )
            mfhir.return_value.read.assert_called_once_with("Consent", "cid-9")
        assert res[0].content["ok"] is True
        assert res[0].content["pdf_base64"] == "B64"

    def test_record_id_not_belonging_to_patient_is_not_found(self):
        # A consent_id that isn't this patient's accepted consent -> not found.
        api = _make_doc_api({"patient_id": "p1", "consent_id": "other"})
        with patch(f"{MODULE}.PatientConsent") as mpc:
            mpc.objects.filter.return_value.values_list.return_value.first.return_value = None
            res = api.document()
        assert res[0].content["ok"] is False
        assert "No recorded consent" in res[0].content["error"]

    def test_system_narrows_the_query(self):
        api = _make_doc_api({"patient_id": "p1", "code": "x", "system": "INTERNAL"})
        with patch(f"{MODULE}.PatientConsent") as mpc, patch(f"{MODULE}.CanvasFhir") as mfhir:
            (mpc.objects.filter.return_value.filter.return_value.order_by.return_value
             .values_list.return_value.first.return_value) = "cid-2"
            mfhir.return_value.read.return_value = {"sourceAttachment": {"data": "B", "title": "c.pdf"}}
            res = api.document()
            mpc.objects.filter.return_value.filter.assert_called_once_with(category__system="INTERNAL")
            mfhir.return_value.read.assert_called_once_with("Consent", "cid-2")
        assert res[0].content["ok"] is True


class TestCollectFhirErrorHandling:
    def _run(self, exc):
        api = _make_api(
            {"patient_id": "patient-1", "consent_code": "x", "method": "Verbal", "local_date": "2026-07-07"}
        )
        with patch(f"{MODULE}.definition_by_code", return_value=_defn(capacity_enabled=False)), patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"), patch(
            f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"
        ), patch(f"{MODULE}.build_consent_payload", return_value={}), patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(f"{MODULE}.CanvasFhir") as mock_fhir, patch(f"{MODULE}.log"):
            mock_fhir.return_value.create.side_effect = exc
            return api.collect()

    def test_2xx_empty_body_treated_as_success(self):
        exc = ValueError("no json")
        exc.response = MagicMock()
        exc.response.status_code = 201
        result = self._run(exc)
        assert result[0].content["ok"] is True

    def test_empty_body_value_error_no_response_treated_as_success(self):
        result = self._run(ValueError("no json"))
        assert result[0].content["ok"] is True

    def test_real_http_error_returns_error_response(self):
        exc = Exception("boom")
        exc.response = MagicMock()
        exc.response.status_code = 400
        exc.response.text = "Bad Request"
        result = self._run(exc)
        assert result[0].content == {
            "ok": False,
            "error": "We couldn't save the consent. If this keeps happening, "
            "please contact your administrator.",
        }


class TestErrorHelper:
    def test_error_builds_json_response(self):
        api = ConsentApi()
        response = api._error("Something went wrong.")
        assert response.content == {"ok": False, "error": "Something went wrong."}


# --------------------------------------------------------------------------- #
# Admin CRUD.
# --------------------------------------------------------------------------- #

def _admin(body=None, secrets=None):
    api = ConsentAdminApi()
    api.request = MagicMock()
    api.request.json.return_value = body or {}
    # Authorize the caller as the root user (always an admin, regardless of the
    # CONSENT_ADMIN_USERS allow-list, which now fails closed when unset).
    api.request.headers.get.return_value = "root"
    api.secrets = secrets if secrets is not None else {"CONSENT_SYSTEM": "http://loinc.org"}
    return api


def test_serialize_definition_shape():
    d = _defn(questions=[{"id": "q1", "prompt": "OK?", "type": "yes_no", "required": True, "affirm": True}])
    d.dbid = 5
    d.required = True
    d.active = True
    d.sort_order = 10
    out = serialize_definition(d)
    assert out["dbid"] == 5
    assert out["code"] == "universal"
    assert out["method_enabled"] is True
    assert out["required"] is True
    assert out["questions"] == [{"id": "q1", "prompt": "OK?", "type": "yes_no", "required": True, "affirm": True}]
    assert set(out) == {
        "dbid", "code", "system", "display", "verbiage", "method_enabled",
        "obtained_by_enabled", "capacity_enabled", "method_options",
        "capacity_patient_template", "capacity_representative_template",
        "questions", "satisfied_by", "required", "active", "sort_order",
    }


def _coding(system="INTERNAL", code="universal", display="Universal Consent", **over):
    c = MagicMock()
    c.system = system
    c.code = code
    c.display = display
    c.expiration_rule = over.get("expiration_rule", "never")
    c.is_mandatory = over.get("is_mandatory", False)
    c.is_proof_required = over.get("is_proof_required", False)
    c.show_in_patient_portal = over.get("show_in_patient_portal", True)
    c.summary = over.get("summary", "")
    c.user_selected = over.get("user_selected", True)
    return c


class TestSerializeCoding:
    def test_maps_expiration_label_and_flags(self):
        out = serialize_coding(_coding(expiration_rule="in_one_year", is_mandatory=True), configured=True)
        assert out["code"] == "universal"
        assert out["expiration_rule"] == "in_one_year"
        assert out["expiration_label"] == "Expires one year after acceptance"
        assert out["is_mandatory"] is True
        assert out["configured"] is True

    def test_unknown_rule_falls_back_to_value(self):
        out = serialize_coding(_coding(expiration_rule="weird"))
        assert out["expiration_label"] == "weird"
        assert out["configured"] is False


class TestRenderAdminPage:
    def test_renders_with_templates_and_consents(self):
        d = _defn()
        d.dbid = 1
        d.active = True
        d.sort_order = 10
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd, patch(
            f"{MODULE}.render_to_string", return_value="<html>page</html>"
        ) as mock_render:
            mock_cd.objects.all.return_value.order_by.return_value = [d]
            html = render_admin_page("INTERNAL")
            assert html == "<html>page</html>"
            template, ctx = mock_render.mock_calls[0].args
            assert template == "templates/admin.html"
            assert json.loads(ctx["consents_json"])[0]["code"] == "universal"
            assert json.loads(ctx["method_options_json"]) == ["Verbal", "Electronic", "Written", "Other"]


class TestSettingsPage:
    def test_serves_html_response(self):
        api = _admin()
        with patch(f"{MODULE}.render_admin_page", return_value="<html>settings</html>") as mock_render:
            result = api.settings_page()
            assert mock_render.mock_calls == [call("http://loinc.org")]
        assert result[0].content == "<html>settings</html>"


class TestAdminAuthz:
    def test_settings_page_forbidden_for_non_admin(self):
        api = _admin()
        with patch(f"{MODULE}.is_consent_admin", return_value=False), patch(
            f"{MODULE}.render_admin_page"
        ) as mock_render:
            result = api.settings_page()
            assert mock_render.mock_calls == []          # never rendered
        assert result[0].status_code == 403
        assert "access" in result[0].content.lower()

    def test_list_consents_forbidden(self):
        api = _admin()
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            result = api.list_consents()
        assert result[0].content["ok"] is False

    def test_list_codings_forbidden(self):
        api = _admin()
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            result = api.list_codings()
        assert result[0].content["ok"] is False

    def test_upsert_forbidden(self):
        api = _admin({"code": "x", "system": "INTERNAL"})
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            result = api.upsert_consent()
        assert result[0].content["ok"] is False

    def test_delete_forbidden(self):
        api = _admin({"dbid": 3})
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            result = api.delete_consent()
        assert result[0].content["ok"] is False


class TestListConsents:
    def test_lists_configured_definitions(self):
        d = _defn()
        d.dbid = 1
        d.active = True
        d.sort_order = 10
        api = _admin()
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd:
            mock_cd.objects.all.return_value.order_by.return_value = [d]
            result = api.list_consents()
        content = result[0].content
        assert content["ok"] is True
        assert content["consents"][0]["code"] == "universal"


class TestListCodings:
    def test_lists_codings_with_configured_flag(self):
        api = _admin()
        cfg = _defn(code="universal", system="INTERNAL")
        c1 = _coding(system="INTERNAL", code="universal", display="Universal")
        c2 = _coding(system="INTERNAL", code="rpm", display="RPM")
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd, patch(
            f"{MODULE}.PatientConsentCoding"
        ) as mock_pcc:
            mock_cd.objects.all.return_value = [cfg]
            mock_pcc.objects.all.return_value.order_by.return_value = [c1, c2]
            result = api.list_codings()
        codings = result[0].content["codings"]
        by_code = {c["code"]: c for c in codings}
        assert by_code["universal"]["configured"] is True
        assert by_code["rpm"]["configured"] is False

    def test_lists_all_codings_regardless_of_user_selected(self):
        # The full catalog is returned; the user_selected flag is no longer a filter
        # (it tends to be True for everything, so it didn't discriminate anything).
        api = _admin()
        c1 = _coding(system="INTERNAL", code="universal", display="Universal", user_selected=True)
        c2 = _coding(system="INTERNAL", code="hidden", display="Hidden", user_selected=False)
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd, patch(
            f"{MODULE}.PatientConsentCoding"
        ) as mock_pcc:
            mock_cd.objects.all.return_value = []
            mock_pcc.objects.all.return_value.order_by.return_value = [c1, c2]
            result = api.list_codings()
        by_code = {c["code"]: c for c in result[0].content["codings"]}
        assert set(by_code) == {"universal", "hidden"}
        assert by_code["universal"]["user_selected"] is True
        assert by_code["hidden"]["user_selected"] is False


class TestAdminUpsert:
    def test_missing_coding_selection(self):
        api = _admin({"code": "", "system": ""})
        result = api.upsert_consent()
        assert result[0].content == {"ok": False, "error": "Choose a consent coding to configure."}

    def test_coding_not_in_canvas(self):
        api = _admin({"code": "ghost", "system": "INTERNAL"})
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc:
            mock_pcc.objects.filter.return_value.first.return_value = None
            result = api.upsert_consent()
        assert result[0].content["ok"] is False
        assert "isn't configured in Canvas" in result[0].content["error"]

    def test_create_uses_coding_display_and_normalizes_questions(self):
        api = _admin({
            "code": "rpm", "system": "INTERNAL",
            "display": "IGNORED CLIENT VALUE",
            "questions": [
                {"prompt": "  ", "type": "yes_no"},                      # dropped
                {"prompt": "Agree?", "type": "bogus", "affirm": True},   # -> yes_no
                {"prompt": "Notes", "type": "text", "affirm": True},     # affirm forced False
            ],
        })
        created = _defn(code="rpm", system="INTERNAL")
        created.dbid = 7
        created.active = True
        created.sort_order = 100
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc, patch(
            f"{MODULE}.ConsentDefinition"
        ) as mock_cd:
            mock_pcc.objects.filter.return_value.first.return_value = _coding(code="rpm", display="Remote Patient Monitoring")
            mock_cd.objects.filter.return_value.first.return_value = None
            mock_cd.objects.create.return_value = created
            result = api.upsert_consent()
            kwargs = mock_cd.objects.create.mock_calls[0].kwargs
            assert kwargs["display"] == "Remote Patient Monitoring"  # from coding, not client
            qs = kwargs["questions"]
            assert len(qs) == 2 and qs[0]["type"] == "yes_no" and qs[1]["affirm"] is False
        assert result[0].content["ok"] is True

    def test_normalizes_method_options(self):
        api = _admin({
            "code": "rpm", "system": "INTERNAL",
            "method_options": ["Written", "Verbal", "verbal", "Phone", "Electronic Form"],
        })
        created = _defn(code="rpm")
        created.dbid = 10
        created.active = True
        created.sort_order = 100
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc, patch(
            f"{MODULE}.ConsentDefinition"
        ) as mock_cd:
            mock_pcc.objects.filter.return_value.first.return_value = _coding(code="rpm")
            mock_cd.objects.filter.return_value.first.return_value = None
            mock_cd.objects.create.return_value = created
            api.upsert_consent()
            # Reduced to the canonical set in canonical order; unknowns ("Phone")
            # dropped, "Electronic Form" mapped to "Electronic", deduped.
            assert mock_cd.objects.create.mock_calls[0].kwargs["method_options"] == [
                "Verbal", "Electronic", "Written",
            ]

    def test_persists_required_flag(self):
        api = _admin({"code": "rpm", "system": "INTERNAL", "required": True})
        created = _defn(code="rpm", required=True)
        created.dbid = 11
        created.active = True
        created.sort_order = 100
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc, patch(
            f"{MODULE}.ConsentDefinition"
        ) as mock_cd:
            mock_pcc.objects.filter.return_value.first.return_value = _coding(code="rpm")
            mock_cd.objects.filter.return_value.first.return_value = None
            mock_cd.objects.create.return_value = created
            api.upsert_consent()
            assert mock_cd.objects.create.mock_calls[0].kwargs["required"] is True

    def test_update_existing_by_dbid(self):
        api = _admin({"dbid": 3, "code": "universal", "system": "INTERNAL", "verbiage": "New."})
        existing = _defn()
        existing.dbid = 3
        existing.active = True
        existing.sort_order = 10
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc, patch(
            f"{MODULE}.ConsentDefinition"
        ) as mock_cd:
            mock_pcc.objects.filter.return_value.first.return_value = _coding()
            mock_cd.objects.filter.return_value.first.return_value = existing
            result = api.upsert_consent()
            # Updated via queryset .update() (no guarded setattr), then re-fetched.
            update_kwargs = mock_cd.objects.filter.return_value.update.mock_calls[0].kwargs
            assert update_kwargs["verbiage"] == "New."
            assert update_kwargs["display"] == "Universal Consent"
        assert result[0].content["ok"] is True

    def test_update_unknown_dbid(self):
        api = _admin({"dbid": 99, "code": "universal", "system": "INTERNAL"})
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc, patch(
            f"{MODULE}.ConsentDefinition"
        ) as mock_cd:
            mock_pcc.objects.filter.return_value.first.return_value = _coding()
            mock_cd.objects.filter.return_value.first.return_value = None
            result = api.upsert_consent()
        assert result[0].content == {"ok": False, "error": "That consent configuration no longer exists."}

    def test_bad_sort_order_ignored(self):
        api = _admin({"code": "universal", "system": "INTERNAL", "sort_order": "nope", "active": False})
        created = _defn()
        created.dbid = 8
        created.active = False
        created.sort_order = 100
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc, patch(
            f"{MODULE}.ConsentDefinition"
        ) as mock_cd:
            mock_pcc.objects.filter.return_value.first.return_value = _coding()
            mock_cd.objects.filter.return_value.first.return_value = None
            mock_cd.objects.create.return_value = created
            api.upsert_consent()
            kwargs = mock_cd.objects.create.mock_calls[0].kwargs
            assert "sort_order" not in kwargs
            assert kwargs["active"] is False


    def test_validates_satisfied_by(self):
        # Own coding (self) and unknown codings are dropped; a valid equivalent with
        # an empty code is kept, and its display is re-derived from the coding.
        api = _admin({
            "code": "universal-verbal-consent", "system": "INTERNAL",
            "satisfied_by": [
                {"system": "INTERNAL", "code": "universal-verbal-consent"},   # self -> drop
                {"system": "GHOST", "code": "ghost"},                          # unknown -> drop
                {"system": "Universal_Written_Consent", "code": "", "display": "stale"},  # valid, empty code
            ],
        })
        created = _defn(code="universal-verbal-consent", system="INTERNAL")
        created.dbid = 20
        created.active = True
        created.sort_order = 100
        own = _coding(code="universal-verbal-consent", system="INTERNAL")
        written = _coding(code="", system="Universal_Written_Consent", display="Universal Written Consent")
        with patch(f"{MODULE}.PatientConsentCoding") as mock_pcc, patch(
            f"{MODULE}.ConsentDefinition"
        ) as mock_cd:
            mock_pcc.objects.filter.return_value.first.return_value = own
            mock_pcc.objects.all.return_value = [own, written]
            mock_cd.objects.filter.return_value.first.return_value = None
            mock_cd.objects.create.return_value = created
            api.upsert_consent()
            assert mock_cd.objects.create.mock_calls[0].kwargs["satisfied_by"] == [
                {"system": "Universal_Written_Consent", "code": "", "display": "Universal Written Consent"}
            ]


class TestAdminDelete:
    def test_missing_dbid(self):
        api = _admin({})
        result = api.delete_consent()
        assert result[0].content == {"ok": False, "error": "No consent was specified."}

    def test_delete_success(self):
        api = _admin({"dbid": 4})
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd:
            mock_cd.objects.filter.return_value.delete.return_value = (1, {})
            result = api.delete_consent()
        assert result[0].content == {"ok": True}

    def test_delete_missing_row(self):
        api = _admin({"dbid": 4})
        with patch(f"{MODULE}.ConsentDefinition") as mock_cd:
            mock_cd.objects.filter.return_value.delete.return_value = (0, {})
            result = api.delete_consent()
        assert result[0].content == {"ok": False, "error": "That consent no longer exists."}


def _stub_bannered(mock_ba, patient_ids):
    (mock_ba.objects.filter.return_value.values_list.return_value.iterator.return_value) = patient_ids


class TestBannerBackfill:
    def test_page_requires_admin(self):
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            res = _admin().banners_page()
        assert res[0].status_code == HTTPStatus.FORBIDDEN

    def test_page_served_for_admin(self):
        with patch(f"{MODULE}.render_to_string", return_value="<html>b</html>"):
            res = _admin().banners_page()
        assert res[0].status_code == HTTPStatus.OK
        assert res[0].content == "<html>b</html>"

    def test_preview_reports_counts_without_effects(self):
        with patch(f"{MODULE}.patients_missing_required", return_value={"p1", "p2", "p3"}), \
             patch(f"{MODULE}.BannerAlert") as mba:
            _stub_bannered(mba, ["p2", "p4"])
            res = _admin().banners_preview()
        assert len(res) == 1  # no effects, just the summary
        c = res[0].content
        assert c["ok"] is True
        assert c["add"] == 2 and c["remove"] == 1 and c["total"] == 3

    def test_preview_requires_admin(self):
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            res = _admin().banners_preview()
        assert res[0].content["ok"] is False

    def test_refresh_adds_needy_and_removes_stale(self):
        with patch(f"{MODULE}.patients_missing_required", return_value={"p1", "p3"}), \
             patch(f"{MODULE}.BannerAlert") as mba, patch(f"{MODULE}.log"):
            _stub_bannered(mba, ["p3", "p4"])
            res = _admin().banners_refresh()
        # Summary first: p1 newly added, p4 removed (p3 already had it, re-applied).
        assert res[0].content == {"ok": True, "added": 1, "removed": 1}
        effects = res[1:]
        adds = [e for e in effects if e["type"] == "AddBannerAlert"]
        removes = [e for e in effects if e["type"] == "RemoveBannerAlert"]
        # One keyed AddBannerAlert per needy patient (all of them, idempotent).
        assert [e["patient_id"] for e in adds] == ["p1", "p3"]
        assert all(e["placement"] == ["chart", "profile"] and e["intent"] == "warning" for e in adds)
        assert [e["patient_id"] for e in removes] == ["p4"]

    def test_refresh_with_no_needy_only_removes(self):
        with patch(f"{MODULE}.patients_missing_required", return_value=set()), \
             patch(f"{MODULE}.BannerAlert") as mba, patch(f"{MODULE}.log"):
            _stub_bannered(mba, ["p4"])
            res = _admin().banners_refresh()
        assert res[0].content == {"ok": True, "added": 0, "removed": 1}
        effects = res[1:]
        assert all(e["type"] == "RemoveBannerAlert" for e in effects)
        assert [e["patient_id"] for e in effects] == ["p4"]

    def test_refresh_requires_admin(self):
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            res = _admin().banners_refresh()
        assert res[0].content["ok"] is False

    def test_preview_when_disabled_reports_only_removals(self):
        # CONSENT_BANNERS_ENABLED off: needy is treated as empty, so the preview would
        # remove every currently-bannered patient and add none.
        admin = _admin(secrets={"CONSENT_BANNERS_ENABLED": "false"})
        with patch(f"{MODULE}.patients_missing_required", return_value={"p1", "p2"}), \
             patch(f"{MODULE}.BannerAlert") as mba:
            _stub_bannered(mba, ["p2", "p4"])
            res = admin.banners_preview()
        c = res[0].content
        assert c["ok"] is True
        assert c["add"] == 0 and c["remove"] == 2 and c["total"] == 0

    def test_refresh_when_disabled_removes_all_and_adds_none(self):
        admin = _admin(secrets={"CONSENT_BANNERS_ENABLED": "off"})
        with patch(f"{MODULE}.patients_missing_required", return_value={"p1", "p2"}), \
             patch(f"{MODULE}.BannerAlert") as mba, patch(f"{MODULE}.log"):
            _stub_bannered(mba, ["p2", "p4"])
            res = admin.banners_refresh()
        assert res[0].content == {"ok": True, "added": 0, "removed": 2}
        effects = res[1:]
        assert all(e["type"] == "RemoveBannerAlert" for e in effects)
        assert sorted(e["patient_id"] for e in effects) == ["p2", "p4"]
