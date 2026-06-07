"""Tests for the Photon dispatch handler."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.v1.data.common import ContactPointSystem

from photon_integration.handlers.dispatch import PhotonDispatchHandler

MODULE = "photon_integration.handlers.dispatch"

PRESCRIBER_UUID = "11111111-1111-1111-1111-111111111111"
TEAM_UUID = "22222222-2222-2222-2222-222222222222"

DEFAULT_SECRETS = {
    "PHOTON_CLIENT_ID": "cid",
    "PHOTON_CLIENT_SECRET": "secret",
    "PHOTON_ENV": "sandbox",
    "PHOTON_TEST_PRESCRIBER_ID": "pro_test",
}

DEFAULT_FIELDS = {
    "prescribe": {"text": "Lisinopril 10 mg tablet"},
    "sig": "Take 1 tablet daily",
    "days_supply": 30,
    "quantity_to_dispense": 30,
    "type_to_dispense": {"description": "tablet", "representative_ndc": "00591012345"},
    "refills": 2,
    "substitutions": "Allowed",
    "pharmacy": {"ncpdp": "1234567"},
    "prescriber": {"id": PRESCRIBER_UUID},
    "note_to_pharmacist": "handle with care",
}


def _patient(stored_ext=None, with_phone=True, with_email=True, with_address=True,
             first="Jane", last="Doe", dob=True, sex="F"):
    patient = MagicMock()
    patient.id = "pt-1"
    patient.first_name = first
    patient.last_name = last
    patient.sex_at_birth = sex
    patient.birth_date = SimpleNamespace(isoformat=lambda: "1990-01-01") if dob else None

    ext_entry = SimpleNamespace(value=stored_ext) if stored_ext else None
    patient.external_identifiers.filter.return_value.first.return_value = ext_entry

    def telecom_filter(system):
        result = MagicMock()
        value = None
        if system == ContactPointSystem.PHONE and with_phone:
            value = "+15551234567"
        elif system == ContactPointSystem.EMAIL and with_email:
            value = "jane@example.com"
        contact = SimpleNamespace(value=value) if value else None
        result.order_by.return_value.first.return_value = contact
        return result

    patient.telecom.filter.side_effect = telecom_filter

    if with_address:
        patient.addresses.first.return_value = SimpleNamespace(
            line1="1 Main St", line2="Apt 2", city="Townsville",
            state_code="CA", postal_code="90001", country="US",
        )
    else:
        patient.addresses.first.return_value = None
    return patient


def _event(fields=None, patient_id="pt-1", command_id="cmd-1"):
    return SimpleNamespace(
        context={
            "patient": {"id": patient_id} if patient_id else {},
            "fields": fields if fields is not None else dict(DEFAULT_FIELDS),
        },
        target=SimpleNamespace(id=command_id),
    )


@contextlib.contextmanager
def _patched(*, selected=True, patient=None, client=None):
    """Patch the dispatch module's collaborators; yield (client, AddTask, CPEI)."""
    client = client or MagicMock()
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(f"{MODULE}._photon_send_selected", return_value=selected)
        )
        patient_cls = stack.enter_context(patch(f"{MODULE}.Patient"))
        patient_cls.DoesNotExist = type("DoesNotExist", (Exception,), {})
        if isinstance(patient, Exception) or (
            isinstance(patient, type) and issubclass(patient, Exception)
        ):
            patient_cls.objects.get.side_effect = patient_cls.DoesNotExist
        else:
            patient_cls.objects.get.return_value = patient if patient is not None else _patient()
        stack.enter_context(patch(f"{MODULE}.build_client", return_value=client))
        add_task = stack.enter_context(patch(f"{MODULE}.AddTask"))
        add_task.return_value.apply.return_value = "TASK_EFFECT"
        cpei = stack.enter_context(
            patch("photon_integration.patient_sync.CreatePatientExternalIdentifier")
        )
        cpei.return_value.create.return_value = "EXT_EFFECT"
        yield client, add_task, cpei


def _make_client_success():
    client = MagicMock()
    client.create_patient.return_value = "pat_new"
    client.find_treatment_id.return_value = "med_1"
    client.create_prescription.return_value = "rx_1"
    client.create_order.return_value = "ord_1"
    return client


class TestGuards:
    def test_not_selected_returns_empty(self):
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(selected=False) as (client, _, _):
            assert handler.compute() == []
        client.create_prescription.assert_not_called()

    def test_missing_patient_id_returns_empty(self):
        handler = PhotonDispatchHandler(
            event=_event(patient_id=None), secrets=DEFAULT_SECRETS
        )
        with _patched() as (client, _, _):
            assert handler.compute() == []
        client.create_prescription.assert_not_called()

    def test_patient_not_found_returns_empty(self):
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=Exception) as (client, _, _):
            assert handler.compute() == []
        client.create_prescription.assert_not_called()


