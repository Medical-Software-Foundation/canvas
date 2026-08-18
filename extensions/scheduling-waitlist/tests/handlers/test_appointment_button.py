"""The add-to-waitlist button on a cancelled or no-showed appointment."""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.appointment_button import (
    AddToWaitlistAppointmentButton,
)

MODULE = "scheduling_waitlist.handlers.appointment_button"


def _button(note_id=536, target_id=None):
    button = AddToWaitlistAppointmentButton.__new__(AddToWaitlistAppointmentButton)
    event = MagicMock()
    event.context = {"note_id": note_id} if note_id is not None else {}
    event.target = MagicMock()
    event.target.id = target_id
    button.event = event
    button.secrets = {}
    return button


def _appointment(status="cancelled", patient_uuid="patient-uuid", **overrides):
    record = MagicMock()
    record.status = status
    record.patient = MagicMock(id=patient_uuid) if patient_uuid else None
    record.note_type_id = 7
    record.provider_id = 101
    record.location_id = 3
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def _found(appointment):
    """Run the lookup chain so it resolves to ``appointment``."""
    model = MagicMock()
    model.objects.filter.return_value.select_related.return_value.first.return_value = (
        appointment
    )
    return model


class TestPlacement:
    def test_it_lives_on_the_note_header(self):
        # Canvas offers no button surface on the calendar or an appointment card,
        # and every appointment has a note.
        assert AddToWaitlistAppointmentButton.BUTTON_LOCATION == "note_header"

    def test_its_key_is_distinct_from_the_chart_buttons(self):
        from scheduling_waitlist.handlers.chart_button import AddToWaitlistButton

        assert (
            AddToWaitlistAppointmentButton.BUTTON_KEY != AddToWaitlistButton.BUTTON_KEY
        )


class TestVisibility:
    def _visible(self, appointment, note_id=536, target_id=None):
        button = _button(note_id=note_id, target_id=target_id)
        with patch(f"{MODULE}.Appointment", _found(appointment)):
            return button.visible()

    def test_shown_on_a_cancelled_appointment(self):
        assert self._visible(_appointment(status="cancelled")) is True

    def test_shown_on_a_no_showed_appointment(self):
        assert self._visible(_appointment(status="noshowed")) is True

    def test_hidden_on_a_booked_appointment(self):
        # Inviting a waitlist entry for a visit somebody is about to attend makes
        # no sense.
        assert self._visible(_appointment(status="confirmed")) is False

    def test_hidden_on_an_arrived_appointment(self):
        assert self._visible(_appointment(status="arrived")) is False

    def test_hidden_on_a_note_with_no_appointment(self):
        # A regular office note: this button would be clutter.
        assert self._visible(None) is False

    def test_hidden_when_the_appointment_has_no_patient(self):
        # A waitlist entry needs somebody to put on it.
        assert self._visible(_appointment(patient_uuid=None)) is False

    def test_hidden_when_the_note_cannot_be_identified(self):
        assert self._visible(_appointment(), note_id=None) is False

    def test_the_note_key_is_read_from_the_target_when_the_context_omits_it(self):
        # The platform puts the note's dbid on both; a button that read only the
        # context would silently never appear.
        assert self._visible(_appointment(), note_id=None, target_id=536) is True

    def test_appointments_marked_entered_in_error_are_excluded(self):
        button = _button()
        model = _found(_appointment())
        with patch(f"{MODULE}.Appointment", model):
            button.visible()

        assert model.objects.filter.call_args.kwargs["entered_in_error__isnull"] is True

    def test_the_appointment_is_found_by_its_note(self):
        button = _button(note_id=536)
        model = _found(_appointment())
        with patch(f"{MODULE}.Appointment", model):
            button.visible()

        assert model.objects.filter.call_args.kwargs["note__dbid"] == 536


class TestClick:
    def _click(self, appointment):
        button = _button()
        with patch(f"{MODULE}.Appointment", _found(appointment)):
            return button.handle()

    def test_a_click_opens_the_compact_add_form(self):
        effects = self._click(_appointment())

        assert len(effects) == 1
        assert effects[0].url.startswith("/plugin-io/api/scheduling_waitlist/app/add?")

    def test_the_form_is_for_the_appointments_patient(self):
        url = self._click(_appointment(patient_uuid="abc-123"))[0].url

        assert "patient=abc-123" in url

    def test_the_freed_slots_service_provider_and_location_are_carried_over(self):
        # The whole reason to offer the button here rather than on a chart: the
        # scheduler does not re-enter what the cancellation already told us.
        url = self._click(_appointment())[0].url

        assert "service=7" in url
        assert "provider=101" in url
        assert "location=3" in url

    def test_a_slot_without_a_provider_carries_no_provider_key(self):
        # A blank key would be indistinguishable from a deliberate "any
        # provider" and would pre-select the wrong thing.
        url = self._click(_appointment(provider_id=None))[0].url

        assert "provider=" not in url
        assert "service=7" in url

    def test_a_slot_without_a_location_carries_no_location_key(self):
        url = self._click(_appointment(location_id=None))[0].url

        assert "location=" not in url

    def test_a_click_with_no_appointment_does_nothing(self):
        assert self._click(None) == []

    def test_a_click_with_no_patient_does_nothing(self):
        assert self._click(_appointment(patient_uuid=None)) == []
