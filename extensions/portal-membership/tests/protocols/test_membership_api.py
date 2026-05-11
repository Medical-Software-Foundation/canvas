"""Unit tests for MembershipPortalAPI (SimpleAPI handler)."""
import json
from datetime import date
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from portal_membership.payment_processor.stripe_processor import StripeError
from portal_membership.protocols.membership_api import (
    MembershipPortalAPI,
    _find_plan,
    _get_plans,
    _render_membership_page,
)
from portal_membership.utils.billing_cycle import next_billing_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(
    mock_event: MagicMock,
    secrets: dict[str, str],
    environment: dict[str, str] | None = None,
    method: str = "GET",
) -> MembershipPortalAPI:
    # SimpleAPI.__init__ reads event.context["method"] during construction.
    mock_event.context = {
        "method": method,
        "path": "/membership/plans",
        "headers": {"canvas-logged-in-user-id": "patient-abc-123"},
    }
    handler = MembershipPortalAPI(event=mock_event)
    handler.secrets = secrets
    handler.environment = environment or {}
    handler.request = MagicMock()
    return handler


# ---------------------------------------------------------------------------
# next_billing_iso (covers all cadences and end-of-month edges)
# ---------------------------------------------------------------------------

class TestNextBillingIso:
    def test_daily(self) -> None:
        assert next_billing_iso(date(2026, 3, 11), "daily") == "2026-03-12"

    def test_daily_month_rollover(self) -> None:
        assert next_billing_iso(date(2026, 3, 31), "daily") == "2026-04-01"

    def test_weekly(self) -> None:
        assert next_billing_iso(date(2026, 3, 11), "weekly") == "2026-03-18"

    def test_weekly_month_rollover(self) -> None:
        assert next_billing_iso(date(2026, 3, 28), "weekly") == "2026-04-04"

    def test_monthly_same_day(self) -> None:
        assert next_billing_iso(date(2026, 3, 11), "monthly") == "2026-04-11"

    def test_monthly_wraps_year(self) -> None:
        assert next_billing_iso(date(2026, 12, 5), "monthly") == "2027-01-05"

    def test_monthly_clamps_jan_31_to_feb_28(self) -> None:
        assert next_billing_iso(date(2026, 1, 31), "monthly") == "2026-02-28"

    def test_monthly_clamps_jan_31_to_feb_29_leap(self) -> None:
        # 2028 is a leap year — Feb 29 exists.
        assert next_billing_iso(date(2028, 1, 31), "monthly") == "2028-02-29"

    def test_monthly_march_31_to_april_30(self) -> None:
        assert next_billing_iso(date(2026, 3, 31), "monthly") == "2026-04-30"

    def test_quarterly_same_day_three_months_later(self) -> None:
        assert next_billing_iso(date(2026, 3, 11), "quarterly") == "2026-06-11"

    def test_quarterly_wraps_year(self) -> None:
        assert next_billing_iso(date(2026, 11, 15), "quarterly") == "2027-02-15"

    def test_quarterly_clamps_to_short_month(self) -> None:
        # Aug 31 + 3 months = Nov 30 (Nov has 30 days).
        assert next_billing_iso(date(2026, 8, 31), "quarterly") == "2026-11-30"

    def test_quarterly_nov_30_to_feb_28(self) -> None:
        assert next_billing_iso(date(2026, 11, 30), "quarterly") == "2027-02-28"

    def test_annually_same_day_next_year(self) -> None:
        assert next_billing_iso(date(2026, 3, 11), "annually") == "2027-03-11"

    def test_annually_leap_to_non_leap(self) -> None:
        # Feb 29, 2028 (leap) + 1 year → clamp to Feb 28, 2029.
        assert next_billing_iso(date(2028, 2, 29), "annually") == "2029-02-28"

    def test_unknown_cadence_falls_back_to_monthly(self) -> None:
        assert next_billing_iso(date(2026, 3, 11), "fortnightly") == "2026-04-11"

    def test_none_cadence_falls_back_to_monthly(self) -> None:
        assert next_billing_iso(date(2026, 3, 11), None) == "2026-04-11"

    def test_accepts_iso_string_input(self) -> None:
        assert next_billing_iso("2026-03-11", "weekly") == "2026-03-18"


# ---------------------------------------------------------------------------
# _get_plans / _find_plan
# ---------------------------------------------------------------------------

