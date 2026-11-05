"""ICD-10-CM lookups against the National Library of Medicine's UMLS service.

Two calls build a quickpick's or order set's diagnosis list:

* ``search_icd10`` — find ICD-10-CM codes by words ("end stage renal").
* ``expand_icd10`` — a code plus every code beneath it in the ICD-10-CM
  hierarchy, so picking "N18" brings N18.1 through N18.9 with it.

Both need the practice's UMLS API key (the ``UMLS_API_KEY`` plugin setting).
They are only called from the builder while a quickpick or order set is being
edited or saved; the in-command panel matches against the stored snapshot and
never waits on this service.

The key travels as a query parameter, which is how UMLS takes it, so a request
URL is never logged.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlencode

from canvas_sdk.utils.http import Http
from logger import log

from charting_tools.icd10 import normalize_icd10

UMLS_KEY_SETTING = "UMLS_API_KEY"
UTS_BASE = "https://uts-ws.nlm.nih.gov/rest"

SEARCH_PAGE_SIZE = 25
DESCENDANT_PAGE_SIZE = 200
# A whole ICD-10-CM chapter is a few thousand codes. The caps keep one careless
# pick (a chapter instead of a condition) from turning into a runaway crawl.
MAX_DESCENDANT_PAGES = 30
MAX_CODES = 6000


class UmlsError(Exception):
    """A lookup that could not be completed, phrased for the admin page."""


def api_key(secrets: Any) -> str:
    """The UMLS key from the plugin's settings, or "" when it isn't set."""
    return str(secrets.get(UMLS_KEY_SETTING) or "").strip()


def _get(path: str, params: dict[str, Any], key: str) -> dict[str, Any] | None:
    """GET a UTS path. ``None`` means "no such thing" (UTS answers 404)."""
    if not key:
        raise UmlsError(
            "The UMLS API key is not set. Add it as UMLS_API_KEY in this "
            "plugin's configuration."
        )
    query = urlencode({**params, "apiKey": key})
    try:
        response = Http().get(f"{UTS_BASE}{path}?{query}")
    except OSError as error:  # requests' connection and timeout errors are OSErrors
        log.warning(f"UMLS request failed: {error.__class__.__name__}")
        raise UmlsError("Could not reach the UMLS service. Try again shortly.") from error
    if response.status_code == 404:
        return None
    if response.status_code in (401, 403):
        raise UmlsError("UMLS rejected the API key. Check UMLS_API_KEY in the plugin configuration.")
    if response.status_code != 200:
        log.warning(f"UMLS answered {response.status_code} for {path.split('?')[0]}")
        raise UmlsError(f"The UMLS service answered with an error ({response.status_code}).")
    try:
        payload: dict[str, Any] = response.json()
        return payload
    except ValueError as error:
        raise UmlsError("The UMLS service sent an unreadable answer.") from error


def _is_code(ui: str) -> bool:
    # Searches answer "NONE" when nothing matched, and the hierarchy includes
    # block ranges like "N17-N19" that are headings, not chartable codes.
    return bool(ui) and ui != "NONE" and "-" not in ui


CODE_PATTERN = re.compile(r"^[A-Z][0-9][0-9A-Z](\.?[0-9A-Z]{1,4})?$")


def as_code(term: str) -> str:
    """``term`` as a dotted ICD-10-CM code ("n186" → "N18.6"), or "" if it isn't one."""
    raw = (term or "").strip().upper()
    if not CODE_PATTERN.match(raw):
        return ""
    bare = raw.replace(".", "")
    return bare if len(bare) == 3 else f"{bare[:3]}.{bare[3:]}"


def _code_lookup(code: str, key: str) -> list[dict[str, str]]:
    """The code itself, then the codes directly beneath it.

    UMLS's word search matches names, so typing "N18" finds diseases that
    *mention* CKD rather than the N18 category. A code-shaped term is looked up
    as a code instead.
    """
    base = f"/content/current/source/ICD10CM/{quote(code, safe='')}"
    out: list[dict[str, str]] = []
    payload = _get(base, {}, key)
    if payload:
        row = payload.get("result") or {}
        if isinstance(row, dict) and row.get("ui"):
            out.append({"code": str(row["ui"]), "display": str(row.get("name") or "")})
    if out:
        children = _get(f"{base}/children", {"pageSize": SEARCH_PAGE_SIZE}, key) or {}
        for row in children.get("result") or []:
            ui = str(row.get("ui") or "").strip()
            if _is_code(ui):
                out.append({"code": ui, "display": str(row.get("name") or "")})
    return out


def search_icd10(term: str, key: str) -> list[dict[str, str]]:
    """ICD-10-CM codes matching ``term``, as ``[{"code", "display"}]``.

    A code-shaped term ("N18", "n18.6", "N186") is looked up as a code first;
    word matches follow.
    """
    term = (term or "").strip()
    if len(term) < 2:
        return []
    code = as_code(term)
    found = _code_lookup(code, key) if code else []
    seen = {row["code"] for row in found}
    for row in _word_search(term, key):
        if row["code"] not in seen:
            seen.add(row["code"])
            found.append(row)
    return found


def _word_search(term: str, key: str) -> list[dict[str, str]]:
    payload = _get(
        "/search/current",
        {
            "string": term,
            "sabs": "ICD10CM",
            "returnIdType": "code",
            "searchType": "words",
            "pageSize": SEARCH_PAGE_SIZE,
        },
        key,
    ) or {}
    rows = ((payload.get("result") or {}).get("results")) or []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        ui = str(row.get("ui") or "").strip()
        if not _is_code(ui) or ui in seen:
            continue
        seen.add(ui)
        out.append({"code": ui, "display": str(row.get("name") or "")})
    return out


def expand_icd10(code: str, key: str) -> list[str]:
    """``code`` and every ICD-10-CM code beneath it, dot-stripped.

    A leaf code (UTS answers 404 for its descendants) is just itself.
    """
    code = (code or "").strip()
    found: list[str] = []
    seen: set[str] = set()

    def add(ui: str) -> None:
        normal = normalize_icd10(ui)
        if normal and normal not in seen and _is_code(ui):
            seen.add(normal)
            found.append(normal)

    add(code)
    path = f"/content/current/source/ICD10CM/{quote(code, safe='')}/descendants"
    page = 1
    while page <= MAX_DESCENDANT_PAGES and len(found) < MAX_CODES:
        payload = _get(path, {"pageNumber": page, "pageSize": DESCENDANT_PAGE_SIZE}, key)
        if not payload:
            break
        for row in payload.get("result") or []:
            add(str(row.get("ui") or "").strip())
        page_count = int(payload.get("pageCount") or 1)
        if page >= page_count:
            break
        page += 1
    return found[:MAX_CODES]


def expand_sources(sources: list[dict[str, Any]], key: str) -> list[str]:
    """The union of every source code's expansion, in pick order."""
    codes: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for normal in expand_icd10(str(source.get("code") or ""), key):
            if normal not in seen:
                seen.add(normal)
                codes.append(normal)
    return codes[:MAX_CODES]
