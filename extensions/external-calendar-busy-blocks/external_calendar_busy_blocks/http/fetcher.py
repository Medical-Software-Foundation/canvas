import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

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


def redact_url(url: str) -> str:
    """Mask probable secret tokens in a URL so it's safe to log."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "***"
    new_path_parts = []
    for segment in parsed.path.split("/"):
        if _SECRET_LIKE_PATH_SEGMENT.fullmatch(segment):
            new_path_parts.append("***")
        else:
            new_path_parts.append(segment)
    new_path = "/".join(new_path_parts)

    new_query_pairs = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        if len(v) >= 16 or k.lower() in ("token", "key", "secret", "auth"):
            new_query_pairs.append((k, "***"))
        else:
            new_query_pairs.append((k, v))
    new_query = urlencode(new_query_pairs)

    return urlunparse(
        (parsed.scheme, parsed.netloc, new_path, parsed.params, new_query, parsed.fragment)
    )


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
