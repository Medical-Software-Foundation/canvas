"""Tests for the Patients, Encounters, and Claims datasets."""

from reporting.datasets import get_dataset, list_datasets


def test_all_four_datasets_registered():
    keys = {d.key for d in list_datasets()}
    assert {"appointments", "patients", "encounters", "claims"} <= keys


def test_patients_dataset():
    ds = get_dataset("patients")
    assert ds.model.__name__ == "Patient"
    assert ds.date_field == "created"
    assert "new_patients" in ds.measures
    # sex is an enum choice field; business line is a dynamic-options reference field
    assert ds.fields["sex_at_birth"].choices
    assert ds.fields["business_line"].options_value_path == "business_line__name"
    assert ds.dimensions["business_line"].group_path == "business_line__name"


def test_encounters_dataset():
    ds = get_dataset("encounters")
    assert ds.model.__name__ == "Encounter"
    assert ds.date_field == "start_time"
    assert "encounters" in ds.measures
    medium_values = [v for v, _ in ds.fields["medium"].choices]
    assert "office" in medium_values and "video" in medium_values
    assert ds.dimensions["state"].group_path == "state"


def test_claims_dataset_is_count_only_with_queue():
    ds = get_dataset("claims")
    assert ds.model.__name__ == "Claim"
    assert ds.date_field == "created"
    assert list(ds.measures.keys()) == ["claims"]  # volume only, no dollar measures
    assert ds.fields["queue"].options_value_path == "current_queue__display_name"
    assert ds.dimensions["queue"].group_path == "current_queue__display_name"
