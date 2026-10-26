"""Tests for keeping the number in an ID carried over from a previous system (for example Charm)."""

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.v1.data import PatientExternalIdentifier
from tests.conftest import make_patient
from patient_numbering.handlers.admin_api import BATCH_SIZE, PatientNumberingAdminAPI
from patient_numbering.handlers.patient_created import NumberNewPatient
from patient_numbering.models import PatientNumber, PatientProxy
from patient_numbering.numbering import (
    NumberFormat,
    adoptable_patients,
    backfill_complete,
    mark_backfill_complete,
    number_effects,
)

CHARM = NumberFormat(prefix="ABC", width=4, source_system="Charm")
CHARM_SECRETS = {
    "ADMIN_STAFF_IDS": "admin1",
    "SOURCE_IDENTIFIER_SYSTEM": "Charm",
    "NUMBER_PREFIX": "ABC",
    "NUMBER_WIDTH": "4",
}


def _source_id(patient: PatientProxy, value: str, system: str = "Charm") -> None:
    PatientExternalIdentifier.objects.create(
        patient=patient,
        system=system,
        value=value,
        use="usual",
        identifier_type="",
        issued_date=date(2026, 1, 1),
        expiration_date=date(2099, 1, 1),
    )


def _api(secrets: dict[str, str] | None = None) -> PatientNumberingAdminAPI:
    api = PatientNumberingAdminAPI.__new__(PatientNumberingAdminAPI)
    api.secrets = secrets if secrets is not None else CHARM_SECRETS
    api.request = SimpleNamespace(headers={"canvas-logged-in-user-id": "admin1"})
    return api


def _backfill(api: PatientNumberingAdminAPI) -> dict[str, object]:
    with patch("patient_numbering.handlers.admin_api.number_effects", return_value=[]):
        body: dict[str, object] = json.loads(api.backfill()[0].content)
    return body


def _numbers() -> dict[int, int]:
    return dict(PatientNumber.objects.values_list("patient_id", "number"))


class TestNumberFormat:
    def test_unset_secrets_mean_plain_numbers(self) -> None:
        fmt = NumberFormat.from_secrets({})
        assert fmt == NumberFormat()
        assert fmt.format(7) == "7"

    def test_reads_secrets(self) -> None:
        assert NumberFormat.from_secrets(CHARM_SECRETS) == CHARM

    def test_invalid_width_is_ignored(self) -> None:
        assert NumberFormat.from_secrets({"NUMBER_WIDTH": "four"}).width == 0

    def test_formats_with_prefix_and_padding(self) -> None:
        assert CHARM.format(42) == "ABC0042"
        assert CHARM.format(12345) == "ABC12345"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("ABC0042", 42),
            (" ABC0349 ", 349),
            ("ABC12345", 12345),
            ("XYZ0042", None),
            ("ABC", None),
            ("ABC00A2", None),
            ("ABC0000", None),
            ("ABC-042", None),
        ],
    )
    def test_parses_source_ids(self, value: str, expected: int | None) -> None:
        assert CHARM.parse(value) == expected

    def test_effects_skip_identifier_when_source_id_already_matches(self) -> None:
        # The Charm ID "ABC0042" already makes "!ABC0042" search work. A second identifier with
        # the same value would make Canvas search list the patient twice.
        with patch("canvas_sdk.effects.patient_metadata.base.Patient") as patient_model:
            patient_model.objects.filter.return_value.exists.return_value = True
            (metadata,) = number_effects("a" * 32, 42, CHARM, searchable_as="ABC0042")
        assert json.loads(metadata.payload)["data"]["value"] == "ABC0042"

    def test_effects_keep_identifier_when_source_id_is_written_differently(self) -> None:
        with patch("canvas_sdk.effects.patient_metadata.base.Patient") as patient_model:
            patient_model.objects.filter.return_value.exists.return_value = True
            identifier, _ = number_effects("a" * 32, 42, CHARM, searchable_as="ABC42")
        assert json.loads(identifier.payload)["data"]["value"] == "ABC0042"

    def test_effects_write_formatted_value(self) -> None:
        with patch("canvas_sdk.effects.patient_metadata.base.Patient") as patient_model:
            patient_model.objects.filter.return_value.exists.return_value = True
            identifier, metadata = number_effects("a" * 32, 349, CHARM)
        assert json.loads(identifier.payload)["data"]["value"] == "ABC0349"
        assert json.loads(metadata.payload)["data"]["value"] == "ABC0349"


