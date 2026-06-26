import datetime
import json
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from scheduling_app.booking import build_booking_effects
from scheduling_app.handlers.recurrence import AppointmentRecurrence
from scheduling_app.recurrence import (
    RECURRENCE_SYSTEM,
    RFV_SYSTEM,
    decode_recurrence,
    decode_rfv,
    encode_recurrence,
    encode_rfv,
    occurrence_start_times,
)

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.v1.data.note import NoteTypeCategories

UTC = datetime.UTC
HANDLER = "scheduling_app.handlers.recurrence"


# --- pure date expansion + (de)serialization ---------------------------------


def test_count_is_total_including_parent() -> None:
    """count=3 ⇒ 2 children (the parent is the first occurrence)."""
    start = datetime.datetime(2026, 6, 10, 17, 0, tzinfo=UTC)
    starts = occurrence_start_times(start, {"frequency": "weekly", "interval": 1, "count": 3})
    assert [d.date().isoformat() for d in starts] == ["2026-06-17", "2026-06-24"]


def test_interval_multiplies_the_step() -> None:
    """`interval` scales each step (every 2 days)."""
    start = datetime.datetime(2026, 6, 10, 17, 0, tzinfo=UTC)
    starts = occurrence_start_times(start, {"frequency": "daily", "interval": 2, "count": 3})
    assert [d.date().isoformat() for d in starts] == ["2026-06-12", "2026-06-14"]


def test_until_is_inclusive() -> None:
    """An occurrence landing on the until-date is included."""
    start = datetime.datetime(2026, 6, 10, 17, 0, tzinfo=UTC)
    starts = occurrence_start_times(
        start, {"frequency": "daily", "interval": 2, "until": "2026-06-16"}
    )
    assert [d.date().isoformat() for d in starts] == ["2026-06-12", "2026-06-14", "2026-06-16"]


def test_monthly_uses_relativedelta_clamping() -> None:
    """Monthly steps use relativedelta (Jan 31 → Feb 28 → Mar 31)."""
    start = datetime.datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
    starts = occurrence_start_times(start, {"frequency": "monthly", "interval": 1, "count": 3})
    assert [d.date().isoformat() for d in starts] == ["2026-02-28", "2026-03-31"]


def test_capped_at_max_occurrences() -> None:
    """A runaway rule is bounded by max_occurrences."""
    start = datetime.datetime(2026, 6, 10, 17, 0, tzinfo=UTC)
    starts = occurrence_start_times(
        start, {"frequency": "daily", "interval": 1, "count": 1000}, max_occurrences=5
    )
    assert len(starts) == 5


def test_decode_requires_frequency_and_end_condition() -> None:
    """A valid rule needs a known frequency and an end condition."""
    assert decode_recurrence(encode_recurrence({"frequency": "weekly", "interval": 1, "count": 3}))
    assert decode_recurrence('{"frequency":"weekly","interval":1}') is None  # no end condition
    assert decode_recurrence('{"frequency":"yearly","interval":1,"count":3}') is None  # bad freq
    assert decode_recurrence("not json") is None


# --- handler -----------------------------------------------------------------


@pytest.fixture
def mock_db_queries() -> Generator[None]:
    """Make the child Appointment(...).create() effect's existence checks pass."""
    with (
        patch("canvas_sdk.v1.data.PracticeLocation.objects") as mock_pl,
        patch("canvas_sdk.v1.data.Staff.objects") as mock_staff,
        patch("canvas_sdk.v1.data.Patient.objects") as mock_patient,
        patch("canvas_sdk.v1.data.NoteType.objects") as mock_note_type,
    ):
        mock_pl.filter.return_value.exists.return_value = True
        mock_staff.filter.return_value.exists.return_value = True
        mock_patient.filter.return_value.exists.return_value = True
        mock_note_type.values_list.return_value.filter.return_value.get.return_value = (
            NoteTypeCategories.ENCOUNTER,
            True,
        )
        yield


