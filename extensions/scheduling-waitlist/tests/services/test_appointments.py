"""What each waiting patient already has booked.

The roster's own answer to staleness. ``appointment_booked`` closes an entry only
when a booking satisfies what it asked for, so a patient seen through any other
route stays on the list with nothing to show it -- which is how schedulers come to
distrust the whole page.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scheduling_waitlist.constants import RECENT_VISIT_WINDOW_DAYS
from scheduling_waitlist.services.appointments import (
    STATE_ATTENDED,
    STATE_UPCOMING,
    next_appointment_map,
)

MODULE = "scheduling_waitlist.services.appointments"

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc)


def _appointment(
    *,
    patient_dbid=55,
    start=None,
    status="confirmed",
    type_name="Office visit",
    provider_name="Ada Chen",
    category="appointment",
):
    record = MagicMock()
    record.patient_id = patient_dbid
    record.start_time = start if start is not None else NOW + timedelta(days=1)
    record.status = status
    record.note_type = MagicMock(name="nt", category=category)
    record.note_type.name = type_name
    record.provider = MagicMock()
    record.provider.first_name = provider_name.split()[0]
    record.provider.last_name = provider_name.split()[-1]
    return record


def _model(rows):
    """Patch the Appointment lookup so the whole chain resolves to ``rows``."""
    model = MagicMock()
    (
        model.objects.filter.return_value.exclude.return_value.select_related.return_value.order_by.return_value
    ) = list(rows)
    return model


def _map(rows, dbids=(55,), now=NOW):
    model = _model(rows)
    with patch(f"{MODULE}.Appointment", model):
        return next_appointment_map(list(dbids), now=now), model


class TestAnUpcomingAppointment:
    def test_a_future_booking_is_reported(self):
        result, _ = _map([_appointment(start=NOW + timedelta(days=3))])

        assert result[55]["state"] == STATE_UPCOMING

    def test_the_soonest_future_booking_wins(self):
        # The reader is deciding whether to ring today, so the next thing in the
        # diary is the one that answers them.
        result, _ = _map(
            [
                _appointment(start=NOW + timedelta(days=1), type_name="Follow-up"),
                _appointment(start=NOW + timedelta(days=9), type_name="Physical"),
            ]
        )

        assert result[55]["type"] == "Follow-up"

    def test_it_carries_the_time_the_service_and_the_provider(self):
        result, _ = _map([_appointment(start=NOW + timedelta(days=2))])

        assert result[55]["start"] == (NOW + timedelta(days=2)).isoformat()
        assert result[55]["type"] == "Office visit"
        assert result[55]["provider"] == "Ada Chen"

    def test_an_appointment_starting_now_still_counts_as_upcoming(self):
        # The boundary is inclusive: a visit starting this minute has not been
        # attended, and calling it "seen" would flag the row wrongly.
        result, _ = _map([_appointment(start=NOW, status="confirmed")])

        assert result[55]["state"] == STATE_UPCOMING


class TestAVisitAlreadyAttended:
    def test_a_past_attended_visit_is_flagged(self):
        result, _ = _map(
            [_appointment(start=NOW - timedelta(days=4), status="exited")]
        )

        assert result[55]["state"] == STATE_ATTENDED

    def test_arrived_and_roomed_count_as_attended(self):
        # Whether the note was ever closed says nothing about whether the patient
        # walked in.
        for status in ("arrived", "roomed"):
            result, _ = _map(
                [_appointment(start=NOW - timedelta(days=2), status=status)]
            )

            assert result[55]["state"] == STATE_ATTENDED, status

    def test_a_past_appointment_nobody_attended_is_not_reported(self):
        # Still sitting at "unconfirmed" a week later tells us nothing.
        result, _ = _map(
            [_appointment(start=NOW - timedelta(days=7), status="unconfirmed")]
        )

        assert result == {}

    def test_the_most_recent_attended_visit_wins(self):
        result, _ = _map(
            [
                _appointment(
                    start=NOW - timedelta(days=30), status="exited", type_name="Physical"
                ),
                _appointment(
                    start=NOW - timedelta(days=2), status="exited", type_name="Follow-up"
                ),
            ]
        )

        assert result[55]["type"] == "Follow-up"

    def test_an_upcoming_booking_outranks_a_recent_visit(self):
        # "Do they still need a call?" is answered outright by something in the
        # diary, so that is what the row shows.
        result, _ = _map(
            [
                _appointment(start=NOW - timedelta(days=2), status="exited"),
                _appointment(start=NOW + timedelta(days=5), status="confirmed"),
            ]
        )

        assert result[55]["state"] == STATE_UPCOMING


class TestWhatIsNotAnAppointment:
    def test_a_calendar_block_is_not_reported(self):
        # The same exclusion the appointment-type dropdown uses: staff schedule
        # time with these and no patient attends them.
        result, _ = _map(
            [
                _appointment(
                    start=NOW + timedelta(days=1), category="schedule_event"
                )
            ]
        )

        assert result == {}

    def test_a_note_type_with_no_category_is_treated_as_a_visit(self):
        # Hiding a real appointment is the worse mistake of the two.
        result, _ = _map([_appointment(start=NOW + timedelta(days=1), category="")])

        assert result[55]["state"] == STATE_UPCOMING

    def test_given_up_slots_are_excluded_in_sql(self):
        _, model = _map([])
        excluded = model.objects.filter.return_value.exclude.call_args.kwargs

        assert set(excluded["status__in"]) == {"cancelled", "noshowed"}


class TestTheQuery:
    def test_it_reads_a_page_of_patients_in_one_query(self):
        # One query for the page is the whole point; per-row lookups would make
        # the most-read page in the plugin the slowest.
        _, model = _map([], dbids=(55, 56, 57))

        assert model.objects.filter.call_count == 1

    def test_it_asks_for_all_the_given_patients(self):
        _, model = _map([], dbids=(55, 56))
        filters = model.objects.filter.call_args.kwargs

        assert set(filters["patient_id__in"]) == {55, 56}

    def test_the_same_patient_is_asked_for_once(self):
        # A patient with two entries appears twice in the roster's list.
        _, model = _map([], dbids=(55, 55))

        assert model.objects.filter.call_args.kwargs["patient_id__in"] == [55]

    def test_retracted_appointments_are_excluded(self):
        _, model = _map([])

        assert model.objects.filter.call_args.kwargs["entered_in_error__isnull"] is True

    def test_history_is_bounded_to_the_recent_window(self):
        # Without a bound, one roster page would read every appointment every
        # waiting patient has ever had.
        _, model = _map([])
        earliest = model.objects.filter.call_args.kwargs["start_time__gte"]

        assert earliest == NOW - timedelta(days=RECENT_VISIT_WINDOW_DAYS)

    def test_the_names_it_shows_are_selected_up_front(self):
        _, model = _map([])
        selected = model.objects.filter.return_value.exclude.return_value.select_related.call_args.args

        assert set(selected) == {"note_type", "provider"}

    def test_no_patients_means_no_query_at_all(self):
        model = _model([])
        with patch(f"{MODULE}.Appointment", model):
            result = next_appointment_map([], now=NOW)

        assert result == {}
        assert model.objects.filter.call_count == 0

    def test_a_list_of_nothing_but_nulls_means_no_query(self):
        model = _model([])
        with patch(f"{MODULE}.Appointment", model):
            result = next_appointment_map([None, None], now=NOW)

        assert result == {}
        assert model.objects.filter.call_count == 0


class TestSeveralPatients:
    def test_each_patient_gets_their_own_answer(self):
        result, _ = _map(
            [
                _appointment(patient_dbid=55, start=NOW + timedelta(days=1)),
                _appointment(
                    patient_dbid=56, start=NOW - timedelta(days=1), status="exited"
                ),
            ],
            dbids=(55, 56),
        )

        assert result[55]["state"] == STATE_UPCOMING
        assert result[56]["state"] == STATE_ATTENDED

    def test_a_patient_with_nothing_to_show_is_absent(self):
        # Absent rather than present-and-empty: having no appointment is the
        # normal state for somebody waiting, and the cell stays blank.
        result, _ = _map(
            [_appointment(patient_dbid=55, start=NOW + timedelta(days=1))],
            dbids=(55, 56),
        )

        assert 56 not in result

    def test_an_appointment_with_no_patient_is_ignored(self):
        result, _ = _map([_appointment(patient_dbid=None)])

        assert result == {}


class TestWhatItSaysWhenDetailIsMissing:
    def test_an_appointment_with_no_provider_names_none(self):
        # The roster joins type and provider and drops blanks, so a placeholder
        # here would fabricate a detail in a column meant to be glanceable.
        row = _appointment(start=NOW + timedelta(days=1))
        row.provider = None

        result, _ = _map([row])

        assert result[55]["provider"] == ""

    def test_the_service_still_reads_as_something(self):
        # An unnamed type is a data problem, not a reason to render "None".
        row = _appointment(start=NOW + timedelta(days=1))
        row.note_type = None

        result, _ = _map([row])

        assert result[55]["type"] == "Unspecified"

    def test_an_appointment_with_no_start_time_is_not_reported(self):
        row = _appointment()
        row.start_time = None

        result, _ = _map([row])

        assert result == {}
