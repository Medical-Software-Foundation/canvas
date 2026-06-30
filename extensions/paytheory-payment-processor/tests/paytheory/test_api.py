from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from requests import RequestException

from paytheory_payment_processor.paytheory.api import (
    REQUEST_TIMEOUT_SECONDS,
    PayTheoryAPI,
    PayorInput,
    TransactionInput,
)
from paytheory_payment_processor.paytheory.exceptions import TransactionError

API_KEY = "test-api-key"
MERCHANT_ID = "test-merchant-id"
ENDPOINT = "https://api.test.paytheory.com/graphql"


@pytest.fixture
def api():
    return PayTheoryAPI(api_key=API_KEY, merchant_id=MERCHANT_ID, endpoint=ENDPOINT)


class TestInit:
    def test_stores_credentials(self, api):
        assert api.api_key == API_KEY
        assert api.merchant_id == MERCHANT_ID
        assert api.endpoint == ENDPOINT

    def test_headers(self, api):
        headers = api._headers
        assert headers == {
            "Authorization": f"{MERCHANT_ID};{API_KEY}",
            "Content-Type": "application/json",
        }


class TestPost:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_passes_timeout(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"createPayor": {"payor_id": "p-1"}}}
        mock_requests.post.return_value = mock_response

        api.create_payor(PayorInput(full_name="Test"))

        assert mock_requests.post.call_args.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_transport_error_raises_transaction_error(self, mock_requests, api):
        mock_requests.post.side_effect = RequestException("connection reset")

        with pytest.raises(TransactionError):
            api.create_payor(PayorInput(full_name="Test"))

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_non_json_body_tolerated(self, mock_requests, api):
        # A 502 returning an HTML body must not blow up on response.json().
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.json.side_effect = ValueError("no json")
        mock_response.text = "<html>Bad Gateway</html>"
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.create_payor(PayorInput(full_name="Test"))


class TestCreatePayor:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_success(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"createPayor": {"payor_id": "payor-123"}}}
        mock_requests.post.return_value = mock_response

        result = api.create_payor(PayorInput(full_name="John Doe"))

        assert result == "payor-123"
        assert mock_requests.post.call_count == 1
        posted_json = mock_requests.post.call_args.kwargs["json"]
        assert posted_json["variables"]["input"]["full_name"] == "John Doe"
        assert posted_json["variables"]["input"]["merchant_uid"] == MERCHANT_ID

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_serializes_metadata_dict(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"createPayor": {"payor_id": "payor-123"}}}
        mock_requests.post.return_value = mock_response

        api.create_payor(PayorInput(full_name="Test", metadata={"key": "value"}))

        posted_json = mock_requests.post.call_args.kwargs["json"]
        # metadata should have been serialized to a JSON string
        assert posted_json["variables"]["input"]["metadata"] == '{"key": "value"}'

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_raises(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"errors": [{"message": "bad request"}]}
        mock_response.text = '{"errors": [{"message": "bad request"}]}'
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.create_payor(PayorInput(full_name="Test"))

        assert mock_requests.post.call_count == 1

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_on_200_with_errors_key(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errors": [{"message": "validation error"}]}
        mock_response.text = '{"errors": [{"message": "validation error"}]}'
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.create_payor(PayorInput(full_name="Test"))


class TestGetOrCreateGuestPayor:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_returns_existing_guest_payor(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"payors": {"items": [{"payor_id": "guest-123"}]}}
        }
        mock_requests.post.return_value = mock_response

        result = api.get_or_create_guest_payor()

        assert result == "guest-123"
        assert mock_requests.post.call_count == 1

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_creates_guest_payor_when_none_exists(self, mock_requests, api):
        lookup_response = MagicMock()
        lookup_response.status_code = 200
        lookup_response.json.return_value = {"data": {"payors": {"items": []}}}

        create_response = MagicMock()
        create_response.status_code = 200
        create_response.json.return_value = {"data": {"createPayor": {"payor_id": "new-guest-123"}}}

        mock_requests.post.side_effect = [lookup_response, create_response]

        result = api.get_or_create_guest_payor()

        assert result == "new-guest-123"
        assert mock_requests.post.call_count == 2

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_raises(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"errors": [{"message": "server error"}]}
        mock_response.text = "server error"
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.get_or_create_guest_payor()


