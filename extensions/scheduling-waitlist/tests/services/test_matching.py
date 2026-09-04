"""Which waiting patients fit a slot."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scheduling_waitlist.constants import PREFERENCE_ANY, PREFERENCE_SPECIFIC
from scheduling_waitlist.services.matching import (
    MAX_EXPLAINED_ENTRIES,
    compatibility_q,
    entry_accepts_time,
    explain_no_match,
    find_entries_to_flip,
    find_matching_entries,
)
from scheduling_waitlist.services.slot import FreedSlot

MODULE = "scheduling_waitlist.services.matching"


def slot(**overrides):
    values = {
        "appointment_dbid": 900,
        "appointment_id": "appt-key",
        "start_time": datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
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


class _Recorder:
    def __init__(self, items=None):
        self.filters = []
        self.excludes = []
        self.select_related_args = ()
        self.order_by_args = ()
        self.items = items or []
        self.slice = None

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def exclude(self, *args, **kwargs):
        self.excludes.append(kwargs)
        return self

    def select_related(self, *args):
        self.select_related_args = args
        return self

    def order_by(self, *args):
        self.order_by_args = args
        return self

    def __getitem__(self, item):
        self.slice = item
        return self.items

    def __iter__(self):
        # Required. Without it, list(queryset) falls back to the legacy
        # iteration protocol and calls __getitem__(0), __getitem__(1), ...
        # forever, because this stub returns the same list for every index and
        # never raises IndexError.
        return iter(self.items)


class TestCompatibilityQ:
    def test_a_named_type_also_admits_entries_that_accept_any_type(self):
        leaves = compatibility_q(7, None, None).leaves()

        assert {"note_type__isnull": True} in leaves
        assert {"note_type_id": 7} in leaves

    def test_a_named_provider_also_admits_entries_that_accept_anyone(self):
        leaves = compatibility_q(None, 101, None).leaves()

        assert {"provider_preference": PREFERENCE_ANY} in leaves
        assert {"desired_provider_id": 101} in leaves

    def test_a_named_location_also_admits_entries_that_accept_anywhere(self):
        leaves = compatibility_q(None, None, 3).leaves()

        assert {"location_preference": PREFERENCE_ANY} in leaves
        assert {"desired_location_id": 3} in leaves

    def test_a_slot_without_a_provider_only_matches_entries_that_accept_anyone(self):
        leaves = compatibility_q(7, None, 3).leaves()

        assert {"provider_preference": PREFERENCE_ANY} in leaves
        assert not any("desired_provider_id" in leaf for leaf in leaves)

    def test_the_three_conditions_are_combined_with_and(self):
        assert compatibility_q(7, 101, 3).connector == "AND"


class TestEntryAcceptsTime:
    def _entry(self, windows, zone="UTC"):
        entry = MagicMock()
        entry.preferred_windows = windows
        entry.preferred_windows_timezone = zone
        return entry

    def test_an_entry_with_no_stored_window_accepts_anything(self):
        assert entry_accepts_time(self._entry([]), slot(), fallback_timezone="UTC") is True

    def test_a_matching_weekday_and_time_is_accepted(self):
        # 2026-08-12 is a Wednesday; 09:00 UTC falls in the morning window.
        windows = [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"}]

        assert entry_accepts_time(self._entry(windows), slot(), fallback_timezone="UTC")

    def test_a_non_matching_weekday_is_rejected(self):
        windows = [{"days": [5, 6], "start": "08:00", "end": "17:00"}]

        assert (
            entry_accepts_time(self._entry(windows), slot(), fallback_timezone="UTC") is False
        )

    def test_a_time_outside_the_window_is_rejected(self):
        windows = [{"days": [0, 1, 2, 3, 4], "start": "13:00", "end": "17:00"}]

        assert (
            entry_accepts_time(self._entry(windows), slot(), fallback_timezone="UTC") is False
        )

    def test_the_window_is_evaluated_in_the_patients_own_timezone(self):
        # 09:00 UTC is 03:00 in Denver, which is outside a morning window there
        # even though it sits inside one in UTC.
        windows = [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"}]

        assert (
            entry_accepts_time(
                self._entry(windows, zone="America/Denver"), slot(), fallback_timezone="UTC"
            )
            is False
        )

    def test_an_unusable_timezone_accepts_rather_than_silently_excluding(self):
        windows = [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"}]

        assert entry_accepts_time(
            self._entry(windows, zone="Mars/Olympus"), slot(), fallback_timezone="UTC"
        )

    def test_a_slot_without_a_start_time_is_accepted(self):
        windows = [{"days": [0], "start": "08:00", "end": "12:00"}]

        assert entry_accepts_time(
            self._entry(windows), slot(start_time=None), fallback_timezone="UTC"
        )


class TestFindMatchingEntries:
    def _run(self, recorder, **kwargs):
        with patch(f"{MODULE}.WaitlistEntry") as model:
            model.objects.filter.return_value = recorder
            return find_matching_entries(slot(), limit=kwargs.pop("limit", 10), **kwargs)

    def test_only_live_entries_are_considered(self):
        recorder = _Recorder()
        self._run(recorder)

        with patch(f"{MODULE}.WaitlistEntry") as model:
            model.objects.filter.return_value = recorder
            find_matching_entries(slot(), limit=10)

        assert model.objects.filter.call_args.kwargs["status__in"] == ["waiting", "offered"]

    def test_the_patient_who_vacated_the_slot_is_excluded(self):
        # Cancelling re-arms their entry, which then matches the very slot the
        # cancellation created. Without this they are offered their own slot.
        recorder = _Recorder()
        self._run(recorder)

        assert {"patient_id": 55} in recorder.excludes

    def test_the_entry_tied_to_this_appointment_is_excluded(self):
        recorder = _Recorder()
        self._run(recorder)

        assert {"scheduled_appointment_id": 900} in recorder.excludes

    def test_related_rows_are_selected_for_the_task_body(self):
        recorder = _Recorder()
        self._run(recorder)

        assert "patient" in recorder.select_related_args

    def test_results_are_ordered_by_priority_then_wait(self):
        recorder = _Recorder()
        self._run(recorder)

        assert recorder.order_by_args == ("priority_rank", "created_at", "dbid")

    def test_the_match_is_capped(self):
        recorder = _Recorder()
        self._run(recorder, limit=5)

        assert recorder.slice == slice(None, 5)

    def test_with_window_enforcement_off_no_entry_is_dropped_for_its_preference(self):
        entry = MagicMock()
        entry.preferred_windows = [{"days": [5, 6], "start": "08:00", "end": "17:00"}]
        entry.preferred_windows_timezone = "UTC"
        recorder = _Recorder(items=[entry])

        matched = self._run(recorder, enforce_time_windows=False)

        assert matched == [entry]

    def test_with_window_enforcement_on_a_non_matching_preference_is_dropped(self):
        entry = MagicMock()
        entry.preferred_windows = [{"days": [5, 6], "start": "08:00", "end": "17:00"}]
        entry.preferred_windows_timezone = "UTC"
        recorder = _Recorder(items=[entry])

        matched = self._run(recorder, enforce_time_windows=True)

        assert matched == []

    def test_with_window_enforcement_on_a_matching_preference_is_kept(self):
        entry = MagicMock()
        entry.preferred_windows = [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"}]
        entry.preferred_windows_timezone = "UTC"
        recorder = _Recorder(items=[entry])

        assert self._run(recorder, enforce_time_windows=True) == [entry]


class TestFindEntriesToFlip:
    def test_an_appointment_without_a_patient_matches_nothing(self):
        appointment = MagicMock()
        appointment.patient_id = None

        assert find_entries_to_flip(appointment) == []

    def test_only_that_patients_live_entries_are_considered(self):
        appointment = MagicMock()
        appointment.patient_id = 55
        appointment.note_type_id = 7
        appointment.provider_id = 101
        appointment.location_id = 3
        recorder = _Recorder()

        with patch(f"{MODULE}.WaitlistEntry") as model:
            model.objects.filter.return_value = recorder
            find_entries_to_flip(appointment)

        kwargs = model.objects.filter.call_args.kwargs
        assert kwargs["patient_id"] == 55
        assert kwargs["status__in"] == ["waiting", "offered"]

    def test_the_same_predicate_governs_both_directions(self):
        # If these ever diverged, the plugin could recommend booking a patient
        # into a slot it would then refuse to recognise.
        appointment = MagicMock()
        appointment.patient_id = 55
        appointment.note_type_id = 7
        appointment.provider_id = 101
        appointment.location_id = 3
        recorder = _Recorder()

        with patch(f"{MODULE}.WaitlistEntry") as model:
            model.objects.filter.return_value = recorder
            find_entries_to_flip(appointment)

        applied = recorder.filters[0][0][0]
        assert applied == compatibility_q(7, 101, 3)


class _Live:
    """A live-entries queryset whose answers are scripted per question."""

    def __init__(self, total=0, compatible=False, vacating=False, entries=None):
        self._total = total
        self._compatible = compatible
        self._vacating = vacating
        self._entries = list(entries or [])
        self.stage = "live"

    def filter(self, *args, **kwargs):
        child = _Live(self._total, self._compatible, self._vacating, self._entries)
        if "patient_id" in kwargs:
            child.stage = "vacating"
        else:
            child.stage = "compatible"
        return child

    def select_related(self, *args):
        return self

    def __getitem__(self, item):
        return self._entries[item]

    def count(self):
        return self._total

    def exists(self):
        if self.stage == "vacating":
            return self._vacating
        return self._compatible


def _named(**attributes):
    """A stand-in for a related row that only has to answer name lookups."""
    return SimpleNamespace(**attributes)


def _entry(
    *,
    note_type=None,
    note_type_id=None,
    provider_preference=PREFERENCE_SPECIFIC,
    desired_provider=None,
    desired_provider_id=None,
    location_preference=PREFERENCE_SPECIFIC,
    desired_location=None,
    desired_location_id=None,
):
    return SimpleNamespace(
        note_type=note_type,
        note_type_id=note_type_id,
        provider_preference=provider_preference,
        desired_provider=desired_provider,
        desired_provider_id=desired_provider_id,
        location_preference=location_preference,
        desired_location=desired_location,
        desired_location_id=desired_location_id,
    )


def _explain(**kwargs):
    live = _Live(**kwargs)
    model = MagicMock()
    model.objects.filter.return_value = live
    with patch(f"{MODULE}.WaitlistEntry", model):
        return explain_no_match(slot())


class TestExplainNoMatch:
    """"Matched nobody" alone is unactionable.

    An empty list, an incompatible list, and a list whose only candidate is the
    patient who cancelled all look identical from outside -- and working out which
    it was meant reading code rather than logs.
    """

    def test_it_always_names_the_slots_shape(self):
        # Half of "why not" is what the slot actually was.
        text = _explain(total=0)

        assert "Established Visit" in text
        assert "Alice Chen" in text
        assert "Riverside Clinic" in text

    def test_an_empty_waitlist_says_so(self):
        assert "nobody is on the waitlist" in _explain(total=0)

    def test_an_incompatible_list_says_what_was_asked_for(self):
        text = _explain(total=3, compatible=False)

        assert "3 live entries" in text
        assert "none of them asked for this service, provider and location" in text

    def test_one_entry_reads_in_the_singular(self):
        assert "1 live entry" in _explain(total=1, compatible=False)

    def test_it_quotes_what_the_entries_asked_for(self):
        # Naming only the slot leaves the reader to guess the other side of a
        # comparison that failed, which is the whole question being asked.
        text = _explain(
            total=1,
            compatible=False,
            entries=[
                _entry(
                    note_type=_named(name="New Patient Visit"),
                    note_type_id=99,
                    desired_provider=_named(first_name="Bob", last_name="Stone"),
                    desired_provider_id=202,
                    desired_location=_named(full_name="Hilltop Clinic"),
                    desired_location_id=4,
                )
            ],
        )

        assert "New Patient Visit" in text
        assert "Bob Stone" in text
        assert "Hilltop Clinic" in text

    def test_it_prints_identifiers_beside_the_labels(self):
        # Two NoteType rows can carry the same name -- Canvas versions them -- so
        # a log that prints only names cannot show that kind of mismatch at all.
        text = _explain(
            total=1,
            compatible=False,
            entries=[_entry(note_type=_named(name="Established Visit"), note_type_id=99)],
        )

        assert "type #7" in text, "the slot's own type identifier is missing"
        assert "type #99" in text, "the entry's type identifier is missing"

    def test_any_preferences_read_as_any(self):
        text = _explain(
            total=1,
            compatible=False,
            entries=[
                _entry(
                    provider_preference=PREFERENCE_ANY,
                    location_preference=PREFERENCE_ANY,
                )
            ],
        )

        assert "any service" in text
        assert "any provider" in text
        assert "any location" in text

    def test_a_long_list_is_capped_and_says_how_many_it_left_out(self):
        entries = [_entry(note_type_id=index) for index in range(10)]
        text = _explain(total=10, compatible=False, entries=entries)

        assert text.count(" | ") == MAX_EXPLAINED_ENTRIES - 1
        assert "7 further entries not quoted" in text

    def test_the_self_exclusion_is_named_when_it_is_the_cause(self):
        # The trap that costs testers the most time.
        text = _explain(total=1, compatible=True, vacating=True)

        assert "gave the slot up" in text
        assert "never offered their own slot back" in text

    def test_anything_else_points_at_the_remaining_filters(self):
        text = _explain(total=2, compatible=True, vacating=False)

        assert "already marked scheduled" in text
        assert "WAITLIST_ENFORCE_TIME_WINDOWS" in text
