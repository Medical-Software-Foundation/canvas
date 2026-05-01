"""Unit tests for MonthlyBillingCron."""
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from portal_membership.payment_processor.stripe_processor import StripeError
from portal_membership.protocols.billing_cron import (
    MonthlyBillingCron,
    RETRY_DELAY_DAYS,
)
from portal_membership.utils.billing_cycle import next_billing_iso


class _DueQs:
    """Mimics the QuerySet returned by `Membership.objects.filter(...).filter(...)`."""

    def __init__(self, instances: list) -> None:
        self._instances = list(instances)

    def count(self) -> int:
        return len(self._instances)

    def __iter__(self):
        return iter(self._instances)


def _set_due(mock_membership_cls: MagicMock, patient_ids: list[str]) -> None:
    """Arrange the Membership mock so that its chained filter returns patients."""
    from types import SimpleNamespace
    instances = [SimpleNamespace(patient_id=pid) for pid in patient_ids]
    mock_membership_cls.objects.filter.return_value.filter.return_value = _DueQs(instances)



# Cadence-aware date math is fully exercised in test_membership_api's
# TestNextBillingIso. The cron-side coverage focuses on _process_patient
# selecting the right cadence from the record (see TestSuccessAdvancesCadence).


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cron(secrets: dict[str, str], event: MagicMock | None = None) -> MonthlyBillingCron:
    ev = event or MagicMock()
    handler = MonthlyBillingCron(event=ev)
    handler.secrets = secrets
    return handler


# ---------------------------------------------------------------------------
# execute — no active members
# ---------------------------------------------------------------------------

