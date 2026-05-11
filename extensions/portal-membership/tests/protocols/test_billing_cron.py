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
    """Mimics the QuerySet returned by ``filter(...).filter(...).select_related(...)``."""

    def __init__(self, instances: list) -> None:
        self._instances = list(instances)

    def count(self) -> int:
        return len(self._instances)

    def select_related(self, *_args, **_kwargs) -> "_DueQs":
        return self

    def __iter__(self):
        return iter(self._instances)


def _set_due(mock_membership_cls: MagicMock, patient_ids: list[str]) -> None:
    """Arrange the Membership mock so that its chained filter returns patients.

    Each instance exposes ``.patient.id`` so the cron can extract the UUID from
    the FK without a real DB lookup.
    """
    from types import SimpleNamespace
    instances = [
        SimpleNamespace(patient=SimpleNamespace(id=pid))
        for pid in patient_ids
    ]
    mock_membership_cls.objects.filter.return_value.filter.return_value = _DueQs(instances)


def _get_update_kwargs(mock_membership_cls: MagicMock) -> dict[str, Any]:
    """Return the kwargs of the most recent ``Membership.objects.filter(...).update(...)``.

    The cron's three handlers (``_handle_success`` /
    ``_handle_failure_with_retry`` / ``_handle_auto_cancel``) now write
    through ``_update_membership_fields``, which issues a single targeted
    UPDATE per call. This helper is the test surface for asserting which
    columns the handler actually mutated — replacing the old
    ``set_membership.call_args[0][1]`` pattern from before targeted UPDATEs
    landed (PR #243 review #6).
    """
    update_mock = mock_membership_cls.objects.filter.return_value.update
    if not update_mock.call_args:
        return {}
    return dict(update_mock.call_args.kwargs)



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

    @patch("portal_membership.protocols.billing_cron.Membership")
    def test_due_query_uses_lte_so_missed_days_self_heal(
        self, mock_membership_cls: MagicMock, secrets: dict[str, str]
    ) -> None:
        """A missed cron day must not permanently strand members.

        The chained date filter must compare with ``__lte=today`` so a
        member whose next_billing_date / retry_date matched the missed
        day still gets picked up on the next successful run.
        """
        from datetime import date

        from django.db.models import Q

        _set_due(mock_membership_cls, [])
        cron = _make_cron(secrets)
        cron.execute()

        # Second filter call carries the date predicate.
        date_filter = mock_membership_cls.objects.filter.return_value.filter.call_args
        # The single positional arg is a Q object; introspect its children.
        q_arg = date_filter.args[0]
        assert isinstance(q_arg, Q)
        today = date.today()
        # Q.children is a list of (field, value) tuples for leaf nodes.
        flat = [child for child in q_arg.children]
        assert ("next_billing_date__lte", today) in flat
        assert ("retry_date__lte", today) in flat

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

    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    def test_one_bad_patient_does_not_abort_batch(
        self,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """A non-StripeError exception on one patient must not halt the
        whole run. Every remaining patient still gets processed; the bad
        record is logged and skipped."""
        _set_due(mock_membership_cls, ["bad-patient", "good-patient"])

        # First call (bad-patient) raises, second (good-patient) returns None.
        mock_get_membership.side_effect = [
            Exception("transient DB error"),
            None,
        ]

        cron = _make_cron(secrets)
        # Must not raise — the loop's per-patient try/except absorbs the error.
        cron.execute()
        # Both patients were attempted.
        assert mock_get_membership.call_count == 2


# ---------------------------------------------------------------------------
# execute — successful charge
# ---------------------------------------------------------------------------

class TestExecuteSuccess:
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_charges_and_advances_date(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
        # Idempotency key includes the attempt counter (1 on first try) so
        # day-2 retries don't replay day-1's cached Stripe response.
        mock_processor.charge.assert_called_once_with(
            customer_id="cus_test123",
            amount_cents=9900,
            currency="usd",
            description="Membership: Gold (recurring)",
            payment_method_id="pm_test456",
            idempotency_key=f"portal_membership:patient-abc-123:{today_str}:attempt1",
        )
        saved = _get_update_kwargs(mock_membership_cls)
        # next_billing_date is written as a date object (targeted UPDATE) and
        # must be advanced past today.
        assert isinstance(saved["next_billing_date"], date)
        assert saved["next_billing_date"] != date.fromisoformat(today_str)
        assert saved["consecutive_failures"] == 0
        # retry_date is explicitly cleared on success.
        assert saved["retry_date"] is None

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_uses_plan_key_as_fallback_description(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_advance_by_cadence(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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

        saved = _get_update_kwargs(mock_membership_cls)
        assert saved["next_billing_date"] == date.fromisoformat(expected_next)

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_missing_cadence_falls_back_to_monthly(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
        saved = _get_update_kwargs(mock_membership_cls)
        assert saved["next_billing_date"] == date(2026, 6, 15)


# ---------------------------------------------------------------------------
# execute — first failure → retry scheduled
# ---------------------------------------------------------------------------

class TestExecuteFirstFailure:
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_first_failure_schedules_retry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
        saved = _get_update_kwargs(mock_membership_cls)
        assert saved["consecutive_failures"] == 1
        assert isinstance(saved["retry_date"], date)
        # Anchor preserved: the retry path does NOT write next_billing_date,
        # so the targeted UPDATE leaves the original billing day intact and
        # a later retry success advances the cadence from that anchor.
        assert "next_billing_date" not in saved

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_second_failure_schedules_another_retry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
        saved = _get_update_kwargs(mock_membership_cls)
        # The retry path doesn't touch status (still 'active' on the row);
        # the targeted UPDATE only writes consecutive_failures + retry_date.
        assert "status" not in saved
        assert saved["consecutive_failures"] == 2
        assert isinstance(saved["retry_date"], date)
        # Anchor preserved across retries — next_billing_date is never
        # rewritten on the failure path.
        assert "next_billing_date" not in saved


class TestCronTargetedUpdateInvariants:
    """Regression coverage for the targeted-UPDATE design.

    The cron must not write columns it didn't mean to mutate — otherwise a
    concurrent /update-payment-method or /cancel landing during the Stripe
    round-trip would be silently reverted by a full-row write.
    """

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_success_does_not_write_payment_method_id(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        """A successful cron charge must not touch payment_method_id /
        stripe_customer_id / status — otherwise a /update-payment-method
        racing with the cron's Stripe call would be silently reverted."""
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record
        mock_processor = MagicMock()
        mock_processor.charge.return_value = "pi_ok"
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        saved = _get_update_kwargs(mock_membership_cls)
        for protected in (
            "payment_method_id",
            "stripe_customer_id",
            "status",
            "plan",
            "plan_name",
            "amount_cents",
            "currency",
            "cadence",
            "billing_day",
        ):
            assert protected not in saved, (
                f"{protected!r} must not be written by _handle_success — "
                "the cron's targeted UPDATE is what protects concurrent "
                "patient-side writes from being clobbered."
            )

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_failure_retry_does_not_write_payment_method_id(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        """Critical: if the patient updates their card via
        /update-payment-method between cron attempts 1 and 2, the cron's
        failure-retry write must not revert payment_method_id to pm_old."""
        _set_due(mock_membership_cls, ["patient-abc-123"])
        mock_get_membership.return_value = active_record
        mock_processor = MagicMock()
        mock_processor.charge.side_effect = StripeError("Declined")
        mock_stripe_cls.return_value = mock_processor

        cron = _make_cron(secrets)
        cron.execute()

        saved = _get_update_kwargs(mock_membership_cls)
        assert "payment_method_id" not in saved

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_idempotency_key_varies_by_attempt(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        """The Idempotency-Key must include the attempt counter so a day-2
        retry doesn't replay Stripe's cached 402 from day 1."""
        keys_seen: list[str] = []
        for consecutive_failures in (0, 1, 2):
            active_record["consecutive_failures"] = consecutive_failures
            _set_due(mock_membership_cls, ["patient-abc-123"])
            mock_get_membership.return_value = active_record
            mock_processor = MagicMock()
            mock_processor.charge.side_effect = StripeError("Declined")
            mock_stripe_cls.return_value = mock_processor

            cron = _make_cron(secrets)
            cron.execute()

            keys_seen.append(mock_processor.charge.call_args.kwargs["idempotency_key"])

        # All three attempts produced distinct keys.
        assert len(set(keys_seen)) == 3
        assert keys_seen[0].endswith(":attempt1")
        assert keys_seen[1].endswith(":attempt2")
        assert keys_seen[2].endswith(":attempt3")


# ---------------------------------------------------------------------------
# execute — third failure → auto-cancel
# ---------------------------------------------------------------------------

class TestExecuteAutoCancel:
    @patch("portal_membership.protocols.billing_cron.resolve_team_id", return_value="team-uuid")
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_auto_cancel_after_third_failure(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
        _mock_resolve_team: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
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

        saved = _get_update_kwargs(mock_membership_cls)
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
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_percent_discount_reduces_charge_and_decrements_counter(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
        saved = _get_update_kwargs(mock_membership_cls)
        # Only the counter is written when the discount remains active —
        # discount_code/type/value are untouched (targeted UPDATE).
        assert saved["discount_cycles_remaining"] == 1  # was 2, decremented
        assert "discount_code" not in saved
        assert "discount_type" not in saved
        assert "discount_value" not in saved

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_last_discount_cycle_clears_fields(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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

        saved = _get_update_kwargs(mock_membership_cls)
        # Cleared discount writes empty strings / zeros so a stale
        # discount_code on the row never resurrects as a phantom.
        assert saved["discount_code"] == ""
        assert saved["discount_type"] == ""
        assert saved["discount_value"] == 0
        assert saved["discount_cycles_remaining"] == 0

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_100_percent_discount_skips_stripe(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
        saved = _get_update_kwargs(mock_membership_cls)
        # Still advances next_billing_date and decrements counter.
        assert saved["discount_cycles_remaining"] == 1

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_failed_discounted_charge_does_not_decrement_counter(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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

        saved = _get_update_kwargs(mock_membership_cls)
        # Failed retry path doesn't write discount columns at all — the
        # counter on the row stays at 2 by virtue of not being touched.
        assert "discount_cycles_remaining" not in saved
        assert saved["consecutive_failures"] == 1
        assert isinstance(saved["retry_date"], date)

    @patch("portal_membership.protocols.billing_cron.append_charge")
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_success_writes_succeeded_history_entry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_failed_charge_writes_failed_history_entry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_discount_code_preserved_in_final_history_entry(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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

        saved = _get_update_kwargs(mock_membership_cls)
        # Persisted record clears the discount fields to empty / zero.
        assert saved["discount_code"] == ""
        assert saved["discount_cycles_remaining"] == 0
        # … but the history entry still captures the code that was active.
        mock_append_charge.assert_called_once()
        assert mock_append_charge.call_args.kwargs["discount_code"] == "WELCOME10"

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_zero_discount_cycles_remaining_charges_full_price(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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

    @patch("portal_membership.protocols.billing_cron._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.billing_cron.get_membership")
    @patch("portal_membership.protocols.billing_cron.Membership")
    @patch("portal_membership.protocols.billing_cron.StripeProcessor")
    def test_auto_cancel_without_team_id(
        self,
        mock_stripe_cls: MagicMock,
        mock_membership_cls: MagicMock,
        mock_get_membership: MagicMock,
        _mock_resolve: MagicMock,
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
