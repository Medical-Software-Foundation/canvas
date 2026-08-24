"""Library reads and curation."""

from unittest.mock import MagicMock

import pytest

from patient_resources.constants import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
)
from patient_resources.models import PatientResource, PatientResourceShare
from patient_resources.services import catalog


@pytest.fixture(autouse=True)
def _reset_managers():
    PatientResource.objects.reset_mock()
    PatientResourceShare.objects.reset_mock()
    yield


def _resource(dbid=1, title="Managing diabetes", url="https://example.org/d", label="Diabetes"):
    resource = MagicMock()
    resource.dbid = dbid
    resource.title = title
    resource.url = url
    resource.label = label
    resource.status = STATUS_ACTIVE
    return resource


def _no_conflict():
    PatientResource.objects.filter.return_value.exists.return_value = False
    PatientResource.objects.filter.return_value.exclude.return_value.exists.return_value = False


def _no_shares():
    PatientResourceShare.objects.filter.return_value.exists.return_value = False


# --- paging ---------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "abc", 0, -5, [], {}])
def test_bad_limit_falls_back_to_the_default(raw):
    assert catalog.normalize_limit(raw) == DEFAULT_PAGE_SIZE


def test_limit_is_capped():
    assert catalog.normalize_limit(MAX_PAGE_SIZE + 500) == MAX_PAGE_SIZE


def test_limit_accepts_a_numeric_string():
    assert catalog.normalize_limit("10") == 10


@pytest.mark.parametrize("raw,expected", [(None, 0), ("x", 0), (-3, 0), ("7", 7), (7, 7)])
def test_offset_is_clamped(raw, expected):
    assert catalog.normalize_offset(raw) == expected


# --- listing --------------------------------------------------------------


def test_listing_excludes_archived_by_default():
    catalog.build_queryset()
    assert PatientResource.objects.all.return_value.filter.call_args.kwargs == {
        "status": STATUS_ACTIVE
    }


def test_listing_can_include_archived_for_a_curator():
    catalog.build_queryset(include_archived=True)
    PatientResource.objects.all.return_value.filter.assert_not_called()


def test_short_search_terms_are_ignored():
    """A one-character search would match nearly the whole library."""
    catalog.build_queryset(search="a", include_archived=True)
    PatientResource.objects.all.return_value.filter.assert_not_called()


def test_search_matches_title_or_label():
    catalog.build_queryset(search="diab", include_archived=True)
    predicate = PatientResource.objects.all.return_value.filter.call_args.args[0]
    assert predicate.connector == "OR"
    assert predicate.leaves() == [
        {"title__icontains": "diab"},
        {"label__icontains": "diab"},
    ]


def test_label_filter_is_exact():
    """The filter list is built from stored labels, so an exact match is right."""
    catalog.build_queryset(label="Diabetes", include_archived=True)
    assert PatientResource.objects.all.return_value.filter.call_args.kwargs == {
        "label": "Diabetes"
    }


def test_listing_returns_a_page_and_a_total():
    queryset = PatientResource.objects.all.return_value.filter.return_value.order_by.return_value
    queryset.__getitem__.return_value = [_resource()]
    queryset.count.return_value = 42

    rows, total = catalog.list_resources(limit=10, offset=0)
    assert len(rows) == 1
    assert total == 42


def test_distinct_labels_drops_blanks_and_sorts():
    PatientResource.objects.filter.return_value.values_list.return_value = [
        "Diabetes",
        "  ",
        None,
        "Cardiac",
        "Diabetes",
    ]
    assert catalog.distinct_labels() == ["Cardiac", "Diabetes"]


def test_distinct_labels_on_an_empty_library_returns_empty():
    PatientResource.objects.filter.return_value.values_list.return_value = []
    assert catalog.distinct_labels() == []


# --- create ---------------------------------------------------------------


def test_create_stores_trimmed_values_and_attributes_the_curator():
    _no_conflict()
    catalog.create_resource(
        title="  Managing diabetes  ", url="  https://example.org/d  ", label="  Diabetes  ",
        staff_dbid=101,
    )
    kwargs = PatientResource.objects.create.call_args.kwargs
    assert kwargs["title"] == "Managing diabetes"
    assert kwargs["url"] == "https://example.org/d"
    assert kwargs["label"] == "Diabetes"
    assert kwargs["status"] == STATUS_ACTIVE
    assert kwargs["created_by_id"] == 101


def test_create_refuses_a_case_insensitive_duplicate():
    """The database constraint is case-sensitive, so this is the real guard."""
    PatientResource.objects.filter.return_value.exists.return_value = True
    with pytest.raises(catalog.DuplicateResourceError):
        catalog.create_resource(
            title="managing diabetes", url="https://example.org/d", label="diabetes",
            staff_dbid=101,
        )
    PatientResource.objects.create.assert_not_called()


def test_duplicate_check_is_scoped_to_live_rows():
    """An archived resource must not block the corrected version."""
    _no_conflict()
    catalog.create_resource(title="T", url="https://example.org/d", label="L", staff_dbid=1)
    assert PatientResource.objects.filter.call_args.kwargs["status"] == STATUS_ACTIVE


# --- update ---------------------------------------------------------------


