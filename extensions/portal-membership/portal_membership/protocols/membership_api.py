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
from canvas_sdk.v1.data.team import Team
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
from portal_membership.utils.membership_store import (
    delete_membership,
    get_membership,
    release_claim,
    set_membership,
    try_claim_signup,
)

# Legacy banner key — a separate "Cancelled Membership" banner was placed
# on the chart before the status banner gained its own cancelled narrative.
# We no longer emit it, but we still clean up any stragglers on restart and
# on plugin redeploy.
LEGACY_CANCELLED_BANNER_KEY = "membership-cancelled"
MEMBERSHIP_PAGE_PATH = "/membership/page"


def _resolve_team_id(raw_id: str) -> str:
    """Validate a team ID against the database, trying both hyphenated and bare UUID formats.

    Returns the valid ID string if found, or empty string if not.
    """
    if not raw_id:
        return ""

    # Try the value as a team ID first.
    if Team.objects.filter(id=raw_id).exists():
        return raw_id

    # Try without hyphens (Canvas sometimes stores bare UUIDs).
    alt_id = raw_id.replace("-", "")
    if alt_id != raw_id and Team.objects.filter(id=alt_id).exists():
        return alt_id

    # Fall back to treating the value as a team name.
    team_by_name = Team.objects.filter(name__iexact=raw_id).first()
    if team_by_name:
        resolved = str(team_by_name.id)
        log.info(f"portal_membership: resolved team name {raw_id!r} to ID {resolved}")
        return resolved

    log.warning(
        f"portal_membership: STAFF_OFFBOARDING_TEAM_ID={raw_id} "
        "not found by ID or name, creating task without team assignment"
    )
    return ""


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
        return [
            JSONResponse(
                {
                    "valid": True,
                    "code": str(entry["code"]).strip().upper(),
                    "type": entry["type"],
                    "value": int(entry["value"]),
                    "months": int(entry["months"]),
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
        set_membership(patient_id, record)
        append_charge(
            patient_id,
            amount_cents=charge_amount,
            status="succeeded",
            description=f"Membership signup: {plan['name']}",
            discount_code=record.get("discount_code"),
        )

        return [
            JSONResponse(
                {
                    "status": "ok",
                    "message": f"Membership activated: {plan['name']}",
                    "next_billing_date": record["next_billing_date"],
                }
            )
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
        record = get_membership(patient_id)

        if record is None or record.get("status") != "active":
            return [
                JSONResponse(
                    {"error": "No active membership found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        record["status"] = "cancelled"
        set_membership(patient_id, record)

        log.info(f"portal_membership: cancelled — patient={patient_id}")

        # Refresh the status banner so the chart header reads
        # "Gold (Cancelled) · Effective: <date>" immediately. This is the
        # only banner we emit — no separate "Cancelled Membership" alert.
        status_banner_effects = build_status_banner_effects(
            patient_id=patient_id, record=record
        )

        team_id = _resolve_team_id(self.secrets.get("STAFF_OFFBOARDING_TEAM_ID", ""))

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
        set_membership(patient_id, record)
        append_charge(
            patient_id,
            amount_cents=charge_amount,
            status="succeeded",
            description=f"Membership restart: {plan['name']}",
            discount_code=record.get("discount_code"),
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

def _esc(value: str) -> str:
    """Minimal HTML-escape without the stdlib ``html`` module (not allowed in sandbox)."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _render_membership_page(
    plans: list[dict],
    record: dict | None,
    api_base: str,
    stripe_publishable_key: str = "",
) -> str:
    """Return a self-contained HTML page for membership management."""
    status = record.get("status", "none") if record else "none"
    current_plan_name = record.get("plan_name", "") if record else ""
    next_billing = record.get("next_billing_date", "") if record else ""
    amount_cents = record.get("amount_cents", 0) if record else 0
    amount_display = f"${amount_cents / 100:.2f}" if amount_cents else ""
    record_cadence_suffix = cadence_suffix(record.get("cadence") if record else None)

    plans_options_html = "\n".join(
        f'<option value="{_esc(str(p["key"]))}">'
        f'${p["price_cents"] / 100:.2f}{cadence_suffix(p.get("cadence"))} — {_esc(str(p["name"]))}</option>'
        for p in plans
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Membership</title>
  <script src="https://js.stripe.com/v3/"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(135deg, #f5f7fa 0%, #e4e9f0 100%);
      color: #2d3748;
      padding: 1rem 1rem;
    }}
    .card {{
      background: #fff;
      border-radius: 16px;
      padding: 1.25rem 1.5rem;
      max-width: 720px;
      margin: 0 auto;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
    }}
    .enroll-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      align-items: start;
    }}
    .enroll-grid .enroll-actions {{
      grid-column: 1 / -1;
    }}
    @media (max-width: 540px) {{
      .enroll-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    h1 {{
      font-size: 1.2rem;
      font-weight: 700;
      margin-bottom: 0.5rem;
      color: #1a202c;
      letter-spacing: -0.01em;
    }}
    .status-badge {{
      display: inline-block;
      padding: 0.2rem 0.625rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      margin-bottom: 0.5rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .status-active {{ background: #c6f6d5; color: #22543d; }}
    .status-cancelled {{ background: #fed7d7; color: #9b2c2c; }}
    .status-none {{ background: #e2e8f0; color: #4a5568; }}
    .detail {{ font-size: 0.8rem; color: #718096; margin-bottom: 0.2rem; line-height: 1.4; }}
    .section {{ margin-top: 0.75rem; }}
    label {{
      display: block;
      font-size: 0.7rem;
      font-weight: 600;
      margin-bottom: 0.25rem;
      color: #4a5568;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    select {{
      width: 100%;
      padding: 0.45rem 0.75rem;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      font-size: 0.8rem;
      margin-bottom: 0.5rem;
      background: #fff;
      color: #2d3748;
      transition: border-color 0.15s, box-shadow 0.15s;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23718096' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 0.6rem center;
    }}
    select:focus {{ border-color: #667eea; box-shadow: 0 0 0 3px rgba(102,126,234,0.15); outline: none; }}
    .card-fields {{
      background: #f7fafc;
      border: 1.5px solid #e2e8f0;
      border-radius: 10px;
      padding: 0.75rem;
      margin-bottom: 0.5rem;
    }}
    .card-icon {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      margin-bottom: 0.5rem;
      color: #718096;
      font-size: 0.7rem;
    }}
    .card-icon svg {{ flex-shrink: 0; }}
    #card-element {{
      padding: 0.45rem 0.6rem;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      background: #fff;
      transition: border-color 0.15s, box-shadow 0.15s;
    }}
    #card-element.StripeElement--focus {{
      border-color: #667eea;
      box-shadow: 0 0 0 3px rgba(102,126,234,0.15);
    }}
    #card-errors {{
      color: #e53e3e;
      font-size: 0.7rem;
      margin-top: 0.25rem;
      min-height: 1rem;
    }}
    button {{
      width: 100%;
      padding: 0.6rem 0.875rem;
      border: none;
      border-radius: 10px;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
      letter-spacing: 0.01em;
    }}
    button:active {{ transform: scale(0.98); }}
    button:disabled {{ opacity: 0.6; cursor: not-allowed; }}
    .btn-primary {{
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: #fff;
      box-shadow: 0 2px 8px rgba(102,126,234,0.35);
    }}
    .btn-primary:hover:not(:disabled) {{
      box-shadow: 0 4px 14px rgba(102,126,234,0.45);
    }}
    .btn-danger {{
      background: #fff;
      color: #e53e3e;
      border: 1.5px solid #feb2b2;
      margin-top: 0.35rem;
    }}
    .btn-danger:hover {{ background: #fff5f5; }}
    .msg {{
      margin-top: 0.5rem;
      padding: 0.5rem 0.75rem;
      border-radius: 10px;
      font-size: 0.8rem;
      display: none;
      line-height: 1.3;
    }}
    .msg.success {{ background: #c6f6d5; color: #22543d; display: block; }}
    .msg.error {{ background: #fed7d7; color: #9b2c2c; display: block; }}
    .hidden {{ display: none !important; }}
    .divider {{ border: none; border-top: 1px solid #e2e8f0; margin: 0.75rem 0; }}
    .lock-note {{
      text-align: center;
      font-size: 0.65rem;
      color: #a0aec0;
      margin-top: 0.5rem;
    }}
    .lock-note svg {{ vertical-align: middle; margin-right: 0.2rem; }}
    .plan-desc {{
      font-size: 0.75rem;
      color: #718096;
      line-height: 1.4;
      min-height: 1rem;
    }}
    .promo-row {{ display: flex; gap: 0.4rem; margin-top: 0.25rem; }}
    .promo-row input {{
      flex: 1;
      padding: 0.45rem 0.75rem;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .promo-row input:focus {{ border-color: #667eea; box-shadow: 0 0 0 3px rgba(102,126,234,0.15); outline: none; }}
    .promo-row button {{
      width: auto;
      padding: 0.45rem 0.9rem;
      background: #edf2f7;
      color: #4a5568;
      font-size: 0.75rem;
    }}
    .promo-row button:hover:not(:disabled) {{ background: #e2e8f0; }}
    .promo-feedback {{
      font-size: 0.7rem;
      margin-top: 0.3rem;
      min-height: 1rem;
      line-height: 1.3;
    }}
    .promo-feedback.ok {{ color: #22543d; }}
    .promo-feedback.err {{ color: #9b2c2c; }}
    .update-card-toggle {{
      background: none;
      border: none;
      color: #667eea;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      padding: 0;
      width: auto;
      text-decoration: underline;
      text-underline-offset: 2px;
    }}
    .update-card-toggle:hover {{ color: #4c51bf; }}
    .update-card-form {{
      margin-top: 0.5rem;
      padding: 0.75rem;
      background: #f7fafc;
      border: 1.5px solid #e2e8f0;
      border-radius: 10px;
    }}
    #update-card-element {{
      padding: 0.45rem 0.6rem;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      background: #fff;
    }}
    #update-card-errors {{
      color: #e53e3e;
      font-size: 0.7rem;
      margin-top: 0.25rem;
      min-height: 1rem;
    }}
    .update-card-actions {{
      display: flex;
      gap: 0.4rem;
      margin-top: 0.5rem;
    }}
    .update-card-actions button {{
      width: auto;
      padding: 0.45rem 0.9rem;
      font-size: 0.75rem;
    }}
    .btn-neutral {{
      background: #edf2f7;
      color: #4a5568;
    }}
    .btn-neutral:hover {{ background: #e2e8f0; }}
    .tabs {{
      display: flex;
      gap: 0.25rem;
      border-bottom: 1.5px solid #e2e8f0;
      margin: 0 -1.5rem 0.75rem;
      padding: 0 1.5rem;
    }}
    .tab {{
      padding: 0.5rem 0.75rem;
      font-size: 0.8rem;
      font-weight: 600;
      color: #718096;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -1.5px;
      transition: color 0.15s, border-color 0.15s;
      background: none;
      border-top: none;
      border-left: none;
      border-right: none;
      width: auto;
      border-radius: 0;
    }}
    .tab:hover:not(.active) {{ color: #4a5568; }}
    .tab.active {{ color: #667eea; border-bottom-color: #667eea; }}
    .charges-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }}
    .charges-table th {{
      text-align: left;
      padding: 0.5rem 0.5rem;
      font-size: 0.68rem;
      font-weight: 600;
      color: #4a5568;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1.5px solid #e2e8f0;
    }}
    .charges-table td {{
      padding: 0.6rem 0.5rem;
      border-bottom: 1px solid #edf2f7;
      vertical-align: top;
    }}
    .charges-table tr:last-child td {{ border-bottom: none; }}
    .charges-amount {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
    .charges-status {{
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 999px;
      font-size: 0.65rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .charges-status.succeeded {{ background: #c6f6d5; color: #22543d; }}
    .charges-status.failed {{ background: #fed7d7; color: #9b2c2c; }}
    .charges-empty {{
      text-align: center;
      padding: 1.5rem 0.5rem;
      font-size: 0.8rem;
      color: #a0aec0;
    }}
    .charges-discount {{
      font-size: 0.7rem;
      color: #667eea;
      margin-top: 0.15rem;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Membership</h1>

    <div class="tabs" role="tablist">
      <button class="tab active" id="tabOverview" role="tab">Overview</button>
      <button class="tab" id="tabCharges" role="tab">Charges</button>
    </div>

    <div id="panelOverview" role="tabpanel">
    <div id="statusSection">
      <span class="status-badge status-{status}" id="statusBadge">{_esc(status.capitalize()) if status != "none" else "Not enrolled"}</span>
      <div class="detail" id="planDetail" {"hidden" if not current_plan_name else ""}>{_esc(current_plan_name)}</div>
      <div class="detail" id="billingDetail" {"hidden" if not next_billing else ""}>
        {"Next billing: " + _esc(next_billing) if status == "active" else ("Access until: " + _esc(next_billing) if next_billing else "")}
      </div>
      <div class="detail" id="amountDetail" {"hidden" if not amount_display else ""}>{_esc(amount_display)}{record_cadence_suffix}</div>
    </div>

    <!-- Shown when NOT enrolled or after cancellation to restart -->
    <div class="section{'' if status in ('none', 'cancelled') else ' hidden'}" id="enrollSection">
      <div class="enroll-grid">
        <div>
          <label for="planSelect">Select plan</label>
          <select id="planSelect">
            <option value="">-- choose a plan --</option>
            {plans_options_html}
          </select>
          <div class="plan-desc" id="planDesc">Select a plan to see what's included</div>

          <label for="promoInput" style="margin-top:0.5rem;">Discount code (optional)</label>
          <div class="promo-row">
            <input id="promoInput" type="text" placeholder="Enter code" autocomplete="off" />
            <button type="button" id="promoApplyBtn">Apply</button>
          </div>
          <div class="promo-feedback" id="promoFeedback"></div>
        </div>

        <div>
          <label>Payment details</label>
          <div class="card-fields">
            <div class="card-icon">
              <svg width="20" height="14" viewBox="0 0 20 14" fill="none"><rect x="0.5" y="0.5" width="19" height="13" rx="2.5" stroke="#a0aec0"/><rect y="3" width="20" height="3" fill="#a0aec0"/></svg>
              Credit or debit card
            </div>
            <div id="card-element"></div>
            <div id="card-errors" role="alert"></div>
          </div>
        </div>

        <div class="enroll-actions">
          <button class="btn-primary" id="enrollBtn"
                  {"style='display:none'" if status == "active" else ""}>
            {"Restart Membership" if status == "cancelled" else "Start Membership"}
          </button>
          <div class="lock-note">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M9 5V4a3 3 0 10-6 0v1a1.5 1.5 0 00-1.5 1.5v4A1.5 1.5 0 003 12h6a1.5 1.5 0 001.5-1.5v-4A1.5 1.5 0 009 5zM4.5 4a1.5 1.5 0 113 0v1h-3V4z" fill="#a0aec0"/></svg>
            Payments processed securely via Stripe
          </div>
        </div>
      </div>
    </div>

    <!-- Shown when active -->
    <div class="section{'' if status == 'active' else ' hidden'}" id="updateCardSection">
      <hr class="divider" />
      <button type="button" class="update-card-toggle" id="updateCardToggle">Update payment method</button>
      <div class="update-card-form hidden" id="updateCardForm">
        <label>New card</label>
        <div id="update-card-element"></div>
        <div id="update-card-errors" role="alert"></div>
        <div class="update-card-actions">
          <button class="btn-primary" id="updateCardSubmit">Save</button>
          <button class="btn-neutral" id="updateCardCancel">Cancel</button>
        </div>
      </div>
    </div>

    <div class="section{'' if status == 'active' else ' hidden'}" id="cancelSection">
      <hr class="divider" />
      <button class="btn-danger" onclick="cancelMembership()">Cancel Membership</button>
    </div>

    <div class="msg" id="message"></div>
    </div>  <!-- /panelOverview -->

    <div id="panelCharges" role="tabpanel" class="hidden">
      <div id="chargesLoading" class="charges-empty">Loading...</div>
      <table class="charges-table hidden" id="chargesTable">
        <thead>
          <tr>
            <th>Date</th>
            <th>Description</th>
            <th style="text-align:right;">Amount</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="chargesBody"></tbody>
      </table>
      <div id="chargesEmpty" class="charges-empty hidden">No charges yet.</div>
    </div>
  </div>

  <script>
    var API_BASE = {json.dumps(api_base)};
    var PLUGIN_PREFIX = API_BASE + "/plugin-io/api/portal_membership/membership";
    var STRIPE_PK = {json.dumps(stripe_publishable_key)};
    var PLAN_DESCRIPTIONS = {json.dumps({_esc(str(p.get("key", ""))): _esc(str(p.get("description", ""))) for p in plans})};

    /* Show plan description on selection change */
    (function() {{
      var sel = document.getElementById("planSelect");
      var desc = document.getElementById("planDesc");
      if (sel && desc) {{
        sel.addEventListener("change", function() {{
          desc.textContent = PLAN_DESCRIPTIONS[sel.value] || "Select a plan to see what's included";
        }});
      }}
    }})();

    /* Initialize Stripe Elements */
    var stripe = Stripe(STRIPE_PK);
    var elements = stripe.elements();
    var cardElement = elements.create("card", {{
      style: {{
        base: {{
          fontSize: "13px",
          color: "#2d3748",
          "::placeholder": {{ color: "#cbd5e0" }}
        }},
        invalid: {{ color: "#e53e3e" }}
      }}
    }});

    var cardMounted = false;
    var enrollSection = document.getElementById("enrollSection");
    if (enrollSection && !enrollSection.classList.contains("hidden")) {{
      cardElement.mount("#card-element");
      cardMounted = true;
    }}

    cardElement.on("change", function(event) {{
      var errEl = document.getElementById("card-errors");
      errEl.textContent = event.error ? event.error.message : "";
    }});

    function showMsg(text, type) {{
      var el = document.getElementById("message");
      el.textContent = text;
      el.className = "msg " + type;
    }}

    /* Track an applied discount code (null until validated) */
    var appliedCode = null;

    function formatCents(cents) {{
      return "$" + (cents / 100).toFixed(2);
    }}

    document.getElementById("promoApplyBtn").addEventListener("click", function() {{
      var code = document.getElementById("promoInput").value.trim();
      var feedback = document.getElementById("promoFeedback");
      var planKey = document.getElementById("planSelect").value;

      if (!code) {{
        appliedCode = null;
        feedback.className = "promo-feedback";
        feedback.textContent = "";
        return;
      }}
      if (!planKey) {{
        feedback.className = "promo-feedback err";
        feedback.textContent = "Select a plan first.";
        return;
      }}

      fetch(PLUGIN_PREFIX + "/validate-code", {{
        method: "POST",
        credentials: "include",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ plan_key: planKey, code: code }})
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (!data.valid) {{
          appliedCode = null;
          feedback.className = "promo-feedback err";
          feedback.textContent = data.error || "Invalid code.";
          return;
        }}
        appliedCode = data.code;
        var descr = data.type === "percent"
          ? (data.value + "% off")
          : (formatCents(data.value) + " off");
        feedback.className = "promo-feedback ok";
        feedback.textContent =
          "Applied " + data.code + " — " + descr + " for " + data.months
          + " month" + (data.months === 1 ? "" : "s")
          + " (first charge: " + formatCents(data.discounted_cents) + ")";
      }})
      .catch(function(e) {{
        appliedCode = null;
        feedback.className = "promo-feedback err";
        feedback.textContent = "Network error: " + e.message;
      }});
    }});

    /* Clear applied code if plan changes (price may differ) */
    document.getElementById("planSelect").addEventListener("change", function() {{
      if (appliedCode) {{
        appliedCode = null;
        var feedback = document.getElementById("promoFeedback");
        feedback.className = "promo-feedback";
        feedback.textContent = "Plan changed — re-apply code to confirm discount.";
      }}
    }});

    /* Create a Stripe PaymentMethod client-side, then send pm_id to server */
    document.getElementById("enrollBtn").addEventListener("click", function() {{
      var planKey = document.getElementById("planSelect").value;
      if (!planKey) {{ showMsg("Please select a plan.", "error"); return; }}

      var btn = document.getElementById("enrollBtn");
      var isRestart = btn.textContent.trim().indexOf("Restart") >= 0;
      var endpoint = isRestart ? "/restart" : "/signup";

      btn.disabled = true;
      btn.textContent = "Processing...";

      stripe.createPaymentMethod({{
        type: "card",
        card: cardElement
      }}).then(function(result) {{
        if (result.error) {{
          showMsg(result.error.message, "error");
          btn.disabled = false;
          btn.textContent = isRestart ? "Restart Membership" : "Start Membership";
          return;
        }}

        var payload = {{
          plan_key: planKey,
          payment_method_id: result.paymentMethod.id
        }};
        if (appliedCode) payload.discount_code = appliedCode;

        return fetch(PLUGIN_PREFIX + endpoint, {{
          method: "POST",
          credentials: "include",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload)
        }});
      }}).then(function(r) {{
        if (!r) return;
        return r.json();
      }}).then(function(data) {{
        if (!data) return;
        if (data.error) {{
          showMsg("Error: " + data.error, "error");
          btn.disabled = false;
          btn.textContent = isRestart ? "Restart Membership" : "Start Membership";
        }} else {{
          showMsg(data.message + " Next billing: " + (data.next_billing_date || ""), "success");
          setTimeout(function() {{ window.location.reload(); }}, 2000);
        }}
      }}).catch(function(e) {{
        showMsg("Network error: " + e.message, "error");
        btn.disabled = false;
        btn.textContent = isRestart ? "Restart Membership" : "Start Membership";
      }});
    }});

    /* Tabs */
    function escapeHtml(s) {{
      return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
    }}

    function renderCharges(charges) {{
      var tbody = document.getElementById("chargesBody");
      var table = document.getElementById("chargesTable");
      var empty = document.getElementById("chargesEmpty");
      var loading = document.getElementById("chargesLoading");
      loading.classList.add("hidden");
      if (!charges || charges.length === 0) {{
        empty.classList.remove("hidden");
        return;
      }}
      var rows = charges.map(function(c) {{
        var discountHtml = c.discount_code
          ? '<div class="charges-discount">' + escapeHtml(c.discount_code) + ' applied</div>'
          : '';
        return '<tr>'
          + '<td>' + escapeHtml(c.date || '') + '</td>'
          + '<td>' + escapeHtml(c.description || '') + discountHtml + '</td>'
          + '<td class="charges-amount">' + formatCents(c.amount_cents || 0) + '</td>'
          + '<td><span class="charges-status ' + escapeHtml(c.status || '') + '">'
          + escapeHtml(c.status || '') + '</span></td>'
          + '</tr>';
      }}).join('');
      tbody.innerHTML = rows;
      table.classList.remove("hidden");
    }}

    var chargesLoaded = false;
    function loadChargesIfNeeded() {{
      if (chargesLoaded) return;
      chargesLoaded = true;
      fetch(PLUGIN_PREFIX + "/history", {{ credentials: "include" }})
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{ renderCharges(data.charges || []); }})
        .catch(function() {{
          document.getElementById("chargesLoading").textContent = "Couldn't load charges.";
        }});
    }}

    function activateTab(which) {{
      var overviewTab = document.getElementById("tabOverview");
      var chargesTab = document.getElementById("tabCharges");
      var overviewPanel = document.getElementById("panelOverview");
      var chargesPanel = document.getElementById("panelCharges");
      if (which === "charges") {{
        overviewTab.classList.remove("active");
        chargesTab.classList.add("active");
        overviewPanel.classList.add("hidden");
        chargesPanel.classList.remove("hidden");
        loadChargesIfNeeded();
      }} else {{
        chargesTab.classList.remove("active");
        overviewTab.classList.add("active");
        chargesPanel.classList.add("hidden");
        overviewPanel.classList.remove("hidden");
      }}
    }}

    document.getElementById("tabOverview").addEventListener("click", function() {{ activateTab("overview"); }});
    document.getElementById("tabCharges").addEventListener("click", function() {{ activateTab("charges"); }});

    /* Deep-link: ?tab=charges opens the Charges tab on load. */
    (function activateFromQuery() {{
      var params = new URLSearchParams(window.location.search);
      if (params.get("tab") === "charges") {{
        activateTab("charges");
      }}
    }})();

    /* Update payment method — for active members only. */
    var updateCardToggle = document.getElementById("updateCardToggle");
    var updateCardForm = document.getElementById("updateCardForm");
    var updateCardElement = null;
    var updateCardMounted = false;

    if (updateCardToggle && updateCardForm) {{
      updateCardToggle.addEventListener("click", function() {{
        updateCardForm.classList.remove("hidden");
        updateCardToggle.style.display = "none";
        if (!updateCardMounted) {{
          updateCardElement = elements.create("card", {{
            style: {{
              base: {{
                fontSize: "13px",
                color: "#2d3748",
                "::placeholder": {{ color: "#cbd5e0" }}
              }},
              invalid: {{ color: "#e53e3e" }}
            }}
          }});
          updateCardElement.mount("#update-card-element");
          updateCardElement.on("change", function(event) {{
            var errEl = document.getElementById("update-card-errors");
            errEl.textContent = event.error ? event.error.message : "";
          }});
          updateCardMounted = true;
        }}
      }});

      document.getElementById("updateCardCancel").addEventListener("click", function() {{
        updateCardForm.classList.add("hidden");
        updateCardToggle.style.display = "";
      }});

      document.getElementById("updateCardSubmit").addEventListener("click", function() {{
        var btn = document.getElementById("updateCardSubmit");
        btn.disabled = true;
        btn.textContent = "Saving...";

        stripe.createPaymentMethod({{
          type: "card",
          card: updateCardElement
        }}).then(function(result) {{
          if (result.error) {{
            document.getElementById("update-card-errors").textContent = result.error.message;
            btn.disabled = false;
            btn.textContent = "Save";
            return;
          }}

          return fetch(PLUGIN_PREFIX + "/update-payment-method", {{
            method: "POST",
            credentials: "include",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ payment_method_id: result.paymentMethod.id }})
          }});
        }}).then(function(r) {{
          if (!r) return;
          return r.json();
        }}).then(function(data) {{
          if (!data) return;
          if (data.error) {{
            showMsg("Error: " + data.error, "error");
            btn.disabled = false;
            btn.textContent = "Save";
          }} else {{
            showMsg(data.message || "Payment method updated.", "success");
            setTimeout(function() {{ window.location.reload(); }}, 1500);
          }}
        }}).catch(function(e) {{
          showMsg("Network error: " + e.message, "error");
          btn.disabled = false;
          btn.textContent = "Save";
        }});
      }});
    }}

    function cancelMembership() {{
      if (!confirm("Are you sure you want to cancel your membership?")) return;
      fetch(PLUGIN_PREFIX + "/cancel", {{
        method: "POST",
        credentials: "include",
        headers: {{ "Content-Type": "application/json" }}
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (data.error) {{
          showMsg("Error: " + data.error, "error");
        }} else {{
          showMsg(data.message, "success");
          setTimeout(function() {{ window.location.reload(); }}, 2000);
        }}
      }})
      .catch(function(e) {{ showMsg("Network error: " + e.message, "error"); }});
    }}
  </script>
</body>
</html>"""
