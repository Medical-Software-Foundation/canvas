"""The add-to-waitlist button on a cancelled or no-showed appointment."""

import json
from unittest.mock import MagicMock, patch

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.v1.data.note import NoteStates

from scheduling_waitlist.handlers.appointment_button import AddToWaitlistAppointmentButton

MODULE = "scheduling_waitlist.handlers.appointment_button"


def _button(note_id=88, secrets=None):
    button = AddToWaitlistAppointmentButton.__new__(AddToWaitlistAppointmentButton)
    event = MagicMock()
    event.context = {"note_id": note_id} if note_id else {}
    button.event = event
    button.secrets = secrets or {"WAITLIST_APPOINTMENT_TYPES": "estab"}
    return button


def _note_in_state(state):
    note = MagicMock()
    note.current_state.state = state
    return note


def _appointment(note_type_id=7, provider_id=101, location_id=3, patient=True):
    appointment = MagicMock()
    appointment.note_type_id = note_type_id
    appointment.provider_id = provider_id
    appointment.location_id = location_id
    appointment.note_type.name = "Established Visit"
    appointment.note_type.code = "estab"
    if patient:
        appointment.patient.dbid = 55
        appointment.patient.id = "patient-key"
        appointment.patient.first_name = "Jordan"
        appointment.patient.last_name = "Lee"
    else:
        appointment.patient = None
    return appointment


class TestVisibility:
    def _visible(self, state):
        with patch(f"{MODULE}.Note") as note_model:
            note_model.objects.filter.return_value.first.return_value = _note_in_state(state)
            return _button().visible()

    def test_shown_on_a_cancelled_appointment(self):
        assert self._visible(NoteStates.CANCELLED) is True

    def test_shown_on_a_no_showed_appointment(self):
        assert self._visible(NoteStates.NOSHOW) is True

    def test_hidden_on_a_booked_appointment(self):
        # Adding someone to the waitlist for a visit they are about to attend
        # makes no sense.
        assert self._visible(NoteStates.BOOKED) is False

    def test_hidden_on_a_checked_in_appointment(self):
        assert self._visible(NoteStates.CONVERTED) is False

    def test_hidden_on_a_signed_note(self):
        assert self._visible(NoteStates.SIGNED) is False

    def test_hidden_when_there_is_no_note_in_context(self):
        assert _button(note_id=None).visible() is False

    def test_hidden_when_the_note_cannot_be_found(self):
        with patch(f"{MODULE}.Note") as note_model:
            note_model.objects.filter.return_value.first.return_value = None

            assert _button().visible() is False

    def test_hidden_when_the_note_has_no_recorded_state(self):
        note = MagicMock()
        note.current_state = None
        with patch(f"{MODULE}.Note") as note_model:
            note_model.objects.filter.return_value.first.return_value = note

            assert _button().visible() is False


class TestHandle:
    def _handle(self, button=None, appointment=None):
        button = button or _button()
        with (
            patch(f"{MODULE}.Appointment") as appointment_model,
            patch(f"{MODULE}.render_to_string", return_value="<form></form>") as render,
            patch(f"{MODULE}.build_form_context", return_value={}) as builder,
        ):
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = (
                _appointment() if appointment is None else appointment
            )
            effects = button.handle()
        return effects, render, builder

    def test_returns_a_single_chart_pane_modal(self):
        effects, _, _ = self._handle()

        assert len(effects) == 1
        assert effects[0].target == LaunchModalEffect.TargetType.RIGHT_CHART_PANE

    def test_renders_inline_rather_than_by_url(self):
        effects, _, _ = self._handle()

        assert effects[0].content is not None
        assert effects[0].url is None

    def test_ignores_appointments_marked_entered_in_error(self):
        # Excluded in the lookup, which is the only place it can be done
        # reliably.
        with (
            patch(f"{MODULE}.Appointment") as appointment_model,
            patch(f"{MODULE}.render_to_string", return_value="<form></form>"),
            patch(f"{MODULE}.build_form_context", return_value={}),
        ):
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = _appointment()
            _button().handle()

        assert (
            appointment_model.objects.filter.call_args.kwargs["entered_in_error__isnull"]
            is True
        )

    def test_does_nothing_without_a_note_in_context(self):
        assert _button(note_id=None).handle() == []

    def test_does_nothing_when_no_appointment_is_linked_to_the_note(self):
        with patch(f"{MODULE}.Appointment") as appointment_model:
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = None

            assert _button().handle() == []

    def test_does_nothing_when_the_appointment_has_no_patient(self):
        with patch(f"{MODULE}.Appointment") as appointment_model:
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = _appointment(patient=False)

            assert _button().handle() == []


class TestPrefill:
    def _prefill(self, appointment):
        with (
            patch(f"{MODULE}.Appointment") as appointment_model,
            patch(f"{MODULE}.render_to_string", return_value="<form></form>"),
            patch(f"{MODULE}.build_form_context", return_value={}) as builder,
        ):
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = appointment
            _button().handle()
        return builder.call_args.kwargs["prefill"]

    def test_service_provider_and_location_come_from_the_freed_slot(self):
        prefill = self._prefill(_appointment())

        assert prefill["appointment_type_id"] == 7
        assert prefill["provider_id"] == 101
        assert prefill["location_id"] == 3

    def test_a_named_provider_is_pre_selected_as_specific(self):
        assert self._prefill(_appointment())["provider_preference"] == "specific"

    def test_an_appointment_without_a_provider_leaves_that_field_open(self):
        prefill = self._prefill(_appointment(provider_id=None))

        assert "provider_id" not in prefill

    def test_an_appointment_without_a_location_leaves_that_field_open(self):
        prefill = self._prefill(_appointment(location_id=None))

        assert "location_id" not in prefill

    def test_an_appointment_without_a_type_leaves_that_field_open(self):
        prefill = self._prefill(_appointment(note_type_id=None))

        assert "appointment_type_id" not in prefill


class TestModalContext:
    def test_the_form_escapes_values_that_could_break_out_of_the_script_block(self):
        appointment = _appointment()
        appointment.note_type.name = "</script><img src=x onerror=alert(1)>"

        with (
            patch(f"{MODULE}.Appointment") as appointment_model,
            patch(f"{MODULE}.render_to_string", return_value="<form></form>") as render,
            patch("scheduling_waitlist.services.form.live_entries_for_patient", return_value=[]),
            patch("scheduling_waitlist.services.options.NoteType") as note_type_model,
            patch("scheduling_waitlist.services.options.Staff") as staff_model,
            patch("scheduling_waitlist.services.options.PracticeLocation") as location_model,
        ):
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = appointment
            note_type_model.objects.filter.return_value.order_by.return_value = []
            staff_model.objects.filter.return_value.order_by.return_value = []
            location_model.objects.filter.return_value.order_by.return_value = []

            _button().handle()

        context = render.call_args[0][1]
        assert "</script>" not in context["config_json"]
        assert json.loads(context["config_json"])["patientId"] == "patient-key"
