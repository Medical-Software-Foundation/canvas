"""Stripe payment processor implementation using requests (no stripe SDK).

The Canvas plugin sandbox does not permit importing the ``stripe`` package.
This module reimplements the two required Stripe operations — create a
Customer and create a PaymentIntent — via the Stripe REST API using
``requests``, which is an allowed module.
"""
from typing import Any, cast

import requests

from portal_membership.payment_processor.base import PaymentProcessor

_STRIPE_API_BASE = "https://api.stripe.com/v1"

# (connect_timeout_seconds, read_timeout_seconds) passed to ``requests``.
# Prevents a hung Stripe call from tying up a plugin worker indefinitely —
# without this, a stalled TCP connection or slow Stripe response would block
# the request thread until the outer platform timeout fires (if any).
_STRIPE_TIMEOUT = (5, 30)


class StripeError(Exception):
    """Raised when the Stripe API returns a non-2xx response or an error body."""

    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


def _stripe_post(
    api_key: str,
    path: str,
    data: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """POST form-encoded data to the Stripe REST API.

    Args:
        api_key: Stripe secret key used for HTTP Basic auth.
        path: API path (e.g. ``/customers``).
        data: Form fields to include in the request body.
        idempotency_key: Optional ``Idempotency-Key`` header value. Stripe
            deduplicates calls bearing the same key for 24 hours, so a
            retried charge after a transient post-charge failure won't bill
            the patient twice. See ``billing_cron`` for the canonical
            ``{patient_id}-{next_billing_date}`` key shape.

    Returns:
        Parsed JSON response body.

    Raises:
        StripeError: For any failure — non-2xx response, error body, network
            timeout, connection/TLS error, or non-JSON response. Wrapping
            non-Stripe failures here keeps callers' ``except StripeError``
            handlers complete, so ``release_claim`` always runs and the
            ``pending_signup`` mutex row is never leaked on a transient
            Stripe blip.
    """
    url = f"{_STRIPE_API_BASE}{path}"
    headers: dict[str, str] = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        response = requests.post(
            url,
            auth=(api_key, ""),
            data=data,
            headers=headers or None,
            timeout=_STRIPE_TIMEOUT,
        )
        body: dict[str, Any] = response.json()
    except requests.RequestException as exc:
        raise StripeError(f"Stripe request failed: {exc}") from exc
    except ValueError as exc:
        # JSONDecodeError subclasses ValueError — happens when an upstream
        # proxy/CDN returns an HTML 502/503 page instead of JSON.
        raise StripeError(f"Stripe response was not valid JSON: {exc}") from exc
    if response.status_code >= 400 or "error" in body:
        error_msg = body.get("error", {}).get("message", response.text)
        raise StripeError(error_msg, http_status=response.status_code)
    return body


class StripeProcessor(PaymentProcessor):
    """Handles Stripe API calls for membership billing.

    Uses PaymentIntents (not Stripe Subscriptions) so the plugin controls
    the billing schedule via the Canvas CronTask rather than Stripe webhooks.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def create_customer(self, patient_id: str, payment_method_id: str, email: str = "") -> str:
        """Create a Stripe Customer, attach the payment method, and set it as the default.

        Args:
            patient_id: Canvas patient ID stored as customer metadata.
            payment_method_id: Stripe PaymentMethod ID (e.g. ``pm_xxx``) from the frontend.
            email: Optional patient email to associate with the Stripe customer.

        Returns:
            Stripe customer ID (e.g. ``cus_xxx``).
        """
        data: dict[str, Any] = {
            "metadata[canvas_patient_id]": patient_id,
            "payment_method": payment_method_id,
            "invoice_settings[default_payment_method]": payment_method_id,
        }
        if email:
            data["email"] = email
        customer = _stripe_post(self._api_key, "/customers", data)
        return cast(str, customer["id"])

    def attach_payment_method(
        self, customer_id: str, payment_method_id: str
    ) -> None:
        """Attach a new PaymentMethod to an existing Stripe customer and set it as default.

        Used when a patient updates their card on file (no charge collected).

        Args:
            customer_id: Stripe customer ID (``cus_xxx``).
            payment_method_id: Stripe PaymentMethod ID (``pm_xxx``) to attach.

        Raises:
            StripeError: If attach or default-PM update fails.
        """
        _stripe_post(
            self._api_key,
            f"/payment_methods/{payment_method_id}/attach",
            {"customer": customer_id},
        )
        _stripe_post(
            self._api_key,
            f"/customers/{customer_id}",
            {"invoice_settings[default_payment_method]": payment_method_id},
        )

    def charge(
        self,
        customer_id: str,
        amount_cents: int,
        currency: str,
        description: str,
        payment_method_id: str = "",
        idempotency_key: str | None = None,
    ) -> str:
        """Charge an existing Stripe customer.

        Args:
            customer_id: Stripe customer ID (``cus_xxx``).
            amount_cents: Amount to charge in the smallest currency unit (e.g. cents for USD).
            currency: ISO currency code (e.g. ``usd``).
            description: Human-readable description shown on the Stripe dashboard.
            payment_method_id: Explicit PaymentMethod ID to charge. Required for
                off-session PaymentIntents; the customer's
                ``invoice_settings.default_payment_method`` only applies to invoices.
            idempotency_key: Optional Stripe idempotency key. Callers that
                may retry a charge for the same billing event (cron retries,
                client resubmits) should pass a stable per-event key
                (e.g. ``{patient_id}-{next_billing_date}``) so Stripe
                deduplicates within its 24h window instead of creating a
                second PaymentIntent.

        Returns:
            Stripe PaymentIntent ID (``pi_xxx``).

        Raises:
            StripeError: If the charge fails for any reason.
        """
        data: dict[str, Any] = {
            "amount": str(amount_cents),
            "currency": currency,
            "customer": customer_id,
            "payment_method_types[]": "card",
            "confirm": "true",
            "off_session": "true",
            "description": description,
        }
        if payment_method_id:
            data["payment_method"] = payment_method_id
        intent = _stripe_post(
            self._api_key, "/payment_intents", data, idempotency_key=idempotency_key
        )
        return cast(str, intent["id"])
