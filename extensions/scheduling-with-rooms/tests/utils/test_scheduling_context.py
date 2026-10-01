"""Tests for utils/scheduling_context.py."""

import datetime
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from scheduling_with_rooms.utils import scheduling_context
from scheduling_with_rooms.utils.scheduling_context import build_prefill, modal_url

MODULE = "scheduling_with_rooms.utils.scheduling_context"

PATIENT_ROW = {
    "id": "pt-1",
    "first_name": "Bob",
    "last_name": "Smith",
    "birth_date": datetime.date(2000, 1, 15),
    "last_known_timezone": "America/New_York",
}


@pytest.fixture
def stub_lookups():
    """Patch every data model the resolver touches; nothing resolves by default."""
    with patch(f"{MODULE}.Patient") as patient, patch(f"{MODULE}.Staff") as staff, patch(
        f"{MODULE}.PracticeLocation"
    ) as location, patch(f"{MODULE}.Appointment") as appointment, patch(
        f"{MODULE}.Command"
    ) as command, patch(
        f"{MODULE}.get_location_timezone", return_value="America/New_York"
    ) as tz:
        patient.objects.filter.return_value.values.return_value.first.return_value = None
        staff.objects.filter.return_value.values.return_value.first.return_value = None
        location.objects.filter.return_value.values.return_value.first.return_value = None
        appointment.objects.select_related.return_value.filter.return_value.first.return_value = (
            None
        )
        command.objects.filter.return_value.order_by.return_value.values.return_value.first.return_value = (
            None
        )
        yield MagicMock(
            patient=patient,
            staff=staff,
            location=location,
            appointment=appointment,
            command=command,
            timezone=tz,
        )


def _resolve_rfv(stub, comment="Follow up on labs"):
    stub.command.objects.filter.return_value.order_by.return_value.values.return_value.first.return_value = (
        {"data": {"comment": comment}} if comment is not None else None
    )


def _resolve_patient(stub, row=PATIENT_ROW):
    stub.patient.objects.filter.return_value.values.return_value.first.return_value = row


def _resolve_staff(stub, staff_id="staff-1", first="Ada", last="Lovelace"):
    stub.staff.objects.filter.return_value.values.return_value.first.return_value = {
        "id": staff_id,
        "first_name": first,
        "last_name": last,
    }


def _resolve_location(stub, location_id="loc-1", name="Main Office"):
    stub.location.objects.filter.return_value.values.return_value.first.return_value = {
        "id": location_id,
        "full_name": name,
    }


def _resolve_appointment(stub, **overrides):
    appointment = MagicMock()
    appointment.patient = None
    appointment.provider = None
    appointment.location = None
    appointment.note_type = None
    appointment.duration_minutes = None
    for key, value in overrides.items():
        setattr(appointment, key, value)
    stub.appointment.objects.select_related.return_value.filter.return_value.first.return_value = (
        appointment
    )
    return appointment


# modal_url -------------------------------------------------------------

def test_modal_url_with_no_params_is_cache_bust_only():
    parsed = urlparse(modal_url())

    assert parsed.path == scheduling_context.MODAL_PATH
    assert set(parse_qs(parsed.query)) == {"v"}


def test_modal_url_forwards_params_and_drops_blanks():
    params = parse_qs(urlparse(modal_url(patient_id="pt-1", mode="", origin=None)).query)

    assert params["patient_id"] == ["pt-1"]
    assert set(params) == {"v", "patient_id"}


def test_modal_url_stringifies_and_escapes_values():
    params = parse_qs(urlparse(modal_url(duration=45, start="2026-08-03T14:00:00+00:00")).query)

    assert params["duration"] == ["45"]
    assert params["start"] == ["2026-08-03T14:00:00+00:00"]


def test_modal_url_is_stable_across_calls():
    """One cache-bust per plugin load, so launchers don't fight over the cache."""
    assert modal_url() == modal_url()


# Defaults --------------------------------------------------------------

def test_empty_params_yields_default_mode(stub_lookups):
    assert build_prefill({}) == {"mode": "schedule", "lock_patient": False}


def test_unrecognized_mode_falls_back_to_schedule(stub_lookups):
    assert build_prefill({"mode": "teleport"})["mode"] == "schedule"


@pytest.mark.parametrize("mode", sorted(scheduling_context.VALID_MODES))
def test_valid_modes_pass_through(stub_lookups, mode):
    assert build_prefill({"mode": mode})["mode"] == mode


# Entity resolution -----------------------------------------------------

def test_patient_resolves_to_chip_payload_and_locks(stub_lookups):
    _resolve_patient(stub_lookups)

    prefill = build_prefill({"patient_id": "pt-1"})

    assert prefill["patient"] == {
        "id": "pt-1",
        "full_name": "Bob Smith",
        "dob": "01/15/2000",
        "timezone": "America/New_York",
    }
    assert prefill["lock_patient"] is True


