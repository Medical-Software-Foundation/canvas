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


def _appointment(
    status="cancelled", patient_uuid="patient-uuid", note_state="NEW", **overrides
):
    record = MagicMock()
    record.status = status
    record.patient = MagicMock(id=patient_uuid) if patient_uuid else None
    record.note_type_id = 7
    record.provider_id = 101
    record.location_id = 3
    if note_state is None:
        # A note with no state history yet: nothing to read.
        record.note = MagicMock(current_state=None)
    else:
        record.note = MagicMock(current_state=MagicMock(state=note_state))
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
    def _visible(self, appointment, note_id=536, target_id=None, waiting=False):
        button = _button(note_id=note_id, target_id=target_id)
        with (
            patch(f"{MODULE}.Appointment", _found(appointment)),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=waiting),
        ):
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
        with (
            patch(f"{MODULE}.Appointment", model),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=False),
        ):
            button.visible()

        assert model.objects.filter.call_args.kwargs["entered_in_error__isnull"] is True

    def test_the_appointment_is_found_by_its_note(self):
        button = _button(note_id=536)
        model = _found(_appointment())
        with (
            patch(f"{MODULE}.Appointment", model),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=False),
        ):
            button.visible()

        assert model.objects.filter.call_args.kwargs["note__dbid"] == 536


class TestEitherRecordCountsAsFreed:
    """A slot can be given up in two records and only one is sure to move.

    Reading the appointment's status alone meant the button never appeared after
    a no-show, because marking no-show is a note state transition and whether it
    also writes Appointment.status is not visible from a plugin.
    """

    def _visible(self, appointment):
        button = _button()
        with (
            patch(f"{MODULE}.Appointment", _found(appointment)),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=False),
        ):
            return button.visible()

    def test_the_status_field_alone_is_enough(self):
        assert self._visible(_appointment(status="noshowed", note_state="NEW")) is True

    def test_a_no_showed_note_alone_is_enough(self):
        # The case that was failing on the instance.
        assert self._visible(_appointment(status="confirmed", note_state="NSW")) is True

    def test_a_cancelled_note_alone_is_enough(self):
        assert self._visible(_appointment(status="confirmed", note_state="CLD")) is True

    def test_neither_record_freed_stays_hidden(self):
        assert self._visible(_appointment(status="confirmed", note_state="NEW")) is False

    def test_a_note_with_no_state_history_falls_back_to_the_status(self):
        assert self._visible(_appointment(status="cancelled", note_state=None)) is True
        assert self._visible(_appointment(status="confirmed", note_state=None)) is False

    def test_an_appointment_with_no_note_does_not_crash(self):
        assert self._visible(_appointment(status="confirmed", note=None)) is False

    def test_the_note_state_is_selected_with_the_appointment(self):
        # Otherwise reading it costs a query on every note header render.
        button = _button()
        model = _found(_appointment())
        with (
            patch(f"{MODULE}.Appointment", model),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=False),
        ):
            button.visible()

        assert "note__current_state" in model.objects.filter.return_value.select_related.call_args.args


class TestClick:
    def _click(self, appointment, waiting=False):
        button = _button()
        with (
            patch(f"{MODULE}.Appointment", _found(appointment)),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=waiting),
        ):
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


class TestLabelReflectsThisSlotsService:
    """The label answers "already waiting for *this* service?", not "on the list?".

    Scoped to the freed slot's service on purpose: somebody waiting for a
    physical is not waiting for the follow-up that just opened, and "On waitlist"
    there would talk a scheduler out of adding the thing they should.
    """

    def _title(self, appointment, waiting):
        button = _button()
        with (
            patch(f"{MODULE}.Appointment", _found(appointment)),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=waiting),
        ):
            button.visible()
        return button.BUTTON_TITLE

    def test_not_yet_waiting_invites_an_add(self):
        assert self._title(_appointment(), waiting=False) == "Add to waitlist"

    def test_already_waiting_for_this_service_says_so(self):
        assert self._title(_appointment(), waiting=True) == "On waitlist"

    def test_the_question_is_asked_about_this_slots_service_and_patient(self):
        button = _button()
        appointment = _appointment()
        appointment.patient.dbid = 55
        with (
            patch(f"{MODULE}.Appointment", _found(appointment)),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=False) as asked,
        ):
            button.visible()

        assert asked.call_args.args == (55, 7)

    def test_the_label_is_not_written_onto_the_class(self):
        # A class attribute would carry one note's label onto the next.
        self._title(_appointment(), waiting=True)

        assert AddToWaitlistAppointmentButton.BUTTON_TITLE == "Add to waitlist"


class TestClickFollowsTheLabel:
    def _click(self, waiting):
        button = _button()
        with (
            patch(f"{MODULE}.Appointment", _found(_appointment())),
            patch(f"{MODULE}.has_live_entry_for_service", return_value=waiting),
        ):
            return button.handle()[0].url

    def test_not_yet_waiting_opens_the_prefilled_form(self):
        url = self._click(waiting=False)

        assert url.startswith("/plugin-io/api/scheduling_waitlist/app/add?")
        assert "service=7" in url

    def test_already_waiting_opens_the_roster_filtered_to_them(self):
        # Offering an add form for a service they already want would only earn a
        # 409 from the duplicate guard.
        url = self._click(waiting=True)

        assert url.startswith("/plugin-io/api/scheduling_waitlist/app/?")
        assert "patient=patient-uuid" in url
