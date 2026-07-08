"""Tests for consent_capture/handlers/consent_api.py."""

from unittest.mock import MagicMock, call, patch

from consent_capture.handlers.consent_api import (
    ConsentApi,
    _clean_text,
    _clean_time,
    _consented_by,
    _full_name,
    _resolve_patient,
    _resolve_staff,
)

MODULE = "consent_capture.handlers.consent_api"


class TestCleanTime:
    def test_empty_returns_empty(self):
        assert _clean_time("") == ""

    def test_none_returns_empty(self):
        assert _clean_time(None) == ""

    def test_strips_disallowed_characters(self):
        # Only digits, colon, space and the letters A/P/M (either case) survive;
        # "<script>" collapses to just its lone allowed "p".
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

            assert mock_patient.mock_calls == [
                call.objects.filter(id="patient-1"),
                call.objects.filter().values_list(
                    "first_name", "last_name", "birth_date"
                ),
                call.objects.filter().values_list().first(),
            ]

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
            assert dob.mock_calls == [call.__bool__(), call.isoformat()]

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

            assert mock_staff.mock_calls == [
                call.objects.filter(id="staff-1"),
                call.objects.filter().values_list("first_name", "last_name"),
                call.objects.filter().values_list().first(),
            ]

    def test_row_returns_full_name(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = (
                "Dr.",
                "Smith",
            )
            assert _resolve_staff("staff-1") == "Dr. Smith"

    def test_row_missing_name_returns_unknown(self):
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values_list.return_value.first.return_value = (
                "",
                "",
            )
            assert _resolve_staff("staff-1") == "Unknown"


def _make_api(body, staff_id="staff-9", secrets=None):
    """Build a ConsentApi with a mocked request and dict secrets."""
    api = ConsentApi()
    api.request = MagicMock()
    api.request.json.return_value = body
    api.request.headers.get.return_value = staff_id
    api.secrets = secrets if secrets is not None else {
        "CONSENT_SYSTEM": "http://loinc.org",
        "CONSENT_CODE": "12345",
        "CONSENT_DISPLAY": "Consent to Treat",
        "CANVAS_FHIR_CLIENT_ID": "client-id",
        "CANVAS_FHIR_CLIENT_SECRET": "client-secret",
        "CONSENT_STATEMENT": "I consent.",
    }
    return api


class TestCollectValidationErrors:
    def test_missing_patient_id(self):
        api = _make_api({"patient_id": ""})
        result = api.collect()
        assert len(result) == 1
        assert result[0].content == {
            "ok": False,
            "error": "No patient was identified for this consent.",
        }

    def test_missing_code(self):
        api = _make_api(
            {"patient_id": "patient-1"},
            secrets={
                "CONSENT_CODE": "",
                "CANVAS_FHIR_CLIENT_ID": "x",
                "CANVAS_FHIR_CLIENT_SECRET": "y",
            },
        )
        result = api.collect()
        assert result[0].content["ok"] is False
        assert "consent code" in result[0].content["error"]

    def test_missing_fhir_credentials(self):
        api = _make_api(
            {"patient_id": "patient-1"},
            secrets={
                "CONSENT_CODE": "12345",
                "CANVAS_FHIR_CLIENT_ID": "",
                "CANVAS_FHIR_CLIENT_SECRET": "",
            },
        )
        result = api.collect()
        assert result[0].content["ok"] is False
        assert "FHIR" in result[0].content["error"]

    def test_patient_not_found(self):
        api = _make_api({"patient_id": "patient-1"})
        with patch(f"{MODULE}._resolve_patient", return_value=None) as mock_resolve:
            result = api.collect()
            assert mock_resolve.mock_calls == [call("patient-1")]
        assert result[0].content == {
            "ok": False,
            "error": "We couldn't find this patient's record.",
        }

    def test_representative_without_name(self):
        api = _make_api(
            {"patient_id": "patient-1", "consent_by": "representative"}
        )
        with patch(
            f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")
        ), patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"):
            result = api.collect()
        assert result[0].content == {
            "ok": False,
            "error": "Please enter the representative's name.",
        }


class TestCollectSuccess:
    def _patch_pipeline(self):
        """Common patches for the happy path from patient onward."""
        return (
            patch(f"{MODULE}._resolve_patient", return_value=("Jane Doe", "1990-01-01")),
            patch(f"{MODULE}._resolve_staff", return_value="Dr. Smith"),
            patch(f"{MODULE}.generate_consent_pdf_base64", return_value="PDF64"),
            patch(f"{MODULE}.build_consent_payload", return_value={"resourceType": "Consent"}),
            patch(f"{MODULE}.parse_statement", return_value=["I consent."]),
        )

    def test_valid_local_date_used(self):
        api = _make_api(
            {
                "patient_id": "patient-1",
                "local_date": "2026-07-07",
                "local_time": "2:32 PM",
            }
        )
        p1, p2, p3, p4, p5 = self._patch_pipeline()
        with p1, p2, p3 as mock_pdf, p4 as mock_payload, p5, patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.return_value = {"id": "consent-1"}
            result = api.collect()

            # PDF built with the browser-supplied local date/time.
            assert mock_pdf.mock_calls == [
                call(
                    title="Consent to Treat",
                    patient_name="Jane Doe",
                    patient_dob="1990-01-01",
                    staff_name="Dr. Smith",
                    date="2026-07-07",
                    statement_paragraphs=["I consent."],
                    time="2:32 PM",
                    consented_by="Patient",
                )
            ]
            assert mock_payload.mock_calls == [
                call(
                    system="http://loinc.org",
                    code="12345",
                    display="Consent to Treat",
                    patient_id="patient-1",
                    pdf_base64="PDF64",
                    today="2026-07-07",
                )
            ]
            assert mock_fhir.mock_calls == [
                call("client-id", "client-secret"),
                call().create("Consent", {"resourceType": "Consent"}),
            ]

        assert result[0].content == {
            "ok": True,
            "preview": {
                "title": "Consent to Treat",
                "patient_name": "Jane Doe",
                "patient_dob": "1990-01-01",
                "consented_by": "Patient",
                "collected_by": "Dr. Smith",
                "date": "2026-07-07",
                "time": "2:32 PM",
            },
        }

    def test_invalid_local_date_falls_back_to_utc(self):
        api = _make_api({"patient_id": "patient-1", "local_date": "not-a-date"})
        p1, p2, p3, p4, p5 = self._patch_pipeline()
        with p1, p2, p3 as mock_pdf, p4, p5, patch(
            f"{MODULE}.CanvasFhir"
        ), patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value.isoformat.return_value = (
                "2026-07-07"
            )
            api.collect()

            # datetime.now(timezone.utc).date().isoformat()
            assert mock_pdf.mock_calls[0].kwargs["date"] == "2026-07-07"


class TestCollectFhirErrorHandling:
    def _base(self):
        api = _make_api({"patient_id": "patient-1", "local_date": "2026-07-07"})
        return api

    def test_2xx_empty_body_treated_as_success(self):
        api = self._base()
        exc = ValueError("no json")
        exc.response = MagicMock()
        exc.response.status_code = 201
        with patch(f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")), patch(
            f"{MODULE}._resolve_staff", return_value="Dr. Smith"
        ), patch(f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"), patch(
            f"{MODULE}.build_consent_payload", return_value={}
        ), patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(
            f"{MODULE}.log"
        ) as mock_log:
            mock_fhir.return_value.create.side_effect = exc
            result = api.collect()

            assert result[0].content["ok"] is True
            assert any(
                "empty body" in str(c) for c in mock_log.mock_calls
            )

    def test_empty_body_value_error_no_response_treated_as_success(self):
        api = self._base()
        exc = ValueError("no json")  # no .response attribute
        with patch(f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")), patch(
            f"{MODULE}._resolve_staff", return_value="Dr. Smith"
        ), patch(f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"), patch(
            f"{MODULE}.build_consent_payload", return_value={}
        ), patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir:
            mock_fhir.return_value.create.side_effect = exc
            result = api.collect()
            assert result[0].content["ok"] is True

    def test_real_http_error_returns_error_response(self):
        api = self._base()
        exc = Exception("boom")
        exc.response = MagicMock()
        exc.response.status_code = 400
        exc.response.text = "Bad Request"
        with patch(f"{MODULE}._resolve_patient", return_value=("Jane Doe", "")), patch(
            f"{MODULE}._resolve_staff", return_value="Dr. Smith"
        ), patch(f"{MODULE}.generate_consent_pdf_base64", return_value="PDF"), patch(
            f"{MODULE}.build_consent_payload", return_value={}
        ), patch(
            f"{MODULE}.parse_statement", return_value=[]
        ), patch(
            f"{MODULE}.CanvasFhir"
        ) as mock_fhir, patch(
            f"{MODULE}.log"
        ) as mock_log:
            mock_fhir.return_value.create.side_effect = exc
            result = api.collect()

            assert result[0].content == {
                "ok": False,
                "error": "We couldn't save the consent. If this keeps happening, "
                "please contact your administrator.",
            }
            assert any("failed" in str(c) for c in mock_log.mock_calls)


class TestError:
    def test_error_builds_json_response(self):
        api = ConsentApi()
        response = api._error("Something went wrong.")
        assert response.content == {"ok": False, "error": "Something went wrong."}
