"""Unit tests for StripeProcessor (mocks httpx calls)."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from portal_membership.payment_processor.stripe_processor import StripeError, StripeProcessor


@pytest.fixture
def processor() -> StripeProcessor:
    return StripeProcessor(api_key="sk_test_fake")


def _mock_response(status_code: int, body: dict) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = str(body)
    return resp


class TestCreateCustomer:
    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_returns_customer_id(self, mock_post: MagicMock, processor: StripeProcessor) -> None:
        mock_post.return_value = _mock_response(200, {"id": "cus_abc"})

        result = processor.create_customer(
            patient_id="patient-123",
            payment_method_id="pm_xyz",
        )

        assert result == "cus_abc"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"]["metadata[canvas_patient_id]"] == "patient-123"
        assert call_kwargs["data"]["payment_method"] == "pm_xyz"
        # A timeout must always be set so a hung Stripe call can't wedge a worker.
        assert call_kwargs["timeout"] is not None

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_passes_email_when_provided(self, mock_post: MagicMock, processor: StripeProcessor) -> None:
        mock_post.return_value = _mock_response(200, {"id": "cus_with_email"})

        processor.create_customer(
            patient_id="p1",
            payment_method_id="pm_1",
            email="patient@example.com",
        )

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"]["email"] == "patient@example.com"

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_omits_email_when_empty_string(self, mock_post: MagicMock, processor: StripeProcessor) -> None:
        mock_post.return_value = _mock_response(200, {"id": "cus_no_email"})

        processor.create_customer(
            patient_id="p1",
            payment_method_id="pm_1",
            email="",
        )

        call_kwargs = mock_post.call_args[1]
        assert "email" not in call_kwargs["data"]


class TestAttachPaymentMethod:
    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_attaches_and_sets_default(self, mock_post: MagicMock, processor: StripeProcessor) -> None:
        mock_post.return_value = _mock_response(200, {"id": "pm_xyz"})

        processor.attach_payment_method(customer_id="cus_abc", payment_method_id="pm_xyz")

        # Two calls: attach, then set default.
        assert mock_post.call_count == 2
        attach_url = mock_post.call_args_list[0].args[0]
        assert attach_url.endswith("/payment_methods/pm_xyz/attach")
        assert mock_post.call_args_list[0].kwargs["data"] == {"customer": "cus_abc"}

        default_url = mock_post.call_args_list[1].args[0]
        assert default_url.endswith("/customers/cus_abc")
        assert mock_post.call_args_list[1].kwargs["data"] == {
            "invoice_settings[default_payment_method]": "pm_xyz",
        }

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_raises_stripe_error_on_attach_failure(
        self, mock_post: MagicMock, processor: StripeProcessor
    ) -> None:
        mock_post.return_value = _mock_response(
            402, {"error": {"message": "Your card was declined."}}
        )
        with pytest.raises(StripeError) as exc_info:
            processor.attach_payment_method(customer_id="cus_abc", payment_method_id="pm_bad")
        assert "declined" in str(exc_info.value).lower()


class TestCharge:
    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_returns_payment_intent_id(self, mock_post: MagicMock, processor: StripeProcessor) -> None:
        mock_post.return_value = _mock_response(200, {"id": "pi_success"})

        result = processor.charge(
            customer_id="cus_abc",
            amount_cents=9900,
            currency="usd",
            description="Membership: Gold (recurring)",
        )

        assert result == "pi_success"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"]["amount"] == "9900"
        assert call_kwargs["data"]["currency"] == "usd"
        assert call_kwargs["data"]["customer"] == "cus_abc"
        assert call_kwargs["data"]["description"] == "Membership: Gold (recurring)"

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_raises_on_stripe_error_response(self, mock_post: MagicMock, processor: StripeProcessor) -> None:
        mock_post.return_value = _mock_response(
            402,
            {"error": {"message": "Your card was declined.", "code": "card_declined"}},
        )

        with pytest.raises(StripeError):
            processor.charge(
                customer_id="cus_abc",
                amount_cents=9900,
                currency="usd",
                description="test",
            )

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_raises_on_error_key_in_2xx_body(self, mock_post: MagicMock, processor: StripeProcessor) -> None:
        """Some Stripe errors still return 200 but with an error key."""
        mock_post.return_value = _mock_response(
            200,
            {"error": {"message": "Something unexpected happened."}},
        )

        with pytest.raises(StripeError):
            processor.charge(
                customer_id="cus_abc",
                amount_cents=100,
                currency="usd",
                description="test",
            )


class TestStripePostNetworkFailures:
    """A network blip must surface as ``StripeError`` so callers'
    ``except StripeError`` clauses run ``release_claim`` and don't leak
    the ``pending_signup`` mutex row."""

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_timeout_becomes_stripe_error(
        self, mock_post: MagicMock, processor: StripeProcessor
    ) -> None:
        mock_post.side_effect = requests.exceptions.Timeout("read timed out")
        with pytest.raises(StripeError):
            processor.create_customer(patient_id="p1", payment_method_id="pm_1")

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_connection_error_becomes_stripe_error(
        self, mock_post: MagicMock, processor: StripeProcessor
    ) -> None:
        mock_post.side_effect = requests.exceptions.ConnectionError("dns failure")
        with pytest.raises(StripeError):
            processor.charge(
                customer_id="cus_abc",
                amount_cents=100,
                currency="usd",
                description="test",
            )

    @patch("portal_membership.payment_processor.stripe_processor.requests.post")
    def test_non_json_response_becomes_stripe_error(
        self, mock_post: MagicMock, processor: StripeProcessor
    ) -> None:
        # Upstream proxy returns an HTML 502 page instead of JSON.
        resp = MagicMock()
        resp.status_code = 502
        resp.json.side_effect = ValueError("not json")
        resp.text = "<html>bad gateway</html>"
        mock_post.return_value = resp
        with pytest.raises(StripeError):
            processor.create_customer(patient_id="p1", payment_method_id="pm_1")
