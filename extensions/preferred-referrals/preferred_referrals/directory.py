"""The preferred-practice directory: import validation, search matching, and merging.

The directory lives in Canvas's own ``ServiceProvider`` table, not in a custom
model. Providers created through the ServiceProvider effect are flagged
``is_customer_managed``, and the Refer command already attaches to a
``ServiceProvider`` record. So selecting a preferred practice in the Refer
search writes a normal referral to that exact record: native reports, faxing
and the Outstanding Referrals queue keep working unchanged.
"""

import re
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.service_provider import ServiceProvider as ServiceProviderEffect
from canvas_sdk.v1.data.service_provider import ServiceProvider

# Shown next to each result we add, so staff can tell ours from the directory's.
PREFERRED_ANNOTATION = "Preferred"

# A loose term ("a") must not pull the whole table into the sandbox.
MAX_SEARCH_MATCHES = 25

# The sandbox has no Q objects, so each field is queried on its own and unioned.
SEARCHABLE_FIELDS = ("first_name", "last_name", "practice_name", "specialty")

# One import request turns into one effect per row. Capping it keeps a single
# request well inside the effect-batch ceiling; the page sends big files in chunks.
MAX_IMPORT_ROWS = 200

REQUIRED_COLUMNS = ("first_name", "specialty", "business_address")
OPTIONAL_COLUMNS = (
    "last_name",
    "practice_name",
    "business_phone",
    "business_fax",
    "npi",
    "direct_address",
    "notes",
)
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

MAX_FIELD_LENGTH = 512
NPI_PATTERN = re.compile(r"\d{10}")


def preferred_providers() -> Any:
    """Every provider this instance manages itself, active or not."""
    return ServiceProvider.objects.filter(is_customer_managed=True)


def matching_preferred(search_term: str) -> list[Any]:
    """Active preferred providers whose name, practice or specialty contain the term."""
    term = (search_term or "").strip()
    if not term:
        return []
    matches: dict[Any, Any] = {}
    for field in SEARCHABLE_FIELDS:
        rows = ServiceProvider.objects.filter(
            is_customer_managed=True,
            is_active=True,
            **{f"{field}__icontains": term},
        ).order_by("first_name", "last_name", "dbid")[:MAX_SEARCH_MATCHES]
        for provider in rows:
            matches.setdefault(provider.dbid, provider)
    return list(matches.values())[:MAX_SEARCH_MATCHES]


def merge_results(preferred: list[Any], directory_results: list[dict]) -> list[dict]:
    """Our providers first, then the directory's, minus the ones we already listed.

    Dedup is deliberately conservative: a directory row is dropped only when it
    points at the same ``ServiceProvider`` or carries exactly the same display
    text. Listing a practice twice is a smaller failure than hiding one.
    """
    ours = [provider.as_search_result([PREFERRED_ANNOTATION]) for provider in preferred]
    our_ids = {row["value"] for row in ours}
    our_texts = {str(row["text"]).strip().lower() for row in ours}

    theirs = []
    for row in directory_results or []:
        contact = (row.get("extra") or {}).get("contact") or {}
        if contact.get("service_provider_id") in our_ids:
            continue
        if str(row.get("text") or "").strip().lower() in our_texts:
            continue
        theirs.append(row)
    return ours + theirs


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def validate_row(raw: Any) -> tuple[dict[str, str] | None, str | None]:
    """Check one imported row. Returns ``(fields, None)`` or ``(None, error)``."""
    if not isinstance(raw, dict):
        return None, "Row is not an object."

    fields = {column: _clean(raw.get(column)) for column in ALL_COLUMNS}
    missing = [column for column in REQUIRED_COLUMNS if not fields[column]]
    if missing:
        return None, f"Missing {', '.join(missing)}."

    too_long = [
        column for column, value in fields.items() if len(value) > MAX_FIELD_LENGTH
    ]
    if too_long:
        return None, f"Too long: {', '.join(too_long)}."

    if fields["npi"] and not NPI_PATTERN.fullmatch(fields["npi"]):
        return None, "NPI must be exactly 10 digits."

    return {column: value for column, value in fields.items() if value}, None


def import_effects(rows: list[Any]) -> tuple[list[Effect], list[dict[str, Any]]]:
    """Build one create effect per valid row, and an error entry per invalid one.

    ``create()`` never duplicates: a row matching an existing provider on first
    name, last name, specialty and address updates that provider instead, so
    re-importing the same file is safe. A deactivated provider stays deactivated.
    """
    effects: list[Effect] = []
    errors: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        fields, error = validate_row(raw)
        if error is not None or fields is None:
            errors.append({"row": index + 1, "error": error})
            continue
        effects.append(ServiceProviderEffect(**fields).create())
    return effects, errors


def serialize_provider(provider: Any, referral_count: int = 0) -> dict[str, Any]:
    """The admin page's view of one provider."""
    return {
        "id": str(provider.id),
        "name": " ".join(
            part for part in (provider.first_name, provider.last_name) if part
        ),
        "practice_name": provider.practice_name or "",
        "specialty": provider.specialty or "",
        "business_address": provider.business_address or "",
        "business_phone": provider.business_phone or "",
        "business_fax": provider.business_fax or "",
        "npi": provider.npi or "",
        "is_active": bool(provider.is_active),
        "referrals": referral_count,
    }
