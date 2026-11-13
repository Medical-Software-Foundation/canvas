"""Facility lookups and the round check run before a rule is saved."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from canvas_sdk.v1.data.appointment import AppointmentProgressStatus

from provider_availability.engine.facilities import (
    active_facility_name,
    check_block_facility,
    check_round,
    facility_block_title,
    facility_patient_counts,
    facility_suggestions,
    get_active_facilities,
)

MODULE = "provider_availability.engine.facilities"
FACILITY_ID = "0d3c9f4e-5a2b-4c8d-9e1f-123456789abc"


class TestActiveFacilityName:
    def test_returns_the_name_of_an_active_facility(self):
        with patch(f"{MODULE}.Facility.objects") as objects:
            objects.filter.return_value.values_list.return_value.first.return_value = "Apple Valley Care"
            assert active_facility_name(FACILITY_ID) == "Apple Valley Care"
            assert objects.filter.call_args.kwargs == {"id": FACILITY_ID, "active": True}

    def test_unknown_or_inactive_facility(self):
        with patch(f"{MODULE}.Facility.objects") as objects:
            objects.filter.return_value.values_list.return_value.first.return_value = None
            assert active_facility_name(FACILITY_ID) is None

    def test_malformed_id_never_reaches_the_database(self):
        with patch(f"{MODULE}.Facility.objects") as objects:
            assert active_facility_name("not-a-uuid") is None
            assert active_facility_name("") is None
            assert objects.mock_calls == []


class TestCheckRound:
    def test_clinic_availability_clears_round_fields(self):
        body = {"facility_id": "", "facility_name": "stale", "max_visits": 8}
        assert check_round(body, rounds_on=False) is None
        assert body == {"facility_id": "", "facility_name": "", "max_visits": None}

    def test_a_round_takes_the_facility_name_from_canvas_not_the_payload(self):
        body = {"facility_id": FACILITY_ID, "facility_name": "Typed by the browser", "max_visits": 6, "location_ids": ["loc-1"]}
        with patch(f"{MODULE}.active_facility_name", return_value="Apple Valley Care"):
            assert check_round(body, rounds_on=True) is None
        assert body == {"facility_id": FACILITY_ID, "facility_name": "Apple Valley Care", "max_visits": 6, "location_ids": []}

    def test_a_round_needs_an_active_facility(self):
        with patch(f"{MODULE}.active_facility_name", return_value=None):
            assert check_round({"facility_id": FACILITY_ID}, rounds_on=True) == "Choose an active facility for this round."

    def test_no_new_rounds_while_the_switch_is_off(self):
        with patch(f"{MODULE}.active_facility_name") as lookup:
            assert check_round({"facility_id": FACILITY_ID}, rounds_on=False) == "Facility rounds are turned off in Settings."
            assert lookup.mock_calls == []

    def test_a_saved_round_can_still_be_edited_while_the_switch_is_off(self):
        body = {"facility_id": FACILITY_ID}
        with patch(f"{MODULE}.active_facility_name", return_value="Apple Valley Care"):
            assert check_round(body, rounds_on=False, existing_facility_id=FACILITY_ID) is None
        assert body["facility_name"] == "Apple Valley Care"

    def test_moving_a_saved_round_to_another_facility_needs_the_switch_on(self):
        other = "11111111-2222-3333-4444-555555555555"
        assert check_round({"facility_id": other}, rounds_on=False, existing_facility_id=FACILITY_ID) == (
            "Facility rounds are turned off in Settings."
        )


class TestActiveFacilities:
    def test_sorted_by_name(self):
        with patch(f"{MODULE}.Facility.objects") as objects:
            objects.filter.return_value.values_list.return_value = [(FACILITY_ID, "willow Bend"), ("f2", "Apple Valley"), ("f3", None)]
            assert get_active_facilities() == [
                {"id": "f3", "name": ""},
                {"id": "f2", "name": "Apple Valley"},
                {"id": FACILITY_ID, "name": "willow Bend"},
            ]
        assert objects.filter.call_args.kwargs == {"active": True}


class TestFacilitySuggestions:
    def test_counts_patients_per_facility_for_one_provider(self):
        now = datetime(2026, 11, 9, tzinfo=UTC)
        with patch(f"{MODULE}.PatientFacilityAddress.objects") as objects:
            rows = objects.filter.return_value.values.return_value.annotate.return_value.order_by.return_value
            rows.__iter__.return_value = iter([{"facility__id": FACILITY_ID, "facility__name": "Apple Valley Care", "patients": 22}])
            assert facility_suggestions("prov-1", now=now) == [{"id": FACILITY_ID, "name": "Apple Valley Care", "patients": 22}]
        assert objects.filter.call_args.kwargs == {
            "state": "active",
            "facility__active": True,
            "patient__appointments__provider__id": "prov-1",
            "patient__appointments__entered_in_error__isnull": True,
            "patient__appointments__start_time__gte": now - timedelta(days=365),
            "patient__appointments__status__in": [s for s in AppointmentProgressStatus.values if s != "cancelled"],
        }
        assert objects.filter.return_value.values.call_args.args == ("facility__id", "facility__name")
        assert objects.filter.return_value.values.return_value.annotate.return_value.order_by.call_args.args == ("-patients", "facility__name")


def test_a_saved_round_at_a_since_inactive_facility_keeps_its_name():
    body = {"facility_id": FACILITY_ID, "max_visits": 4}
    with patch(f"{MODULE}.active_facility_name", return_value=None):
        assert check_round(body, rounds_on=True, existing_facility_id=FACILITY_ID, existing_facility_name="Old Name") is None
    assert body["facility_name"] == "Old Name"


def test_a_new_round_at_an_inactive_facility_is_refused_even_with_a_name():
    with patch(f"{MODULE}.active_facility_name", return_value=None):
        assert check_round({"facility_id": FACILITY_ID}, rounds_on=True, existing_facility_name="Old Name") == (
            "Choose an active facility for this round."
        )


class TestCheckBlockFacility:
    def test_time_off_clears_facility_fields_and_keeps_its_reason(self):
        body = {"facility_id": "", "facility_name": "stale", "reason": "PTO", "location_ids": ["loc-1"]}
        assert check_block_facility(body, blocks_on=False) is None
        assert body == {"facility_id": "", "facility_name": "", "reason": "PTO", "location_ids": ["loc-1"]}

    def test_a_facility_block_is_titled_the_way_canvas_reads_a_facility_block(self):
        body = {"facility_id": FACILITY_ID, "facility_name": "Typed", "reason": "PTO", "location_ids": ["loc-1"], "hold_type": "same_day"}
        with patch(f"{MODULE}.active_facility_name", return_value="Riverstone Assisted Living"):
            assert check_block_facility(body, blocks_on=True) is None
        assert body == {
            "facility_id": FACILITY_ID,
            "facility_name": "Riverstone Assisted Living",
            "reason": "Riverstone Assisted Living Visit",
            "location_ids": [],
            "hold_type": "none",
        }

    def test_title(self):
        assert facility_block_title("Apple Valley Care") == "Apple Valley Care Visit"

    def test_needs_an_active_facility(self):
        with patch(f"{MODULE}.active_facility_name", return_value=None):
            assert check_block_facility({"facility_id": FACILITY_ID}, blocks_on=True) == "Choose an active facility for this block."

    def test_no_new_facility_blocks_while_the_switch_is_off(self):
        with patch(f"{MODULE}.active_facility_name") as lookup:
            assert check_block_facility({"facility_id": FACILITY_ID}, blocks_on=False) == "Facility blocks are turned off in Settings."
            assert lookup.mock_calls == []

    def test_a_saved_block_at_a_since_inactive_facility_can_be_edited_while_off(self):
        body = {"facility_id": FACILITY_ID}
        with patch(f"{MODULE}.active_facility_name", return_value=None):
            assert check_block_facility(
                body, blocks_on=False, existing_facility_id=FACILITY_ID, existing_facility_name="Old Name"
            ) is None
        assert body["reason"] == "Old Name Visit"


def test_patient_counts_per_active_facility():
    with patch(f"{MODULE}.PatientFacilityAddress.objects") as objects:
        objects.filter.return_value.values.return_value.annotate.return_value = [
            {"facility__id": FACILITY_ID, "patients": 6},
        ]
        assert facility_patient_counts() == {FACILITY_ID: 6}
    assert objects.filter.call_args.kwargs == {"state": "active", "facility__active": True}
    assert objects.filter.return_value.values.call_args.args == ("facility__id",)