class TestPlanHelpers:
    def test_get_plans_parses_json(self, secrets: dict[str, str]) -> None:
        plans = _get_plans(secrets)
        assert len(plans) == 2
        assert plans[0]["key"] == "basic"

    def test_get_plans_empty_string(self) -> None:
        assert _get_plans({"MEMBERSHIP_PLANS": "[]"}) == []

    def test_get_plans_missing_key(self) -> None:
        assert _get_plans({}) == []

    def test_find_plan_found(self, secrets: dict[str, str]) -> None:
        plan = _find_plan(secrets, "gold")
        assert plan is not None
        assert plan["price_cents"] == 9900

    def test_find_plan_not_found(self, secrets: dict[str, str]) -> None:
        assert _find_plan(secrets, "platinum") is None


# ---------------------------------------------------------------------------
# GET /plans
# ---------------------------------------------------------------------------

class TestGetPlans:
    def test_returns_plans(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        results = handler.get_plans()
        assert len(results) == 1
        body = json.loads(results[0].content)
        assert "plans" in body
        assert len(body["plans"]) == 2


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------

class TestGetStatus:
    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_no_membership(self, mock_get: MagicMock, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        mock_get.return_value = None
        handler = _make_handler(mock_event, secrets)
        results = handler.get_status()
        body = json.loads(results[0].content)
        assert body["status"] == "none"

    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_active_membership(
        self,
        mock_get: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        mock_get.return_value = active_record
        handler = _make_handler(mock_event, secrets)
        results = handler.get_status()
        body = json.loads(results[0].content)
        assert body["status"] == "active"
        assert body["plan"] == "gold"
        assert body["next_billing_date"] == "2026-04-11"
        assert body["amount_cents"] == 9900

    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_cancelled_membership(
        self,
        mock_get: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        cancelled_record: dict[str, Any],
    ) -> None:
        mock_get.return_value = cancelled_record
        handler = _make_handler(mock_event, secrets)
        results = handler.get_status()
        body = json.loads(results[0].content)
        assert body["status"] == "cancelled"


# ---------------------------------------------------------------------------
# GET /page
# ---------------------------------------------------------------------------

class TestGetPage:
    @patch("portal_membership.protocols.membership_api.render_to_string")
    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_returns_html(
        self,
        mock_get: MagicMock,
        mock_render: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_get.return_value = None
        mock_render.return_value = "<html>rendered</html>"
        handler = _make_handler(mock_event, secrets, environment={"CUSTOMER_IDENTIFIER": "testclinic"})
        results = handler.get_page()
        assert results[0].status_code == HTTPStatus.OK
        template, context = mock_render.call_args.args
        assert template == "templates/membership_page.html"
        assert context["api_base"] == "https://testclinic.canvasmedical.com"
        assert context["status"] == "none"


# ---------------------------------------------------------------------------
# POST /signup
# ---------------------------------------------------------------------------

VALID_SIGNUP_BODY: dict[str, Any] = {
    "plan_key": "gold",
    "payment_method_id": "pm_test_123",
}


class TestPostSignup:
    def test_missing_plan_key(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"payment_method_id": "pm_test"}
        results = handler.post_signup()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    def test_missing_payment_method_id(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "gold"}
        results = handler.post_signup()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_plan(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "diamond", "payment_method_id": "pm_test"}
        results = handler.post_signup()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    def test_already_active(
        self,
        mock_claim: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("already_active", None)
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        results = handler.post_signup()
        assert results[0].status_code == HTTPStatus.CONFLICT

    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    def test_concurrent_signup_rejected(
        self,
        mock_claim: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """A second /signup while a pending_signup row exists returns 409."""
        mock_claim.return_value = ("in_progress", None)
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        results = handler.post_signup()
        assert results[0].status_code == HTTPStatus.CONFLICT
        body = json.loads(results[0].content)
        assert "in progress" in body["error"].lower()

    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_successful_signup(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_new"
        mock_processor.charge.return_value = "pi_new"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        results = handler.post_signup()

        # results: [banner_effect, JSONResponse]
        body = json.loads(results[-1].content)
        assert body["status"] == "ok"
        assert "next_billing_date" in body
        mock_processor.create_customer.assert_called_once_with(
            patient_id="patient-abc-123",
            payment_method_id="pm_test_123",
        )
        mock_processor.charge.assert_called_once()
        mock_set.assert_called_once()

    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_existing_cancelled_allowed(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """A previously-cancelled patient should be able to sign up fresh."""
        mock_claim.return_value = ("claimed", "cancelled")
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_new2"
        mock_processor.charge.return_value = "pi_new2"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "basic", "payment_method_id": "pm_new2"}
        results = handler.post_signup()

        resp_body = json.loads(results[-1].content)
        assert resp_body["status"] == "ok"

    @patch("portal_membership.protocols.membership_api.release_claim")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_stripe_error_returns_json(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_release: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """A StripeError during payment should return a JSON error, not a 500,
        and must release the signup claim so the patient can retry."""
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.side_effect = StripeError("Your card was declined.", http_status=402)
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        results = handler.post_signup()

        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(results[0].content)
        assert "Payment failed" in body["error"]
        # Verify Stripe error details are NOT leaked to the client
        assert "declined" not in body["error"]
        # Claim must be released with the original prior_status so the row
        # either gets deleted (None) or reverts to its original state.
        mock_release.assert_called_once_with("patient-abc-123", None)

    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_persists_plan_cadence(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_event: MagicMock,
    ) -> None:
        """Plan cadence is copied onto the record and used for next_billing_date."""
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_q"
        mock_stripe_cls.return_value = mock_processor
        custom_secrets = {
            "STRIPE_SECRET_KEY": "sk_test_fake",
            "MEMBERSHIP_PLANS": json.dumps(
                [{"key": "annual", "name": "Annual", "price_cents": 99900, "cadence": "annually"}]
            ),
            "BILLING_CURRENCY": "usd",
        }
        handler = _make_handler(mock_event, custom_secrets)
        handler.request.json.return_value = {"plan_key": "annual", "payment_method_id": "pm_x"}
        with patch("portal_membership.protocols.membership_api.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 15)
            mock_date.fromisoformat = date.fromisoformat
            handler.post_signup()
        saved = mock_set.call_args.args[1]
        assert saved["cadence"] == "annually"
        assert saved["next_billing_date"] == "2027-05-15"

    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_defaults_cadence_to_monthly_when_missing(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_m"
        mock_stripe_cls.return_value = mock_processor
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        handler.post_signup()
        saved = mock_set.call_args.args[1]
        assert saved["cadence"] == "monthly"

    def test_missing_stripe_key(self, mock_event: MagicMock) -> None:
        """Missing STRIPE_SECRET_KEY should return a 500, not crash."""
        secrets_no_stripe: dict[str, str] = {
            "MEMBERSHIP_PLANS": json.dumps([{"key": "gold", "name": "Gold", "price_cents": 9900}]),
        }
        handler = _make_handler(mock_event, secrets_no_stripe)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        results = handler.post_signup()
        assert results[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    @patch("portal_membership.protocols.membership_api.release_claim")
    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_db_write_failure_releases_claim(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_release: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """Stripe is already charged when set_membership runs. A DB blip
        here must release the claim and surface a contact-support 5xx so
        the patient doesn't retry and get double-billed, and so the
        pending_signup mutex row doesn't leak (permanent lockout)."""
        mock_claim.return_value = ("claimed", "cancelled")
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_paid"
        mock_processor.charge.return_value = "pi_paid"
        mock_stripe_cls.return_value = mock_processor
        mock_set.side_effect = Exception("transient DB error")

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        results = handler.post_signup()

        assert results[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        body = json.loads(results[0].content)
        assert "contact support" in body["error"].lower()
        # Stripe details must not leak.
        assert "transient DB error" not in body["error"]
        # Critical: release_claim must run so the patient isn't locked out.
        mock_release.assert_called_once_with("patient-abc-123", "cancelled")

    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_passes_idempotency_key(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """A stable per-day idempotency key is passed on the signup charge so
        Stripe dedupes if a transient post-charge failure triggers a retry."""
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_x"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        handler.post_signup()

        key = mock_processor.charge.call_args.kwargs["idempotency_key"]
        assert key.startswith("portal_membership:signup:patient-abc-123:")


# ---------------------------------------------------------------------------
# POST /signup — discount-code cases
# ---------------------------------------------------------------------------

class TestPostSignupWithDiscount:
    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_percent_discount_applied_to_charge(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_new"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {
            **VALID_SIGNUP_BODY,
            "discount_code": "WELCOME10",
        }
        results = handler.post_signup()

        body = json.loads(results[-1].content)
        assert body["status"] == "ok"
        # 10% off 9900 = 990 off → 8910 charged
        charge_kwargs = mock_processor.charge.call_args.kwargs
        assert charge_kwargs["amount_cents"] == 8910

        # Record keeps base price, captures discount terms, decrements months.
        saved_record = mock_set.call_args.args[1]
        assert saved_record["amount_cents"] == 9900
        assert saved_record["discount_code"] == "WELCOME10"
        assert saved_record["discount_type"] == "percent"
        assert saved_record["discount_value"] == 10
        assert saved_record["discount_cycles_remaining"] == 2  # 3 - signup

    @patch("portal_membership.protocols.membership_api.append_charge")
    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_fixed_discount_applied_to_charge(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_append_charge: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_new"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {
            **VALID_SIGNUP_BODY,
            "discount_code": "save20",  # lowercase — should still match
        }
        handler.post_signup()

        # $20 off $99 = $79 (7900 cents)
        assert mock_processor.charge.call_args.kwargs["amount_cents"] == 7900
        saved = mock_set.call_args.args[1]
        # months=1: signup consumes the only cycle, so the persisted record
        # should not retain the discount fields — otherwise /status, the
        # widget, and the page would surface a phantom code forever.
        for key in (
            "discount_code",
            "discount_type",
            "discount_value",
            "discount_cycles_remaining",
        ):
            assert key not in saved
        # The signup charge entry in history still attributes the discount.
        assert mock_append_charge.call_args.kwargs["discount_code"] == "SAVE20"

    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_100_percent_discount_skips_stripe_charge(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """A 100% code short-circuits the Stripe charge (Stripe rejects sub-$0.50)."""
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_free"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {
            **VALID_SIGNUP_BODY,
            "discount_code": "FREEMONTH",
        }
        results = handler.post_signup()

        assert json.loads(results[-1].content)["status"] == "ok"
        mock_processor.create_customer.assert_called_once()
        mock_processor.charge.assert_not_called()

    def test_invalid_discount_code_rejects_signup(
        self, mock_event: MagicMock, secrets: dict[str, str]
    ) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {**VALID_SIGNUP_BODY, "discount_code": "NOPE"}
        # No try_claim_signup mock needed — discount validation rejects before claim.
        results = handler.post_signup()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        assert "Invalid" in json.loads(results[0].content)["error"]


# ---------------------------------------------------------------------------
# POST /validate-code
# ---------------------------------------------------------------------------

class TestValidateCode:
    def test_valid_percent_preview(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "gold", "code": "welcome10"}
        results = handler.post_validate_code()
        body = json.loads(results[0].content)
        assert body["valid"] is True
        assert body["code"] == "WELCOME10"
        assert body["type"] == "percent"
        assert body["value"] == 10
        assert body["months"] == 3
        assert body["original_cents"] == 9900
        assert body["discounted_cents"] == 8910

    def test_valid_fixed_preview(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "gold", "code": "SAVE20"}
        results = handler.post_validate_code()
        body = json.loads(results[0].content)
        assert body["discounted_cents"] == 7900

    def test_returns_plan_cadence(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        """JS uses the cadence to render the duration label ("3 years" vs
        "3 months") — the response must surface it. Plans without an explicit
        cadence default to monthly."""
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "gold", "code": "WELCOME10"}
        body = json.loads(handler.post_validate_code()[0].content)
        assert body["cadence"] == "monthly"

    def test_returns_explicit_plan_cadence(
        self, mock_event: MagicMock, discount_codes: list[dict[str, Any]]
    ) -> None:
        """A plan declaring cadence='annually' should surface that in the
        preview so the JS can render '3 years' rather than '3 months'."""
        plans = [{"name": "Yearly", "key": "yearly", "price_cents": 99900, "cadence": "annually"}]
        secrets_yearly = {
            "STRIPE_SECRET_KEY": "sk_test_fake",
            "MEMBERSHIP_PLANS": json.dumps(plans),
            "DISCOUNT_CODES": json.dumps(discount_codes),
            "STAFF_OFFBOARDING_TEAM_ID": "team-uuid-999",
            "BILLING_CURRENCY": "usd",
        }
        handler = _make_handler(mock_event, secrets_yearly)
        handler.request.json.return_value = {"plan_key": "yearly", "code": "WELCOME10"}
        body = json.loads(handler.post_validate_code()[0].content)
        assert body["cadence"] == "annually"

    def test_unknown_plan(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "diamond", "code": "WELCOME10"}
        results = handler.post_validate_code()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_code(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "gold", "code": "NOPE"}
        results = handler.post_validate_code()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(results[0].content)
        assert body["valid"] is False


# ---------------------------------------------------------------------------
# GET /status — discount surfacing
# ---------------------------------------------------------------------------

class TestStatusWithDiscount:
    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_status_includes_discount_summary(
        self,
        mock_get: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        record = {
            **active_record,
            "discount_code": "WELCOME10",
            "discount_type": "percent",
            "discount_value": 10,
            "discount_cycles_remaining": 2,
        }
        mock_get.return_value = record
        handler = _make_handler(mock_event, secrets)
        results = handler.get_status()
        body = json.loads(results[0].content)
        assert body["discount"] == {
            "code": "WELCOME10",
            "type": "percent",
            "value": 10,
            "cycles_remaining": 2,
        }

    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_status_omits_discount_when_none(
        self,
        mock_get: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        mock_get.return_value = active_record
        handler = _make_handler(mock_event, secrets)
        results = handler.get_status()
        body = json.loads(results[0].content)
        assert "discount" not in body


# ---------------------------------------------------------------------------
# GET /history
# ---------------------------------------------------------------------------

class TestGetHistory:
    @patch("portal_membership.protocols.membership_api.get_charges")
    def test_no_charges_returns_empty(
        self, mock_get_charges: MagicMock, mock_event: MagicMock, secrets: dict[str, str]
    ) -> None:
        mock_get_charges.return_value = []
        handler = _make_handler(mock_event, secrets)
        results = handler.get_history()
        body = json.loads(results[0].content)
        assert body == {"charges": []}

    @patch("portal_membership.protocols.membership_api.get_charges")
    def test_returns_charges_newest_first(
        self,
        mock_get_charges: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_get_charges.return_value = [
            {"date": "2026-02-01", "amount_cents": 200, "status": "succeeded", "description": "B"},
            {"date": "2026-01-01", "amount_cents": 100, "status": "succeeded", "description": "A"},
        ]
        handler = _make_handler(mock_event, secrets)
        results = handler.get_history()
        body = json.loads(results[0].content)
        assert [c["description"] for c in body["charges"]] == ["B", "A"]
        mock_get_charges.assert_called_once_with("patient-abc-123")

    @patch("portal_membership.protocols.membership_api.append_charge")
    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_writes_history_entry(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_append_charge: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_new"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = VALID_SIGNUP_BODY
        handler.post_signup()

        mock_append_charge.assert_called_once()
        kwargs = mock_append_charge.call_args.kwargs
        assert kwargs["status"] == "succeeded"
        assert kwargs["amount_cents"] == 9900
        assert "signup" in kwargs["description"].lower()
        assert not kwargs.get("discount_code")

    @patch("portal_membership.protocols.membership_api.append_charge")
    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_signup_with_discount_records_code_in_history(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_append_charge: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("claimed", None)
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_new"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {**VALID_SIGNUP_BODY, "discount_code": "welcome10"}
        handler.post_signup()

        mock_append_charge.assert_called_once()
        kwargs = mock_append_charge.call_args.kwargs
        assert kwargs["discount_code"] == "WELCOME10"
        assert kwargs["amount_cents"] == 8910


# ---------------------------------------------------------------------------
# POST /cancel
# ---------------------------------------------------------------------------

class TestPostCancel:
    @patch("portal_membership.protocols.membership_api._resolve_patient_dbid", return_value=None)
    def test_no_active_membership(
        self, _mock_resolve: MagicMock, mock_event: MagicMock, secrets: dict[str, str]
    ) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {}
        results = handler.post_cancel()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("portal_membership.protocols.membership_api.Membership")
    @patch("portal_membership.protocols.membership_api._resolve_patient_dbid", return_value=1)
    def test_already_cancelled(
        self,
        _mock_resolve: MagicMock,
        mock_membership_cls: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        # Conditional UPDATE matches zero rows (membership is not active).
        mock_membership_cls.objects.filter.return_value.update.return_value = 0
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {}
        results = handler.post_cancel()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    def _arrange_cancel(
        self,
        mock_membership_cls: MagicMock,
        mock_get: MagicMock,
        active_record: dict,
    ) -> None:
        # Conditional UPDATE flips active → cancelled. Return 1 to indicate
        # the current worker won the race.
        mock_membership_cls.objects.filter.return_value.update.return_value = 1
        # Re-read after the UPDATE returns the cancelled record.
        cancelled = {**active_record, "status": "cancelled"}
        mock_get.return_value = cancelled

    @patch("portal_membership.protocols.membership_api.resolve_team_id", return_value="team-uuid")
    @patch("portal_membership.protocols.membership_api.Membership")
    @patch("portal_membership.protocols.membership_api._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_successful_cancel_returns_expected_effects(
        self,
        mock_get: MagicMock,
        _mock_resolve: MagicMock,
        mock_membership_cls: MagicMock,
        _mock_resolve_team: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        self._arrange_cancel(mock_membership_cls, mock_get, active_record)
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {}
        results = handler.post_cancel()

        # refreshed status banner, task, JSONResponse — no separate cancel banner
        assert len(results) == 3
        body = json.loads(results[-1].content)
        assert body["status"] == "ok"

        # The refreshed status banner should narrate the cancellation with
        # effective date, not leave the old "Active" banner stale on the chart.
        payloads = [str(getattr(r, "payload", "")) for r in results[:-1]]
        assert any("(Cancelled)" in p and "Effective:" in p for p in payloads)

    @patch("portal_membership.protocols.membership_api.Membership")
    @patch("portal_membership.protocols.membership_api._resolve_patient_dbid", return_value=1)
    def test_concurrent_cancel_only_one_emits_side_effects(
        self,
        _mock_resolve: MagicMock,
        mock_membership_cls: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """The losing worker in a /cancel race returns 404, so the staff
        queue gets exactly one off-boarding task per cancellation."""
        # The losing worker's UPDATE matches zero rows because the winning
        # worker already flipped status to 'cancelled'.
        mock_membership_cls.objects.filter.return_value.update.return_value = 0
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {}
        results = handler.post_cancel()
        assert len(results) == 1
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("portal_membership.protocols.membership_api.resolve_team_id", return_value="team-uuid")
    @patch("portal_membership.protocols.membership_api.Membership")
    @patch("portal_membership.protocols.membership_api._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_does_not_emit_legacy_cancelled_banner(
        self,
        mock_get: MagicMock,
        _mock_resolve: MagicMock,
        mock_membership_cls: MagicMock,
        _mock_resolve_team: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        """Regression: the separate 'Cancelled Membership' banner was removed —
        the status banner alone conveys the cancellation."""
        self._arrange_cancel(mock_membership_cls, mock_get, active_record)
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {}
        results = handler.post_cancel()

        payloads = [str(getattr(r, "payload", "")) for r in results]
        assert not any('"key": "membership-cancelled"' in p for p in payloads)

    @patch("portal_membership.protocols.membership_api.Membership")
    @patch("portal_membership.protocols.membership_api._resolve_patient_dbid", return_value=1)
    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_cancel_without_team_id(
        self,
        mock_get: MagicMock,
        _mock_resolve: MagicMock,
        mock_membership_cls: MagicMock,
        mock_event: MagicMock,
        active_record: dict[str, Any],
    ) -> None:
        """Cancel should still work when STAFF_OFFBOARDING_TEAM_ID is not set."""
        self._arrange_cancel(mock_membership_cls, mock_get, active_record)
        secrets_no_team: dict[str, str] = {
            "STRIPE_SECRET_KEY": "sk_test_fake",
            "MEMBERSHIP_PLANS": "[]",
            "BILLING_CURRENCY": "usd",
        }
        handler = _make_handler(mock_event, secrets_no_team)
        handler.request.json.return_value = {}
        results = handler.post_cancel()
        # refreshed status banner, task, JSONResponse
        assert len(results) == 3


# ---------------------------------------------------------------------------
# POST /restart
# ---------------------------------------------------------------------------

class TestPostRestart:
    def test_missing_plan_key(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"payment_method_id": "pm_test"}
        results = handler.post_restart()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    def test_missing_payment_method_id(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "gold"}
        results = handler.post_restart()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_plan(self, mock_event: MagicMock, secrets: dict[str, str]) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "platinum", "payment_method_id": "pm_test"}
        results = handler.post_restart()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("portal_membership.protocols.membership_api.set_membership")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_successful_restart(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_set: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        mock_claim.return_value = ("claimed", "cancelled")
        mock_processor = MagicMock()
        mock_processor.create_customer.return_value = "cus_restart"
        mock_processor.charge.return_value = "pi_restart"
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "basic", "payment_method_id": "pm_restart"}
        results = handler.post_restart()

        # RemoveBannerAlert.apply(), refreshed status banner, JSONResponse
        assert len(results) == 3
        resp_body = json.loads(results[-1].content)
        assert resp_body["status"] == "ok"
        assert "next_billing_date" in resp_body
        mock_processor.create_customer.assert_called_once()
        mock_set.assert_called_once()

    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    def test_restart_rejects_already_active(
        self,
        mock_claim: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """Restart against an already-active membership must 409 (no double charge)."""
        mock_claim.return_value = ("already_active", None)
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "basic", "payment_method_id": "pm_restart"}
        results = handler.post_restart()
        assert results[0].status_code == HTTPStatus.CONFLICT

    @patch("portal_membership.protocols.membership_api.release_claim")
    @patch("portal_membership.protocols.membership_api.try_claim_signup")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_restart_stripe_error_releases_claim(
        self,
        mock_stripe_cls: MagicMock,
        mock_claim: MagicMock,
        mock_release: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
    ) -> None:
        """A Stripe failure during restart must revert the pending claim to cancelled."""
        mock_claim.return_value = ("claimed", "cancelled")
        mock_processor = MagicMock()
        mock_processor.create_customer.side_effect = StripeError("declined", http_status=402)
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"plan_key": "basic", "payment_method_id": "pm_restart"}
        results = handler.post_restart()

        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        mock_release.assert_called_once_with("patient-abc-123", "cancelled")


# ---------------------------------------------------------------------------
# POST /update-payment-method
# ---------------------------------------------------------------------------

class TestPostUpdatePaymentMethod:
    def test_missing_payment_method_id(
        self, mock_event: MagicMock, secrets: dict[str, str]
    ) -> None:
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {}
        results = handler.post_update_payment_method()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_no_membership_returns_404(
        self, mock_get: MagicMock, mock_event: MagicMock, secrets: dict[str, str]
    ) -> None:
        mock_get.return_value = None
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"payment_method_id": "pm_new"}
        results = handler.post_update_payment_method()
        assert results[0].status_code == HTTPStatus.NOT_FOUND

    @patch("portal_membership.protocols.membership_api.get_membership")
    def test_missing_stripe_customer_on_record(
        self,
        mock_get: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        bad_record = dict(active_record)
        bad_record["stripe_customer_id"] = ""
        mock_get.return_value = bad_record
        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"payment_method_id": "pm_new"}
        results = handler.post_update_payment_method()
        assert results[0].status_code == HTTPStatus.BAD_REQUEST

    @patch("portal_membership.protocols.membership_api.Membership")
    @patch("portal_membership.protocols.membership_api._resolve_patient_dbid", return_value=42)
    @patch("portal_membership.protocols.membership_api.get_membership")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_successful_update(
        self,
        mock_stripe_cls: MagicMock,
        mock_get: MagicMock,
        _mock_resolve: MagicMock,
        mock_membership_cls: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        mock_get.return_value = active_record
        mock_processor = MagicMock()
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"payment_method_id": "pm_new_card"}
        results = handler.post_update_payment_method()

        body = json.loads(results[0].content)
        assert body["status"] == "ok"
        mock_processor.attach_payment_method.assert_called_once_with(
            customer_id=active_record["stripe_customer_id"],
            payment_method_id="pm_new_card",
        )
        # Targeted UPDATE writes only the one column the handler is meant to
        # change — no read-modify-write that could resurrect a stale status.
        mock_membership_cls.objects.filter.assert_called_once_with(patient_id=42)
        mock_membership_cls.objects.filter.return_value.update.assert_called_once_with(
            payment_method_id="pm_new_card"
        )

    @patch("portal_membership.protocols.membership_api.get_membership")
    @patch("portal_membership.protocols.membership_api.StripeProcessor")
    def test_stripe_error_returns_400_without_leaking_details(
        self,
        mock_stripe_cls: MagicMock,
        mock_get: MagicMock,
        mock_event: MagicMock,
        secrets: dict[str, str],
        active_record: dict[str, Any],
    ) -> None:
        mock_get.return_value = active_record
        mock_processor = MagicMock()
        mock_processor.attach_payment_method.side_effect = StripeError(
            "Your card was declined.", http_status=402
        )
        mock_stripe_cls.return_value = mock_processor

        handler = _make_handler(mock_event, secrets)
        handler.request.json.return_value = {"payment_method_id": "pm_bad"}
        results = handler.post_update_payment_method()

        assert results[0].status_code == HTTPStatus.BAD_REQUEST
        body = json.loads(results[0].content)
        assert "declined" not in body["error"]

    def test_missing_stripe_secret_returns_500(self, mock_event: MagicMock) -> None:
        secrets_no_stripe: dict[str, str] = {"MEMBERSHIP_PLANS": "[]"}
        handler = _make_handler(mock_event, secrets_no_stripe)
        handler.request.json.return_value = {"payment_method_id": "pm_new"}
        with patch(
            "portal_membership.protocols.membership_api.get_membership",
            return_value={"stripe_customer_id": "cus_abc"},
        ):
            results = handler.post_update_payment_method()
        assert results[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# _render_membership_page
# ---------------------------------------------------------------------------

class TestRenderMembershipPage:
    """The function delegates rendering to a Django template — the test
    surface is the context dict passed to ``render_to_string``."""

    @patch("portal_membership.protocols.membership_api.render_to_string")
    def _context(
        self,
        mock_render: MagicMock,
        plans: list[dict[str, Any]],
        record: dict[str, Any] | None,
        api_base: str = "",
        billing_currency: str = "usd",
    ) -> dict[str, Any]:
        mock_render.return_value = "<html />"
        _render_membership_page(
            plans=plans,
            record=record,
            api_base=api_base,
            billing_currency=billing_currency,
        )
        _, ctx = mock_render.call_args.args
        return ctx

    def test_no_enrollment(self, membership_plans: list[dict[str, Any]]) -> None:
        ctx = self._context(plans=membership_plans, record=None, api_base="https://test.canvasmedical.com")
        assert ctx["status"] == "none"
        assert ctx["api_base"] == "https://test.canvasmedical.com"
        assert any(p["key"] == "basic" for p in ctx["plan_options"])

    def test_active_status(
        self, membership_plans: list[dict[str, Any]], active_record: dict[str, Any]
    ) -> None:
        ctx = self._context(plans=membership_plans, record=active_record)
        assert ctx["status"] == "active"

    def test_cancelled_status(
        self, membership_plans: list[dict[str, Any]], cancelled_record: dict[str, Any]
    ) -> None:
        ctx = self._context(plans=membership_plans, record=cancelled_record)
        assert ctx["status"] == "cancelled"

    def test_plan_descriptions_json_keyed_by_plan_key(
        self, membership_plans: list[dict[str, Any]]
    ) -> None:
        ctx = self._context(plans=membership_plans, record=None)
        descriptions = json.loads(ctx["plan_descriptions_json"])
        for plan in membership_plans:
            assert plan["key"] in descriptions

    def test_plan_options_include_price_display_and_cadence(
        self, membership_plans: list[dict[str, Any]]
    ) -> None:
        ctx = self._context(plans=membership_plans, record=None)
        for option in ctx["plan_options"]:
            assert "price_display" in option
            assert "cadence_suffix" in option

    def test_usd_renders_dollar_sign(
        self, membership_plans: list[dict[str, Any]], active_record: dict[str, Any]
    ) -> None:
        active_record["currency"] = "usd"
        ctx = self._context(plans=membership_plans, record=active_record)
        assert ctx["currency_symbol"] == "$"
        assert ctx["amount_display"].startswith("$")
        for option in ctx["plan_options"]:
            assert option["price_display"].startswith("$")

    def test_non_usd_omits_dollar_sign(
        self, membership_plans: list[dict[str, Any]], active_record: dict[str, Any]
    ) -> None:
        """Match the behaviour of portal_widget / membership_card / admin_api:
        EUR/GBP/etc. render the bare amount, no leading ``$``."""
        active_record["currency"] = "eur"
        ctx = self._context(plans=membership_plans, record=active_record)
        assert ctx["currency_symbol"] == ""
        assert "$" not in ctx["amount_display"]
        for option in ctx["plan_options"]:
            assert "$" not in option["price_display"]

    def test_non_usd_signup_screen_uses_billing_currency_fallback(
        self, membership_plans: list[dict[str, Any]]
    ) -> None:
        """A not-yet-enrolled patient on a non-USD instance must see bare
        amounts on the plan dropdown — the BILLING_CURRENCY secret is the
        only signal available because there's no record yet."""
        ctx = self._context(
            plans=membership_plans, record=None, billing_currency="eur"
        )
        assert ctx["currency_symbol"] == ""
        for option in ctx["plan_options"]:
            assert "$" not in option["price_display"]
