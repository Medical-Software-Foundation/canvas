from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from paytheory_payment_processor.paytheory.exceptions import TransactionError


SECRETS = {
    "paytheory_merchant_id": "merchant-123",
    "paytheory_public_key": "pub-key-123",
    "paytheory_secret_key": "secret-key-123",
    "paytheory_partner": "canvas",
    "paytheory_environment": "sandbox",
}


@pytest.fixture
def mock_patient():
    patient = MagicMock()
    patient.id = "patient-abc"
    patient.full_name = "Jane Doe"
    return patient


@pytest.fixture
def processor():
    with (
        patch(
            "paytheory_payment_processor.handlers.paytheory_payment_processor.CardPaymentProcessor.__init__"
        ),
        patch(
            "paytheory_payment_processor.handlers.paytheory_payment_processor.PayTheoryAPI"
        ) as mock_api_class,
    ):
        from paytheory_payment_processor.handlers.paytheory_payment_processor import (
            PayTheoryPaymentProcessor,
        )

        instance = PayTheoryPaymentProcessor.__new__(PayTheoryPaymentProcessor)
        instance.secrets = SECRETS
        instance.__init__()

        assert mock_api_class.mock_calls == [
            call(
                api_key="secret-key-123",
                merchant_id="merchant-123",
                endpoint="https://api.canvas.paytheorystudy.com/graphql",
            )
        ]

        instance.api = mock_api_class.return_value
        return instance


class TestInit:
    def test_environment_urls(self, processor):
        assert processor.sdk_url == "https://canvas.sdk.paytheorystudy.com/index.js"
        assert processor.public_api_key == "pub-key-123"

    def test_default_environment(self):
        with (
            patch(
                "paytheory_payment_processor.handlers.paytheory_payment_processor.CardPaymentProcessor.__init__"
            ),
            patch(
                "paytheory_payment_processor.handlers.paytheory_payment_processor.PayTheoryAPI"
            ),
        ):
            from paytheory_payment_processor.handlers.paytheory_payment_processor import (
                PayTheoryPaymentProcessor,
            )

            instance = PayTheoryPaymentProcessor.__new__(PayTheoryPaymentProcessor)
            instance.secrets = {
                "paytheory_merchant_id": "m",
                "paytheory_public_key": "p",
                "paytheory_secret_key": "s",
            }
            instance.__init__()

            assert instance.sdk_url == "https://canvas.sdk.paytheory.com/index.js"


class TestPaymentForm:
    @patch("paytheory_payment_processor.handlers.paytheory_payment_processor.render_to_string")
    def test_returns_form(self, mock_render, processor):
        mock_render.return_value = "<html>form</html>"

        result = processor.payment_form()

        assert mock_render.mock_calls == [
            call(
                "templates/form.html",
                {
                    "intent": "pay",
                    "public_api_key": "pub-key-123",
                    "sdk_url": "https://canvas.sdk.paytheorystudy.com/index.js",
                },
            )
        ]
        assert result.content == "<html>form</html>"
        assert result.intent == "pay"


class TestAddCardForm:
    @patch("paytheory_payment_processor.handlers.paytheory_payment_processor.render_to_string")
    def test_returns_form_with_payor_id(self, mock_render, processor, mock_patient):
        mock_render.return_value = "<html>add card</html>"
        processor.api.get_payor_id.return_value = "payor-xyz"

        result = processor.add_card_form(mock_patient)

        assert processor.api.get_payor_id.mock_calls == [call(mock_patient.id)]
        assert mock_render.mock_calls == [
            call(
                "templates/form.html",
                {
                    "payor_id": "payor-xyz",
                    "intent": "add_card",
                    "public_api_key": "pub-key-123",
                    "sdk_url": "https://canvas.sdk.paytheorystudy.com/index.js",
                },
            )
        ]
        assert result.intent == "add_card"


class TestGetOrCreatePayorId:
    def test_returns_none_without_patient(self, processor):
        result = processor.get_or_create_payor_id(None)

        assert result is None
        assert processor.api.get_payor_id.mock_calls == []

    def test_returns_existing_payor(self, processor, mock_patient):
        processor.api.get_payor_id.return_value = "existing-payor"

        result = processor.get_or_create_payor_id(mock_patient)

        assert result == "existing-payor"
        assert processor.api.get_payor_id.mock_calls == [call("patient-abc")]
        assert processor.api.create_payor.mock_calls == []

    def test_creates_payor_when_not_found(self, processor, mock_patient):
        processor.api.get_payor_id.side_effect = [None, "new-payor"]
        processor.api.create_payor.return_value = "new-payor"

        result = processor.get_or_create_payor_id(mock_patient)

        assert result == "new-payor"
        assert processor.api.create_payor.mock_calls == [
            call({"full_name": "Jane Doe", "metadata": {"canvas_patient_id": "patient-abc"}})
        ]
        # Called twice: first lookup returns None, then re-fetch after create
        assert processor.api.get_payor_id.mock_calls == [
            call("patient-abc"),
            call("patient-abc"),
        ]


