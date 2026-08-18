"""The wording a scheduler actually reads."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from scheduling_waitlist.services.slot import FreedSlot
from scheduling_waitlist.services.task_composer import (
    TITLE_MAX,
    compose_body,
    compose_title,
    describe_cause,
    describe_wait,
    format_slot_time,
)

TODAY = date(2026, 8, 12)


def slot(**overrides):
    values = {
        "appointment_dbid": 900,
        "appointment_id": "appt-key",
        "start_time": datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "note_type_dbid": 7,
        "note_type_label": "Established Visit",
        "provider_dbid": 101,
        "provider_label": "Alice Chen",
        "location_dbid": 3,
        "location_label": "Riverside Clinic",
        "vacating_patient_dbid": 55,
        "source_event": "APPOINTMENT_CANCELED",
    }
    values.update(overrides)
    return FreedSlot(**values)


def entry(name="Jordan Lee", priority="High", windows=None, window_note="", note=""):
    record = MagicMock()
    first, _, last = name.partition(" ")
    record.patient.first_name = first
    record.patient.last_name = last
    record.priority_label = priority
    record.preferred_windows = windows or []
    record.preferred_window_note = window_note
    record.note = note
    record.note_type.name = "Established Visit"
    record.provider_preference = "specific"
    record.desired_provider.first_name = "Alice"
    record.desired_provider.last_name = "Chen"
    record.location_preference = "specific"
    record.desired_location.full_name = "Riverside Clinic"
    record.created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    return record


class TestFormatSlotTime:
    def test_renders_the_local_time_with_its_zone(self):
        text = format_slot_time(slot(), timezone_name="UTC")

        assert "3:30 PM" in text
        assert "UTC" in text

    def test_converts_into_the_configured_zone(self):
        text = format_slot_time(slot(), timezone_name="America/Denver")

        assert "9:30 AM" in text

    def test_always_shows_the_zone_so_a_wrong_setting_is_visible(self):
        # Locations carry no timezone of their own, so this is one instance-wide
        # setting; a mistake has to be readable rather than silently shifting.
        assert "MDT" in format_slot_time(slot(), timezone_name="America/Denver")

    def test_includes_the_duration(self):
        assert "(30 min)" in format_slot_time(slot(), timezone_name="UTC")

    def test_an_unusable_zone_falls_back_to_utc(self):
        assert "UTC" in format_slot_time(slot(), timezone_name="Mars/Olympus")

    def test_a_slot_without_a_start_time_says_so(self):
        assert format_slot_time(slot(start_time=None), timezone_name="UTC") == "Time unknown"


class TestBriefTime:
    """The title's clock, which trades precision for room in a narrow column."""

    def test_it_drops_the_year_zone_and_duration(self):
        text = format_slot_time(slot(), timezone_name="UTC", brief=True)

        assert text == "Wed 12 Aug, 3:30 PM"

    def test_the_full_form_keeps_them(self):
        text = format_slot_time(slot(), timezone_name="UTC")

        assert "2026" in text
        assert "UTC" in text
        assert "(30 min)" in text


class TestDescribeCause:
    """The raw event used to be printed, which read as "Slot freed (4)"."""

    def test_each_subscribed_event_has_words(self):
        for name in (
            "APPOINTMENT_CANCELED",
            "APPOINTMENT_NO_SHOWED",
            "APPOINTMENT_RESCHEDULED",
            "PATIENT_PORTAL__APPOINTMENT_CANCELED",
            "PATIENT_PORTAL__APPOINTMENT_RESCHEDULED",
        ):
            assert describe_cause(name), name

    def test_a_portal_cancellation_says_who_did_it(self):
        assert describe_cause("PATIENT_PORTAL__APPOINTMENT_CANCELED") == (
            "Cancelled by the patient."
        )

    def test_an_unknown_event_says_nothing_rather_than_guessing(self):
        assert describe_cause("SOMETHING_NEW") == ""
        assert describe_cause("") == ""

    def test_an_enum_number_is_not_mistaken_for_a_cause(self):
        # The regression: event.type is an integer, and "4" reached schedulers.
        assert describe_cause("4") == ""


class TestDescribeWait:
    def test_a_same_day_entry_does_not_say_zero_days(self):
        assert describe_wait(0) == "added today"

    def test_one_day_is_singular(self):
        assert describe_wait(1) == "waiting 1 day"

    def test_several_days_are_plural(self):
        assert describe_wait(4) == "waiting 4 days"

    def test_a_negative_wait_is_treated_as_today(self):
        assert describe_wait(-2) == "added today"