class TestGetPayorId:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_found(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"payors": {"items": [{"payor_id": "payor-456"}]}}
        }
        mock_requests.post.return_value = mock_response

        result = api.get_payor_id("patient-123")

        assert result == "payor-456"
        assert mock_requests.post.call_count == 1
        # patient_id is passed as a GraphQL variable, not interpolated into the query.
        posted_json = mock_requests.post.call_args.kwargs["json"]
        assert posted_json["variables"]["patient_id"] == "patient-123"
        assert "patient-123" not in posted_json["query"]
        assert "$patient_id: String!" in posted_json["query"]

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_not_found(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"payors": {"items": []}}}
        mock_requests.post.return_value = mock_response

        result = api.get_payor_id("patient-123")

        assert result is None

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_raises(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"errors": [{"message": "bad"}]}
        mock_response.text = "bad"
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.get_payor_id("patient-123")


class TestGetPaymentMethods:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_returns_methods(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "paymentMethodTokens": {
                    "items": [
                        {
                            "payment_method_id": "pm-1",
                            "card_brand": "VISA",
                            "exp_date": "1225",
                            "country": "US",
                            "full_name": "John Doe",
                            "is_active": True,
                            "last_four": "4242",
                            "postal_code": "12345",
                        }
                    ]
                }
            }
        }
        mock_requests.post.return_value = mock_response

        result = api.get_payment_methods("payor-123")

        assert len(result) == 1
        assert result[0]["payment_method_id"] == "pm-1"
        assert result[0]["card_brand"] == "VISA"

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_empty_list(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"paymentMethodTokens": {"items": []}}}
        mock_requests.post.return_value = mock_response

        result = api.get_payment_methods("payor-123")

        assert result == []

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_raises(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"errors": [{"message": "error"}]}
        mock_response.text = "error"
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.get_payment_methods("payor-123")


class TestGetPaymentMethod:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_found(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "paymentMethodTokens": {
                    "items": [
                        {
                            "payment_method_id": "pm-1",
                            "card_brand": "VISA",
                            "exp_date": "1225",
                            "country": "US",
                            "full_name": "Jane",
                            "is_active": True,
                            "last_four": "1234",
                            "postal_code": "99999",
                        }
                    ]
                }
            }
        }
        mock_requests.post.return_value = mock_response

        result = api.get_payment_method("pm-1", "payor-123")

        assert result is not None
        assert result["payment_method_id"] == "pm-1"

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_not_found(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"paymentMethodTokens": {"items": []}}}
        mock_requests.post.return_value = mock_response

        result = api.get_payment_method("pm-1", "payor-123")

        assert result is None

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_raises(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"errors": [{"message": "err"}]}
        mock_response.text = "err"
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.get_payment_method("pm-1", "payor-123")


