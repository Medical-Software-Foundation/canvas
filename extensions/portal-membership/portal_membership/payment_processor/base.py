"""Abstract base class for payment processors."""
from abc import ABC, abstractmethod


class PaymentProcessor(ABC):
    """Abstract interface for payment processing."""

    @abstractmethod
    def create_customer(self, patient_id: str, payment_method_id: str, email: str = "") -> str:
        """Create a payment customer and attach the payment method.

        The *payment_method_id* should be created client-side via the
        processor's JS SDK (e.g. Stripe Elements) — raw card details must
        never pass through the server.

        Returns the processor-specific customer ID.
        """
        ...

    @abstractmethod
    def charge(
        self,
        customer_id: str,
        amount_cents: int,
        currency: str,
        description: str,
        payment_method_id: str = "",
        idempotency_key: str | None = None,
    ) -> str:
        """Charge an existing customer.

        If *payment_method_id* is provided it is sent explicitly on the
        PaymentIntent; otherwise the processor falls back to the customer's
        default payment method. *idempotency_key* (if provided) lets the
        processor deduplicate retried charges so a transient failure
        between the charge and the local DB write doesn't double-bill.

        Returns the processor-specific payment/charge ID.
        Raises an exception if the charge fails.
        """
        ...