@pytest.mark.django_db
class TestAdoptableQuery:
    def test_only_matching_system_and_format(self) -> None:
        a, b, c, d = make_patient(), make_patient(), make_patient(), make_patient()
        _source_id(a, "ABC0010")
        _source_id(b, "ABC0011", system="Other")
        _source_id(c, "not-an-id")
        assert adoptable_patients(CHARM) == ([(a, 10, "ABC0010")], 1)
        assert d not in [p for p, _, _ in adoptable_patients(CHARM)[0]]

    def test_nothing_adoptable_without_source_system(self) -> None:
        _source_id(make_patient(), "ABC0010")
        assert adoptable_patients(NumberFormat(prefix="ABC", width=4)) == ([], 0)

    def test_limit_loads_only_the_batch_but_counts_all(self) -> None:
        patients = [make_patient() for _ in range(3)]
        for index, patient in enumerate(patients, start=1):
            _source_id(patient, CHARM.format(index))
        batch, total = adoptable_patients(CHARM, limit=2)
        assert [p for p, _, _ in batch] == patients[:2]
        assert total == 3

    def test_taken_source_number_is_not_adoptable(self) -> None:
        holder, imported = make_patient(), make_patient()
        PatientNumber.objects.create(patient=holder, number=7)
        _source_id(imported, "ABC0007")
        assert adoptable_patients(CHARM) == ([], 0)


@pytest.mark.django_db
class TestBackfillAdoption:
    def test_adopted_patients_get_metadata_only_and_others_get_both(self) -> None:
        adopted, conflict = make_patient(), make_patient()
        _source_id(adopted, "ABC0010")
        _source_id(conflict, "ABC0010")
        with patch("patient_numbering.handlers.admin_api.number_effects", return_value=[]) as fx:
            _admin_backfill = _api().backfill()
        calls = {c.args[0]: c.kwargs.get("searchable_as") for c in fx.call_args_list}
        assert calls[adopted.id] == "ABC0010"
        assert calls[conflict.id] is None
        assert _admin_backfill

    def test_keeps_source_numbers_then_continues_after_highest(self) -> None:
        # A typical import: patients carry source IDs with gaps, plus one test patient
        # created in Canvas with no Charm ID.
        test_patient = make_patient()
        imported = [make_patient() for _ in range(3)]
        for patient, value in zip(imported, ["ABC0002", "ABC0348", "ABC0107"], strict=True):
            _source_id(patient, value)

        body = _backfill(_api())

        numbers = _numbers()
        assert [numbers[p.dbid] for p in imported] == [2, 348, 107]
        assert numbers[test_patient.dbid] == 349
        assert body["adopted"] == 3
        assert body["remaining"] == 0
        assert body["backfill_complete"] is True
        assert backfill_complete() is True

    def test_new_patient_after_backfill_gets_next_formatted_id(self) -> None:
        imported = make_patient()
        _source_id(imported, "ABC0348")
        _backfill(_api())

        new = make_patient()
        event = MagicMock()
        event.target.id = new.id
        handler = NumberNewPatient(event=event, secrets=CHARM_SECRETS)
        with patch("patient_numbering.handlers.patient_created.number_effects") as effects:
            effects.return_value = ["effects"]
            assert handler.compute() == ["effects"]
        effects.assert_called_once_with(new.id, 349, CHARM)

    def test_duplicate_source_id_gets_a_new_number(self) -> None:
        first, duplicate = make_patient(), make_patient()
        _source_id(first, "ABC0005")
        _source_id(duplicate, "ABC0005")

        body = _backfill(_api())

        numbers = _numbers()
        assert numbers[first.dbid] == 5
        assert numbers[duplicate.dbid] == 6
        assert body["conflicts"] == 1
        assert body["backfill_complete"] is True

    def test_source_number_taken_by_existing_patient(self) -> None:
        # A patient numbered before the import already holds 1. The imported patient whose
        # Charm number is 1 can't keep it, so it is numbered after the highest in use.
        earlier = make_patient()
        PatientNumber.objects.create(patient=earlier, number=1)
        imported = make_patient()
        _source_id(imported, "ABC0001")

        body = _backfill(_api())

        assert _numbers()[imported.dbid] == 2
        assert body["conflicts"] == 1

    def test_adopts_every_source_id_before_numbering_anyone(self) -> None:
        # The patient without a source ID is older, but must not be numbered until all source
        # IDs are adopted, or it could take a number that belongs to a later batch.
        older = make_patient()
        imported = [make_patient() for _ in range(BATCH_SIZE + 1)]
        for index, patient in enumerate(imported, start=1):
            _source_id(patient, CHARM.format(index))

        first = _backfill(_api())
        assert first["adopted"] == BATCH_SIZE
        assert older.dbid not in _numbers()

        # The last source ID is adopted first, then the rest of the batch numbers the older
        # patient after the highest number in use.
        second = _backfill(_api())
        assert second["adopted"] == 1
        assert second["assigned"] == 2
        assert _numbers()[older.dbid] == BATCH_SIZE + 2
        assert second["backfill_complete"] is True

    def test_existing_number_is_never_replaced(self) -> None:
        patient = make_patient()
        PatientNumber.objects.create(patient=patient, number=50)
        _source_id(patient, "ABC0007")
        mark_backfill_complete()

        _backfill(_api())

        assert _numbers()[patient.dbid] == 50

    def test_status_reports_adopted_and_next_id(self) -> None:
        imported, other = make_patient(), make_patient()
        _source_id(imported, "ABC0348")
        _backfill(_api())

        status = json.loads(_api().status()[0].content)
        assert status["source_system"] == "Charm"
        assert status["adopted"] == 1
        assert status["numbered"] == 2
        assert status["next_patient_id"] == "ABC0350"
        assert _numbers()[other.dbid] == 349