def _appointment(identifier_value: str | None, rfv_value: str | None = None) -> SimpleNamespace:
    """A stand-in parent appointment whose external_identifiers carry a rule (+ optional RFV).

    ``external_identifiers.filter(system=...)`` is system-aware so the handler can
    read the recurrence rule and the RFV identifier independently.
    """
    identifiers = {}
    if identifier_value is not None:
        identifiers[RECURRENCE_SYSTEM] = SimpleNamespace(
            system=RECURRENCE_SYSTEM, value=identifier_value
        )
    if rfv_value is not None:
        identifiers[RFV_SYSTEM] = SimpleNamespace(system=RFV_SYSTEM, value=rfv_value)

    external_identifiers = MagicMock()

    def _filter(system: str) -> MagicMock:
        qs = MagicMock()
        qs.first.return_value = identifiers.get(system)
        qs.exists.return_value = system in identifiers
        return qs

    external_identifiers.filter.side_effect = _filter

    return SimpleNamespace(
        id="appt-parent",
        patient=SimpleNamespace(id="pat-1"),
        provider=SimpleNamespace(id="prov-1"),
        location=SimpleNamespace(id="loc-1"),
        note_type=SimpleNamespace(id="nt-1"),
        duration_minutes=30,
        start_time=datetime.datetime(2026, 6, 10, 17, 0, tzinfo=UTC),
        meeting_link=None,
        external_identifiers=external_identifiers,
    )


def _run_handler(appointment: SimpleNamespace) -> list:
    event = MagicMock()
    event.target.id = appointment.id
    with patch(f"{HANDLER}.AppointmentModel") as mock_model:
        mock_model.objects.filter.return_value.select_related.return_value.first.return_value = (
            appointment
        )
        return AppointmentRecurrence(event=event).compute()


def _data(effect: object) -> dict:
    return json.loads(effect.payload)["data"]


def test_handler_creates_linked_children(mock_db_queries: None) -> None:
    """A series parent expands into children linked by parent_appointment_id."""
    rule = encode_recurrence({"frequency": "weekly", "interval": 1, "count": 3})

    effects = _run_handler(_appointment(rule))

    assert len(effects) == 2  # count=3 total → 2 children
    assert all(e.type == EffectType.CREATE_APPOINTMENT for e in effects)
    assert all(_data(e)["parent_appointment_id"] == "appt-parent" for e in effects)
    assert [_data(e)["start_time"][:10] for e in effects] == ["2026-06-17", "2026-06-24"]


def test_handler_skips_appointment_without_recurrence_identifier(mock_db_queries: None) -> None:
    """Children (and non-recurring appointments) lack the identifier → no recursion."""
    assert _run_handler(_appointment(None)) == []


def test_handler_skips_invalid_rule(mock_db_queries: None) -> None:
    """A malformed/end-condition-less rule yields no children."""
    assert _run_handler(_appointment('{"frequency":"weekly"}')) == []


def test_handler_replicates_coded_rfv_onto_children(mock_db_queries: None) -> None:
    """The parent's coded RFV (from its RFV identifier) is originated on each child's note."""
    rule = encode_recurrence({"frequency": "weekly", "interval": 1, "count": 3})
    rfv = encode_rfv(
        {"reason_for_visit_coding": "rfv-ext-id", "reason_for_visit_comment": "since Monday"}
    )
    appt = _appointment(rule, rfv_value=rfv)

    # `.originate()` validates the coding exists against the DB; mock it present.
    with patch(
        "canvas_sdk.commands.commands.reason_for_visit.ReasonForVisitSettingCoding.objects"
    ) as mock_coding:
        mock_coding.filter.return_value.exists.return_value = True
        effects = _run_handler(appt)

    assert [e.type for e in effects] == [
        EffectType.CREATE_APPOINTMENT,
        EffectType.ORIGINATE_REASON_FOR_VISIT_COMMAND,
        EffectType.CREATE_APPOINTMENT,
        EffectType.ORIGINATE_REASON_FOR_VISIT_COMMAND,
    ]
    # Each RFV targets the child note its preceding create makes, carrying the coding.
    create0, rfv0 = effects[0], effects[1]
    assert json.loads(rfv0.payload)["note"] == _data(create0)["instance_id"]
    assert _data(rfv0)["coding"] == "rfv-ext-id"
    assert _data(rfv0)["comment"] == "since Monday"


