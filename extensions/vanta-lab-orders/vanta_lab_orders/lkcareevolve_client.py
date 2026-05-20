"""Thin wrapper for posting orders to the LKCareEvolve (ELLKAY) API.

Uses canvas_sdk.utils.Http (the only HTTP client allowed in the Canvas plugin
sandbox). Returns a requests.Response-compatible object.

Design rules:
- No retry logic — non-2xx propagates immediately.
- Bearer auth via LKCAREEVOLVE_API_KEY secret.
- raise_for_status() always called — never swallow HTTP errors.
- Timeout is whatever canvas_sdk.utils.Http defaults to; the wrapper
  doesn't accept a per-call timeout kwarg.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.utils import Http

_ORDER_PATH = "/orders"


def post_order(
    payload: dict[str, Any],
    base_url: str,
    api_key: str,
) -> Any:
    """POST an ELLKAY Orders JSON v2.2 payload to LKCareEvolve.

    Args:
        payload: The dict built by payload.build_order_payload().
        base_url: LKCareEvolve base URL (no trailing slash), e.g. 'https://api.lkcareevolve.ellkay.com'.
        api_key: Bearer token issued by ELLKAY.

    Returns:
        The HTTP response on success (2xx). Has .status_code, .ok, .text, .json().

    Raises:
        requests.HTTPError: On non-2xx response (via raise_for_status).
        requests.RequestException: On network-level failure (timeout, DNS, etc.).
    """
    url = f"{base_url}{_ORDER_PATH}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    http = Http()
    response = http.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response
