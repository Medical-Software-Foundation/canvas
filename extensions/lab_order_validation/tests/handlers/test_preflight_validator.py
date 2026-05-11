"""Tests for the LabOrderPreflightValidator handler."""

from unittest.mock import MagicMock, patch

from lab_order_validation.handlers.preflight_validator import (
    LabOrderPreflightValidator,
)


PATIENT_PATH = "lab_order_validation.handlers.preflight_validator.Patient"


def _electronic_partner(name="Labcorp"):
    return {
        "text": name,
        "value": name,
        "extra": {"electronic_ordering_enabled": True},
    }


def _paper_partner(name="Paper Lab"):
    return {
        "text": name,
        "value": name,
        "extra": {"electronic_ordering_enabled": False},
    }


def _build_handler(*, lab_partner_field, patient_id="patient-1", note_uuid="note-1"):
    event = MagicMock()
    event.context = {
        "fields": {"lab_partner": lab_partner_field},
        "patient": {"id": patient_id},
        "note": {"uuid": note_uuid},
    }
    return LabOrderPreflightValidator(event)


def test_no_op_when_lab_partner_not_electronic():
    handler = _build_handler(lab_partner_field=_paper_partner())

    with patch(PATIENT_PATH) as mock_patient_cls:
        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []


def test_no_op_when_no_lab_partner_selected():
    handler = _build_handler(lab_partner_field=None)

    with patch(PATIENT_PATH) as mock_patient_cls:
        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []


def test_no_op_when_no_patient_id():
    event = MagicMock()
    event.context = {
        "fields": {"lab_partner": _electronic_partner()},
        "patient": {},
        "note": {"uuid": "note-1"},
    }
    handler = LabOrderPreflightValidator(event)

    with patch(PATIENT_PATH) as mock_patient_cls:
        effects = handler.compute()

        assert effects == []
        assert mock_patient_cls.mock_calls == []


def test_no_op_when_patient_not_found():
    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls:
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = None

        effects = handler.compute()

        assert effects == []


def test_pass_when_all_rules_satisfied(healthy_patient):
    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls:
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = healthy_patient

        effects = handler.compute()

        assert effects == []


def test_blocks_when_address_rule_fails(patient_with, make_patient_address, make_coverage):
    bad_patient = patient_with(
        coverages=[make_coverage(rank=1, issuer=MagicMock(dbid=1, name="Acme"))],
        addresses=[make_patient_address(use="home", type="physical")],
    )
    bad_patient.coverages.all.return_value[0].issuer.addresses.all.return_value = [
        _ok_transactor_address()
    ]
    bad_patient.coverages.all.return_value[0].issuer.phones.all.return_value = [
        _ok_transactor_phone()
    ]

    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls:
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = bad_patient

        effects = handler.compute()

        assert len(effects) == 1


def test_blocks_when_rule2_fires(
    patient_with, make_coverage, make_issuer, make_patient_address
):
    duplicate_issuer = make_issuer(dbid=99, name="Acme")
    patient = patient_with(
        coverages=[
            make_coverage(rank=1, issuer=duplicate_issuer),
            make_coverage(rank=2, issuer=duplicate_issuer),
        ],
        addresses=[make_patient_address()],
    )

    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls:
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = patient

        effects = handler.compute()

        assert len(effects) == 1


def test_blocks_when_subscriber_address_missing(
    patient_with, make_coverage, make_issuer, make_patient_address
):
    issuer = make_issuer(dbid=1, name="Acme")
    bare_subscriber = MagicMock()
    bare_subscriber.id = "subscriber-uuid"
    bare_subscriber.full_name = "Jane Doe"
    bare_subscriber.first_name = "Jane"
    bare_subscriber.last_name = "Doe"
    bare_subscriber.addresses.all.return_value = []

    patient = patient_with(
        coverages=[make_coverage(rank=1, issuer=issuer, subscriber=bare_subscriber)],
        addresses=[make_patient_address()],
    )

    handler = _build_handler(lab_partner_field=_electronic_partner())

    with patch(PATIENT_PATH) as mock_patient_cls:
        mock_patient_cls.objects.filter.return_value.prefetch_related.return_value.first.return_value = patient

        effects = handler.compute()

        assert len(effects) == 1


def _ok_transactor_address():
    addr = MagicMock()
    addr.line1 = "1 Health Way"
    addr.city = "Boston"
    addr.state_code = "MA"
    addr.postal_code = "02101"
    return addr


def _ok_transactor_phone():
    phone = MagicMock()
    phone.value = "617-555-0100"
    return phone
