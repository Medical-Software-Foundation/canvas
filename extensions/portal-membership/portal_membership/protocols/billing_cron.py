"""Daily billing CronTask for recurring membership charges.

Runs at 09:00 UTC every day.  For each patient in the active-IDs index,
checks whether today is their ``next_billing_date`` and, if so, attempts to
charge them via Stripe.

On success, ``next_billing_date`` is advanced according to the membership's
``cadence`` (daily / weekly / monthly / quarterly / annually) — see
``utils/billing_cycle.py``.

Retry policy (3 total attempts, 1-day spacing between retries):
  Attempt 1 (on billing day):
    success  → advance next_billing_date, reset consecutive_failures = 0
    failure  → consecutive_failures becomes 1, schedule retry_date = today + 1 day.
               next_billing_date is preserved so the next successful charge
               advances from the patient's original billing anchor.

  Attempt 2 (on retry_date):
    success  → advance next_billing_date, reset consecutive_failures = 0
    failure  → consecutive_failures becomes 2, schedule another retry +1 day.

  Attempt 3 (on second retry_date):
    success  → advance next_billing_date, reset consecutive_failures = 0
    failure  → auto-cancel: status = "cancelled"; status banner refreshes
               via membership_card, plus an off-boarding AddTask.

The cron query matches ``Q(next_billing_date=today) | Q(retry_date=today)``,
so a single code path handles both normal billing and the retry grace period.
"""
from datetime import date

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.cron_task import CronTask
from logger import log

from django.db.models import Q

from portal_membership.models import Membership
from portal_membership.payment_processor.stripe_processor import StripeError, StripeProcessor
from portal_membership.protocols.membership_card import (
    _build_banner_effects as build_status_banner_effects,
)
from portal_membership.utils.billing_cycle import next_billing_iso
from portal_membership.utils.charge_history import append_charge
from portal_membership.utils.discount import apply_discount
from portal_membership.utils.membership_store import (
    get_membership,
    set_membership,
)
from portal_membership.utils.team_resolver import resolve_team_id

# Number of days to wait between retry attempts.
RETRY_DELAY_DAYS = 1

# Total billing attempts allowed before auto-cancel (initial + retries).
MAX_ATTEMPTS = 3


