"""Tests for the membership_store ORM wrapper.

The ORM layer is mocked — no live test DB. We verify dict↔model conversion,
the update_or_create call shape, and the patient FK resolution flow.
"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from portal_membership.utils import membership_store as store

PATIENT_UUID = "44827549-a55d-46f6-86ed-ac91058a88e6"
PATIENT_DBID = 12345


def _full_record() -> dict:
    return {
        "plan": "gold",
        "plan_name": "Gold",
        "status": "active",
        "stripe_customer_id": "cus_test",
        "payment_method_id": "pm_test",
        "amount_cents": 9900,
        "currency": "usd",
        "billing_day": 11,
        "next_billing_date": "2026-04-11",
        "consecutive_failures": 0,
    }


def _instance_from(**overrides) -> SimpleNamespace:
    """Return a stand-in for a Membership ORM instance."""
    base = {
        "plan": "gold",
        "plan_name": "Gold",
        "status": "active",
        "stripe_customer_id": "cus_test",
        "payment_method_id": "pm_test",
        "amount_cents": 9900,
        "currency": "usd",
        "billing_day": 11,
        "next_billing_date": date(2026, 4, 11),
        "retry_date": None,
        "consecutive_failures": 0,
        "discount_code": "",
        "discount_type": "",
        "discount_value": 0,
        "discount_cycles_remaining": 0,
        "cadence": "monthly",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestGetMembership:
    @patch("portal_membership.utils.membership_store.Membership")
    def test_returns_none_when_absent(self, mock_model: MagicMock) -> None:
        mock_model.DoesNotExist = Exception
        mock_model.objects.get.side_effect = Exception()
        assert store.get_membership(PATIENT_UUID) is None

    @patch("portal_membership.utils.membership_store.Membership")
    def test_serializes_instance_to_dict(self, mock_model: MagicMock) -> None:
        mock_model.objects.get.return_value = _instance_from()
        out = store.get_membership(PATIENT_UUID)
        assert out["plan"] == "gold"
        assert out["next_billing_date"] == "2026-04-11"

    @patch("portal_membership.utils.membership_store.Membership")
    def test_uses_related_lookup_on_patient_uuid(self, mock_model: MagicMock) -> None:
        mock_model.objects.get.return_value = _instance_from()
        store.get_membership(PATIENT_UUID)
        assert mock_model.objects.get.call_args.kwargs == {"patient__id": PATIENT_UUID}

    @patch("portal_membership.utils.membership_store.Membership")
    def test_omits_retry_date_when_null(self, mock_model: MagicMock) -> None:
        mock_model.objects.get.return_value = _instance_from()
        assert "retry_date" not in store.get_membership(PATIENT_UUID)

    @patch("portal_membership.utils.membership_store.Membership")
    def test_includes_retry_date_when_present(self, mock_model: MagicMock) -> None:
        mock_model.objects.get.return_value = _instance_from(retry_date=date(2026, 4, 15))
        assert store.get_membership(PATIENT_UUID)["retry_date"] == "2026-04-15"

    @patch("portal_membership.utils.membership_store.Membership")
    def test_omits_discount_fields_when_empty(self, mock_model: MagicMock) -> None:
        mock_model.objects.get.return_value = _instance_from()
        out = store.get_membership(PATIENT_UUID)
        for key in ("discount_code", "discount_type", "discount_value", "discount_cycles_remaining"):
            assert key not in out

    @patch("portal_membership.utils.membership_store.Membership")
    def test_includes_discount_fields_when_set(self, mock_model: MagicMock) -> None:
        mock_model.objects.get.return_value = _instance_from(
            discount_code="WELCOME10",
            discount_type="percent",
            discount_value=10,
            discount_cycles_remaining=2,
        )
        out = store.get_membership(PATIENT_UUID)
        assert out["discount_code"] == "WELCOME10"
        assert out["discount_cycles_remaining"] == 2


class TestSetMembership:
    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_calls_update_or_create(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        store.set_membership(PATIENT_UUID, _full_record())
        mock_model.objects.update_or_create.assert_called_once()
        call = mock_model.objects.update_or_create.call_args
        assert call.kwargs["patient_id"] == PATIENT_DBID
        assert "defaults" in call.kwargs

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_defaults_contain_all_fields(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        store.set_membership(PATIENT_UUID, _full_record())
        defaults = mock_model.objects.update_or_create.call_args.kwargs["defaults"]
        for key in ("plan", "plan_name", "status", "amount_cents", "currency", "billing_day"):
            assert key in defaults

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_missing_key_sets_default(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        store.set_membership(PATIENT_UUID, _full_record())
        defaults = mock_model.objects.update_or_create.call_args.kwargs["defaults"]
        assert defaults["discount_code"] == ""
        assert defaults["discount_value"] == 0
        assert defaults["discount_cycles_remaining"] == 0
        assert defaults["cadence"] == "monthly"
        assert defaults["retry_date"] is None

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_accepts_iso_string_dates(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        data = {**_full_record(), "retry_date": "2026-04-15"}
        store.set_membership(PATIENT_UUID, data)
        defaults = mock_model.objects.update_or_create.call_args.kwargs["defaults"]
        assert defaults["next_billing_date"] == date(2026, 4, 11)
        assert defaults["retry_date"] == date(2026, 4, 15)

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_accepts_date_objects(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        data = {**_full_record(), "next_billing_date": date(2026, 5, 1)}
        store.set_membership(PATIENT_UUID, data)
        defaults = mock_model.objects.update_or_create.call_args.kwargs["defaults"]
        assert defaults["next_billing_date"] == date(2026, 5, 1)

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=None)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_unknown_patient_skips_write(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        store.set_membership(PATIENT_UUID, _full_record())
        mock_model.objects.update_or_create.assert_not_called()


class TestDeleteMembership:
    @patch("portal_membership.utils.membership_store.Membership")
    def test_calls_filter_delete(self, mock_model: MagicMock) -> None:
        store.delete_membership(PATIENT_UUID)
        mock_model.objects.filter.assert_called_once_with(patient__id=PATIENT_UUID)
        mock_model.objects.filter.return_value.delete.assert_called_once()

    @patch("portal_membership.utils.membership_store.Membership")
    def test_noop_on_blank(self, mock_model: MagicMock) -> None:
        store.delete_membership("")
        mock_model.objects.filter.assert_not_called()


class _FakeDoesNotExist(Exception):
    """Stand-in for Membership.DoesNotExist when the model is mocked."""


class TestTryClaimSignup:
    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=None)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_rejects_unknown_patient(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        result, prior = store.try_claim_signup(PATIENT_UUID)
        assert result == "in_progress"
        assert prior is None
        mock_model.objects.get.assert_not_called()

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_creates_new_pending_row_when_no_existing(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        mock_model.DoesNotExist = _FakeDoesNotExist
        mock_model.objects.get.side_effect = _FakeDoesNotExist()
        result, prior = store.try_claim_signup(PATIENT_UUID)
        assert result == "claimed"
        assert prior is None
        mock_model.objects.create.assert_called_once()
        kwargs = mock_model.objects.create.call_args.kwargs
        assert kwargs["patient_id"] == PATIENT_DBID
        assert kwargs["status"] == store.PENDING_SIGNUP_STATUS

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_concurrent_create_returns_in_progress(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        from django.db import IntegrityError
        mock_model.DoesNotExist = _FakeDoesNotExist
        mock_model.objects.get.side_effect = _FakeDoesNotExist()
        mock_model.objects.create.side_effect = IntegrityError("duplicate")
        result, prior = store.try_claim_signup(PATIENT_UUID)
        assert result == "in_progress"
        assert prior is None

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_rejects_when_existing_active(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        mock_model.objects.get.return_value = _instance_from(status="active")
        result, prior = store.try_claim_signup(PATIENT_UUID)
        assert result == "already_active"
        assert prior is None

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_rejects_when_already_pending(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        mock_model.objects.get.return_value = _instance_from(status=store.PENDING_SIGNUP_STATUS)
        result, _prior = store.try_claim_signup(PATIENT_UUID)
        assert result == "in_progress"

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_transitions_cancelled_to_pending(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        mock_model.objects.get.return_value = _instance_from(status="cancelled")
        mock_model.objects.filter.return_value.update.return_value = 1
        result, prior = store.try_claim_signup(PATIENT_UUID)
        assert result == "claimed"
        assert prior == "cancelled"
        filter_kwargs = mock_model.objects.filter.call_args.kwargs
        assert filter_kwargs["status"] == "cancelled"
        assert filter_kwargs["patient_id"] == PATIENT_DBID

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_transition_race_returns_in_progress(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        mock_model.objects.get.return_value = _instance_from(status="cancelled")
        mock_model.objects.filter.return_value.update.return_value = 0
        result, prior = store.try_claim_signup(PATIENT_UUID)
        assert result == "in_progress"
        assert prior is None


class TestReleaseClaim:
    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_deletes_when_prior_status_none(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        store.release_claim(PATIENT_UUID, None)
        mock_model.objects.filter.assert_called_once_with(
            patient_id=PATIENT_DBID,
            status=store.PENDING_SIGNUP_STATUS,
        )
        mock_model.objects.filter.return_value.delete.assert_called_once()

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=PATIENT_DBID)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_reverts_to_prior_status_when_provided(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        store.release_claim(PATIENT_UUID, "cancelled")
        mock_model.objects.filter.return_value.update.assert_called_once_with(status="cancelled")

    @patch("portal_membership.utils.membership_store._resolve_patient_dbid", return_value=None)
    @patch("portal_membership.utils.membership_store.Membership")
    def test_noop_on_unknown_patient(
        self, mock_model: MagicMock, _mock_resolve: MagicMock
    ) -> None:
        store.release_claim(PATIENT_UUID, None)
        mock_model.objects.filter.assert_not_called()
