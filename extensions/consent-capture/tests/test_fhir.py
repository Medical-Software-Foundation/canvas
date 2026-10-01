"""Tests for consent_capture/fhir.py."""

from consent_capture.fhir import _attachment_filename, build_consent_payload


class TestAttachmentFilename:
    def test_uses_display_when_present(self):
        assert (
            _attachment_filename("Consent to Treat", "12345", "2026-07-07")
            == "Consent_to_Treat_2026-07-07.pdf"
        )

    def test_falls_back_to_code_when_no_display(self):
        assert (
            _attachment_filename("", "12345", "2026-07-07")
            == "12345_2026-07-07.pdf"
        )

    def test_falls_back_to_consent_when_no_display_or_code(self):
        assert (
            _attachment_filename("", "", "2026-07-07")
            == "Consent_2026-07-07.pdf"
        )

    def test_strips_unsafe_characters(self):
        assert (
            _attachment_filename("Consent/Release: @Home!", "c", "2026-07-07")
            == "ConsentRelease_Home_2026-07-07.pdf"
        )

    def test_label_with_only_unsafe_chars_becomes_consent(self):
        assert (
            _attachment_filename("@@@***", "", "2026-07-07")
            == "Consent_2026-07-07.pdf"
        )

    def test_always_ends_in_pdf(self):
        assert _attachment_filename("X", "Y", "2026-01-01").endswith(".pdf")


class TestBuildConsentPayload:
    def test_full_payload_with_display(self):
        payload = build_consent_payload(
            system="http://loinc.org",
            code="12345",
            display="Consent to Treat",
            patient_id="patient-abc",
            pdf_base64="QkFTRTY0",
            today="2026-07-07",
        )

        assert payload["resourceType"] == "Consent"
        assert payload["status"] == "active"
        assert payload["scope"] == {}
        assert payload["category"] == [
            {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "12345",
                        "display": "Consent to Treat",
                    }
                ]
            }
        ]
        assert payload["patient"] == {
            "reference": "Patient/patient-abc",
            "type": "Patient",
        }
        assert payload["sourceAttachment"] == {
            "title": "Consent_to_Treat_2026-07-07.pdf",
            "contentType": "application/pdf",
            "data": "QkFTRTY0",
        }
        assert payload["provision"] == {"period": {"start": "2026-07-07"}}

    def test_coding_omits_display_when_empty(self):
        payload = build_consent_payload(
            system="http://loinc.org",
            code="12345",
            display="",
            patient_id="patient-abc",
            pdf_base64="QkFTRTY0",
            today="2026-07-07",
        )

        coding = payload["category"][0]["coding"][0]
        assert coding == {"system": "http://loinc.org", "code": "12345"}
        assert "display" not in coding

    def test_no_period_end_means_never_expires(self):
        payload = build_consent_payload(
            system="s",
            code="c",
            display="d",
            patient_id="p",
            pdf_base64="x",
            today="2026-07-07",
        )
        assert "end" not in payload["provision"]["period"]

    def test_omits_attachment_when_no_pdf(self):
        # A "Written" consent passes no PDF — the payload carries no attachment.
        payload = build_consent_payload(
            system="s",
            code="c",
            display="d",
            patient_id="p",
            today="2026-07-07",
            pdf_base64="",
        )
        assert "sourceAttachment" not in payload
        assert payload["resourceType"] == "Consent"
        assert payload["provision"] == {"period": {"start": "2026-07-07"}}

    def test_attachment_present_when_pdf_given(self):
        payload = build_consent_payload(
            system="s",
            code="c",
            display="d",
            patient_id="p",
            today="2026-07-07",
            pdf_base64="QkFTRTY0",
        )
        assert payload["sourceAttachment"]["data"] == "QkFTRTY0"

    def test_pdf_base64_defaults_to_empty(self):
        # Called positionally without a PDF -> no attachment.
        payload = build_consent_payload("s", "c", "d", "p", "2026-07-07")
        assert "sourceAttachment" not in payload