class TestExecuteNoMembers:
    @patch("portal_membership.protocols.billing_cron.Membership")
    def test_no_active_ids(self, mock_membership_cls: MagicMock, secrets: dict[str, str]) -> None:
        _set_due(mock_membership_cls, [])
        cron = _make_cron(secrets)
        effects = cron.execute()
        assert effects == []

    @patch("portal_membership.protocols.billing_cron.Membership")
    def test_queries_with_status_and_date_filters(
        self, mock_membership_cls: MagicMock, secrets: dict[str, str]
    ) -> None:
        """execute() should filter by status='active' and today's billing/retry date.

        The per-patient billing-date check no longer lives in Python — it's the
        ORM query's responsibility. This test locks in the query shape.
        """
        _set_due(mock_membership_cls, [])
        cron = _make_cron(secrets)
        cron.execute()

        first_filter = mock_membership_cls.objects.filter.call_args_list[0]
        assert first_filter.kwargs == {"status": "active"}

    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    def test_skips_none_record(
        self,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        _set_due(mock_membership_cls, ["ghost-patient"])
        mock_get_membership.return_value = None
        cron = _make_cron(secrets)
        effects = cron.execute()
        assert effects == []


# ---------------------------------------------------------------------------
# execute — successful charge
# ---------------------------------------------------------------------------

class TestExecuteSuccess:
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_charges_and_advances_date(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        today_str = date.today().isoformat()
        active_record["next_billing_date"] = today_str

        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record

        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_success"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        effects = cron.execute()

        assert effects == []
        mock_processor.charge.assert_called_once_with(
            customer_id="cus_test123",
            amount_cents=9900,
            currency="usd",
            description="Membership: Gold (recurring)",
            payment_method_id="pm_test456",
        )
        saved = mock_set_membership.call_args[0][1]
        # next_billing_date must be a real ISO date string, not mocked
        assert saved["next_billing_date"] != today_str
        assert len(saved["next_billing_date"]) == 10  # "YYYY-MM-DD"
        assert saved["consecutive_failures"] == 0
        assert "retry_date" not in saved

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_uses_plan_key_as_fallback_description(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        """When plan_name is absent, falls back to plan key in description."""
        today_str = date.today().isoformat()
        record = dict(active_record)
        record["next_billing_date"] = today_str
        del record["plan_name"]

        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = record

        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        description = mock_processor.charge.call_args.kwargs["description"]
        assert "gold" in description.lower()


class TestExecuteCadenceAdvancement:
    """The cron must advance next_billing_date by the record's cadence."""

    @pytest.mark.parametrize(
        ("cadence", "today", "expected_next"),
        [
            ("daily", "2026-05-15", "2026-05-16"),
            ("weekly", "2026-05-15", "2026-05-22"),
            ("monthly", "2026-05-15", "2026-06-15"),
            ("quarterly", "2026-05-15", "2026-08-15"),
            ("annually", "2026-05-15", "2027-05-15"),
            # Quarterly + end-of-month clamp: Aug 31 → Nov 30.
            ("quarterly", "2026-08-31", "2026-11-30"),
            # Annually + leap-year clamp: Feb 29, 2028 → Feb 28, 2029.
            ("annually", "2028-02-29", "2029-02-28"),
        ],
    )
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_advance_by_cadence(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
        cadence: str,
        today: str,
        expected_next: str,
    ) -> None:
        active_record["cadence"] = cadence
        active_record["next_billing_date"] = today
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        saved = mock_set_membership.call_args[0][1]
        assert saved["next_billing_date"] == expected_next

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_missing_cadence_falls_back_to_monthly(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        """Pre-cadence records (no cadence key) keep advancing monthly."""
        active_record.pop("cadence", None)
        active_record["next_billing_date"] = "2026-05-15"
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()
        saved = mock_set_membership.call_args[0][1]
        assert saved["next_billing_date"] == "2026-06-15"


# ---------------------------------------------------------------------------
# execute — first failure → retry scheduled
# ---------------------------------------------------------------------------

class TestExecuteFirstFailure:
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_first_failure_schedules_retry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        today_str = date.today().isoformat()
        active_record["next_billing_date"] = today_str
        active_record["consecutive_failures"] = 0

        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record

        mock_processor = MagicMock()
        mock_processor.charge.side_effect = StripeError("Declined")
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        effects = cron.execute()

        assert effects == []
        saved = mock_set_membership.call_args[0][1]
        assert saved["consecutive_failures"] == 1
        assert "retry_date" in saved
        assert saved["next_billing_date"] == saved["retry_date"]

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_second_failure_schedules_another_retry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        """Attempt 2 of 3 still retries — auto-cancel only happens on the third failure."""
        today_str = date.today().isoformat()
        active_record["next_billing_date"] = today_str
        active_record["consecutive_failures"] = 1
        active_record["retry_date"] = today_str

        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record

        mock_processor = MagicMock()
        mock_processor.charge.side_effect = StripeError("Declined")
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        effects = cron.execute()

        # No banner/task effects — the membership stays active.
        assert effects == []
        saved = mock_set_membership.call_args[0][1]
        assert saved["status"] == "active"
        assert saved["consecutive_failures"] == 2
        assert "retry_date" in saved
        assert saved["next_billing_date"] == saved["retry_date"]


# ---------------------------------------------------------------------------
# execute — third failure → auto-cancel
# ---------------------------------------------------------------------------

class TestExecuteAutoCancel:
    @patch("portal_membership.protocols.billing_cron.Team")
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_auto_cancel_after_third_failure(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        mock_team_cls: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        mock_team_cls.objects.filter.return_value.exists.return_value = True
        today_str = date.today().isoformat()
        active_record["next_billing_date"] = today_str
        # Two prior failures recorded — this is attempt 3 of 3.
        active_record["consecutive_failures"] = 2
        active_record["retry_date"] = today_str

        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record

        mock_processor = MagicMock()
        mock_processor.charge.side_effect = StripeError("Declined")
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        effects = cron.execute()

        # refreshed status banner, task — no separate cancel banner
        assert len(effects) == 2

        saved = mock_set_membership.call_args[0][1]
        assert saved["status"] == "cancelled"


# ---------------------------------------------------------------------------
# execute — discount handling
# ---------------------------------------------------------------------------

@pytest.fixture
def discounted_active_record(active_record: dict[str, Any]) -> dict[str, Any]:
    r = dict(active_record)
    r["next_billing_date"] = date.today().isoformat()
    r["discount_code"] = "WELCOME10"
    r["discount_type"] = "percent"
    r["discount_value"] = 10
    r["discount_cycles_remaining"] = 2
    return r


class TestExecuteDiscount:
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_percent_discount_reduces_charge_and_decrements_counter(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        discounted_active_record: dict[str, Any],
    ) -> None:
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = discounted_active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        # 10% off 9900 = 8910
        assert mock_processor.charge.call_args.kwargs["amount_cents"] == 8910
        saved = mock_set_membership.call_args.args[1]
        assert saved["discount_cycles_remaining"] == 1  # was 2, decremented
        assert saved["discount_code"] == "WELCOME10"  # still present

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_last_discount_cycle_clears_fields(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        discounted_active_record: dict[str, Any],
    ) -> None:
        """When cycles_remaining hits 0, the discount fields are removed."""
        discounted_active_record["discount_cycles_remaining"] = 1
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = discounted_active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        saved = mock_set_membership.call_args.args[1]
        assert "discount_code" not in saved
        assert "discount_type" not in saved
        assert "discount_value" not in saved
        assert "discount_cycles_remaining" not in saved

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_100_percent_discount_skips_stripe(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        discounted_active_record: dict[str, Any],
    ) -> None:
        discounted_active_record["discount_value"] = 100
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = discounted_active_record
        mock_processor = MagicMock()
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        mock_processor.charge.assert_not_called()
        saved = mock_set_membership.call_args.args[1]
        # Still advances next_billing_date and decrements counter.
        assert saved["discount_cycles_remaining"] == 1

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_failed_discounted_charge_does_not_decrement_counter(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        discounted_active_record: dict[str, Any],
    ) -> None:
        """A failed charge should schedule a retry without burning a discount cycle."""
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = discounted_active_record
        mock_processor = MagicMock()
        mock_processor.charge.side_effect = StripeError("Declined")
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        saved = mock_set_membership.call_args.args[1]
        assert saved["discount_cycles_remaining"] == 2  # unchanged
        assert saved["consecutive_failures"] == 1
        assert "retry_date" in saved

    @patch("portal_membership.protocols.billing_cron.append_charge")
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_success_writes_succeeded_history_entry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        mock_append_charge: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        today_str = date.today().isoformat()
        active_record["next_billing_date"] = today_str
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        mock_append_charge.assert_called_once()
        call = mock_append_charge.call_args
        assert call.args[0] == "patient-abc-123"
        assert call.kwargs["status"] == "succeeded"
        assert call.kwargs["amount_cents"] == 9900
        assert "Gold" in call.kwargs["description"]

    @patch("portal_membership.protocols.billing_cron.append_charge")
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_failed_charge_writes_failed_history_entry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        mock_append_charge: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        today_str = date.today().isoformat()
        active_record["next_billing_date"] = today_str
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record
        mock_processor = MagicMock()
        mock_processor.charge.side_effect = StripeError("Declined")
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        mock_append_charge.assert_called_once()
        kwargs = mock_append_charge.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert "retry" in kwargs["description"].lower()

    @patch("portal_membership.protocols.billing_cron.append_charge")
    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_discount_code_preserved_in_final_history_entry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        mock_append_charge: MagicMock,
        secrets: dict[str, str],
        discounted_active_record: dict[str, Any],
    ) -> None:
        """Even when the last discount cycle clears the discount fields,
        the history entry for that cycle still records the code."""
        discounted_active_record["discount_cycles_remaining"] = 1
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = discounted_active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        saved = mock_set_membership.call_args.args[1]
        # Discount fields cleared from the persisted record …
        assert "discount_code" not in saved
        # … but the history entry still captures the code that was active.
        mock_append_charge.assert_called_once()
        assert mock_append_charge.call_args.kwargs["discount_code"] == "WELCOME10"

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_zero_discount_cycles_remaining_charges_full_price(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        secrets: dict[str, str],
        discounted_active_record: dict[str, Any],
    ) -> None:
        """A record with cycles_remaining=0 (shouldn't normally happen, but defensive) bills full."""
        discounted_active_record["discount_cycles_remaining"] = 0
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = discounted_active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        assert mock_processor.charge.call_args.kwargs["amount_cents"] == 9900

    @patch("portal_membership.protocols.billing_cron.set_membership")
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_auto_cancel_without_team_id(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        mock_set_membership: MagicMock,
        active_record: dict[str, Any],
    ) -> None:
        """Auto-cancel should work even when STAFF_OFFBOARDING_TEAM_ID is absent."""
        today_str = date.today().isoformat()
        active_record["next_billing_date"] = today_str
        # Two prior failures — this is the final attempt before auto-cancel.
        active_record["consecutive_failures"] = 2

        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record

        mock_processor = MagicMock()
        mock_processor.charge.side_effect = StripeError("Failure")
        mock_stripe_cls.return_value = mock_processor

        secrets_no_team: dict[str, str] = {
            "STRIPE_SECRET_KEY": "sk_test_fake",
            "MEMBERSHIP_PLANS": "[]",
            "BILLING_CURRENCY": "usd",
        }
        cron = _make_cron(secrets_no_team)
        effects = cron.execute()

        # refreshed status banner, task — no separate cancel banner
        assert len(effects) == 2
