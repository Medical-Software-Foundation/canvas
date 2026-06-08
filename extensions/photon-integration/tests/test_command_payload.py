"""Tests for extracting a Photon Rx payload from command data."""

from __future__ import annotations

import pytest

from photon_integration.command_payload import extract_rx, medication_term

FULL = {
    "prescribe": {"text": "Lisinopril 10 mg tablet"},
    "sig": "Take 1 tablet daily",
    "days_supply": 30,
    "quantity_to_dispense": 30,
    "type_to_dispense": {"description": "tablet", "representative_ndc": "00781180501"},
    "refills": 2,
    "substitutions": "Allowed",
    "note_to_pharmacist": "handle with care",
}


class TestMedicationTerm:
    def test_from_prescribe_dict(self):
        assert medication_term(FULL) == "Lisinopril 10 mg tablet"

    def test_change_medication_takes_precedence(self):
        data = dict(FULL, change_medication_to={"name": "Amlodipine 5 mg tablet"})
        assert medication_term(data) == "Amlodipine 5 mg tablet"

    def test_string_value(self):
        assert medication_term({"prescribe": "Metformin"}) == "Metformin"

    def test_none_when_absent(self):
        assert medication_term({"prescribe": {}}) is None


class TestExtractRx:
    def test_maps_fields(self):
        rx = extract_rx(FULL)
        assert rx["term"] == "Lisinopril 10 mg tablet"
        assert rx["instructions"] == "Take 1 tablet daily"
        assert rx["dispenseQuantity"] == 30.0
        assert rx["dispenseUnit"] == "tablet"
        assert rx["ndc"] == "00781180501"
        assert rx["refillsAllowed"] == 2
        assert rx["daysSupply"] == 30
        assert rx["notes"] == "handle with care"
        assert rx["dispenseAsWritten"] is False

    def test_dispense_as_written_when_not_allowed(self):
        assert extract_rx(dict(FULL, substitutions="Not allowed"))["dispenseAsWritten"] is True

    @pytest.mark.parametrize("quantity", [None])
    def test_missing_quantity_is_none(self, quantity):
        assert extract_rx(dict(FULL, quantity_to_dispense=quantity))["dispenseQuantity"] is None

    def test_missing_refills_defaults_zero(self):
        data = {k: v for k, v in FULL.items() if k != "refills"}
        assert extract_rx(data)["refillsAllowed"] == 0
