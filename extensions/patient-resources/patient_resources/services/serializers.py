"""Turning rows into the JSON the three front ends consume.

Every function here tolerates ``None`` in every column. That is not defensive
habit: the plugin DDL pipeline emits no NOT NULL constraints and no column
defaults, so a row written by anything other than this plugin's create path can
legitimately have nulls where the model declares a default.
"""

from typing import Any

from patient_resources.constants import STATUS_ACTIVE
from patient_resources.services.validation import is_safe_href


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _isoformat(value: Any) -> str | None:
    """An ISO-8601 timestamp, or ``None``.

    Returned as UTC text rather than a formatted date because the portal renders
    it in the patient's own device timezone. ``None`` stays ``None`` -- rendering
    it as the string "None" is exactly the placeholder problem this repo's review
    rules call out.
    """
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if isoformat is None:
        return _text(value)
    # str() because the column is untyped: a row written elsewhere could hold
    # something whose isoformat() returns anything at all.
    return str(isoformat())


def _safe_url(value: Any) -> str:
    """A URL only if it is still safe to render as a link.

    Re-checked here, not just on write, because storage is not a trust boundary:
    the database enforces nothing, and a row may predate a fix to the validator.
    A value that fails renders as inert text in the UI rather than an anchor.
    """
    candidate = _text(value)
    return candidate if is_safe_href(candidate) else ""


def serialize_resource(
    resource: Any,
    *,
    shared: bool | None = None,
    has_live_shares: bool | None = None,
    has_withdrawn_shares: bool | None = None,
) -> dict[str, Any]:
    """One catalog row, for the admin library or the chart picker."""
    data: dict[str, Any] = {
        "id": resource.dbid,
        "title": _text(getattr(resource, "title", "")),
        "url": _safe_url(getattr(resource, "url", "")),
        "label": _text(getattr(resource, "label", "")),
        "status": _text(getattr(resource, "status", "")),
        "is_active": _text(getattr(resource, "status", "")) == STATUS_ACTIVE,
        "created_at": _isoformat(getattr(resource, "created_at", None)),
        "updated_at": _isoformat(getattr(resource, "updated_at", None)),
    }
    if shared is not None:
        data["shared"] = shared
    # Two facts rather than one, because the row's controls turn on different
    # questions. `shared` above means "this patient already has it"; these mean
    # "some patient currently holds it" and "some patient had it taken back".
    # Together they decide all three cases: withdrawable, already withdrawn, and
    # never shared and so deletable.
    if has_live_shares is not None:
        data["has_live_shares"] = has_live_shares
    if has_withdrawn_shares is not None:
        data["has_withdrawn_shares"] = has_withdrawn_shares
    return data


def serialize_share_for_staff(share: Any) -> dict[str, Any]:
    """One share, for the picker's "already shared" list."""
    return {
        "resource_id": getattr(share, "resource_id", None),
        "title": _text(getattr(share, "title_at_share", "")),
        "label": _text(getattr(share, "label_at_share", "")),
        "url": _safe_url(getattr(share, "url_at_share", "")),
        "shared_at": _isoformat(getattr(share, "shared_at", None)),
    }


def serialize_share_for_patient(share: Any) -> dict[str, Any]:
    """One share, for the patient's own list.

    Title and label come from the live catalog row, so correcting a typo reaches
    the patients who already have it. Reading the snapshot instead meant a
    misspelling followed them forever, with no way to fix it.

    That is safe because the link is frozen once a resource has been shared: with
    the URL immutable, a title edit can only redescribe the same resource, never
    swap it for a different one. Repurposing was the risk the snapshot guarded
    against, and the immutable URL already covers it.

    The URL itself still comes from the snapshot. It cannot have changed, so the
    two agree -- and the snapshot keeps working if the catalog row is ever
    missing, since that foreign key is nullable.
    """
    resource = getattr(share, "resource", None)
    live_title = getattr(resource, "title", None) if resource is not None else None
    live_label = getattr(resource, "label", None) if resource is not None else None

    return {
        "title": _text(live_title or getattr(share, "title_at_share", "")),
        # An empty label is a real value, so only a missing row falls back.
        "label": _text(
            live_label if live_label is not None else getattr(share, "label_at_share", "")
        ),
        "url": _safe_url(getattr(share, "url_at_share", "")),
        "shared_at": _isoformat(getattr(share, "shared_at", None)),
    }


def serialize_withdrawn_share(share: Any) -> dict[str, Any]:
    """A withdrawn resource: named and dated, but not linkable.

    Still the snapshot here, unlike the live list. A withdrawn resource is
    archived and may since have been edited or removed, and the patient cannot
    open it anyway, so the name they were given is the more useful record.
    """
    return {
        "title": _text(getattr(share, "title_at_share", "")),
        "label": _text(getattr(share, "label_at_share", "")),
        "revoked_at": _isoformat(getattr(share, "revoked_at", None)),
    }