def test_patient_without_dob_or_timezone(stub_lookups):
    _resolve_patient(
        stub_lookups,
        {**PATIENT_ROW, "birth_date": None, "last_known_timezone": None},
    )

    prefill = build_prefill({"patient_id": "pt-1"})

    assert prefill["patient"]["dob"] == ""
    assert prefill["patient"]["timezone"] == ""


def test_unresolvable_patient_is_omitted(stub_lookups):
    prefill = build_prefill({"patient_id": "ghost"})

    assert "patient" not in prefill
    assert prefill["lock_patient"] is False


def test_provider_and_location_resolve_to_id_and_name(stub_lookups):
    _resolve_staff(stub_lookups)
    _resolve_location(stub_lookups)

    prefill = build_prefill({"provider_id": "staff-1", "location_id": "loc-1"})

    assert prefill["provider"] == {"id": "staff-1", "name": "Ada Lovelace"}
    assert prefill["location"] == {"id": "loc-1", "name": "Main Office"}


def test_unresolvable_provider_and_location_are_omitted(stub_lookups):
    prefill = build_prefill({"provider_id": "ghost", "location_id": "ghost"})

    assert "provider" not in prefill
    assert "location" not in prefill


def test_location_without_a_name_resolves_to_empty_string(stub_lookups):
    _resolve_location(stub_lookups, name=None)

    assert build_prefill({"location_id": "loc-1"})["location"]["name"] == ""


def test_global_panel_origin_survives_into_the_prefill(stub_lookups):
    """The modal keys its close-after-booking behavior off this value."""
    prefill = build_prefill({"origin": scheduling_context.ORIGIN_GLOBAL_PANEL})

    assert prefill["origin"] == "global_panel"


def test_canvas_origins_pass_through_unchanged(stub_lookups):
    for origin in ("schedule_page", "patient_chart", "calendar", "note_reschedule"):
        assert build_prefill({"origin": origin})["origin"] == origin


def test_note_id_passes_through(stub_lookups):
    assert build_prefill({"note_id": "note-1"})["note_id"] == "note-1"


# Appointment backfill --------------------------------------------------

def test_appointment_backfills_everything_the_surface_omitted(stub_lookups):
    _resolve_patient(stub_lookups)
    note_type = MagicMock()
    note_type.id = "nt-1"
    note_type.code = "VISIT"
    note_type.name = "Office Visit"
    provider = MagicMock()
    provider.id = "staff-9"
    provider.first_name = "Grace"
    provider.last_name = "Hopper"
    location = MagicMock()
    location.id = "loc-9"
    location.full_name = "Annex"
    _resolve_appointment(
        stub_lookups,
        patient=MagicMock(id="pt-1"),
        provider=provider,
        location=location,
        note_type=note_type,
        duration_minutes=45,
    )

    prefill = build_prefill({"appointment_id": "appt-1", "mode": "reschedule"})

    assert prefill["appointment_id"] == "appt-1"
    assert prefill["patient"]["full_name"] == "Bob Smith"
    assert prefill["provider"] == {"id": "staff-9", "name": "Grace Hopper"}
    assert prefill["location"] == {"id": "loc-9", "name": "Annex"}
    assert prefill["note_type"] == {"id": "nt-1", "code": "VISIT", "name": "Office Visit"}
    assert prefill["duration_minutes"] == 45


def test_explicit_entities_win_over_the_appointment(stub_lookups):
    _resolve_staff(stub_lookups, staff_id="staff-1")
    _resolve_location(stub_lookups, location_id="loc-1")
    appointment_provider = MagicMock()
    appointment_provider.id = "staff-9"
    appointment_provider.first_name = "Grace"
    appointment_provider.last_name = "Hopper"
    _resolve_appointment(stub_lookups, provider=appointment_provider)

    prefill = build_prefill({
        "appointment_id": "appt-1",
        "provider_id": "staff-1",
        "location_id": "loc-1",
    })

    assert prefill["provider"]["id"] == "staff-1"
    assert prefill["location"]["id"] == "loc-1"


def test_missing_appointment_leaves_only_the_id(stub_lookups):
    prefill = build_prefill({"appointment_id": "ghost", "mode": "reschedule"})

    assert prefill["appointment_id"] == "ghost"
    assert "note_type" not in prefill
    assert "duration_minutes" not in prefill


# Reason for visit ------------------------------------------------------

def test_reason_for_visit_resolved_from_note_id_param(stub_lookups):
    _resolve_rfv(stub_lookups)

    prefill = build_prefill({"note_id": "note-1"})

    assert prefill["reason_for_visit"] == "Follow up on labs"


def test_reason_for_visit_queries_only_staged_commands(stub_lookups):
    """A Reason-for-Visit command is never committed, so staged is the filter."""
    _resolve_rfv(stub_lookups)

    build_prefill({"note_id": "note-1"})

    kwargs = stub_lookups.command.objects.filter.call_args.kwargs
    assert kwargs["note__id"] == "note-1"
    assert kwargs["schema_key"] == "reasonForVisit"
    assert kwargs["state"] == "staged"
    assert "state__in" not in kwargs


def test_reason_for_visit_takes_the_newest_command(stub_lookups):
    _resolve_rfv(stub_lookups)

    build_prefill({"note_id": "note-1"})

    stub_lookups.command.objects.filter.return_value.order_by.assert_called_once_with("-created")