def test_update_assigns_exactly_the_editable_fields():
    _no_conflict()
    _no_shares()
    resource = _resource()
    catalog.update_resource(
        resource, title="New title", url="https://example.org/d", label="Cardiac", staff_dbid=7
    )
    assert resource.title == "New title"
    assert resource.label == "Cardiac"
    assert resource.updated_by_id == 7
    resource.save.assert_called_once()


def test_update_cannot_change_status():
    """Archiving goes through set_status, which is a separate, confirmed action."""
    _no_conflict()
    _no_shares()
    resource = _resource()
    resource.status = STATUS_ACTIVE
    catalog.update_resource(
        resource, title="T", url="https://example.org/d", label="L", staff_dbid=1
    )
    assert resource.status == STATUS_ACTIVE


def test_editable_fields_matches_what_update_assigns():
    """Pins constants.EDITABLE_FIELDS to the assignments in update_resource.

    The sandbox blocks setattr, so the fields cannot be applied in a loop and the
    two places can drift silently. This is the only thing that notices.
    """
    import ast
    import inspect

    from patient_resources.constants import EDITABLE_FIELDS

    tree = ast.parse(inspect.getsource(catalog.update_resource).lstrip())
    assigned = {
        target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "resource"
    }
    assert assigned == set(EDITABLE_FIELDS) | {"updated_by_id"}


def test_update_refuses_a_url_change_once_shared():
    """The URL is the identity of what a patient was given.

    Editing it in place is how somebody's March link silently becomes a June
    link, so a replacement resource is required instead.
    """
    _no_conflict()
    PatientResourceShare.objects.filter.return_value.exists.return_value = True
    resource = _resource(url="https://example.org/old")
    with pytest.raises(catalog.ResourceInUseError):
        catalog.update_resource(
            resource, title="T", url="https://example.org/new", label="L", staff_dbid=1
        )
    resource.save.assert_not_called()


def test_update_allows_a_url_change_before_anyone_has_it():
    _no_conflict()
    _no_shares()
    resource = _resource(url="https://example.org/old")
    catalog.update_resource(
        resource, title="T", url="https://example.org/new", label="L", staff_dbid=1
    )
    assert resource.url == "https://example.org/new"


def test_update_refuses_a_duplicate_excluding_itself():
    _no_shares()
    PatientResource.objects.filter.return_value.exclude.return_value.exists.return_value = True
    resource = _resource()
    with pytest.raises(catalog.DuplicateResourceError):
        catalog.update_resource(
            resource, title="Other", url=resource.url, label="L", staff_dbid=1
        )


# --- status ---------------------------------------------------------------


def test_archiving_flips_status_without_deleting():
    resource = _resource()
    catalog.set_status(resource, STATUS_ARCHIVED, staff_dbid=9)
    assert resource.status == STATUS_ARCHIVED
    resource.save.assert_called_once()
    resource.delete.assert_not_called()


def test_restoring_flips_it_back():
    resource = _resource()
    resource.status = STATUS_ARCHIVED
    catalog.set_status(resource, STATUS_ACTIVE, staff_dbid=9)
    assert resource.status == STATUS_ACTIVE


def test_unknown_status_is_refused():
    with pytest.raises(ValueError):
        catalog.set_status(_resource(), "deleted", staff_dbid=9)


def test_get_resource_looks_up_by_dbid():
    """dbid, not id: dbid is the primary key on a plugin-owned table."""
    expected = _resource(dbid=12)
    PatientResource.objects.filter.return_value.first.return_value = expected
    assert catalog.get_resource(12) is expected
    assert PatientResource.objects.filter.call_args.kwargs == {"dbid": 12}


def test_get_resource_returns_none_when_absent():
    PatientResource.objects.filter.return_value.first.return_value = None
    assert catalog.get_resource(999) is None


# --- delete ---------------------------------------------------------------


def test_delete_removes_a_resource_no_patient_ever_had():
    _no_shares()
    resource = _resource(dbid=12)
    catalog.delete_resource(resource)
    assert PatientResource.objects.filter.call_args.kwargs == {"dbid": 12}
    PatientResource.objects.filter.return_value.delete.assert_called_once()


def test_delete_is_refused_once_a_patient_has_it():
    """Withdraw exists for that. Deleting would leave share rows pointing at
    nothing, since the foreign keys carry no cascade.
    """
    PatientResourceShare.objects.filter.return_value.exists.return_value = True
    with pytest.raises(catalog.ResourceInUseError):
        catalog.delete_resource(_resource(dbid=12))
    PatientResource.objects.filter.return_value.delete.assert_not_called()


def test_a_withdrawn_share_still_blocks_deletion():
    """A withdrawn share is still a record that a patient received something.

    The has-shares check is deliberately unfiltered on revoked_at, so this is the
    same code path -- asserted separately because the distinction is the whole
    reason the filter is absent.
    """
    PatientResourceShare.objects.filter.return_value.exists.return_value = True
    with pytest.raises(catalog.ResourceInUseError):
        catalog.delete_resource(_resource(dbid=12))
    share_filter = PatientResourceShare.objects.filter.call_args.kwargs
    assert "revoked_at__isnull" not in share_filter


def test_the_refusal_names_the_alternatives():
    """A dead end is worse than a redirection."""
    PatientResourceShare.objects.filter.return_value.exists.return_value = True
    with pytest.raises(catalog.ResourceInUseError) as caught:
        catalog.delete_resource(_resource(dbid=12))
    message = str(caught.value).lower()
    assert "withdraw" in message
    assert "archive" in message
