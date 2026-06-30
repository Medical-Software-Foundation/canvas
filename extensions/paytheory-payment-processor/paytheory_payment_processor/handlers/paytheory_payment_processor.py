from decimal import Decimal
from typing import Any

from canvas_sdk.effects.payment_processor import (
    AddPaymentMethodResponse,
    CardTransaction,
    PaymentMethod,
    PaymentProcessorForm,
    RemovePaymentMethodResponse,
)
from canvas_sdk.handlers.payment_processors.card import (
    CardPaymentProcessor,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from logger import log
from paytheory_payment_processor.paytheory.api import PayorInput, PayTheoryAPI, TransactionInput
from paytheory_payment_processor.paytheory.environment import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_PARTNER,
    get_api_url,
    get_sdk_url,
)
from paytheory_payment_processor.paytheory.exceptions import TransactionError

# Statuses PayTheory may return for a charge that should be treated as successful.
# Settlement happens asynchronously, so PENDING/SETTLED are successes for booking
# purposes; SUCCESS and SUCCEEDED are both observed depending on the flow.
SUCCESS_STATUSES = frozenset({"SUCCESS", "SUCCEEDED", "PENDING", "SETTLED"})


class PayTheoryPaymentProcessor(CardPaymentProcessor):
    """Custom payment processor for handling credit card payments with PayTheory."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the PayTheory payment processor."""
        super().__init__(*args, **kwargs)
        partner = self.secrets.get("paytheory_partner", DEFAULT_PARTNER)
        environment = self.secrets.get("paytheory_environment", DEFAULT_ENVIRONMENT)

        api_url = get_api_url(partner, environment)
        self.sdk_url = get_sdk_url(partner, environment)

        log.info(f"PayTheory environment: partner={partner}, environment={environment}")
        log.info(f"PayTheory API URL: {api_url}")
        log.info(f"PayTheory SDK URL: {self.sdk_url}")

        self.api = PayTheoryAPI(
            api_key=self.secrets["paytheory_secret_key"],
            merchant_id=self.secrets["paytheory_merchant_id"],
            endpoint=api_url,
        )
        self.public_api_key = self.secrets["paytheory_public_key"]

    def payment_form(self, patient: Patient | None = None) -> PaymentProcessorForm:
        """Return the payment form for the credit card processor."""
        content = render_to_string(
            "templates/form.html",
            {
                "intent": self.PaymentIntent.PAY,
                "public_api_key": self.public_api_key,
                "sdk_url": self.sdk_url,
            },
        )

        return PaymentProcessorForm(content=content, intent=self.PaymentIntent.PAY)

    def add_card_form(self, patient: Patient | None = None) -> PaymentProcessorForm:
        """Return the form for adding a card."""
        payor_id = self.get_or_create_payor_id(patient)

        content = render_to_string(
            "templates/form.html",
            {
                "payor_id": payor_id,
                "intent": self.PaymentIntent.ADD_CARD,
                "public_api_key": self.public_api_key,
                "sdk_url": self.sdk_url,
            },
        )

        return PaymentProcessorForm(content=content, intent=self.PaymentIntent.ADD_CARD)

    def get_or_create_payor_id(self, patient: Patient | None = None) -> str | None:
        """Retrieve or create a payor_id based on the patient_id."""
        if not patient:
            return None

        payor_id = self.api.get_payor_id(patient.id)

        if not payor_id:
            self.api.create_payor(
                PayorInput(full_name=patient.full_name, metadata={"canvas_patient_id": patient.id})
            )
            # Re-fetch to handle race conditions where concurrent requests
            # both create a payor. Use the first one PayTheory indexed.
            payor_id = self.api.get_payor_id(patient.id)

        return payor_id

    def charge(
        self, amount: Decimal, token: str, patient: Patient | None = None, **kwargs: Any
    ) -> CardTransaction:
        """Charge the credit card using the PayTheory API."""
        try:
            transaction = self.api.create_transaction(
                TransactionInput(payment_method_id=token, amount=amount)
            )

            status = (transaction.get("status") or "").upper()
            success = status in SUCCESS_STATUSES
            # failure_reasons may be absent or an empty list; never index blindly.
            reasons = transaction.get("failure_reasons") or []
            error_code = (reasons[0] if reasons else status or "declined") if not success else None

            return CardTransaction(
                success=success,
                transaction_id=transaction["transaction_id"],
                api_response=transaction,
                error_code=error_code,
            )

        except TransactionError as ex:
            return CardTransaction(
                success=False,
                transaction_id=None,
                api_response=ex.api_response,
            )

    def payment_methods(self, patient: Patient | None = None) -> list[PaymentMethod]:
        """Return the payment methods for the card payment processor."""
        if not patient:
            return []

        payor_id = self.get_or_create_payor_id(patient)
        # payor creation can succeed while the re-fetch still returns None (PayTheory
        # indexing lag); never pass None to get_payment_methods (payor_id is String!).
        if not payor_id:
            return []

        payment_methods = self.api.get_payment_methods(payor_id=payor_id)

        return [self._to_payment_method(method) for method in payment_methods]

    @staticmethod
    def _to_payment_method(method: dict) -> PaymentMethod:
        """Map a PayTheory payment method to Canvas's PaymentMethod effect.

        Canvas's GraphQL schema treats these card fields as non-nullable, so we
        coerce every value to a string (or 0) — a None would make the Collect
        Payment modal error with "Cannot return null for ... postalCode".
        """
        exp_date = method.get("exp_date") or ""
        try:
            expiration_month = int(exp_date[:2]) if len(exp_date) >= 2 else 0
            expiration_year = int(f"20{exp_date[-2:]}") if len(exp_date) >= 2 else 0
        except ValueError:
            expiration_month = expiration_year = 0

        return PaymentMethod(
            payment_method_id=method.get("payment_method_id") or "",
            card_holder_name=method.get("full_name") or "",
            brand=method.get("card_brand") or "Card",
            postal_code=method.get("postal_code") or "",
            country=method.get("country") or "US",
            expiration_month=expiration_month,
            expiration_year=expiration_year,
            card_last_four_digits=method.get("last_four") or "",
        )

    def add_payment_method(
        self, token: str, patient: Patient, **kwargs: Any
    ) -> AddPaymentMethodResponse:
        """Add a new payment method for the patient."""
        return AddPaymentMethodResponse(success=True)

    def remove_payment_method(self, token, patient: Patient) -> RemovePaymentMethodResponse:
        """Remove a payment method for the patient."""
        payor_id = self.api.get_payor_id(patient.id)

        if not payor_id:
            log.warning(
                f"No payor_id found for patient {patient.id}, discarding remove_payment_method request."
            )
            return RemovePaymentMethodResponse(success=False)

        result = self.api.disable_payment_method(payment_method_id=token)

        return RemovePaymentMethodResponse(success=result)