class TestCreateTransaction:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_success(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "createTransaction": {
                    "transaction_id": "txn-123",
                    "status": "PENDING",
                    "account_code": "",
                    "currency": "USD",
                    "dispute_status": "",
                    "failure_reasons": [],
                    "fee_mode": "MERCHANT_FEE",
                    "fees": 0,
                    "gross_amount": 1000,
                    "is_settled": False,
                    "merchant_uid": MERCHANT_ID,
                    "metadata": None,
                    "net_amount": 1000,
                    "parent_id": None,
                    "payment_method": {"payment_method_id": "pm-1"},
                    "timezone": "UTC",
                    "transaction_date": "2026-01-01",
                    "transaction_type": "DEBIT",
                }
            }
        }
        mock_requests.post.return_value = mock_response

        result = api.create_transaction(
            TransactionInput(amount=Decimal("10.00"), payment_method_id="pm-1")
        )

        assert result["transaction_id"] == "txn-123"
        assert result["status"] == "PENDING"
        # Verify amount was converted to cents
        posted_json = mock_requests.post.call_args.kwargs["json"]
        assert posted_json["variables"]["amount"] == 1000

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_rounds_amount_correctly(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "createTransaction": {
                    "transaction_id": "txn-456",
                    "status": "PENDING",
                    "account_code": "",
                    "currency": "USD",
                    "dispute_status": "",
                    "failure_reasons": [],
                    "fee_mode": "MERCHANT_FEE",
                    "fees": 0,
                    "gross_amount": 193,
                    "is_settled": False,
                    "merchant_uid": MERCHANT_ID,
                    "metadata": None,
                    "net_amount": 193,
                    "parent_id": None,
                    "payment_method": {"payment_method_id": "pm-1"},
                    "timezone": "UTC",
                    "transaction_date": "2026-01-01",
                    "transaction_type": "DEBIT",
                }
            }
        }
        mock_requests.post.return_value = mock_response

        # Use a float amount that could cause rounding issues
        api.create_transaction(TransactionInput(amount=Decimal("1.93"), payment_method_id="pm-1"))

        posted_json = mock_requests.post.call_args.kwargs["json"]
        assert posted_json["variables"]["amount"] == 193

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_raises_transaction_error(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errors": [{"message": "insufficient funds"}]}
        mock_requests.post.return_value = mock_response

        with pytest.raises(TransactionError):
            api.create_transaction(
                TransactionInput(amount=Decimal("1.93"), payment_method_id="pm-1")
            )

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_serializes_metadata(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "createTransaction": {
                    "transaction_id": "txn-789",
                    "status": "PENDING",
                    "account_code": "",
                    "currency": "USD",
                    "dispute_status": "",
                    "failure_reasons": [],
                    "fee_mode": "MERCHANT_FEE",
                    "fees": 0,
                    "gross_amount": 100,
                    "is_settled": False,
                    "merchant_uid": MERCHANT_ID,
                    "metadata": None,
                    "net_amount": 100,
                    "parent_id": None,
                    "payment_method": {"payment_method_id": "pm-1"},
                    "timezone": "UTC",
                    "transaction_date": "2026-01-01",
                    "transaction_type": "DEBIT",
                }
            }
        }
        mock_requests.post.return_value = mock_response

        api.create_transaction(
            TransactionInput(
                amount=Decimal("1.00"),
                payment_method_id="pm-1",
                metadata={"order": "123"},
            )
        )

        assert mock_requests.post.call_count == 1
        # metadata must be sent as a JSON-encoded string (AWSJSON scalar).
        posted_json = mock_requests.post.call_args.kwargs["json"]
        assert posted_json["variables"]["metadata"] == '{"order": "123"}'
        assert "$metadata: AWSJSON" in posted_json["query"]

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_omits_metadata_when_not_provided(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"createTransaction": {"transaction_id": "t", "status": "PENDING"}}
        }
        mock_requests.post.return_value = mock_response

        api.create_transaction(TransactionInput(amount=Decimal("1.00"), payment_method_id="pm-1"))

        posted_json = mock_requests.post.call_args.kwargs["json"]
        assert posted_json["variables"]["metadata"] is None


class TestDisablePaymentMethod:
    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_success(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"updatePaymentMethodToDisabled": True}}
        mock_requests.post.return_value = mock_response

        result = api.disable_payment_method("pm-1")

        assert result is True
        assert mock_requests.post.call_count == 1

    @patch("paytheory_payment_processor.paytheory.api.requests")
    def test_error_raises(self, mock_requests, api):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"errors": [{"message": "error"}]}
        mock_response.text = "error"
        mock_requests.post.return_value = mock_response

        with pytest.raises(Exception, match="GraphQL error"):
            api.disable_payment_method("pm-1")
