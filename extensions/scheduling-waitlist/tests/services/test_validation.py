"""Server-side validation of a waitlist submission."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from scheduling_waitlist.constants import PREFERENCE_ANY, PREFERENCE_SPECIFIC
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.validation import expiry_for, validate_entry

TODAY = date(2026, 8, 3)
CONFIG = WaitlistConfig.from_secrets(
    {"WAITLIST_APPOINTMENT_TYPES": "estab", "WAITLIST_TTL_DAYS": "60"}
)


def _found(**attrs):
    record = MagicMock()
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


OFFERED = [{"dbid": 7, "code": "estab", "name": "Established Visit"}]


@pytest.fixture
def lookups():
    """Patch every model the validator resolves against.

    The appointment type is not among them: the validator asks
    ``list_appointment_types`` what is on offer rather than querying NoteType
    itself, so that the dropdown and the validator cannot disagree.
    """
    with (
        patch("scheduling_waitlist.services.validation.Patient") as patient_model,
        patch(
            "scheduling_waitlist.services.validation.list_appointment_types",
            return_value=list(OFFERED),
        ) as offered,
        patch("scheduling_waitlist.services.validation.Staff") as staff_model,
        patch("scheduling_waitlist.services.validation.PracticeLocation") as location_model,
    ):
        patient_model.objects.filter.return_value.first.return_value = _found(dbid=55)
        staff_model.objects.filter.return_value.first.return_value = _found(dbid=101)
        location_model.objects.filter.return_value.first.return_value = _found(dbid=3)
        yield {
            "patient": patient_model,
            "offered": offered,
            "staff": staff_model,
            "location": location_model,
        }


def valid_payload(**overrides):
    payload = {
        "patient_id": "patient-key",
        "appointment_type_id": "7",
        "provider_preference": PREFERENCE_SPECIFIC,
        "provider_id": "101",
        "location_preference": PREFERENCE_SPECIFIC,
        "location_id": "3",
        "priority": "High",
        "preferred_window": "weekday_am",
        "note": "Prefers early slots",
    }
    payload.update(overrides)
    return payload


def run(payload, config=CONFIG):
    return validate_entry(payload, config=config, today=TODAY)


class TestExpiry:
    def test_shelf_life_is_added_to_today(self):
        assert expiry_for(CONFIG, TODAY) == date(2026, 10, 2)

    def test_no_configured_shelf_life_means_no_expiry(self):
        assert expiry_for(WaitlistConfig.from_secrets({}), TODAY) is None


class TestHappyPath:
    def test_a_complete_submission_is_accepted(self, lookups):
        assert run(valid_payload()).ok is True

    def test_identifiers_are_resolved_to_their_stored_keys(self, lookups):
        cleaned = run(valid_payload()).cleaned

        assert cleaned["patient_id"] == 55
        assert cleaned["note_type_id"] == 7
        assert cleaned["desired_provider_id"] == 101
        assert cleaned["desired_location_id"] == 3

    def test_priority_rank_is_derived_from_configuration(self, lookups):
        assert run(valid_payload()).cleaned["priority_rank"] == 0

    def test_the_chosen_window_is_stored_structured(self, lookups):
        cleaned = run(valid_payload()).cleaned

        assert cleaned["preferred_windows"] == [
            {"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "12:00"}
        ]

    def test_expiry_is_stamped_at_creation(self, lookups):
        assert run(valid_payload()).cleaned["expires_on"] == date(2026, 10, 2)


class TestPatient:
    def test_a_missing_patient_is_refused(self, lookups):
        result = run(valid_payload(patient_id=""))

        assert "patient_id" in result.errors

    def test_an_unknown_patient_is_refused(self, lookups):
        lookups["patient"].objects.filter.return_value.first.return_value = None

        assert "patient_id" in run(valid_payload()).errors

    def test_an_edit_does_not_require_or_accept_a_patient(self, lookups):
        result = validate_entry(
            valid_payload(patient_id=""), config=CONFIG, today=TODAY, require_patient=False
        )

        assert result.ok is True
        assert "patient_id" not in result.cleaned


class TestAppointmentType:
    def test_a_missing_service_is_refused(self, lookups):
        assert "appointment_type_id" in run(valid_payload(appointment_type_id="")).errors

    def test_an_offered_service_is_accepted(self, lookups):
        assert run(valid_payload()).cleaned["note_type_id"] == 7

    def test_any_service_is_stored_as_no_service(self, lookups):
        # The column is nullable so an entry can match every type, and both the
        # serializer and the banner already render that state -- but no form
        # could produce it, so the service field silently defaulted to whichever
        # bookable type sorted first and matched nothing.
        result = run(valid_payload(appointment_type_id=PREFERENCE_ANY))

        assert result.ok
        assert result.cleaned["note_type_id"] is None

    def test_any_service_does_not_need_to_be_on_the_offered_list(self, lookups):
        # "Any" is not one of the instance's types, so checking it against them
        # would refuse the very answer the form now leads with.
        lookups["offered"].return_value = []

        assert run(valid_payload(appointment_type_id=PREFERENCE_ANY)).ok

    def test_a_blank_service_is_still_refused_rather_than_read_as_any(self, lookups):
        # A blank field is a broken client, not a preference. Reading it as "any"
        # would turn a bug in the form into a silently over-broad entry.
        assert "appointment_type_id" in run(valid_payload(appointment_type_id="")).errors

    def test_a_service_not_on_offer_is_refused(self, lookups):
        # Either unbookable or excluded by a configured allow-list. A stale or
        # tampered form lands here rather than writing an unbookable entry.
        assert "appointment_type_id" in run(valid_payload(appointment_type_id="9")).errors

    def test_with_nothing_configured_a_bookable_service_is_still_accepted(self, lookups):
        # The whole point of the fix: an unset allow-list means every bookable
        # type is on offer, so a reference plugin works on a fresh install.
        result = run(valid_payload(), config=WaitlistConfig.from_secrets({}))

        assert result.ok
        assert result.cleaned["note_type_id"] == 7

    def test_the_configured_list_is_passed_to_the_single_authority(self, lookups):
        # Validation must not re-derive "may be waitlisted" from configuration;
        # deriving it twice is what made the form offer services it refused.
        config = WaitlistConfig.from_secrets({"WAITLIST_APPOINTMENT_TYPES": "estab"})

        run(valid_payload(), config=config)

        assert lookups["offered"].call_args.args[0] is config

    def test_an_instance_with_nothing_bookable_is_refused_with_a_reason(self, lookups):
        lookups["offered"].return_value = []

        result = run(valid_payload())

        assert "scheduled" in result.errors["appointment_type_id"]

    def test_options_without_a_key_are_ignored_rather_than_matched(self, lookups):
        # A malformed row must not become the match for every submission.
        lookups["offered"].return_value = [{"dbid": None, "code": "x", "name": "X"}]

        assert "appointment_type_id" in run(valid_payload()).errors


class TestProvider:
    def test_any_provider_stores_the_preference_and_no_key(self, lookups):
        cleaned = run(valid_payload(provider_preference=PREFERENCE_ANY)).cleaned

        assert cleaned["provider_preference"] == PREFERENCE_ANY
        assert cleaned["desired_provider_id"] is None

    def test_a_specific_provider_without_a_choice_is_refused(self, lookups):
        assert "provider_id" in run(valid_payload(provider_id="")).errors

    def test_an_inactive_provider_is_refused(self, lookups):
        lookups["staff"].objects.filter.return_value.first.return_value = None

        assert "provider_id" in run(valid_payload()).errors

    def test_only_active_providers_are_looked_up(self, lookups):
        run(valid_payload())

        assert lookups["staff"].objects.filter.call_args.kwargs["active"] is True


class TestLocation:
    def test_any_location_stores_the_preference_and_no_key(self, lookups):
        cleaned = run(valid_payload(location_preference=PREFERENCE_ANY)).cleaned

        assert cleaned["location_preference"] == PREFERENCE_ANY
        assert cleaned["desired_location_id"] is None

    def test_a_specific_location_without_a_choice_is_refused(self, lookups):
        assert "location_id" in run(valid_payload(location_id="")).errors

    def test_an_inactive_location_is_refused(self, lookups):
        lookups["location"].objects.filter.return_value.first.return_value = None

        assert "location_id" in run(valid_payload()).errors


class TestPriority:
    def test_an_unconfigured_priority_is_refused(self, lookups):
        assert "priority" in run(valid_payload(priority="Yesterday")).errors

    def test_an_omitted_priority_falls_back_to_the_least_urgent(self, lookups):
        cleaned = run(valid_payload(priority="")).cleaned

        assert cleaned["priority_label"] == "Low"
        assert cleaned["priority_rank"] == 2


class TestPreferredWindow:
    def test_an_unknown_window_is_refused(self, lookups):
        assert "preferred_window" in run(valid_payload(preferred_window="whenever")).errors

    def test_any_time_stores_no_structured_window(self, lookups):
        assert run(valid_payload(preferred_window="any")).cleaned["preferred_windows"] == []

    def test_an_omitted_window_defaults_to_any_time(self, lookups):
        assert run(valid_payload(preferred_window="")).cleaned["preferred_windows"] == []

    def test_the_browser_timezone_is_kept_for_later_matching(self, lookups):
        cleaned = run(
            valid_payload(preferred_window_timezone="America/Denver")
        ).cleaned

        assert cleaned["preferred_windows_timezone"] == "America/Denver"


class TestNote:
    def test_an_overlong_note_is_refused(self, lookups):
        assert "note" in run(valid_payload(note="x" * 501)).errors

    def test_a_note_at_the_limit_is_accepted(self, lookups):
        assert run(valid_payload(note="x" * 500)).ok is True

    def test_a_missing_note_becomes_an_empty_string(self, lookups):
        assert run(valid_payload(note=None)).cleaned["note"] == ""

    def test_surrounding_whitespace_is_trimmed(self, lookups):
        assert run(valid_payload(note="  hello  ")).cleaned["note"] == "hello"


class TestMultipleProblems:
    def test_every_bad_field_is_reported_at_once(self, lookups):
        result = run(
            valid_payload(appointment_type_id="", priority="Yesterday", note="x" * 501)
        )

        assert set(result.errors) >= {"appointment_type_id", "priority", "note"}
