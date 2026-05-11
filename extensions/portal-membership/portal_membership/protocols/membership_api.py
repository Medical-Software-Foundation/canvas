"""Patient portal API for membership sign-up, cancellation, and restart.

Endpoints (all require an authenticated patient portal session):
  GET  /membership/plans    — list available membership tiers
  GET  /membership/status   — current membership status for the logged-in patient
  POST /membership/signup   — enrol and charge upfront
  POST /membership/cancel   — cancel membership and trigger staff task + banner
  POST /membership/restart  — re-activate membership and clear the banner

Base URL:
  https://<instance>.canvasmedical.com/plugin-io/api/portal_membership/membership
"""
import json
from datetime import date
from http import HTTPStatus
from typing import Any, cast

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.effects.task import AddTask, TaskStatus
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from logger import log

from portal_membership.payment_processor.stripe_processor import StripeError, StripeProcessor
from portal_membership.protocols.membership_card import (
    _build_banner_effects as build_status_banner_effects,
)
from portal_membership.utils.billing_cycle import cadence_suffix, next_billing_iso
from portal_membership.utils.charge_history import append_charge, get_charges
from portal_membership.utils.discount import (
    apply_discount,
    build_record_fields as build_discount_fields,
    describe as describe_discount,
    find_code as find_discount_code,
)
from portal_membership.models import Membership
from portal_membership.utils.membership_store import (
    _resolve_patient_dbid,
    delete_membership,
    get_membership,
    release_claim,
    set_membership,
    try_claim_signup,
)
from portal_membership.utils.team_resolver import resolve_team_id

# Legacy banner key — a separate "Cancelled Membership" banner was placed
# on the chart before the status banner gained its own cancelled narrative.
# We no longer emit it, but we still clean up any stragglers on restart and
# on plugin redeploy.
LEGACY_CANCELLED_BANNER_KEY = "membership-cancelled"
MEMBERSHIP_PAGE_PATH = "/membership/page"


def _get_plans(secrets: dict[str, Any]) -> list[dict[Any, Any]]:
    """Parse the MEMBERSHIP_PLANS secret into a list of plan dicts."""
    raw = secrets.get("MEMBERSHIP_PLANS", "[]")
    return cast(list[dict[Any, Any]], json.loads(raw))


def _find_plan(secrets: dict[str, Any], plan_key: str) -> dict[Any, Any] | None:
    """Return the plan matching *plan_key*, or ``None``."""
    for plan in _get_plans(secrets):
        if plan.get("key") == plan_key:
            return plan
    return None


