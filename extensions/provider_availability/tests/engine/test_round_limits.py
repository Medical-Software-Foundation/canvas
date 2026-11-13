"""Facility round visits: the facility label and the "Round full" block."""

import datetime as dt
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from provider_availability.engine import round_limits, settings
from provider_availability.engine.models import DateOverride, ProviderAvailabilityRule, TimeWindow

MODULE = "provider_availability.engine.round_limits"
PROVIDER_ID = "provider-uuid-123"
PACIFIC = ZoneInfo("US/Pacific")
APPT_ID = "5b1e2c3d-4f5a-4b6c-8d7e-9f0a1b2c3d4e"


def _round(**overrides):
    fields: dict[str, Any] = dict(
        id="round-1",
        provider_id=PROVIDER_ID,
        weekly_schedule={"tuesday": [TimeWindow(start=dt.time(8, 0), end=dt.time(12, 0))]},
        facility_id="fac-1",
        facility_name="Apple Valley Care",
        max_visits=2,
        effective_start=dt.date(2026, 11, 3),
    )
    fields.update(overrides)
    return ProviderAvailabilityRule(**fields)


# Tue Nov 3, 2026, 9:00 AM Pacific = 17:00 UTC; the round runs 8:00-12:00 Pacific = 16:00-20:00 UTC.
NINE_AM = datetime(2026, 11, 3, 17, 0, tzinfo=UTC)
ROUND_START = datetime(2026, 11, 3, 16, 0, tzinfo=UTC)
ROUND_END = datetime(2026, 11, 3, 20, 0, tzinfo=UTC)


@pytest.fixture
def rounds_on(settings_cache):
    settings.set_feature("facility_rounds", True)


@pytest.fixture
def pacific():
    with patch(f"{MODULE}.provider_tz", return_value=PACIFIC):
        yield


class TestRoundAt:
    def test_finds_the_round_and_its_occurrence(self, rounds_on, pacific):
        rule = _round()
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[rule]):
            assert round_limits.round_at(PROVIDER_ID, NINE_AM) == (rule, ROUND_START, ROUND_END)

    def test_outside_the_round_hours(self, rounds_on, pacific):
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[_round()]):
            assert round_limits.round_at(PROVIDER_ID, datetime(2026, 11, 3, 21, 0, tzinfo=UTC)) is None

    def test_clinic_rules_and_inactive_rounds_are_ignored(self, rounds_on, pacific):
        clinic = _round(id="clinic", facility_id="", facility_name="")
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[clinic, _round(is_active=False)]):
            assert round_limits.round_at(PROVIDER_ID, NINE_AM) is None

    def test_a_closed_override_means_no_round_that_day(self, rounds_on, pacific):
        rule = _round(date_overrides=[DateOverride(date=dt.date(2026, 11, 3), is_closed=True)])
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[rule]):
            assert round_limits.round_at(PROVIDER_ID, NINE_AM) is None

    def test_nothing_while_rounds_are_removed(self, settings_cache, pacific):
        with patch(f"{MODULE}.get_rules_for_provider", return_value=[_round()]) as rules:
            assert round_limits.round_at(PROVIDER_ID, NINE_AM) is None
            assert rules.mock_calls == []