def test_handler_replicates_free_text_rfv_onto_children(mock_db_queries: None) -> None:
    """A free-text parent reason (from its RFV identifier) is originated on each child's note."""
    rule = encode_recurrence({"frequency": "weekly", "interval": 1, "count": 2})  # 1 child
    appt = _appointment(rule, rfv_value=encode_rfv({"reason_for_visit": "Persistent cough"}))

    effects = _run_handler(appt)

    assert [e.type for e in effects] == [
        EffectType.CREATE_APPOINTMENT,
        EffectType.ORIGINATE_REASON_FOR_VISIT_COMMAND,
    ]
    rfv = effects[1]
    assert json.loads(rfv.payload)["note"] == _data(effects[0])["instance_id"]
    assert _data(rfv)["comment"] == "Persistent cough"


def test_handler_creates_bare_children_when_parent_has_no_rfv(mock_db_queries: None) -> None:
    """No RFV identifier on the parent → children get no RFV (just the creates)."""
    rule = encode_recurrence({"frequency": "weekly", "interval": 1, "count": 2})

    effects = _run_handler(_appointment(rule))

    assert [e.type for e in effects] == [EffectType.CREATE_APPOINTMENT]


# --- booking.py stamps the rule onto the parent ------------------------------


def _booking_payload(recurrence: dict | None = None) -> dict:
    payload = {
        "mode": "schedule",
        "category": "appointment",
        "patient_id": "pat-1",
        "grouping": "concurrent",
        "visits": [
            {
                "providers": ["staff-1"],
                "location_id": "loc-1",
                "visit_type_id": "nt-1",
                "duration_minutes": 30,
                "start_time": "2026-06-10T17:00:00",
                "labels": [],
                "description": "",
            }
        ],
    }
    if recurrence:
        payload["recurrence"] = recurrence
    return payload


def test_non_recurring_booking_omits_external_identifiers(mock_db_queries: None) -> None:
    """Regression: a non-recurring booking must NOT serialize external_identifiers
    (a null value crashes the home-app CREATE_APPOINTMENT interpreter).
    """
    effects = build_booking_effects(_booking_payload())

    assert effects[0].type == EffectType.CREATE_APPOINTMENT
    assert "external_identifiers" not in _data(effects[0])


def test_recurring_booking_stamps_the_rule(mock_db_queries: None) -> None:
    """A recurring booking stamps the parent with the namespaced rule identifier."""
    rule = {"frequency": "weekly", "interval": 1, "count": 3}
    effects = build_booking_effects(_booking_payload(rule))

    identifiers = _data(effects[0])["external_identifiers"]
    assert identifiers[0]["system"] == RECURRENCE_SYSTEM
    assert decode_recurrence(identifiers[0]["value"]) == rule


def test_recurring_booking_with_rfv_also_stamps_the_rfv(mock_db_queries: None) -> None:
    """A recurring booking carries the reason for visit in a second identifier so the
    handler can replicate it onto children without racing the parent's note command.
    """
    payload = _booking_payload({"frequency": "weekly", "interval": 1, "count": 3})
    payload["visits"][0]["reason_for_visit"] = "sistema"

    effects = build_booking_effects(payload)

    systems = {i["system"]: i["value"] for i in _data(effects[0])["external_identifiers"]}
    assert RECURRENCE_SYSTEM in systems
    assert decode_rfv(systems[RFV_SYSTEM]) == {"reason_for_visit": "sistema"}
