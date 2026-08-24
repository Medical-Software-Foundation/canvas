"""Reading and curating the resource library."""

from typing import Any

from django.db.models import Q

from patient_resources.constants import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MIN_SEARCH_LENGTH,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
)
from patient_resources.models import PatientResource
from patient_resources.services.validation import normalize_resource


class DuplicateResourceError(Exception):
    """A live resource already has this title and label."""


class ResourceInUseError(Exception):
    """A URL change was attempted on a resource that has already been shared.

    The URL is the identity of the thing a patient was given. Editing it in place
    is how somebody's March link silently becomes a June link, so the caller has
    to create a replacement instead.
    """


def normalize_limit(raw: Any) -> int:
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    if limit <= 0:
        return DEFAULT_PAGE_SIZE
    return min(limit, MAX_PAGE_SIZE)


def normalize_offset(raw: Any) -> int:
    try:
        offset = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(offset, 0)


def build_queryset(*, search: str = "", label: str = "", include_archived: bool = False) -> Any:
    """The library listing, filtered.

    ``include_archived`` is honored only for callers that have already checked
    the requester may curate; the routes never pass it through from a query
    parameter unchecked.
    """
    queryset = PatientResource.objects.all()

    if not include_archived:
        queryset = queryset.filter(status=STATUS_ACTIVE)

    term = (search or "").strip()
    if len(term) >= MIN_SEARCH_LENGTH:
        # Searched across both fields because that is how staff look for things:
        # by what it is called, or by the topic it was filed under.
        queryset = queryset.filter(Q(title__icontains=term) | Q(label__icontains=term))

    clean_label = (label or "").strip()
    if clean_label:
        queryset = queryset.filter(label=clean_label)

    return queryset.order_by("title", "dbid")


def list_resources(
    *,
    search: str = "",
    label: str = "",
    include_archived: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> tuple[list[Any], int]:
    """One page of the library, plus the total matching count."""
    queryset = build_queryset(search=search, label=label, include_archived=include_archived)
    return list(queryset[offset : offset + limit]), queryset.count()


def get_resource(resource_dbid: Any) -> Any | None:
    return PatientResource.objects.filter(dbid=resource_dbid).first()


def distinct_labels() -> list[str]:
    """The labels actually in use on live resources.

    Derived rather than configured, so an empty library yields an empty filter
    instead of a stale hardcoded vocabulary.
    """
    values = PatientResource.objects.filter(status=STATUS_ACTIVE).values_list("label", flat=True)
    return sorted({(value or "").strip() for value in values if (value or "").strip()})


def _live_title_label_conflict(title: str, label: str, *, exclude_dbid: Any = None) -> bool:
    """Case-insensitive duplicate check.

    The database constraint is case-sensitive, as Postgres text comparison is, so
    it catches only exact repeats. "Managing Diabetes" and "managing diabetes"
    are the same resource to a human and would confuse a picker, so they are
    refused here.
    """
    queryset = PatientResource.objects.filter(
        status=STATUS_ACTIVE,
        title__iexact=title,
        label__iexact=label,
    )
    if exclude_dbid is not None:
        queryset = queryset.exclude(dbid=exclude_dbid)
    return queryset.exists()


def create_resource(*, title: str, url: str, label: str, staff_dbid: Any) -> Any:
    """Add a resource to the library. Assumes ``validate_resource`` already passed."""
    fields = normalize_resource(title, url, label)
    if _live_title_label_conflict(fields["title"], fields["label"]):
        raise DuplicateResourceError(
            f"A resource called {fields['title']!r} already exists with that label."
        )
    return PatientResource.objects.create(
        title=fields["title"],
        url=fields["url"],
        label=fields["label"],
        status=STATUS_ACTIVE,
        created_by_id=staff_dbid,
        updated_by_id=staff_dbid,
    )


def update_resource(resource: Any, *, title: str, url: str, label: str, staff_dbid: Any) -> Any:
    """Edit a resource in place.

    The fields are assigned one at a time on purpose. The RestrictedPython
    sandbox blocks ``setattr``, so the concise ``for field in EDITABLE_FIELDS``
    version passes the test suite under CPython and then raises ``TypeError`` on
    the instance -- which is exactly how the order-sets plugin's edit endpoint
    broke. ``EDITABLE_FIELDS`` in constants.py stays the single list of what may
    change, and a test pins it to the assignments below.

    A URL change is refused once the resource has been shared; see
    ``ResourceInUseError``.
    """
    fields = normalize_resource(title, url, label)

    if fields["url"] != resource.url and has_shares(resource):
        raise ResourceInUseError(
            "This resource has already been shared with patients, so its link cannot "
            "be changed. Add a replacement resource and archive this one."
        )

    if _live_title_label_conflict(fields["title"], fields["label"], exclude_dbid=resource.dbid):
        raise DuplicateResourceError(
            f"A resource called {fields['title']!r} already exists with that label."
        )

    resource.title = fields["title"]
    resource.url = fields["url"]
    resource.label = fields["label"]
    resource.updated_by_id = staff_dbid
    resource.save()
    return resource


def has_shares(resource: Any) -> bool:
    """True if this resource has ever been given to a patient."""
    from patient_resources.models import PatientResourceShare

    return PatientResourceShare.objects.filter(resource__dbid=resource.dbid).exists()


def delete_resource(resource: Any) -> None:
    """Remove a resource that has never reached a patient.

    Refuses anything with share rows, including shares that were later
    withdrawn: a withdrawn share is still a record that a patient received
    something, and the foreign keys carry no cascade, so removing the catalog row
    would leave those rows pointing at nothing.

    Deliberately without a transaction. The delete is a single statement, so
    there is nothing partial to roll back, and a transaction would not close the
    only real gap -- a provider sharing this resource between the check and the
    delete. Closing that needs row locking the DDL pipeline does not give us. A
    share created inside that window is lost rather than left dangling, and the
    window is one statement wide.
    """
    if has_shares(resource):
        raise ResourceInUseError(
            "This resource has been shared with patients, so it cannot be deleted. "
            "Withdraw it to take it back from them, or archive it to stop offering it."
        )
    PatientResource.objects.filter(dbid=resource.dbid).delete()


def set_status(resource: Any, status: str, *, staff_dbid: Any) -> Any:
    """Archive or restore a resource.

    Archiving is the only removal this plugin offers. A hard delete would orphan
    every share row -- the foreign keys are ``DO_NOTHING`` and the DDL emits no
    cascade -- and destroy the record of what patients were given.
    """
    if status not in (STATUS_ACTIVE, STATUS_ARCHIVED):
        raise ValueError(f"unknown status {status!r}")
    resource.status = status
    resource.updated_by_id = staff_dbid
    resource.save()
    return resource
