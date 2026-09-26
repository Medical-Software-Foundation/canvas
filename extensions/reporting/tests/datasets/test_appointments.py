# tests/datasets/test_appointments.py
from __future__ import annotations

from reporting.datasets import get_dataset, list_datasets
from reporting.query.measures import RatioMeasure


def test_appointments_dataset_registered():
    keys = [d.key for d in list_datasets()]
    assert "appointments" in keys


def test_appointments_has_date_field_and_model():
    ds = get_dataset("appointments")
    assert ds.date_field == "start_time"
    assert ds.model.__name__ == "Appointment"


def test_provider_dimension_resolves_group_paths():
    ds = get_dataset("appointments")
    dim = ds.dimensions["provider"]
    assert dim.group_path == "provider__id"
    assert dim.display_paths == ["provider__first_name", "provider__last_name"]


def test_no_show_rate_measure_present_and_is_ratio():
    ds = get_dataset("appointments")
    m = ds.measures["no_show_rate"]
    assert isinstance(m, RatioMeasure)
    assert m.as_percent is True
    assert m.numerator_where == {"status": "noshowed"}  # cancellations excluded


def test_status_field_filterable_with_is_one_of():
    ds = get_dataset("appointments")
    f = ds.fields["status"]
    assert "is_one_of" in f.operators
    assert f.orm_path == "status"


def test_status_field_exposes_choices():
    ds = get_dataset("appointments")
    f = ds.fields["status"]
    values = [v for v, _label in f.choices]
    assert "noshowed" in values and "cancelled" in values
    # choices are (value, label) pairs
    assert all(len(c) == 2 for c in f.choices)


def test_get_unknown_dataset_raises():
    import pytest

    with pytest.raises(KeyError):
        get_dataset("nope")


def test_provider_field_has_dynamic_options():
    ds = get_dataset("appointments")
    f = ds.fields["provider"]
    assert f.options_value_path == "provider__id"
    assert f.options_label_paths == ("provider__first_name", "provider__last_name")
