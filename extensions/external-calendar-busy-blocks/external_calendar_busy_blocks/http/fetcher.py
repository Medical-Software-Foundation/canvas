import re
from dataclasses import dataclass

from canvas_sdk.utils.http import Http


@dataclass(frozen=True)
class FetchOk:
    body: bytes
    etag: str | None
    last_modified: str | None


class NotModified:
    pass


class Unauthorized:
    pass


class NotFound:
    pass


@dataclass(frozen=True)
class TransientError:
    reason: str


FetchResult = FetchOk | NotModified | Unauthorized | NotFound | TransientError


_SECRET_LIKE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{16,}$")
_URL_REGEX = re.compile(r"^(https?://[^/?#]+)(/[^?#]*)?(\?[^#]*)?(.*)$")
_SECRET_QUERY_PARAM_NAME = re.compile(r"(?i)(token|key|secret|auth)")


def redact_url(url: str) -> str:
    """Mask probable secret tokens in a URL so it's safe to log."""
    match = _URL_REGEX.match(url)
    if not match:
        return "***"
    scheme_host, path, query, rest = match.groups()
    path = path or ""
    query = query or ""

    # Redact secret-looking path segments
    redacted_path = "/".join(
        "***" if _SECRET_LIKE_PATH_SEGMENT.fullmatch(seg) else seg
        for seg in path.split("/")
    )

    # Redact secret-looking query values
    if query.startswith("?"):
        pairs = []
        for chunk in query[1:].split("&"):
            if not chunk:
                continue
            if "=" in chunk:
                k, v = chunk.split("=", 1)
            else:
                k, v = chunk, ""
            if len(v) >= 16 or _SECRET_QUERY_PARAM_NAME.fullmatch(k):
                v = "***"
            pairs.append(f"{k}={v}" if "=" in chunk else k)
        query = "?" + "&".join(pairs)

    return scheme_host + redacted_path + query + rest


def fetch_feed(
    url: str,
    etag: str | None,
    last_modified: str | None,
) -> FetchResult:
    """Fetch an ICS feed with conditional headers."""
    headers: dict[str, str] = {"User-Agent": "Canvas External Calendar Busy Blocks/0.1"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    try:
        response = Http().get(url, headers=headers, timeout=30)
    except Exception as exc:  # noqa: BLE001 — surface all transient errors uniformly
        return TransientError(reason=f"{type(exc).__name__}: {exc}")

    code = response.status_code
    if code == 304:
        return NotModified()
    if code == 401 or code == 403:
        return Unauthorized()
    if code == 404:
        return NotFound()
    if 200 <= code < 300:
        return FetchOk(
            body=response.content,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
    return TransientError(reason=f"HTTP {code}")