class TestFullBlock:
    def _admin(self):
        return patch.multiple(
            MODULE,
            get_admin_calendars=MagicMock(return_value=[SimpleNamespace(id="admin-cal")]),
            get_admin_calendar_id=MagicMock(return_value=("admin-cal", [])),
            resolve_provider_name=MagicMock(return_value="Dr X"),
        )

    def test_blocks_the_occurrence_when_it_reaches_the_limit(self):
        with self._admin(), patch(f"{MODULE}._full_events", return_value=[]), \
             patch(f"{MODULE}.visits_in", return_value=2), \
             patch(f"{MODULE}.datetime") as clock:
            clock.now.return_value = ROUND_START - dt.timedelta(days=1)
            effects = round_limits.full_block_effects(PROVIDER_ID, _round(), ROUND_START, ROUND_END)
        (created,) = effects
        data = json.loads(created.payload)["data"]
        assert (data["title"], data["calendar_id"]) == ("Round full", "admin-cal")
        assert (data["starts_at"], data["ends_at"]) == (ROUND_START.isoformat(), ROUND_END.isoformat())

    def test_no_block_below_the_limit(self):
        with self._admin(), patch(f"{MODULE}._full_events", return_value=[]), patch(f"{MODULE}.visits_in", return_value=1):
            assert round_limits.full_block_effects(PROVIDER_ID, _round(), ROUND_START, ROUND_END) == []

    def test_no_limit_never_blocks(self):
        with self._admin(), patch(f"{MODULE}._full_events", return_value=[]), patch(f"{MODULE}.visits_in", return_value=40):
            assert round_limits.full_block_effects(PROVIDER_ID, _round(max_visits=None), ROUND_START, ROUND_END) == []

    def test_unblocks_when_a_visit_frees_a_place(self):
        with self._admin(), patch(f"{MODULE}._full_events", return_value=[SimpleNamespace(id="full-1")]), \
             patch(f"{MODULE}.visits_in", return_value=1):
            (deleted,) = round_limits.full_block_effects(PROVIDER_ID, _round(), ROUND_START, ROUND_END)
        assert json.loads(deleted.payload)["data"]["event_id"] == "full-1"

    def test_an_already_blocked_full_round_is_left_alone(self):
        with self._admin(), patch(f"{MODULE}._full_events", return_value=[SimpleNamespace(id="full-1")]), \
             patch(f"{MODULE}.visits_in", return_value=2):
            assert round_limits.full_block_effects(PROVIDER_ID, _round(), ROUND_START, ROUND_END) == []

    def test_a_past_round_is_not_blocked(self):
        with self._admin(), patch(f"{MODULE}._full_events", return_value=[]), \
             patch(f"{MODULE}.visits_in", return_value=2), \
             patch(f"{MODULE}.datetime") as clock:
            clock.now.return_value = ROUND_END + dt.timedelta(hours=1)
            assert round_limits.full_block_effects(PROVIDER_ID, _round(), ROUND_START, ROUND_END) == []


def _appt(labels=(), patient_id=7, status="confirmed"):
    appt = MagicMock()
    appt.id = APPT_ID
    appt.patient_id = patient_id
    appt.status = status
    appt.start_time = NINE_AM
    appt.provider.id = PROVIDER_ID
    appt.labels.values_list.return_value = list(labels)
    return appt


class TestLabel:
    def test_adds_the_facility_label(self):
        # The SDK effect counts the visit's labels in the database when it is built.
        with patch("canvas_sdk.effects.note.appointment.AppointmentDataModel.objects") as appts:
            appts.filter.return_value.annotate.return_value.values_list.return_value.first.return_value = 0
            (effect,) = round_limits.label_effects(_appt(), _round())
        assert appts.filter.call_args.kwargs == {"id": APPT_ID}
        assert json.loads(effect.payload)["data"] == {"appointment_id": APPT_ID, "labels": ["Apple Valley Care"]}

    def test_not_added_twice(self):
        assert round_limits.label_effects(_appt(labels=["Apple Valley Care"]), _round()) == []

    def test_skipped_when_the_visit_already_has_three_labels(self):
        assert round_limits.label_effects(_appt(labels=["A", "B", "C"]), _round()) == []

    def test_only_patient_visits_are_labeled(self):
        assert round_limits.label_effects(_appt(patient_id=None), _round()) == []


class TestVisitEffects:
    def test_labels_and_recounts_a_visit_in_a_round(self):
        rule = _round()
        with patch(f"{MODULE}.round_at", return_value=(rule, ROUND_START, ROUND_END)), \
             patch(f"{MODULE}.label_effects", return_value=["label"]), \
             patch(f"{MODULE}.full_block_effects", return_value=["block"]) as block:
            assert round_limits.visit_effects(_appt()) == ["label", "block"]
        assert block.call_args.args == (PROVIDER_ID, rule, ROUND_START, ROUND_END)

    def test_a_cancelled_visit_is_only_recounted(self):
        with patch(f"{MODULE}.round_at", return_value=(_round(), ROUND_START, ROUND_END)), \
             patch(f"{MODULE}.label_effects") as label, \
             patch(f"{MODULE}.full_block_effects", return_value=["unblock"]):
            assert round_limits.visit_effects(_appt(status="cancelled")) == ["unblock"]
        assert label.mock_calls == []

    def test_a_visit_outside_any_round_changes_nothing(self):
        with patch(f"{MODULE}.round_at", return_value=None):
            assert round_limits.visit_effects(_appt()) == []