class TestCharge:
    def test_success_pending(self, processor):
        processor.api.create_transaction.return_value = {
            "status": "PENDING",
            "transaction_id": "txn-1",
            "failure_reasons": [],
        }

        result = processor.charge(Decimal("10.00"), "pm-token")

        assert result.success is True
        assert result.transaction_id == "txn-1"
        assert result.error_code is None

    def test_success_succeeded(self, processor):
        processor.api.create_transaction.return_value = {
            "status": "SUCCEEDED",
            "transaction_id": "txn-2",
            "failure_reasons": [],
        }

        result = processor.charge(Decimal("5.00"), "pm-token")

        assert result.success is True
        assert result.transaction_id == "txn-2"

    def test_success_status_success(self, processor):
        processor.api.create_transaction.return_value = {
            "status": "SUCCESS",
            "transaction_id": "txn-s",
            "failure_reasons": [],
        }

        result = processor.charge(Decimal("5.00"), "pm-token")

        assert result.success is True
        assert result.error_code is None

    def test_success_status_settled(self, processor):
        processor.api.create_transaction.return_value = {
            "status": "SETTLED",
            "transaction_id": "txn-st",
            "failure_reasons": [],
        }

        result = processor.charge(Decimal("5.00"), "pm-token")

        assert result.success is True

    def test_success_status_is_case_insensitive(self, processor):
        processor.api.create_transaction.return_value = {
            "status": "succeeded",
            "transaction_id": "txn-lc",
            "failure_reasons": [],
        }

        result = processor.charge(Decimal("5.00"), "pm-token")

        assert result.success is True

    def test_failure_status(self, processor):
        processor.api.create_transaction.return_value = {
            "status": "FAILED",
            "transaction_id": "txn-3",
            "failure_reasons": ["INSUFFICIENT_FUNDS"],
        }

        result = processor.charge(Decimal("1.93"), "pm-token")

        assert result.success is False
        assert result.error_code == "INSUFFICIENT_FUNDS"

    def test_failure_with_empty_reasons_falls_back_to_status(self, processor):
        # An empty failure_reasons list must not raise IndexError.
        processor.api.create_transaction.return_value = {
            "status": "DECLINED",
            "transaction_id": "txn-4",
            "failure_reasons": [],
        }

        result = processor.charge(Decimal("1.93"), "pm-token")

        assert result.success is False
        assert result.error_code == "DECLINED"

    def test_failure_with_missing_reasons_key(self, processor):
        # No failure_reasons key at all must not raise either.
        processor.api.create_transaction.return_value = {
            "status": "DECLINED",
            "transaction_id": "txn-5",
        }

        result = processor.charge(Decimal("1.93"), "pm-token")

        assert result.success is False
        assert result.error_code == "DECLINED"

    def test_transaction_error(self, processor):
        processor.api.create_transaction.side_effect = TransactionError(
            api_response={"errors": [{"message": "declined"}]}
        )

        result = processor.charge(Decimal("1.02"), "pm-token")

        assert result.success is False
        assert result.transaction_id is None
        assert result.api_response == {"errors": [{"message": "declined"}]}


class TestPaymentMethods:
    def test_returns_empty_without_patient(self, processor):
        result = processor.payment_methods(None)

        assert result == []
        assert processor.api.get_payor_id.mock_calls == []

    def test_returns_mapped_methods(self, processor, mock_patient):
        processor.api.get_payor_id.return_value = "payor-123"
        processor.api.get_payment_methods.return_value = [
            {
                "payment_method_id": "pm-1",
                "full_name": "Jane Doe",
                "card_brand": "VISA",
                "postal_code": "12345",
                "country": "US",
                "exp_date": "1225",
                "last_four": "4242",
                "is_active": True,
            }
        ]

        result = processor.payment_methods(mock_patient)

        assert len(result) == 1
        assert result[0].payment_method_id == "pm-1"
        assert result[0].brand == "VISA"
        assert result[0].expiration_month == 12
        assert result[0].expiration_year == 2025
        assert result[0].card_last_four_digits == "4242"

    def test_coerces_null_fields_to_empty_strings(self, processor, mock_patient):
        # Canvas's schema is non-nullable for these fields; None would error the
        # Collect Payment modal, so they must come back as "" / 0 defaults.
        processor.api.get_payor_id.return_value = "payor-123"
        processor.api.get_payment_methods.return_value = [
            {
                "payment_method_id": "pm-1",
                "full_name": None,
                "card_brand": None,
                "postal_code": None,
                "country": None,
                "exp_date": None,
                "last_four": None,
                "is_active": True,
            }
        ]

        result = processor.payment_methods(mock_patient)

        assert len(result) == 1
        method = result[0]
        assert method.card_holder_name == ""
        assert method.brand == "Card"
        assert method.postal_code == ""
        assert method.country == "US"
        assert method.expiration_month == 0
        assert method.expiration_year == 0
        assert method.card_last_four_digits == ""


class TestAddPaymentMethod:
    def test_returns_success(self, processor, mock_patient):
        result = processor.add_payment_method("token-1", mock_patient)

        assert result.success is True


class TestRemovePaymentMethod:
    def test_success(self, processor, mock_patient):
        processor.api.get_payor_id.return_value = "payor-123"
        processor.api.disable_payment_method.return_value = True

        result = processor.remove_payment_method("pm-1", mock_patient)

        assert result.success is True
        assert processor.api.disable_payment_method.mock_calls == [call(payment_method_id="pm-1")]

    def test_no_payor_returns_failure(self, processor, mock_patient):
        processor.api.get_payor_id.return_value = None

        result = processor.remove_payment_method("pm-1", mock_patient)

        assert result.success is False
        assert processor.api.disable_payment_method.mock_calls == []
