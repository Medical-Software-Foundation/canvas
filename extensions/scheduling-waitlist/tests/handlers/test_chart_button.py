"""The add-to-waitlist button on the chart header."""

import json
from unittest.mock import MagicMock, patch

from canvas_sdk.effects.launch_modal import LaunchModalEffect

from scheduling_waitlist.handlers.chart_button import AddToWaitlistChartButton

MODULE = "scheduling_waitlist.handlers.chart_button"


def _button(patient_id="patient-key", secrets=None):
    button = AddToWaitlistChartButton.__new__(AddToWaitlistChartButton)
    event = MagicMock()
    event.target.id = patient_id
    button.event = event
    button.secrets = secrets or {"WAITLIST_APPOINTMENT_TYPES": "estab"}
    return button


def _patient():
    patient = MagicMock()
    patient.dbid = 55
    patient.id = "patient-key"
    patient.first_name = "Jordan"
    patient.last_name = "Lee"
    return patient


class TestButtonTitle:
    def test_reads_plain_when_the_patient_is_not_waiting(self):
        with (
            patch(f"{MODULE}.Patient") as patient_model,
            patch(f"{MODULE}.live_entries_for_patient", return_value=[]),
        ):
            patient_model.objects.filter.return_value.first.return_value = _patient()

            assert _button().BUTTON_TITLE == "Waitlist"

    def test_carries_a_count_when_the_patient_is_already_waiting(self):
        with (
            patch(f"{MODULE}.Patient") as patient_model,
            patch(f"{MODULE}.live_entries_for_patient", return_value=[1, 2]),
        ):
            patient_model.objects.filter.return_value.first.return_value = _patient()

            assert _button().BUTTON_TITLE == "Waitlist (2)"

    def test_falls_back_when_no_patient_is_in_context(self):
        assert _button(patient_id=None).BUTTON_TITLE == "Waitlist"

    def test_falls_back_when_the_patient_cannot_be_found(self):
        with patch(f"{MODULE}.Patient") as patient_model:
            patient_model.objects.filter.return_value.first.return_value = None

            assert _button().BUTTON_TITLE == "Waitlist"


class TestHandle:
    def _handle(self, button):
        with (
            patch(f"{MODULE}.Patient") as patient_model,
            patch(f"{MODULE}.live_entries_for_patient", return_value=[]),
            patch(f"{MODULE}.render_to_string", return_value="<form></form>"),
        ):
            patient_model.objects.filter.return_value.first.return_value = _patient()
            return button.handle()

    def test_returns_a_single_modal_effect(self):
        effects = self._handle(_button())

        assert len(effects) == 1

    def test_opens_in_the_chart_side_pane_to_keep_the_chart_in_view(self):
        effects = self._handle(_button())

        assert effects[0].target == LaunchModalEffect.TargetType.RIGHT_CHART_PANE

    def test_renders_inline_rather_than_pointing_at_a_url(self):
        # Inline keeps the patient identifier out of an iframe URL and the
        # browser's history.
        effects = self._handle(_button())

        assert effects[0].content is not None
        assert effects[0].url is None

    def test_does_nothing_without_a_patient_in_context(self):
        assert _button(patient_id=None).handle() == []

    def test_does_nothing_when_the_patient_cannot_be_found(self):
        with patch(f"{MODULE}.Patient") as patient_model:
            patient_model.objects.filter.return_value.first.return_value = None

            assert _button().handle() == []


class TestModalContext:
    def _context(self, note_type_name="Established Visit"):
        note_type = MagicMock()
        note_type.dbid = 7
        note_type.code = "estab"
        note_type.name = note_type_name

        with (
            patch(f"{MODULE}.Patient") as patient_model,
            patch(f"{MODULE}.live_entries_for_patient", return_value=[]),
            patch(f"{MODULE}.render_to_string", return_value="<form></form>") as render,
            patch("scheduling_waitlist.services.options.NoteType") as note_type_model,
            patch("scheduling_waitlist.services.options.Staff") as staff_model,
            patch("scheduling_waitlist.services.options.PracticeLocation") as location_model,
        ):
            patient_model.objects.filter.return_value.first.return_value = _patient()
            note_type_model.objects.filter.return_value.order_by.return_value = [note_type]
            staff_model.objects.filter.return_value.order_by.return_value = []
            location_model.objects.filter.return_value.order_by.return_value = []

            _button().handle()

        return render.call_args[0][1]

    def test_uses_the_shared_form_template(self):
        with (
            patch(f"{MODULE}.Patient") as patient_model,
            patch(f"{MODULE}.live_entries_for_patient", return_value=[]),
            patch(f"{MODULE}.render_to_string", return_value="<form></form>") as render,
        ):
            patient_model.objects.filter.return_value.first.return_value = _patient()
            _button().handle()

        assert render.call_args[0][0] == "templates/add_to_waitlist.html"

    def test_embedded_config_is_valid_json(self):
        embedded = json.loads(self._context()["config_json"])

        assert embedded["patientId"] == "patient-key"

    def test_a_service_named_like_a_script_tag_cannot_break_out(self):
        # json.dumps leaves < and > alone, so an unescaped value containing a
        # closing script tag would end the inline block and run as markup.
        raw = self._context(note_type_name="</script><img src=x onerror=alert(1)>")[
            "config_json"
        ]

        assert "</script>" not in raw
        assert "\\u003c" in raw

    def test_escaped_config_still_decodes_to_the_original_text(self):
        name = "</script>Cardiology & Vascular"
        decoded = json.loads(self._context(note_type_name=name)["config_json"])

        assert decoded["options"]["appointment_types"][0]["name"] == name