class TestRefreshProvider:
    def _run(self, rules, starts, now=ROUND_START - dt.timedelta(days=1), calendar="admin-cal"):
        qs = MagicMock()
        qs.values_list.return_value = starts
        with patch(f"{MODULE}._full_events", return_value=[SimpleNamespace(id="old-full")]), \
             patch(f"{MODULE}.get_rules_for_provider", return_value=rules), \
             patch(f"{MODULE}._visits_qs", return_value=qs) as visits, \
             patch(f"{MODULE}.get_admin_calendar_id", return_value=(calendar, [])), \
             patch(f"{MODULE}.resolve_provider_name", return_value="Dr X"):
            effects = round_limits.refresh_provider(PROVIDER_ID, now=now)
        return [json.loads(e.payload)["data"] for e in effects], visits

    def test_blocks_occurrences_at_their_limit_from_one_query(self, rounds_on, pacific):
        next_week = dt.timedelta(days=7)
        payloads, visits = self._run([_round()], [NINE_AM, NINE_AM + dt.timedelta(minutes=30), NINE_AM + next_week])
        assert payloads[0]["event_id"] == "old-full"
        # Two visits fill Nov 3; Nov 10 has one of two places taken.
        assert [(p["title"], p["starts_at"]) for p in payloads[1:]] == [("Round full", ROUND_START.isoformat())]
        assert visits.call_count == 1

    def test_counts_from_a_day_back_so_a_round_in_progress_counts(self, rounds_on, pacific):
        now = NINE_AM + dt.timedelta(minutes=45)
        payloads, visits = self._run([_round()], [NINE_AM, NINE_AM + dt.timedelta(minutes=30)], now=now)
        assert [p.get("title") for p in payloads[1:]] == ["Round full"]
        assert visits.call_args.args[1] == now - dt.timedelta(days=1)

    def test_a_finished_round_is_not_blocked_again(self, rounds_on, pacific):
        payloads, _ = self._run([_round()], [NINE_AM, NINE_AM + dt.timedelta(minutes=30)], now=ROUND_END + dt.timedelta(hours=1))
        assert [p["event_id"] for p in payloads] == ["old-full"]

    def test_visits_outside_rounds_are_not_counted(self, rounds_on, pacific):
        evening = datetime(2026, 11, 4, 2, 0, tzinfo=UTC)
        payloads, _ = self._run([_round()], [evening, evening + dt.timedelta(minutes=30)])
        assert len(payloads) == 1

    def test_without_an_admin_calendar_only_clears(self, rounds_on, pacific):
        payloads, _ = self._run([_round()], [NINE_AM, NINE_AM + dt.timedelta(minutes=30)], calendar=None)
        assert len(payloads) == 1

    def test_only_clears_when_no_round_has_a_limit(self, rounds_on):
        payloads, visits = self._run([_round(max_visits=None)], [])
        assert [p["event_id"] for p in payloads] == ["old-full"]
        assert visits.mock_calls == []



class TestWindowsOn:
    def test_before_start_and_after_end(self, rounds_on):
        rule = _round(effective_start=dt.date(2026, 11, 10), effective_end=dt.date(2026, 11, 30))
        assert round_limits._windows_on(rule, dt.date(2026, 11, 3)) == []
        assert round_limits._windows_on(rule, dt.date(2026, 12, 1)) == []
        assert len(round_limits._windows_on(rule, dt.date(2026, 11, 10))) == 1

    def test_off_pattern_week(self, rounds_on):
        rule = _round(recurrence_interval=2)
        assert round_limits._windows_on(rule, dt.date(2026, 11, 10)) == []
        assert len(round_limits._windows_on(rule, dt.date(2026, 11, 17))) == 1

    def test_daily_rounds_use_their_time_windows(self, rounds_on):
        window = TimeWindow(start=dt.time(13, 0), end=dt.time(15, 0))
        rule = _round(weekly_schedule={}, recurrence_frequency="daily", time_windows=[window])
        assert round_limits._windows_on(rule, dt.date(2026, 11, 4)) == [window]

    def test_an_override_with_hours_replaces_the_day(self, rounds_on):
        window = TimeWindow(start=dt.time(9, 0), end=dt.time(10, 0))
        rule = _round(date_overrides=[DateOverride(date=dt.date(2026, 11, 3), time_windows=[window])])
        assert round_limits._windows_on(rule, dt.date(2026, 11, 3)) == [window]


