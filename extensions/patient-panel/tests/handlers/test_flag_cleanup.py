"""Tests for weekly flag cleanup cron task.

Uses real PatientMetadata records and real PatientMetadataEffect — no
canvas_sdk mocking. The handler's `execute()` returns a list of effects;
we inspect their payloads rather than asserting on mocked call args.
"""

__is_plugin__ = True

import json
from typing import Any

import arrow
import pytest

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientMetadata as PatientMetadataRecord

from handlers.flag_cleanup import WeeklyFlagCleanup


def _decode(payload: str | dict[str, Any]) -> dict[str, Any]:
    return json.loads(payload) if isinstance(payload, str) else payload


pytestmark = pytest.mark.django_db


def _make_handler() -> WeeklyFlagCleanup:
    return WeeklyFlagCleanup.__new__(WeeklyFlagCleanup)


def _seed_flag(patient: object, value: str) -> PatientMetadataRecord:
    return PatientMetadataRecord.objects.create(
        patient=patient,
        key="daily_flag",
        value=value,
    )


class TestWeeklyFlagCleanup:
    def test_schedule_is_monday_at_8am_utc(self) -> None:
        assert WeeklyFlagCleanup.SCHEDULE == "0 8 * * 1"

    def test_stale_flag_produces_upsert_effect(self) -> None:
        patient = PatientFactory.create()
        yesterday = arrow.now().shift(days=-1).format("YYYY-MM-DD")
        _seed_flag(patient, f"{yesterday}:red")

        effects = _make_handler().execute()
        assert len(effects) == 1
        payload = _decode(effects[0].payload)
        # The exact payload shape is owned by canvas_sdk; assert only that
        # it contains the patient id somewhere and clears the value.
        assert str(patient.id) in json.dumps(payload)
        assert payload.get("value") == "" or payload.get("data", {}).get("value") == ""

    def test_todays_flag_is_left_alone(self) -> None:
        patient = PatientFactory.create()
        today = arrow.now().format("YYYY-MM-DD")
        _seed_flag(patient, f"{today}:green")

        effects = _make_handler().execute()
        assert effects == []

    def test_empty_value_is_skipped(self) -> None:
        patient = PatientFactory.create()
        _seed_flag(patient, "")

        effects = _make_handler().execute()
        assert effects == []

    def test_no_metadata_returns_empty(self) -> None:
        # No PatientMetadata at all in DB → nothing to clean up.
        effects = _make_handler().execute()
        assert effects == []

    def test_multiple_stale_flags(self) -> None:
        p1 = PatientFactory.create()
        p2 = PatientFactory.create()
        p3 = PatientFactory.create()
        _seed_flag(p1, "2026-01-14:red")
        _seed_flag(p2, "2026-01-13:green")
        _seed_flag(p3, "2026-01-10:yellow")

        effects = _make_handler().execute()
        assert len(effects) == 3
        # All effects clear the value
        for effect in effects:
            payload = _decode(effect.payload)
            assert payload.get("value") == "" or payload.get("data", {}).get("value") == ""