def test_reason_for_visit_falls_back_to_the_appointments_note(stub_lookups):
    _resolve_rfv(stub_lookups, "Med check")
    _resolve_appointment(stub_lookups, note=MagicMock(id="note-9"))

    prefill = build_prefill({"appointment_id": "appt-1", "mode": "reschedule"})

    assert prefill["note_id"] == "note-9"
    assert prefill["reason_for_visit"] == "Med check"


def test_explicit_note_id_wins_over_the_appointments_note(stub_lookups):
    _resolve_rfv(stub_lookups)
    _resolve_appointment(stub_lookups, note=MagicMock(id="note-9"))

    prefill = build_prefill({"appointment_id": "appt-1", "note_id": "note-1"})

    assert prefill["note_id"] == "note-1"
    assert stub_lookups.command.objects.filter.call_args.kwargs["note__id"] == "note-1"


def test_no_rfv_command_yields_no_reason(stub_lookups):
    _resolve_rfv(stub_lookups, comment=None)

    assert "reason_for_visit" not in build_prefill({"note_id": "note-1"})


def test_blank_rfv_comment_is_omitted(stub_lookups):
    _resolve_rfv(stub_lookups, comment="   ")

    assert "reason_for_visit" not in build_prefill({"note_id": "note-1"})


def test_rfv_not_queried_without_a_note(stub_lookups):
    build_prefill({"patient_id": "pt-1"})

    stub_lookups.command.objects.filter.assert_not_called()


def test_appointment_without_a_note_yields_no_note_id(stub_lookups):
    _resolve_appointment(stub_lookups, note=None, duration_minutes=30)

    prefill = build_prefill({"appointment_id": "appt-1"})

    assert "note_id" not in prefill
    assert "reason_for_visit" not in prefill


# Timing ---------------------------------------------------------------

def test_start_is_converted_to_calendar_local_time(stub_lookups):
    _resolve_staff(stub_lookups)
    _resolve_location(stub_lookups)

    prefill = build_prefill({
        "provider_id": "staff-1",
        "location_id": "loc-1",
        "start": "2026-08-03T18:00:00+00:00",
    })

    # 18:00 UTC is 14:00 in America/New_York (EDT).
    assert prefill["start"] == "2026-08-03T14:00:00"
    assert prefill["date"] == "2026-08-03"
    assert prefill["time"] == "14:00"
    stub_lookups.timezone.assert_called_once_with("staff-1", "Main Office")


def test_start_without_a_provider_stays_in_utc(stub_lookups):
    prefill = build_prefill({"start": "2026-08-03T18:00:00+00:00"})

    assert prefill["start"] == "2026-08-03T18:00:00"
    stub_lookups.timezone.assert_not_called()


def test_naive_start_is_used_as_is(stub_lookups):
    prefill = build_prefill({"start": "2026-08-03T14:00:00"})

    assert prefill["start"] == "2026-08-03T14:00:00"
    assert prefill["time"] == "14:00"


def test_trailing_z_is_accepted(stub_lookups):
    assert build_prefill({"start": "2026-08-03T18:00:00Z"})["date"] == "2026-08-03"


def test_unparseable_start_is_dropped(stub_lookups):
    prefill = build_prefill({"start": "next tuesday"})

    assert "start" not in prefill
    assert "date" not in prefill


def test_unknown_calendar_timezone_falls_back_to_utc(stub_lookups):
    _resolve_staff(stub_lookups)
    _resolve_location(stub_lookups)
    stub_lookups.timezone.return_value = "Mars/Olympus_Mons"

    prefill = build_prefill({
        "provider_id": "staff-1",
        "location_id": "loc-1",
        "start": "2026-08-03T18:00:00+00:00",
    })

    assert prefill["start"] == "2026-08-03T18:00:00"


def test_duration_param_is_used_directly(stub_lookups):
    assert build_prefill({"duration": "45"})["duration_minutes"] == 45


def test_duration_is_derived_from_end_when_absent(stub_lookups):
    prefill = build_prefill({
        "start": "2026-08-03T14:00:00",
        "end": "2026-08-03T14:30:00",
    })

    assert prefill["duration_minutes"] == 30


def test_duration_param_wins_over_end(stub_lookups):
    prefill = build_prefill({
        "start": "2026-08-03T14:00:00",
        "end": "2026-08-03T15:00:00",
        "duration": "20",
    })

    assert prefill["duration_minutes"] == 20


def test_non_positive_duration_is_dropped(stub_lookups):
    assert "duration_minutes" not in build_prefill({"duration": "0"})
    assert "duration_minutes" not in build_prefill({"duration": "-15"})
    assert "duration_minutes" not in build_prefill({"duration": "half an hour"})


def test_zero_length_end_does_not_produce_a_duration(stub_lookups):
    prefill = build_prefill({
        "start": "2026-08-03T14:00:00",
        "end": "2026-08-03T14:00:00",
    })

    assert "duration_minutes" not in prefill