class TestQueries:
    def test_visits_query_counts_booked_patient_visits_only(self):
        with patch(f"{MODULE}.Appointment.objects") as objects:
            round_limits._visits_qs(PROVIDER_ID, ROUND_START, ROUND_END)
        moved, visits = objects.filter.call_args_list
        assert moved.kwargs == {"appointment_rescheduled_from__provider__id": PROVIDER_ID}
        assert visits.kwargs == {
            "provider__id": PROVIDER_ID, "patient__isnull": False, "entered_in_error__isnull": True,
            "start_time__gte": ROUND_START, "start_time__lt": ROUND_END,
        }
        first = objects.filter.return_value.exclude
        assert first.call_args.kwargs == {"status": "cancelled"}
        assert first.return_value.exclude.call_args.kwargs == {"note_type__category": "schedule_event"}
        assert "id__in" in first.return_value.exclude.return_value.exclude.call_args.kwargs

    def test_visits_in_counts_the_query(self):
        with patch(f"{MODULE}._visits_qs") as qs:
            qs.return_value.count.return_value = 3
            assert round_limits.visits_in(PROVIDER_ID, ROUND_START, ROUND_END) == 3

    def test_full_events_for_one_occurrence(self):
        with patch(f"{MODULE}.get_admin_calendars", return_value=[SimpleNamespace(id="cal-1")]), \
             patch(f"{MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{MODULE}.EventModel.objects") as events:
            events.filter.return_value.filter.return_value = ["evt"]
            assert round_limits._full_events(PROVIDER_ID, ROUND_START, ROUND_END) == ["evt"]
        assert events.filter.call_args.kwargs == {"calendar__id__in": ["cal-1"], "title": "Round full", "is_cancelled": False}
        assert events.filter.return_value.filter.call_args.kwargs == {"starts_at": ROUND_START, "ends_at": ROUND_END}

    def test_full_events_ahead_when_no_occurrence_is_given(self):
        with patch(f"{MODULE}.get_admin_calendars", return_value=[SimpleNamespace(id="cal-1")]), \
             patch(f"{MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{MODULE}.EventModel.objects") as events:
            events.filter.return_value.filter.return_value = []
            assert round_limits._full_events(PROVIDER_ID) == []
        assert "ends_at__gt" in events.filter.return_value.filter.call_args.kwargs

    def test_no_admin_calendars_means_no_events(self):
        with patch(f"{MODULE}.get_admin_calendars", return_value=[]), \
             patch(f"{MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{MODULE}.EventModel.objects") as events:
            assert round_limits._full_events(PROVIDER_ID) == []
        assert events.mock_calls == []


class TestNoAdminCalendar:
    def test_a_full_round_without_an_admin_calendar_is_left_unblocked(self):
        with patch(f"{MODULE}._full_events", return_value=[]), patch(f"{MODULE}.visits_in", return_value=2), \
             patch(f"{MODULE}.get_admin_calendar_id", return_value=(None, [])), \
             patch(f"{MODULE}.resolve_provider_name", return_value="Dr X"), \
             patch(f"{MODULE}.datetime") as clock:
            clock.now.return_value = ROUND_START - dt.timedelta(days=1)
            assert round_limits.full_block_effects(PROVIDER_ID, _round(), ROUND_START, ROUND_END) == []



def test_a_visit_without_a_provider_is_skipped():
    appt = _appt()
    appt.provider = None
    assert round_limits.visit_effects(appt) == []


class TestCountedOnce:
    def test_a_visit_moved_within_one_round_is_recounted_once(self):
        rule = _round()
        counted: set = set()
        with patch(f"{MODULE}.round_at", return_value=(rule, ROUND_START, ROUND_END)), \
             patch(f"{MODULE}.label_effects", return_value=["label"]), \
             patch(f"{MODULE}.full_block_effects", return_value=["block"]) as block:
            assert round_limits.visit_effects(_appt(), label=False, counted=counted) == ["block"]
            assert round_limits.visit_effects(_appt(), counted=counted) == ["label"]
        assert block.call_count == 1

    def test_extra_full_blocks_are_removed(self):
        existing = [SimpleNamespace(id="full-1"), SimpleNamespace(id="full-2")]
        with patch(f"{MODULE}._full_events", return_value=existing), patch(f"{MODULE}.visits_in", return_value=2):
            (deleted,) = round_limits.full_block_effects(PROVIDER_ID, _round(), ROUND_START, ROUND_END)
        assert json.loads(deleted.payload)["data"]["event_id"] == "full-2"