class MembershipPortalAPI(PatientSessionAuthMixin, SimpleAPI):
    """Patient-facing membership management API.

    Authentication is handled by ``PatientSessionAuthMixin``: only logged-in
    patients can access these endpoints.  Staff attempting to call these routes
    will receive a 401.
    """

    PREFIX = "/membership"

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------

    @api.get("/plans")
    def get_plans(self) -> list[Response | Effect]:
        """Return all configured membership tiers."""
        plans = _get_plans(self.secrets)
        return [JSONResponse({"plans": plans})]

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @api.get("/status")
    def get_status(self) -> list[Response | Effect]:
        """Return the membership status for the current patient."""
        patient_id = self._patient_id()
        record = get_membership(patient_id)
        if record is None:
            return [JSONResponse({"status": "none"})]
        payload: dict[str, Any] = {
            "status": record.get("status", "none"),
            "plan": record.get("plan"),
            "next_billing_date": record.get("next_billing_date"),
            "amount_cents": record.get("amount_cents"),
        }
        discount_summary = describe_discount(record)
        if discount_summary:
            payload["discount"] = discount_summary
        return [JSONResponse(payload)]

    # ------------------------------------------------------------------
    # Charge history
    # ------------------------------------------------------------------

    @api.get("/history")
    def get_history(self) -> list[Response | Effect]:
        """Return the patient's charge history, newest first.

        Each entry: ``{date, amount_cents, status, description, discount_code?}``.
        Stripe IDs and raw error messages are never exposed.
        """
        patient_id = self._patient_id()
        return [JSONResponse({"charges": get_charges(patient_id)})]

    # ------------------------------------------------------------------
    # Validate discount code (price preview)
    # ------------------------------------------------------------------

    @api.post("/validate-code")
    def post_validate_code(self) -> list[Response | Effect]:
        """Preview the discounted amount for a ``plan_key`` + ``code`` combo.

        Response:
          200 → {"valid": true, "code": ..., "original_cents": ..., "discounted_cents": ...,
                 "months": ..., "type": "percent"|"fixed", "value": ...}
          400 → {"valid": false, "error": "..."}
        """
        body = self.request.json()
        plan_key = body.get("plan_key")
        code = body.get("code", "")

        plan = _find_plan(self.secrets, plan_key)
        if plan is None:
            return [
                JSONResponse(
                    {"valid": False, "error": f"Unknown plan: {plan_key}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        entry = find_discount_code(self.secrets, code)
        if entry is None:
            return [
                JSONResponse(
                    {"valid": False, "error": "Invalid or expired code"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        original = int(plan["price_cents"])
        discounted = apply_discount(original, entry["type"], int(entry["value"]))
        # ``months`` is the practice-facing config field name but semantically
        # counts billing cycles. Returning the plan's cadence lets the JS
        # render the preview as "3 years" / "3 days" / "3 months" instead of
        # the misleading hardcoded "months" label.
        return [
            JSONResponse(
                {
                    "valid": True,
                    "code": str(entry["code"]).strip().upper(),
                    "type": entry["type"],
                    "value": int(entry["value"]),
                    "months": int(entry["months"]),
                    "cadence": plan.get("cadence") or "monthly",
                    "original_cents": original,
                    "discounted_cents": discounted,
                }
            )
        ]

    # ------------------------------------------------------------------
    # Portal UI page
    # ------------------------------------------------------------------

    @api.get("/page")
    def get_page(self) -> list[Response | Effect]:
        """Serve the membership management HTML page."""
        patient_id = self._patient_id()
        record = get_membership(patient_id)
        plans = _get_plans(self.secrets)
        instance = self.environment.get("CUSTOMER_IDENTIFIER", "")
        api_base = f"https://{instance}.canvasmedical.com" if instance else ""

        stripe_pub_key = self.secrets.get("STRIPE_PUBLISHABLE_KEY", "")
        html_content = _render_membership_page(
            plans=plans,
            record=record,
            api_base=api_base,
            stripe_publishable_key=stripe_pub_key,
        )
        return [HTMLResponse(html_content, status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------------
    # Signup
    # ------------------------------------------------------------------

    @api.post("/signup")
    def post_signup(self) -> list[Response | Effect]:
        """Enrol a patient in a membership plan.

        Expected JSON body::

            {
                "plan_key": "gold",
                "payment_method_id": "pm_xxx"
            }

        The ``payment_method_id`` must be created client-side via Stripe
        Elements — raw card details never touch the server.
        """
        patient_id = self._patient_id()
        body = self.request.json()

        plan_key = body.get("plan_key")
        payment_method_id = body.get("payment_method_id", "")
        discount_code_input = body.get("discount_code", "")

        if not plan_key or not payment_method_id:
            return [
                JSONResponse(
                    {"error": "plan_key and payment_method_id are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        plan = _find_plan(self.secrets, plan_key)
        if plan is None:
            return [
                JSONResponse(
                    {"error": f"Unknown plan: {plan_key}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        discount_entry = None
        if discount_code_input:
            discount_entry = find_discount_code(self.secrets, discount_code_input)
            if discount_entry is None:
                return [
                    JSONResponse(
                        {"error": "Invalid or expired discount code"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

        stripe_key = self.secrets.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            log.error("portal_membership: STRIPE_SECRET_KEY not configured")
            return [
                JSONResponse(
                    {"error": "Payment processing is not configured"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        # Atomic claim guards against duplicate Stripe customers + double
        # charges when two signup requests land concurrently for the same
        # patient. Must run before the Stripe calls; rolled back on failure.
        claim_result, prior_status = try_claim_signup(patient_id)
        if claim_result == "already_active":
            return [
                JSONResponse(
                    {"error": "Patient already has an active membership"},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]
        if claim_result == "in_progress":
            return [
                JSONResponse(
                    {"error": "A signup is already in progress for this patient"},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        processor = StripeProcessor(api_key=stripe_key)
        currency = self.secrets.get("BILLING_CURRENCY", "usd")
        base_amount = int(plan["price_cents"])
        charge_amount = (
            apply_discount(base_amount, discount_entry["type"], int(discount_entry["value"]))
            if discount_entry
            else base_amount
        )

        try:
            stripe_customer_id = processor.create_customer(
                patient_id=patient_id,
                payment_method_id=payment_method_id,
            )

            if charge_amount > 0:
                processor.charge(
                    customer_id=stripe_customer_id,
                    amount_cents=charge_amount,
                    currency=currency,
                    description=f"Membership: {plan['name']} (first payment)",
                    payment_method_id=payment_method_id,
                )
        except StripeError as exc:
            release_claim(patient_id, prior_status)
            log.warning(
                f"portal_membership: signup payment failed — patient={patient_id} "
                f"error={exc}"
            )
            return [
                JSONResponse(
                    {"error": "Payment failed. Please check your card details and try again."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(
            f"portal_membership: signup — patient={patient_id} plan={plan_key} "
            f"customer={stripe_customer_id}"
        )
        log.info(
            f"portal_membership: initial charge succeeded — patient={patient_id} "
            f"amount={charge_amount} {currency} (base={base_amount})"
        )

        today = date.today()
        cadence = plan.get("cadence") or "monthly"
        record: dict[str, Any] = {
            "plan": plan_key,
            "plan_name": plan["name"],
            "status": "active",
            "stripe_customer_id": stripe_customer_id,
            "payment_method_id": payment_method_id,
            "cadence": cadence,
            "next_billing_date": next_billing_iso(today, cadence),
            "billing_day": today.day,
            "amount_cents": base_amount,
            "currency": currency,
            "consecutive_failures": 0,
        }
        if discount_entry:
            fields = build_discount_fields(discount_entry)
            # Signup is cycle 1 — decrement remaining by one up front.
            fields["discount_cycles_remaining"] = max(0, fields["discount_cycles_remaining"] - 1)
            record.update(fields)
        # Snapshot the code for charge history before any cleanup below.
        applied_discount_code = record.get("discount_code")
        # If the discount is exhausted after this signup cycle, drop the
        # fields entirely so /status / widget / page don't surface a
        # phantom code with cycles_remaining=0 forever.
        if record.get("discount_cycles_remaining", 0) <= 0:
            for key in (
                "discount_code",
                "discount_type",
                "discount_value",
                "discount_cycles_remaining",
            ):
                record.pop(key, None)
        set_membership(patient_id, record)
        append_charge(
            patient_id,
            amount_cents=charge_amount,
            status="succeeded",
            description=f"Membership signup: {plan['name']}",
            discount_code=applied_discount_code,
        )

        # Refresh the chart status banner so the provider sees the new
        # active membership immediately — matches /cancel, /restart, and
        # the cron's auto-cancel path. Without this, the banner only
        # appears on the next PATIENT_UPDATED event or plugin redeploy.
        status_banner_effects = build_status_banner_effects(
            patient_id=patient_id, record=record
        )

        return [
            *status_banner_effects,
            JSONResponse(
                {
                    "status": "ok",
                    "message": f"Membership activated: {plan['name']}",
                    "next_billing_date": record["next_billing_date"],
                }
            ),
        ]

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    @api.post("/cancel")
    def post_cancel(self) -> list[Response | Effect]:
        """Cancel the patient's membership.

        Marks the membership as cancelled in the cache, places a banner on
        the patient chart, and creates a staff off-boarding task.  Access
        until end of period is preserved (the next_billing_date is retained
        so the cron skips charging but the patient keeps access until that
        date).
        """
        patient_id = self._patient_id()
        dbid = _resolve_patient_dbid(patient_id)
        if dbid is None:
            return [
                JSONResponse(
                    {"error": "No active membership found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        # DB-backed mutex: only the worker whose UPDATE flips the row from
        # 'active' to 'cancelled' emits the side effects. Without this guard,
        # two concurrent /cancel requests (double-click, two tabs, retried
        # POST) both pass the read-check and both fire AddTask, duplicating
        # the staff off-boarding task.
        updated = Membership.objects.filter(
            patient_id=dbid, status="active"
        ).update(status="cancelled")
        if updated != 1:
            return [
                JSONResponse(
                    {"error": "No active membership found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        record = get_membership(patient_id)
        if record is None:
            # The row vanished between the UPDATE and the re-read — defensive.
            return [
                JSONResponse(
                    {"error": "No active membership found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        log.info(f"portal_membership: cancelled — patient={patient_id}")

        # Refresh the status banner so the chart header reads
        # "Gold (Cancelled) · Effective: <date>" immediately. This is the
        # only banner we emit — no separate "Cancelled Membership" alert.
        status_banner_effects = build_status_banner_effects(
            patient_id=patient_id, record=record
        )

        team_id = resolve_team_id(self.secrets.get("STAFF_OFFBOARDING_TEAM_ID", ""))

        due = arrow.utcnow().shift(days=5).datetime
        task_kwargs: dict = {
            "patient_id": patient_id,
            "title": "Membership Cancelled - Off-board patient",
            "status": TaskStatus.OPEN,
            "due": due,
            "labels": ["membership", "offboarding"],
        }
        if team_id:
            task_kwargs["team_id"] = team_id

        return [
            *status_banner_effects,
            AddTask(**task_kwargs).apply(),
            JSONResponse(
                {
                    "status": "ok",
                    "message": "Membership cancelled",
                    "access_until": record.get("next_billing_date"),
                }
            ),
        ]

    # ------------------------------------------------------------------
    # Restart
    # ------------------------------------------------------------------

    @api.post("/restart")
    def post_restart(self) -> list[Response | Effect]:
        """Re-activate a cancelled membership.

        Expected JSON body::

            {
                "plan_key": "gold",
                "payment_method_id": "pm_xxx"
            }

        The ``payment_method_id`` must be created client-side via Stripe
        Elements.  A new upfront charge is collected, a new Stripe customer
        is created (to attach the fresh payment method), and the banner is
        cleared.
        """
        patient_id = self._patient_id()
        body = self.request.json()

        plan_key = body.get("plan_key")
        payment_method_id = body.get("payment_method_id", "")
        discount_code_input = body.get("discount_code", "")

        if not plan_key or not payment_method_id:
            return [
                JSONResponse(
                    {"error": "plan_key and payment_method_id are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        plan = _find_plan(self.secrets, plan_key)
        if plan is None:
            return [
                JSONResponse(
                    {"error": f"Unknown plan: {plan_key}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        discount_entry = None
        if discount_code_input:
            discount_entry = find_discount_code(self.secrets, discount_code_input)
            if discount_entry is None:
                return [
                    JSONResponse(
                        {"error": "Invalid or expired discount code"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]

        stripe_key = self.secrets.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            log.error("portal_membership: STRIPE_SECRET_KEY not configured")
            return [
                JSONResponse(
                    {"error": "Payment processing is not configured"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        # Same atomic claim the /signup path uses — prevents two concurrent
        # restart requests from creating duplicate Stripe customers. Also
        # rejects restarts against an already-active membership, which the
        # previous implementation silently double-charged.
        claim_result, prior_status = try_claim_signup(patient_id)
        if claim_result == "already_active":
            return [
                JSONResponse(
                    {"error": "Patient already has an active membership"},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]
        if claim_result == "in_progress":
            return [
                JSONResponse(
                    {"error": "A signup is already in progress for this patient"},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        processor = StripeProcessor(api_key=stripe_key)
        currency = self.secrets.get("BILLING_CURRENCY", "usd")
        base_amount = int(plan["price_cents"])
        charge_amount = (
            apply_discount(base_amount, discount_entry["type"], int(discount_entry["value"]))
            if discount_entry
            else base_amount
        )

        try:
            stripe_customer_id = processor.create_customer(
                patient_id=patient_id,
                payment_method_id=payment_method_id,
            )
            if charge_amount > 0:
                processor.charge(
                    customer_id=stripe_customer_id,
                    amount_cents=charge_amount,
                    currency=currency,
                    description=f"Membership: {plan['name']} (restart)",
                    payment_method_id=payment_method_id,
                )
        except StripeError as exc:
            release_claim(patient_id, prior_status)
            log.warning(
                f"portal_membership: restart payment failed — patient={patient_id} "
                f"error={exc}"
            )
            return [
                JSONResponse(
                    {"error": "Payment failed. Please check your card details and try again."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(
            f"portal_membership: restart charge succeeded — patient={patient_id} "
            f"plan={plan_key} amount={charge_amount} base={base_amount}"
        )

        today = date.today()
        cadence = plan.get("cadence") or "monthly"
        record: dict[str, Any] = {
            "plan": plan_key,
            "plan_name": plan["name"],
            "status": "active",
            "stripe_customer_id": stripe_customer_id,
            "payment_method_id": payment_method_id,
            "cadence": cadence,
            "next_billing_date": next_billing_iso(today, cadence),
            "billing_day": today.day,
            "amount_cents": base_amount,
            "currency": currency,
            "consecutive_failures": 0,
        }
        if discount_entry:
            fields = build_discount_fields(discount_entry)
            fields["discount_cycles_remaining"] = max(0, fields["discount_cycles_remaining"] - 1)
            record.update(fields)
        applied_discount_code = record.get("discount_code")
        if record.get("discount_cycles_remaining", 0) <= 0:
            for key in (
                "discount_code",
                "discount_type",
                "discount_value",
                "discount_cycles_remaining",
            ):
                record.pop(key, None)
        set_membership(patient_id, record)
        append_charge(
            patient_id,
            amount_cents=charge_amount,
            status="succeeded",
            description=f"Membership restart: {plan['name']}",
            discount_code=applied_discount_code,
        )

        # Clear any stale "Cancelled Membership" banner left over from older
        # plugin versions (harmless if none exists).
        remove_legacy_banner = RemoveBannerAlert(
            key=LEGACY_CANCELLED_BANNER_KEY,
            patient_id=patient_id,
        )

        # Refresh the status banner so the chart header reflects the new plan
        # (or renewed Active state) immediately.
        status_banner_effects = build_status_banner_effects(
            patient_id=patient_id, record=record
        )

        return [
            remove_legacy_banner.apply(),
            *status_banner_effects,
            JSONResponse(
                {
                    "status": "ok",
                    "message": f"Membership restarted: {plan['name']}",
                    "next_billing_date": record["next_billing_date"],
                }
            ),
        ]

    # ------------------------------------------------------------------
    # Update payment method
    # ------------------------------------------------------------------

    @api.post("/update-payment-method")
    def post_update_payment_method(self) -> list[Response | Effect]:
        """Replace the Stripe payment method on file for the patient.

        No charge is collected — the new PaymentMethod is attached to the
        existing Stripe customer and set as the default for the off-session
        recurring charges driven by the billing cron.

        Request body::

            {"payment_method_id": "pm_xxx"}

        Response:
          200 ``{"status": "ok"}``
          400 — missing pm_id, no membership on file, or Stripe declined
          500 — Stripe secret key not configured
        """
        patient_id = self._patient_id()
        body = self.request.json()
        payment_method_id = body.get("payment_method_id", "")

        if not payment_method_id:
            return [
                JSONResponse(
                    {"error": "payment_method_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        record = get_membership(patient_id)
        if record is None:
            return [
                JSONResponse(
                    {"error": "No membership found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        stripe_customer_id = record.get("stripe_customer_id")
        if not stripe_customer_id:
            return [
                JSONResponse(
                    {"error": "No Stripe customer on record"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        stripe_key = self.secrets.get("STRIPE_SECRET_KEY")
        if not stripe_key:
            log.error("portal_membership: STRIPE_SECRET_KEY not configured")
            return [
                JSONResponse(
                    {"error": "Payment processing is not configured"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        processor = StripeProcessor(api_key=stripe_key)
        try:
            processor.attach_payment_method(
                customer_id=stripe_customer_id,
                payment_method_id=payment_method_id,
            )
        except StripeError as exc:
            log.warning(
                f"portal_membership: update payment method failed — patient={patient_id} "
                f"error={exc}"
            )
            return [
                JSONResponse(
                    {"error": "Could not update card. Please check the details and try again."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        record["payment_method_id"] = payment_method_id
        set_membership(patient_id, record)
        log.info(
            f"portal_membership: payment method updated — patient={patient_id}"
        )

        return [JSONResponse({"status": "ok", "message": "Payment method updated."})]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _patient_id(self) -> str:
        """Extract the patient ID from the portal session.

        For SimpleAPI handlers the patient identity is provided via the
        ``canvas-logged-in-user-id`` request header, not the event context.
        """
        headers = self.event.context.get("headers", {})
        return cast(str, headers.get("canvas-logged-in-user-id", ""))


# ---------------------------------------------------------------------------
# HTML template renderer
# ---------------------------------------------------------------------------

def _render_membership_page(
    plans: list[dict],
    record: dict | None,
    api_base: str,
    stripe_publishable_key: str = "",
) -> str:
    """Return the membership management HTML page rendered from a template."""
    status = record.get("status", "none") if record else "none"
    current_plan_name = record.get("plan_name", "") if record else ""
    next_billing = record.get("next_billing_date", "") if record else ""
    amount_cents = record.get("amount_cents", 0) if record else 0
    currency = (record.get("currency") if record else None) or "usd"
    # Same idiom as portal_widget / membership_card / admin_api: USD shows
    # a leading "$"; non-USD currencies render the bare amount.
    currency_symbol = "$" if currency.lower() == "usd" else ""
    amount_display = f"{currency_symbol}{amount_cents / 100:.2f}" if amount_cents else ""
    record_cadence_suffix = cadence_suffix(record.get("cadence") if record else None)

    plan_options = [
        {
            "key": str(p.get("key", "")),
            "name": str(p.get("name", "")),
            "price_display": f"{currency_symbol}{p['price_cents'] / 100:.2f}",
            "cadence_suffix": cadence_suffix(p.get("cadence")),
        }
        for p in plans
    ]
    plan_descriptions = {
        str(p.get("key", "")): str(p.get("description", ""))
        for p in plans
    }
    # Embedded inside a <script> block, so guard against a description that
    # contains a literal ``</script>`` payload.
    plan_descriptions_json = json.dumps(plan_descriptions).replace("</", "<\\/")

    return render_to_string(
        "templates/membership_page.html",
        {
            "status": status,
            "status_label": status.capitalize(),
            "current_plan_name": current_plan_name,
            "next_billing": next_billing,
            "amount_display": amount_display,
            "record_cadence_suffix": record_cadence_suffix,
            "plan_options": plan_options,
            "plan_descriptions_json": plan_descriptions_json,
            "api_base": api_base,
            "stripe_publishable_key": stripe_publishable_key,
            "currency_symbol": currency_symbol,
        },
    )
