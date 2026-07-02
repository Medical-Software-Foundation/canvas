"""Thin wrapper for posting orders to the LKCareEvolve (ELLKAY) API.

Uses canvas_sdk.utils.Http (the only HTTP client allowed in the Canvas plugin
sandbox). Returns a requests.Response-compatible object.

Design rules:
- No retry logic — non-2xx propagates immediately.
- Basic auth via LKCAREEVOLVE_API_KEY secret (ELLKAY issues the API key as a
  base64-encoded Basic credential, not a bearer token).
- raise_for_status() always called — never swallow HTTP errors.
- Timeout is whatever canvas_sdk.utils.Http defaults to; the wrapper
  doesn't accept a per-call timeout kwarg.
- The full LKCareEvolve ingestion endpoint is supplied via the
  LKCAREEVOLVE_BASE_URL secret (e.g. the SendRawMessage URL); the payload is
  POSTed to that URL as-is.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.utils import Http


def post_order(
    payload: dict[str, Any],
    base_url: str,
    api_key: str,
) -> Any:
    """POST an ELLKAY Orders JSON v2.2 payload to LKCareEvolve.

    Args:
        payload: The dict built by payload.build_order_payload().
        base_url: Full LKCareEvolve ingestion URL (no trailing slash), e.g. the
            ELLKAY SendRawMessage endpoint.
        api_key: Base64-encoded Basic auth credential issued by ELLKAY.

    Returns:
        The HTTP response on success (2xx). Has .status_code, .ok, .text, .json().

    Raises:
        requests.HTTPError: On non-2xx response (via raise_for_status).
        requests.RequestException: On network-level failure (timeout, DNS, etc.).
    """
    url = base_url
    headers = {
        "Authorization": f"Basic {api_key}",
        "Content-Type": "application/json",
    }
    http = Http()
    response = http.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response