class MonthlyBillingCron(CronTask):
    """Fires daily at 09:00 UTC; charges members whose billing is due today."""

    # Run daily at 09:00 UTC.
    SCHEDULE = "0 9 * * *"

    def execute(self) -> list[Effect]:
        """Charge all active members whose billing or retry date is due.

        We match ``__lte=today`` (not ``=today``) so a missed cron run —
        deploy outage, infra incident, mid-loop exception — doesn't
        permanently strand members whose date matched the missed day.
        Success advances ``next_billing_date`` by exactly one cycle, so
        a member missed for N days catches up on the next run with one
        charge, not N.
        """
        today = date.today()
        due = Membership.objects.filter(status="active").filter(
            Q(next_billing_date__lte=today) | Q(retry_date__lte=today)
        )
        log.info(
            f"portal_membership billing_cron: running for {today.isoformat()}, "
            f"{due.count()} member(s) due"
        )

        effects: list[Effect] = []
        for instance in due.select_related("patient"):
            patient_id = str(instance.patient.id)
            # Isolate per-patient failures so one bad record can't abort the
            # whole batch (and skip every still-queued patient for the day).
            # The combination of __lte=today in the query and the Stripe
            # Idempotency-Key on the charge call means retried days don't
            # double-charge.
            try:
                record = get_membership(patient_id)
                if record is None:
                    # Shouldn't happen — we just queried it — but guard defensively.
                    continue
                log.info(
                    f"portal_membership billing_cron: billing due — patient={patient_id} "
                    f"amount={record.get('amount_cents')} {record.get('currency')}"
                )
                effects.extend(self._process_patient(patient_id, record))
            except Exception as exc:  # noqa: BLE001 — see comment above
                log.error(
                    f"portal_membership billing_cron: skipping patient={patient_id} "
                    f"after unhandled error: {type(exc).__name__}: {exc}"
                )
                continue
        return effects

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _process_patient(self, patient_id: str, record: dict) -> list[Effect]:
        """Attempt to charge a patient; handle success, retry, and auto-cancel."""
        stripe_key = self.secrets.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            log.error("portal_membership billing_cron: STRIPE_SECRET_KEY not configured")
            return []

        stripe_customer_id = record.get("stripe_customer_id")
        amount_cents = record.get("amount_cents")
        if not stripe_customer_id or not amount_cents:
            log.error(
                f"portal_membership billing_cron: missing stripe_customer_id or "
                f"amount_cents for patient={patient_id}, skipping"
            )
            return []

        processor = StripeProcessor(api_key=stripe_key)
        currency = record.get("currency", "usd")
        plan_name = record.get("plan_name", record.get("plan", "membership"))
        pm_id = record.get("payment_method_id", "")

        discount_applied = False
        charge_amount = amount_cents
        if record.get("discount_cycles_remaining", 0) > 0:
            charge_amount = apply_discount(
                amount_cents,
                record.get("discount_type"),
                record.get("discount_value"),
            )
            discount_applied = True

        charge_succeeded = False
        if charge_amount <= 0:
            # 100% discount — nothing to charge, treat as success.
            charge_succeeded = True
            log.info(
                f"portal_membership billing_cron: $0 charge (full discount) — "
                f"patient={patient_id} code={record.get('discount_code')}"
            )
        else:
            # Idempotency-Key on the (patient, billing-date) pair so a retried
            # cron run after a post-charge DB blip doesn't double-charge —
            # Stripe deduplicates on this header within a 24h window.
            idempotency_key = (
                f"portal_membership:{patient_id}:{record.get('next_billing_date')}"
            )
            try:
                processor.charge(
                    customer_id=stripe_customer_id,
                    amount_cents=charge_amount,
                    currency=currency,
                    description=f"Membership: {plan_name} (recurring)",
                    payment_method_id=pm_id,
                    idempotency_key=idempotency_key,
                )
                charge_succeeded = True
            except StripeError as exc:
                log.warning(
                    f"portal_membership billing_cron: charge failed — patient={patient_id} "
                    f"error={exc}"
                )

        if charge_succeeded:
            return self._handle_success(patient_id, record, charge_amount, discount_applied)

        consecutive_failures = record.get("consecutive_failures", 0) + 1
        if consecutive_failures >= MAX_ATTEMPTS:
            return self._handle_auto_cancel(patient_id, record, charge_amount)

        return self._handle_failure_with_retry(
            patient_id, record, consecutive_failures, charge_amount
        )

    def _handle_success(
        self,
        patient_id: str,
        record: dict,
        charge_amount: int,
        discount_applied: bool = False,
    ) -> list[Effect]:
        """Advance the billing date and reset the failure counter.

        If a discount was applied to this cycle, decrement its remaining cycles
        and clear the fields once exhausted so the record stays clean.
        """
        next_date = next_billing_iso(record["next_billing_date"], record.get("cadence"))
        plan_name = record.get("plan_name", record.get("plan", "membership"))
        record["next_billing_date"] = next_date
        record["consecutive_failures"] = 0
        record.pop("retry_date", None)
        # Snapshot discount_code for history before it may be cleared below.
        history_discount_code = record.get("discount_code") if discount_applied else None
        if discount_applied:
            remaining = record.get("discount_cycles_remaining", 0) - 1
            if remaining <= 0:
                for key in (
                    "discount_code",
                    "discount_type",
                    "discount_value",
                    "discount_cycles_remaining",
                ):
                    record.pop(key, None)
            else:
                record["discount_cycles_remaining"] = remaining
        set_membership(patient_id, record)
        append_charge(
            patient_id,
            amount_cents=charge_amount,
            status="succeeded",
            description=f"Recurring charge: {plan_name}",
            discount_code=history_discount_code,
        )
        log.info(
            f"portal_membership billing_cron: charge succeeded — patient={patient_id} "
            f"next_billing_date={next_date}"
        )
        return []

    def _handle_failure_with_retry(
        self,
        patient_id: str,
        record: dict,
        consecutive_failures: int,
        charge_amount: int,
    ) -> list[Effect]:
        """Schedule the next retry and retain the current billing period.

        ``next_billing_date`` is preserved as-is so that when a retry succeeds
        ``_handle_success`` advances the cadence from the patient's original
        billing anchor — without this the anchor would drift forward by one
        day per retried recovery (see PR #243 review).
        """
        retry_date = arrow.utcnow().shift(days=RETRY_DELAY_DAYS).date().isoformat()
        plan_name = record.get("plan_name", record.get("plan", "membership"))
        record["consecutive_failures"] = consecutive_failures
        record["retry_date"] = retry_date
        set_membership(patient_id, record)
        append_charge(
            patient_id,
            amount_cents=charge_amount,
            status="failed",
            description=(
                f"Recurring charge failed: {plan_name} "
                f"(attempt {consecutive_failures} of {MAX_ATTEMPTS}, retry scheduled)"
            ),
            discount_code=record.get("discount_code"),
        )
        log.warning(
            f"portal_membership billing_cron: failure {consecutive_failures}/{MAX_ATTEMPTS} — "
            f"patient={patient_id} retry_date={retry_date}"
        )
        return []

    def _handle_auto_cancel(
        self, patient_id: str, record: dict, charge_amount: int
    ) -> list[Effect]:
        """Auto-cancel after the final failed attempt; emit banner + staff task."""
        plan_name = record.get("plan_name", record.get("plan", "membership"))
        record["status"] = "cancelled"
        record["consecutive_failures"] = 0
        set_membership(patient_id, record)
        append_charge(
            patient_id,
            amount_cents=charge_amount,
            status="failed",
            description=f"Recurring charge failed: {plan_name} (auto-cancelled)",
            discount_code=record.get("discount_code"),
        )
        log.warning(
            f"portal_membership billing_cron: auto-cancelled — patient={patient_id} "
            f"after {MAX_ATTEMPTS} consecutive charge failures"
        )

        team_id = resolve_team_id(self.secrets.get("STAFF_OFFBOARDING_TEAM_ID", ""))

        due = arrow.utcnow().shift(days=5).datetime
        task_kwargs: dict = {
            "patient_id": patient_id,
            "title": "Membership Auto-Cancelled (payment failure) - Off-board patient",
            "status": TaskStatus.OPEN,
            "due": due,
            "labels": ["membership", "offboarding", "payment-failure"],
        }
        if team_id:
            task_kwargs["team_id"] = team_id

        # Refresh the status banner to reflect the auto-cancel immediately.
        status_banner_effects = build_status_banner_effects(
            patient_id=patient_id, record=record
        )

        return [*status_banner_effects, AddTask(**task_kwargs).apply()]


