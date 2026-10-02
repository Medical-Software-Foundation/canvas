"""Tests for the clinical-wave datasets."""

from reporting.datasets import get_dataset, list_datasets

CLINICAL_KEYS = [
    "conditions", "medications", "observations", "immunizations",
    "allergies", "goals", "referrals", "care_teams", "labs",
]


def test_all_clinical_datasets_registered():
    keys = {d.key for d in list_datasets()}
    assert set(CLINICAL_KEYS) <= keys


def test_each_clinical_dataset_has_model_date_field_and_a_measure():
    for key in CLINICAL_KEYS:
        ds = get_dataset(key)
        assert ds.model is not None
        assert ds.date_field
        assert ds.measures  # at least one count measure


def test_conditions_active_measure_filters_status():
    ds = get_dataset("conditions")
    m = ds.measures["active_conditions"]
    assert m.where == {"deleted": False, "clinical_status": "active"}


def test_immunizations_provider_dimension_uses_given_by():
    ds = get_dataset("immunizations")
    assert ds.dimensions["provider"].group_path == "given_by__id"


def test_categorical_fields_use_dynamic_options():
    # clinical categorical fields are populated from live distinct values
    assert get_dataset("medications").fields["status"].options_value_path == "status"
    assert get_dataset("labs").fields["transmission_type"].options_value_path == "transmission_type"