class TestComposeTitle:
    """Read in the task queue, where the column is narrow."""

    def test_it_names_when_what_and_how_many(self):
        title = compose_title(slot(), 2, timezone_name="UTC")

        assert title == "Slot opened Wed 12 Aug, 3:30 PM · Established Visit · 2 to call"

    def test_it_stays_short_enough_for_the_queue_column(self):
        # The previous title ran past a hundred characters and wrapped to eight
        # lines, burying the count at the end.
        title = compose_title(slot(), 2, timezone_name="UTC")

        assert len(title) < 80

    def test_it_says_what_to_do_not_what_matched(self):
        title = compose_title(slot(), 3, timezone_name="UTC")

        assert "to call" in title
        assert "match" not in title

    def test_a_single_match_is_still_counted(self):
        assert "1 to call" in compose_title(slot(), 1, timezone_name="UTC")

    def test_the_provider_and_location_are_left_to_the_comment(self):
        title = compose_title(slot(), 1, timezone_name="UTC")

        assert "Alice Chen" not in title
        assert "Riverside Clinic" not in title

    def test_an_overlong_title_is_shortened(self):
        long_slot = slot(note_type_label="X" * 400)

        title = compose_title(long_slot, 1, timezone_name="UTC")

        assert len(title) == TITLE_MAX
        assert title.endswith("…")


class TestComposeBody:
    def _body(self, entries=None, **kwargs):
        return compose_body(
            slot(),
            entries if entries is not None else [entry()],
            timezone_name="UTC",
            today=TODAY,
            **kwargs,
        )

    def test_it_opens_with_how_the_slot_came_free(self):
        assert self._body().startswith("Cancelled.")

    def test_no_internal_event_identifier_reaches_the_reader(self):
        # "Slot freed (4)" was an enum integer in staff-facing text.
        body = compose_body(
            slot(source_event="4"), [entry()], timezone_name="UTC", today=TODAY
        )

        assert "(4)" not in body
        assert "APPOINTMENT" not in body

    def test_the_slot_is_described_once_on_a_single_line(self):
        body = self._body()

        assert "3:30 PM UTC (30 min) · Established Visit · Alice Chen · Riverside Clinic" in body
        # Not the labelled block it replaced, which the title already duplicated.
        assert "When:" not in body
        assert "Service:" not in body

    def test_it_instructs_rather_than_describes(self):
        body = self._body()

        assert "Call in priority order:" in body
        assert "Matching waitlisted patients" not in body

    def test_each_patient_is_one_line_with_priority_and_wait(self):
        body = self._body()

        assert "1. Jordan Lee - High priority, waiting 10 days" in body

    def test_a_patient_added_today_reads_as_such(self):
        record = entry()
        record.created_at = datetime(2026, 8, 12, tzinfo=timezone.utc)

        assert "added today" in self._body([record])

    def test_patients_keep_the_order_they_were_given(self):
        body = self._body([entry(name="First One"), entry(name="Second One")])

        assert body.index("1. First One") < body.index("2. Second One")

    def test_what_they_asked_for_is_not_restated(self):
        # A matching patient necessarily accepts this slot's service, provider and
        # location, so repeating them under every name told the reader nothing.
        body = self._body()

        assert "Wants:" not in body

    def test_a_stored_window_is_described_with_runs_collapsed(self):
        record = entry(
            windows=[{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"}]
        )

        assert "prefers Mon-Fri 08:00-12:00" in self._body([record])

    def test_non_consecutive_days_are_listed_individually(self):
        record = entry(windows=[{"days": [0, 2, 4], "start": "08:00", "end": "12:00"}])

        assert "prefers Mon, Wed, Fri 08:00-12:00" in self._body([record])

    def test_free_text_takes_precedence_over_the_structured_window(self):
        record = entry(
            window_note="after school",
            windows=[{"days": [0], "start": "08:00", "end": "12:00"}],
        )

        assert "prefers after school" in self._body([record])

    def test_no_stored_preference_is_left_out_rather_than_called_any_time(self):
        # "Any time" is nothing a reader can act on.
        body = self._body([entry()])

        assert "prefers" not in body
        assert "Any time" not in body

    def test_a_staff_note_gets_its_own_line(self):
        body = self._body([entry(note="Happy with short notice")])

        assert "   Note: Happy with short notice" in body

    def test_the_hint_appears_only_when_a_preference_was_shown(self):
        with_window = self._body(
            [entry(windows=[{"days": [0], "start": "08:00", "end": "12:00"}])]
        )
        without = self._body([entry()])

        assert "a hint" in with_window
        assert "a hint" not in without

    def test_the_hint_is_withheld_when_windows_really_did_filter(self):
        # Saying matching ignored them would then be false.
        body = self._body(
            [entry(windows=[{"days": [0], "start": "08:00", "end": "12:00"}])],
            enforce_time_windows=True,
        )

        assert "a hint" not in body

    def test_it_closes_by_saying_nobody_was_booked(self):
        body = self._body()

        assert body.rstrip().endswith(
            "Book in Canvas as usual - this plugin never books anyone into the slot."
        )

    def test_the_closing_notice_is_one_sentence(self):
        # It appears on every task; two paragraphs went unread.
        body = self._body()
        tail = body.rstrip().splitlines()[-1]

        assert tail.count(".") == 1
