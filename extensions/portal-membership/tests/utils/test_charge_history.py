"""Tests for charge_history ORM wrapper.

The ORM layer is mocked so we can run without a live test database. This
matches the pattern used by other plugins in the repo (e.g. vida_sticky_note).
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from portal_membership.utils import charge_history


class TestAppendCharge:
    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_calls_create_with_expected_fields(self, mock_model: MagicMock) -> None:
        charge_history.append_charge(
            "patientabc",
            amount_cents=9900,
            status="succeeded",
            description="Signup",
        )
        mock_model.objects.create.assert_called_once_with(
            patient_id="patientabc",
            amount_cents=9900,
            status="succeeded",
            description="Signup",
            discount_code="",
        )

    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_passes_discount_code(self, mock_model: MagicMock) -> None:
        charge_history.append_charge(
            "patientabc",
            amount_cents=8910,
            status="succeeded",
            description="Monthly",
            discount_code="WELCOME10",
        )
        kwargs = mock_model.objects.create.call_args.kwargs
        assert kwargs["discount_code"] == "WELCOME10"

    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_none_discount_code_stored_as_empty(self, mock_model: MagicMock) -> None:
        charge_history.append_charge(
            "patientabc",
            amount_cents=9900,
            status="succeeded",
            description="X",
            discount_code=None,
        )
        assert mock_model.objects.create.call_args.kwargs["discount_code"] == ""

    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_coerces_amount_to_int(self, mock_model: MagicMock) -> None:
        charge_history.append_charge(
            "patientabc",
            amount_cents="123",  # type: ignore[arg-type]
            status="succeeded",
            description="X",
        )
        assert mock_model.objects.create.call_args.kwargs["amount_cents"] == 123


def _fake_row(date_iso: str, amount: int, status: str, description: str, code: str = "") -> SimpleNamespace:
    """Stand-in for a ChargeRecord instance returned by the ORM."""
    # Use a fixed tzinfo so `.date().isoformat()` is deterministic.
    ts = datetime.fromisoformat(f"{date_iso}T12:00:00+00:00")
    return SimpleNamespace(
        charged_at=ts,
        amount_cents=amount,
        status=status,
        description=description,
        discount_code=code,
    )


class TestGetCharges:
    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_returns_entries_in_dict_shape(self, mock_model: MagicMock) -> None:
        rows = [
            _fake_row("2026-04-10", 9900, "succeeded", "Signup", "WELCOME10"),
            _fake_row("2026-03-10", 9900, "succeeded", "Earlier"),
        ]
        mock_model.objects.filter.return_value.order_by.return_value.__getitem__.return_value = rows

        out = charge_history.get_charges("patientabc")
        assert out[0] == {
            "date": "2026-04-10",
            "amount_cents": 9900,
            "status": "succeeded",
            "description": "Signup",
            "discount_code": "WELCOME10",
        }
        # No discount_code key when the row's code is empty.
        assert "discount_code" not in out[1]

    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_filters_by_patient_id_and_orders_desc(self, mock_model: MagicMock) -> None:
        filter_qs = MagicMock()
        filter_qs.order_by.return_value.__getitem__.return_value = []
        mock_model.objects.filter.return_value = filter_qs

        charge_history.get_charges("patientabc")
        mock_model.objects.filter.assert_called_once_with(patient_id="patientabc")
        filter_qs.order_by.assert_called_once_with("-charged_at")

    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_applies_limit(self, mock_model: MagicMock) -> None:
        slice_mock = MagicMock()
        slice_mock.__getitem__.return_value = []
        mock_model.objects.filter.return_value.order_by.return_value = slice_mock

        charge_history.get_charges("patientabc", limit=5)
        slice_mock.__getitem__.assert_called_once_with(slice(None, 5, None))

    @patch("portal_membership.utils.charge_history.ChargeRecord")
    def test_empty_when_no_rows(self, mock_model: MagicMock) -> None:
        mock_model.objects.filter.return_value.order_by.return_value.__getitem__.return_value = []
        assert charge_history.get_charges("patientabc") == []
