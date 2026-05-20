"""Unit tests for vanta_lab_orders.lkcareevolve_client.post_order.

These tests patch canvas_sdk.utils.Http (the only HTTP wrapper allowed in
the Canvas plugin sandbox) so we exercise the real post_order body —
URL composition, header set, and raise_for_status — rather than mocking
at the protocol level as the integration tests do.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from vanta_lab_orders.lkcareevolve_client import post_order


def test_post_order_posts_to_orders_path(mocker: Any) -> None:
    """URL is composed as base_url + '/orders'."""
    mock_http_cls = mocker.patch("vanta_lab_orders.lkcareevolve_client.Http")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_http_cls.return_value.post.return_value = mock_response

    post_order({"x": 1}, "https://lkce.example.com", "tkn")

    call_args = mock_http_cls.return_value.post.call_args
    assert call_args.args[0] == "https://lkce.example.com/orders"


def test_post_order_sets_bearer_auth_header(mocker: Any) -> None:
    """Authorization header is `Bearer <api_key>`."""
    mock_http_cls = mocker.patch("vanta_lab_orders.lkcareevolve_client.Http")
    mock_response = MagicMock()
    mock_http_cls.return_value.post.return_value = mock_response

    post_order({}, "https://lkce.example.com", "secret-token")

    headers = mock_http_cls.return_value.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_post_order_passes_payload_as_json_body(mocker: Any) -> None:
    """The payload dict is passed via json= kwarg (not data=)."""
    mock_http_cls = mocker.patch("vanta_lab_orders.lkcareevolve_client.Http")
    mock_http_cls.return_value.post.return_value = MagicMock()

    payload = {"MessageHeader": {"PlacerOrderNumber": "abc-123"}}
    post_order(payload, "https://lkce.example.com", "tkn")

    assert mock_http_cls.return_value.post.call_args.kwargs["json"] is payload


def test_post_order_calls_raise_for_status(mocker: Any) -> None:
    """raise_for_status is always invoked — no swallowing non-2xx."""
    mock_http_cls = mocker.patch("vanta_lab_orders.lkcareevolve_client.Http")
    mock_response = MagicMock()
    mock_http_cls.return_value.post.return_value = mock_response

    post_order({}, "https://lkce.example.com", "tkn")

    mock_response.raise_for_status.assert_called_once()


def test_post_order_propagates_http_error(mocker: Any) -> None:
    """An HTTP error from raise_for_status bubbles out to the caller."""
    mock_http_cls = mocker.patch("vanta_lab_orders.lkcareevolve_client.Http")
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = RuntimeError("502 Bad Gateway")
    mock_http_cls.return_value.post.return_value = mock_response

    with pytest.raises(RuntimeError, match="502 Bad Gateway"):
        post_order({}, "https://lkce.example.com", "tkn")
