"""Tests for the Hospitalization custom data model."""
from __future__ import annotations

import datetime

import pytest
from canvas_sdk.test_utils.factories import PatientFactory

from hospitalization_tracker.models import Hospitalization
from tests.conftest import HospitalizationFactory


# ---------------------------------------------------------------------------
# length_of_stay_days property
# ---------------------------------------------------------------------------


def test_length_of_stay_days_with_both_dates() -> None:
    """Returns the difference in days when both admission and discharge are set."""
    h = Hospitalization(
        admission_date=datetime.date(2024, 3, 1),
        discharge_date=datetime.date(2024, 3, 8),
    )
    assert h.length_of_stay_days == 7


def test_length_of_stay_days_same_day() -> None:
    """Returns 0 when admission and discharge are the same day."""
    d = datetime.date(2024, 3, 1)
    h = Hospitalization(admission_date=d, discharge_date=d)
    assert h.length_of_stay_days == 0


def test_length_of_stay_days_no_discharge() -> None:
    """Returns None when discharge_date is not set."""
    h = Hospitalization(
        admission_date=datetime.date(2024, 3, 1),
        discharge_date=None,
    )
    assert h.length_of_stay_days is None


def test_length_of_stay_days_no_admission() -> None:
    """Returns None when admission_date is not set."""
    h = Hospitalization(
        admission_date=None,
        discharge_date=datetime.date(2024, 3, 8),
    )
    assert h.length_of_stay_days is None


# ---------------------------------------------------------------------------
# CRUD via factory (integration tests)
# ---------------------------------------------------------------------------


@pytest.mark.integtest
def test_create_hospitalization() -> None:
    """Creating a Hospitalization through the factory assigns a dbid."""
    h = HospitalizationFactory.create(
        hospital_name="City Medical Center",
        reason_for_admission="Stroke",
        icu_stay=True,
        icu_duration_days=3,
    )
    assert h.dbid is not None
    assert h.hospital_name == "City Medical Center"
    assert h.icu_stay is True
    assert h.icu_duration_days == 3


@pytest.mark.integtest
def test_read_hospitalization() -> None:
    """A created Hospitalization can be fetched back by dbid."""
    h = HospitalizationFactory.create(hospital_name="Riverside Hospital")
    fetched = Hospitalization.objects.get(dbid=h.dbid)
    assert fetched.hospital_name == "Riverside Hospital"


@pytest.mark.integtest
def test_update_hospitalization() -> None:
    """Updating a field on a Hospitalization persists the change."""
    h = HospitalizationFactory.create(hospital_name="Old Name")
    h.hospital_name = "New Name"
    h.save()
    assert Hospitalization.objects.get(dbid=h.dbid).hospital_name == "New Name"


@pytest.mark.integtest
def test_delete_hospitalization() -> None:
    """Deleting a Hospitalization removes it from the database."""
    h = HospitalizationFactory.create()
    dbid = h.dbid
    h.delete()
    assert not Hospitalization.objects.filter(dbid=dbid).exists()


@pytest.mark.integtest
def test_filter_by_patient() -> None:
    """Hospitalizations can be filtered by patient FK via patient__id."""
    patient = PatientFactory.create()
    HospitalizationFactory.create(patient=patient)
    HospitalizationFactory.create(patient=patient)
    # Another patient should not appear
    HospitalizationFactory.create()

    qs = Hospitalization.objects.filter(patient__id=patient.id)
    assert qs.count() == 2


@pytest.mark.integtest
def test_order_by_admission_date_desc() -> None:
    """Most recent hospitalization appears first when ordered by -admission_date."""
    patient = PatientFactory.create()
    HospitalizationFactory.create(
        patient=patient,
        admission_date=datetime.date(2023, 1, 1),
        discharge_date=datetime.date(2023, 1, 5),
    )
    HospitalizationFactory.create(
        patient=patient,
        admission_date=datetime.date(2024, 6, 1),
        discharge_date=datetime.date(2024, 6, 10),
    )

    results = list(
        Hospitalization.objects.filter(patient__id=patient.id).order_by("-admission_date")
    )
    assert results[0].admission_date == datetime.date(2024, 6, 1)
    assert results[1].admission_date == datetime.date(2023, 1, 1)


@pytest.mark.integtest
def test_length_of_stay_persisted() -> None:
    """length_of_stay_days reflects the actual dates stored in the database."""
    h = HospitalizationFactory.create(
        admission_date=datetime.date(2024, 5, 1),
        discharge_date=datetime.date(2024, 5, 11),
    )
    fetched = Hospitalization.objects.get(dbid=h.dbid)
    assert fetched.length_of_stay_days == 10


@pytest.mark.integtest
def test_icu_flags_persisted() -> None:
    """icu_stay=True with a duration is stored and retrieved correctly."""
    h = HospitalizationFactory.create(icu_stay=True, icu_duration_days=5)
    fetched = Hospitalization.objects.get(dbid=h.dbid)
    assert fetched.icu_stay is True
    assert fetched.icu_duration_days == 5


@pytest.mark.integtest
def test_readmission_flag_persisted() -> None:
    """readmission_within_30_days=True is stored and retrieved correctly."""
    h = HospitalizationFactory.create(readmission_within_30_days=True)
    fetched = Hospitalization.objects.get(dbid=h.dbid)
    assert fetched.readmission_within_30_days is True
