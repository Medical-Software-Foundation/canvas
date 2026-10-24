"""Tests for sequential patient numbering."""

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_patient
from patient_numbering.handlers.patient_created import NumberNewPatient
from patient_numbering.handlers.profile_field import PatientNumberProfileField
from patient_numbering.models import PatientNumber
from patient_numbering.numbering import (
    IDENTIFIER_SYSTEM,
    METADATA_KEY,
    assign_number,
    backfill_complete,
    mark_backfill_complete,
    number_effects,
    unnumbered_patients,
)



def _event(target: str) -> MagicMock:
    event = MagicMock()
    event.target.id = target
    return event


@pytest.mark.django_db
class TestAssignNumber:
    def test_first_patient_gets_one_and_numbers_increase(self) -> None:
        first, second = make_patient(), make_patient()
        assert assign_number(first) == (1, True)
        assert assign_number(second) == (2, True)

    def test_patient_keeps_existing_number(self) -> None:
        patient = make_patient()
        assign_number(patient)
        assert assign_number(patient) == (1, False)
        assert PatientNumber.objects.count() == 1

    def test_number_stays_with_removed_patient(self) -> None:
        # The plugin never deletes PatientNumber rows (the FK is DO_NOTHING), so a number
        # assigned to a patient that is later removed stays taken and is skipped.
        a, b = make_patient(), make_patient()
        assign_number(a)
        assert assign_number(b) == (2, True)
        assert sorted(PatientNumber.objects.values_list("number", flat=True)) == [1, 2]

    def test_number_taken_concurrently_retries(self) -> None:
        a, b = make_patient(), make_patient()
        assign_number(a)
        real_aggregate = PatientNumber.objects.aggregate
        calls = {"n": 0}

        def stale_then_real(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            # First read is stale (as if another worker had not committed yet), so the
            # insert of number 1 hits the unique constraint and the loop retries.
            if calls["n"] == 1:
                return {"highest": 0}
            return real_aggregate(*args, **kwargs)

        with patch.object(PatientNumber.objects, "aggregate", side_effect=stale_then_real):
            assert assign_number(b) == (2, True)
        assert calls["n"] == 2


@pytest.mark.django_db
class TestBackfillOrder:
    def test_unnumbered_patients_oldest_first(self) -> None:
        a, b, c = make_patient(), make_patient(), make_patient()
        assign_number(b)
        assert list(unnumbered_patients()) == [a, c]

    def test_backfill_flag(self) -> None:
        assert backfill_complete() is False
        mark_backfill_complete()
        assert backfill_complete() is True


class TestEffects:
    def test_number_effects_write_identifier_and_metadata(self) -> None:
        with patch("canvas_sdk.effects.patient_metadata.base.Patient") as patient_model:
            patient_model.objects.filter.return_value.exists.return_value = True
            identifier, metadata = number_effects("a" * 32, 42)

        identifier_data = json.loads(identifier.payload)["data"]
        assert identifier_data == {
            "value": "42",
            "system": IDENTIFIER_SYSTEM,
            "patient_id": "a" * 32,
        }
        metadata_data = json.loads(metadata.payload)["data"]
        assert metadata_data["key"] == METADATA_KEY
        assert metadata_data["value"] == "42"

    def test_profile_field_is_read_only(self) -> None:
        handler = PatientNumberProfileField(event=MagicMock())
        (effect,) = handler.compute()
        form = json.loads(effect.payload)["data"]["form"]
        assert form == [
            {
                "key": METADATA_KEY,
                "label": "Patient ID",
                "required": False,
                "editable": False,
                "type": "text",
                "options": None,
                "value": None,
            }
        ]


@pytest.mark.django_db
class TestNewPatientHandler:
    def test_missing_patient_returns_nothing(self) -> None:
        mark_backfill_complete()
        handler = NumberNewPatient(event=_event("f" * 32))
        assert handler.compute() == []

    def test_existing_number_not_reassigned(self) -> None:
        patient = make_patient()
        assign_number(patient)
        mark_backfill_complete()
        handler = NumberNewPatient(event=_event(patient.id))
        assert handler.compute() == []

    def test_skips_until_backfill_complete(self) -> None:
        patient = make_patient()
        handler = NumberNewPatient(event=_event(patient.id))
        assert handler.compute() == []
        assert PatientNumber.objects.count() == 0

    def test_numbers_new_patient_after_backfill(self) -> None:
        existing, new = make_patient(), make_patient()
        assign_number(existing)
        mark_backfill_complete()
        handler = NumberNewPatient(event=_event(new.id))
        with patch("patient_numbering.handlers.patient_created.number_effects") as effects:
            effects.return_value = ["effects"]
            assert handler.compute() == ["effects"]
        effects.assert_called_once_with(new.id, 2)
