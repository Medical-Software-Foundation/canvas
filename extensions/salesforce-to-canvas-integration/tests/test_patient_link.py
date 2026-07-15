"""Tests for the patient link and duplicate lookup utilities.

Covers the early return guards (empty id, empty last name) that are not hit
by the ORM integration tests, plus the DB paths to round out coverage.
"""

from __future__ import annotations

from datetime import date

from salesforce_to_canvas_integration.services.patient_link import (
    find_duplicate_patients,
    find_linked_patient_id,
)


def test_find_linked_patient_id_returns_none_for_empty_string() -> None:
    assert find_linked_patient_id("") is None


def test_find_linked_patient_id_returns_none_for_unlinked_id() -> None:
    assert find_linked_patient_id("003NOTLINKED") is None


def test_find_duplicate_patients_returns_empty_list_for_empty_last_name() -> None:
    assert find_duplicate_patients(last_name="", birth_date=date(1990, 1, 1)) == []


def test_find_duplicate_patients_returns_empty_when_no_match() -> None:
    result = find_duplicate_patients(last_name="Zzyzx", birth_date=date(1900, 1, 1))
    assert result == []
