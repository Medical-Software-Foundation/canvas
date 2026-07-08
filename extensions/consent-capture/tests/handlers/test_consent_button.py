"""Tests for consent_capture/handlers/consent_button.py."""

from unittest.mock import MagicMock, call, patch

from consent_capture.handlers.consent_button import ConsentButton, should_prompt

MODULE = "consent_capture.handlers.consent_button"


class TestShouldPrompt:
    def test_no_patient_hides(self):
        assert should_prompt("", "code", False) is False

    def test_no_code_shows(self):
        assert should_prompt("patient-1", "", False) is True

    def test_accepted_exists_hides(self):
        assert should_prompt("patient-1", "code", True) is False

    def test_no_accepted_shows(self):
        assert should_prompt("patient-1", "code", False) is True


class TestPatientId:
    def test_returns_target_id(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"

        assert button._patient_id() == "patient-123"

        # Only attribute reads/sets occurred — no recorded method calls.
        assert button.event.mock_calls == []

    def test_no_target_returns_none(self):
        button = ConsentButton()
        button.event = None
        assert button._patient_id() is None


class TestVisible:
    def test_no_patient_id_not_visible(self):
        button = ConsentButton()
        button.event = None
        assert button.visible() is False

    def test_no_code_configured_is_visible(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        button.secrets = {"CONSENT_SYSTEM": "http://loinc.org", "CONSENT_CODE": ""}

        assert button.visible() is True

    def test_accepted_consent_hides_button(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        button.secrets = {
            "CONSENT_SYSTEM": "http://loinc.org",
            "CONSENT_CODE": "12345",
        }

        with patch(f"{MODULE}.PatientConsent") as mock_consent:
            mock_consent.objects.filter.return_value.exists.return_value = True

            assert button.visible() is False

            assert mock_consent.mock_calls == [
                call.objects.filter(
                    patient__id="patient-123",
                    category__code="12345",
                    state__in=("accepted", "accepted_via_patient_portal"),
                    category__system="http://loinc.org",
                ),
                call.objects.filter().exists(),
            ]

    def test_no_accepted_consent_shows_button(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        button.secrets = {
            "CONSENT_SYSTEM": "http://loinc.org",
            "CONSENT_CODE": "12345",
        }

        with patch(f"{MODULE}.PatientConsent") as mock_consent:
            mock_consent.objects.filter.return_value.exists.return_value = False

            assert button.visible() is True

            assert mock_consent.mock_calls == [
                call.objects.filter(
                    patient__id="patient-123",
                    category__code="12345",
                    state__in=("accepted", "accepted_via_patient_portal"),
                    category__system="http://loinc.org",
                ),
                call.objects.filter().exists(),
            ]

    def test_no_system_omits_system_filter(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        button.secrets = {"CONSENT_SYSTEM": "", "CONSENT_CODE": "12345"}

        with patch(f"{MODULE}.PatientConsent") as mock_consent:
            mock_consent.objects.filter.return_value.exists.return_value = False

            assert button.visible() is True

            assert mock_consent.mock_calls == [
                call.objects.filter(
                    patient__id="patient-123",
                    category__code="12345",
                    state__in=("accepted", "accepted_via_patient_portal"),
                ),
                call.objects.filter().exists(),
            ]


class TestHandle:
    def _button(self, statement=""):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        button.event.context = {"user": {"id": "staff-9"}}
        button.secrets = {
            "CONSENT_DISPLAY": "Consent to Treat",
            "CONSENT_STATEMENT": statement,
        }
        return button

    def test_handle_builds_modal_with_patient_row(self):
        button = self._button(statement="I consent.")

        dob = MagicMock()
        dob.isoformat.return_value = "1990-01-01"

        with patch(f"{MODULE}.Patient") as mock_patient, patch(
            f"{MODULE}.render_to_string"
        ) as mock_render, patch(f"{MODULE}.log") as mock_log:
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                "Jane",
                "Doe",
                dob,
            )
            mock_render.return_value = "<html>modal</html>"

            effects = button.handle()

            assert mock_patient.mock_calls == [
                call.objects.filter(id="patient-123"),
                call.objects.filter().values_list(
                    "first_name", "last_name", "birth_date"
                ),
                call.objects.filter().values_list().first(),
            ]
            assert mock_render.mock_calls == [
                call(
                    "templates/consent.html",
                    {
                        "patient_id": "patient-123",
                        "patient_name": "Jane Doe",
                        "patient_dob": "1990-01-01",
                        "consent_display": "Consent to Treat",
                        "paragraphs": ["I consent."],
                        "no_statement_note": "Review the consent with the patient before recording.",
                    },
                )
            ]
            assert mock_log.mock_calls == [
                call.info(
                    "ConsentButton: opened for patient patient-123 by staff staff-9"
                )
            ]
            assert dob.mock_calls == [call.__bool__(), call.isoformat()]

        assert len(effects) == 1
        effect = effects[0]
        assert effect == {
            "type": "LaunchModalEffect",
            "target": "default_modal",
            "content": "<html>modal</html>",
        }

    def test_handle_with_no_patient_row(self):
        button = self._button(statement="")

        with patch(f"{MODULE}.Patient") as mock_patient, patch(
            f"{MODULE}.render_to_string"
        ) as mock_render, patch(f"{MODULE}.log") as mock_log:
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                None
            )
            mock_render.return_value = "<html>empty</html>"

            effects = button.handle()

            assert mock_patient.mock_calls == [
                call.objects.filter(id="patient-123"),
                call.objects.filter().values_list(
                    "first_name", "last_name", "birth_date"
                ),
                call.objects.filter().values_list().first(),
            ]
            # Name/dob blank because there was no row.
            assert mock_render.mock_calls == [
                call(
                    "templates/consent.html",
                    {
                        "patient_id": "patient-123",
                        "patient_name": "",
                        "patient_dob": "",
                        "consent_display": "Consent to Treat",
                        "paragraphs": [],
                        "no_statement_note": "Review the consent with the patient before recording.",
                    },
                )
            ]
            assert mock_log.mock_calls == [
                call.info(
                    "ConsentButton: opened for patient patient-123 by staff staff-9"
                )
            ]

        assert len(effects) == 1

    def test_handle_row_without_birth_date(self):
        button = self._button(statement="")

        with patch(f"{MODULE}.Patient") as mock_patient, patch(
            f"{MODULE}.render_to_string"
        ) as mock_render, patch(f"{MODULE}.log"):
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                "Jane",
                "Doe",
                None,
            )
            mock_render.return_value = "<html>ok</html>"

            button.handle()

            context = mock_render.mock_calls[0].args[1]
            assert context["patient_name"] == "Jane Doe"
            assert context["patient_dob"] == ""

    def test_handle_missing_user_context(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        button.event.context = {}
        button.secrets = {"CONSENT_DISPLAY": "", "CONSENT_STATEMENT": ""}

        with patch(f"{MODULE}.Patient") as mock_patient, patch(
            f"{MODULE}.render_to_string"
        ) as mock_render, patch(f"{MODULE}.log") as mock_log:
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                None
            )
            mock_render.return_value = "x"

            button.handle()

            assert mock_log.mock_calls == [
                call.info(
                    "ConsentButton: opened for patient patient-123 by staff "
                )
            ]
