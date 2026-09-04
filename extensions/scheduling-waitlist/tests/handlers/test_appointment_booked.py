"""Closing waitlist entries when the patient gets booked."""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.appointment_booked import AppointmentBookedHandler

MODULE = "scheduling_waitlist.handlers.appointment_booked"


def _handler(appointment_id="appt-key"):
    handler = AppointmentBookedHandler.__new__(AppointmentBookedHandler)
    event = MagicMock()
    event.target.id = appointment_id
    event.context = {}
    handler.event = event
    handler.secrets = {}
    return handler


def _appointment(**overrides):
    record = MagicMock()
    record.dbid = 900
    record.id = "appt-key"
    record.patient_id = 55
    record.note_type_id = 7
    record.provider_id = 101
    record.location_id = 3
    record.appointment_rescheduled_from_id = None
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


BANNER = "banner-effect"


def _run(handler, appointment=None, entries=None):
    with (
        patch(f"{MODULE}.Appointment") as appointment_model,
        patch(f"{MODULE}.find_entries_to_flip", return_value=entries or []) as matcher,
        patch(f"{MODULE}.apply_transition") as transition,
        patch(f"{MODULE}.banner_effects", return_value=[BANNER]),
    ):
        queryset = appointment_model.objects.filter.return_value.select_related.return_value
        queryset.first.return_value = appointment
        effects = handler.compute()
    return effects, matcher, transition


class TestGuards:
    def test_an_event_with_no_identifier_is_ignored(self):
        assert _handler(appointment_id=None).compute() == []

    def test_a_missing_appointment_is_ignored(self):
        effects, _, transition = _run(_handler(), appointment=None)

        assert effects == []
        transition.assert_not_called()

    def test_an_appointment_without_a_patient_is_ignored(self):
        effects, _, transition = _run(
            _handler(), appointment=_appointment(patient_id=None)
        )

        assert effects == []
        transition.assert_not_called()

    def test_a_rescheduled_appointment_does_not_count_as_a_new_booking(self):
        # A move is not a slot being taken, and treating it as one would close
        # an entry the patient still wants.
        effects, matcher, transition = _run(
            _handler(), appointment=_appointment(appointment_rescheduled_from_id=800)
        )

        assert effects == []
        matcher.assert_not_called()
        transition.assert_not_called()


class TestFlipping:
    def test_a_matching_entry_is_marked_scheduled(self):
        _, _, transition = _run(_handler(), appointment=_appointment(), entries=[MagicMock()])

        assert transition.call_args.kwargs["to_status"] == "scheduled"

    def test_the_satisfying_appointment_is_recorded(self):
        _, _, transition = _run(_handler(), appointment=_appointment(), entries=[MagicMock()])

        assert transition.call_args.kwargs["appointment_dbid"] == 900

    def test_every_matching_entry_is_closed(self):
        _, _, transition = _run(
            _handler(), appointment=_appointment(), entries=[MagicMock(), MagicMock()]
        )

        assert transition.call_count == 2

    def test_closing_an_entry_refreshes_the_chart_banner(self):
        # The patient is no longer waiting for this service, so their chart must
        # stop saying they are.
        effects, _, _ = _run(_handler(), appointment=_appointment(), entries=[MagicMock()])

        assert effects == [BANNER]

    def test_closing_nothing_leaves_the_banner_alone(self):
        # Nothing changed, so there is nothing to redraw -- and re-emitting on
        # every booking would put a write on every appointment in the practice.
        effects, _, _ = _run(_handler(), appointment=_appointment(), entries=[])

        assert effects == []

    def test_a_refused_transition_does_not_stop_the_others(self):
        from scheduling_waitlist.services.transitions import TransitionError

        with (
            patch(f"{MODULE}.Appointment") as appointment_model,
            patch(f"{MODULE}.find_entries_to_flip", return_value=[MagicMock(), MagicMock()]),
            patch(
                f"{MODULE}.apply_transition",
                side_effect=[TransitionError("nope"), None],
            ) as transition,
            patch(f"{MODULE}.banner_effects", return_value=[BANNER]),
        ):
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = _appointment()

            # The second entry closed, so the banner is still refreshed.
            assert _handler().compute() == [BANNER]

        assert transition.call_count == 2

    def test_appointments_marked_entered_in_error_are_excluded(self):
        with (
            patch(f"{MODULE}.Appointment") as appointment_model,
            patch(f"{MODULE}.find_entries_to_flip", return_value=[]),
            patch(f"{MODULE}.apply_transition"),
        ):
            queryset = appointment_model.objects.filter.return_value.select_related.return_value
            queryset.first.return_value = _appointment()
            _handler().compute()

        assert (
            appointment_model.objects.filter.call_args.kwargs["entered_in_error__isnull"]
            is True
        )