class TestSuccess:
    def test_new_patient_full_flow(self):
        client = _make_client_success()
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(), client=client) as (_, _, cpei):
            effects = handler.compute()

        # New patient -> external id persisted; that effect is returned.
        assert effects == ["EXT_EFFECT"]
        client.create_patient.assert_called_once()
        cpei.assert_called_once_with(
            patient_id="pt-1",
            system="https://photon.health/patient",
            value="pat_new",
        )
        # prescription payload mapped correctly
        rx_input = client.create_prescription.call_args.args[0]
        assert rx_input["patientId"] == "pat_new"
        assert rx_input["treatmentId"] == "med_1"
        assert "prescriberId" not in rx_input  # not a createPrescription argument
        assert rx_input["refillsAllowed"] == 2  # Canvas refills
        assert rx_input["dispenseAsWritten"] is False  # substitutions allowed
        assert rx_input["dispenseQuantity"] == 30.0
        assert rx_input["dispenseUnit"] == "tablet"
        assert rx_input["instructions"] == "Take 1 tablet daily"
        # order created, pharmacy unresolved -> None
        order_kwargs = client.create_order.call_args.kwargs
        assert order_kwargs["patient_id"] == "pat_new"
        assert order_kwargs["prescription_id"] == "rx_1"
        assert order_kwargs["pharmacy_id"] is None

    def test_existing_stored_external_id_skips_create(self):
        client = _make_client_success()
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_existing"), client=client) as (_, _, cpei):
            effects = handler.compute()

        assert effects == []  # nothing persisted, no failure
        client.create_patient.assert_not_called()
        cpei.assert_not_called()
        assert client.create_prescription.call_args.args[0]["patientId"] == "pat_existing"

    def test_dispense_as_written_when_not_allowed(self):
        client = _make_client_success()
        fields = dict(DEFAULT_FIELDS, substitutions="Not allowed")
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client):
            handler.compute()
        assert client.create_prescription.call_args.args[0]["dispenseAsWritten"] is True

    def test_pharmacy_photon_id_passed_through(self):
        client = _make_client_success()
        fields = dict(DEFAULT_FIELDS, pharmacy={"photon_id": "phr_555"})
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client):
            handler.compute()
        assert client.create_order.call_args.kwargs["pharmacy_id"] == "phr_555"

    def test_adjust_uses_change_medication_to(self):
        client = _make_client_success()
        fields = dict(DEFAULT_FIELDS)
        fields["change_medication_to"] = {"text": "Amlodipine 5 mg tablet"}
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client):
            handler.compute()
        client.find_treatment_id.assert_called_once_with("Amlodipine 5 mg tablet")


class TestFailures:
    def test_treatment_not_found_creates_task(self):
        client = _make_client_success()
        client.find_treatment_id.return_value = None
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client) as (_, add_task, _):
            effects = handler.compute()
        assert effects == ["TASK_EFFECT"]
        client.create_prescription.assert_not_called()
        kwargs = add_task.call_args.kwargs
        assert kwargs["patient_id"] == "pt-1"
        assert kwargs["assignee_id"] == PRESCRIBER_UUID
        assert kwargs["labels"] == ["photon"]

    def test_non_uuid_prescriber_leaves_task_unassigned(self):
        client = _make_client_success()
        client.find_treatment_id.return_value = None
        # CanvasUser ids (usr_...) are not Staff UUIDs and must not be passed
        # to AddTask, which would otherwise raise a ValidationError.
        fields = dict(DEFAULT_FIELDS, prescriber={"id": "usr_01KTFYYT32QNR8ZPCW7QTWBXXD"})
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client) as (_, add_task, _):
            effects = handler.compute()
        assert effects == ["TASK_EFFECT"]
        kwargs = add_task.call_args.kwargs
        assert kwargs["assignee_id"] is None
        assert kwargs["author_id"] is None

    def test_new_patient_then_failure_keeps_external_id_and_task(self):
        client = _make_client_success()
        client.find_treatment_id.return_value = None  # fail after patient creation
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(), client=client):
            effects = handler.compute()
        assert effects == ["EXT_EFFECT", "TASK_EFFECT"]

    def test_missing_sig_creates_task(self):
        client = _make_client_success()
        fields = dict(DEFAULT_FIELDS, sig="")
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client) as (_, add_task, _):
            effects = handler.compute()
        assert effects == ["TASK_EFFECT"]
        assert "SIG" in add_task.call_args.kwargs["title"]

    def test_missing_quantity_creates_task(self):
        client = _make_client_success()
        fields = dict(DEFAULT_FIELDS, quantity_to_dispense=None)
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client):
            assert handler.compute() == ["TASK_EFFECT"]

    def test_missing_dispense_unit_creates_task(self):
        client = _make_client_success()
        fields = dict(DEFAULT_FIELDS, type_to_dispense={})
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client):
            assert handler.compute() == ["TASK_EFFECT"]

    def test_missing_phone_creates_task_on_new_patient(self):
        client = _make_client_success()
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(with_phone=False), client=client) as (_, add_task, _):
            effects = handler.compute()
        assert effects == ["TASK_EFFECT"]
        assert "phone" in add_task.call_args.kwargs["title"]

    def test_missing_address_creates_task_on_order(self):
        client = _make_client_success()
        # stored ext id so patient sync is skipped; address only needed for order
        handler = PhotonDispatchHandler(event=_event(), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x", with_address=False), client=client):
            assert handler.compute() == ["TASK_EFFECT"]

    def test_no_medication_name_creates_task(self):
        client = _make_client_success()
        fields = dict(DEFAULT_FIELDS, prescribe={}, change_medication_to=None)
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=DEFAULT_SECRETS)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client):
            assert handler.compute() == ["TASK_EFFECT"]

    def test_fallback_team_used_when_no_prescriber(self):
        client = _make_client_success()
        client.find_treatment_id.return_value = None
        fields = dict(DEFAULT_FIELDS, prescriber=None)
        secrets = dict(DEFAULT_SECRETS, PHOTON_FALLBACK_TEAM_ID=TEAM_UUID)
        handler = PhotonDispatchHandler(event=_event(fields=fields), secrets=secrets)
        with _patched(patient=_patient(stored_ext="pat_x"), client=client) as (_, add_task, _):
            handler.compute()
        kwargs = add_task.call_args.kwargs
        assert kwargs["team_id"] == TEAM_UUID
        assert kwargs["assignee_id"] is None
