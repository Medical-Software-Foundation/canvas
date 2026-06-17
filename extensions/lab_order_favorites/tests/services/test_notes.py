"""Tests for the chart review note-creation helpers."""

from typing import Any

from lab_order_favorites.services.notes import (
    chart_review_note_type_id,
    default_practice_location_id,
)


def _make_review_type(**kwargs: Any):  # type: ignore[no-untyped-def]
    from canvas_sdk.v1.data.note import NoteType, NoteTypeCategories

    defaults = dict(
        category=NoteTypeCategories.REVIEW,
        name="Chart Review",
        is_active=True,
        is_visible=True,
        rank=1,
    )
    defaults.update(kwargs)
    return NoteType.objects.create(**defaults)


def _make_location(**kwargs: Any):  # type: ignore[no-untyped-def]
    from canvas_sdk.v1.data.practicelocation import PracticeLocation

    defaults = dict(
        full_name="Main Clinic",
        active=True,
        bill_through_organization=False,
        include_zz_qualifier=False,
    )
    defaults.update(kwargs)
    return PracticeLocation.objects.create(**defaults)


# --- chart_review_note_type_id ---

def test_chart_review_note_type_id_none_when_absent():
    assert chart_review_note_type_id() is None


def test_chart_review_note_type_id_returns_active_review_type():
    review = _make_review_type()
    assert chart_review_note_type_id() == str(review.id)


def test_chart_review_note_type_id_picks_lowest_rank():
    _make_review_type(name="Second", rank=5)
    first = _make_review_type(name="First", rank=1)
    assert chart_review_note_type_id() == str(first.id)


def test_chart_review_note_type_id_ignores_inactive_and_hidden():
    _make_review_type(name="Inactive", is_active=False)
    _make_review_type(name="Hidden", is_visible=False)
    assert chart_review_note_type_id() is None


def test_chart_review_note_type_id_ignores_other_categories():
    from canvas_sdk.v1.data.note import NoteType, NoteTypeCategories

    NoteType.objects.create(
        category=NoteTypeCategories.ENCOUNTER,
        name="Office Visit",
        is_active=True,
        is_visible=True,
        rank=1,
    )
    assert chart_review_note_type_id() is None


# --- default_practice_location_id ---

def test_default_location_uses_provider_primary(make_staff):
    loc = _make_location(full_name="Provider Home")
    staff = make_staff()
    staff.primary_practice_location = loc
    staff.save()
    assert default_practice_location_id(str(staff.id)) == str(loc.id)


def test_default_location_falls_back_to_first_active(make_staff):
    # The staff has no primary location, so the first active location is used.
    active = _make_location(full_name="Active")
    staff = make_staff()
    assert default_practice_location_id(str(staff.id)) == str(active.id)


def test_default_location_none_when_no_active_location(make_staff):
    staff = make_staff()
    _make_location(full_name="Closed", active=False)
    assert default_practice_location_id(str(staff.id)) is None


def test_default_location_unknown_staff_falls_back():
    active = _make_location(full_name="Active")
    assert default_practice_location_id("00000000-0000-0000-0000-000000000000") == str(active.id)
