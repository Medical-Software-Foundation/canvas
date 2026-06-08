"""Tests for the favorites service: storage, visibility, and search."""

import pytest

from lab_order_favorites.models import LabFavorite
from lab_order_favorites.services import FavoritesService
from lab_order_favorites.services.favorites_service import (
    _matches,
    _normalize_codes,
    _normalize_tags,
    _normalize_tests,
)

TESTS = [{"order_code": "001", "order_name": "Glucose", "cpt_code": "82947"}]


def _payload(**overrides):
    base = {
        "name": "Glucose",
        "lab_partner_id": "partner-1",
        "lab_partner_name": "LabCorp",
        "tests": TESTS,
        "tags": ["Wellness", "wellness", "AM"],
        "diagnosis_codes": ["Z00.00", " "],
        "comment": " fast 8h ",
        "fasting_required": True,
        "is_shared": True,
    }
    base.update(overrides)
    return base


def test_create_normalizes_and_persists(make_staff):
    staff = make_staff()
    service = FavoritesService()

    created = service.create_favorite(_payload(), str(staff.id))

    assert created["id"].startswith("labfav_")
    assert created["tags"] == ["wellness", "am"]  # lowercased + de-duped
    assert created["diagnosis_codes"] == ["Z00.00"]  # blank dropped
    assert created["comment"] == "fast 8h"  # trimmed
    assert created["is_mine"] is True
    assert created["created_by_name"] == "Pat Provider"
    assert LabFavorite.objects.count() == 1


def test_create_requires_name_partner_and_tests(make_staff):
    staff = make_staff()
    service = FavoritesService()

    with pytest.raises(ValueError):
        service.create_favorite(_payload(name=""), str(staff.id))
    with pytest.raises(ValueError):
        service.create_favorite(_payload(lab_partner_id=""), str(staff.id))
    with pytest.raises(ValueError):
        service.create_favorite(_payload(tests=[]), str(staff.id))


def test_create_unknown_staff_raises(make_staff):
    service = FavoritesService()
    with pytest.raises(ValueError):
        service.create_favorite(_payload(), "00000000-0000-0000-0000-000000000000")


def test_visibility_shared_mine_and_others(make_staff):
    me = make_staff(first_name="Me")
    other = make_staff(first_name="Other")
    service = FavoritesService()

    service.create_favorite(_payload(name="Shared by other", is_shared=True), str(other.id))
    service.create_favorite(_payload(name="Private of other", is_shared=False), str(other.id))
    service.create_favorite(_payload(name="My private", is_shared=False), str(me.id))

    names = {f["name"] for f in service.list_favorites(str(me.id))}

    assert "Shared by other" in names
    assert "My private" in names
    assert "Private of other" not in names


def test_filter_mine_and_shared(make_staff):
    me = make_staff(first_name="Me")
    other = make_staff(first_name="Other")
    service = FavoritesService()
    service.create_favorite(_payload(name="My shared", is_shared=True), str(me.id))
    service.create_favorite(_payload(name="Other shared", is_shared=True), str(other.id))

    mine = {f["name"] for f in service.list_favorites(str(me.id), visibility_filter="mine")}
    shared = {f["name"] for f in service.list_favorites(str(me.id), visibility_filter="shared")}

    assert mine == {"My shared"}
    assert shared == {"My shared", "Other shared"}


def test_search_matches_each_axis(make_staff):
    staff = make_staff(first_name="Gregory", last_name="House")
    service = FavoritesService()
    service.create_favorite(
        _payload(
            name="Morning Panel",
            lab_partner_name="Quest",
            tags=["fasting"],
            tests=[{"order_code": "ABC9", "order_name": "Comprehensive Metabolic", "cpt_code": ""}],
        ),
        str(staff.id),
    )

    assert service.list_favorites(str(staff.id), search="morning")
    assert service.list_favorites(str(staff.id), search="fasting")
    assert service.list_favorites(str(staff.id), search="house")  # author
    assert service.list_favorites(str(staff.id), search="metabolic")  # test name
    assert service.list_favorites(str(staff.id), search="abc9")  # test code
    assert service.list_favorites(str(staff.id), search="quest")  # lab
    assert service.list_favorites(str(staff.id), search="nomatch") == []


def test_get_favorite_respects_visibility(make_staff):
    me = make_staff(first_name="Me")
    other = make_staff(first_name="Other")
    service = FavoritesService()
    created = service.create_favorite(_payload(is_shared=False), str(other.id))

    assert service.get_favorite(created["id"], str(other.id)) is not None
    assert service.get_favorite(created["id"], str(me.id)) is None
    assert service.get_favorite("labfav_missing", str(me.id)) is None


def test_update_partial(make_staff):
    # Authorization lives in the API layer; the service updates by id.
    me = make_staff(first_name="Me")
    service = FavoritesService()
    created = service.create_favorite(_payload(name="Old"), str(me.id))

    updated = service.update_favorite(
        created["id"], {"name": "New", "is_shared": False}, str(me.id)
    )
    assert updated is not None
    assert updated["name"] == "New"
    assert updated["is_shared"] is False
    # Untouched fields remain.
    assert updated["tests"] == TESTS


def test_update_rejects_empty_name_and_empty_tests(make_staff):
    staff = make_staff()
    service = FavoritesService()
    created = service.create_favorite(_payload(), str(staff.id))

    with pytest.raises(ValueError):
        service.update_favorite(created["id"], {"name": "  "}, str(staff.id))
    with pytest.raises(ValueError):
        service.update_favorite(created["id"], {"tests": []}, str(staff.id))


def test_update_missing_favorite_returns_none(make_staff):
    staff = make_staff()
    service = FavoritesService()
    assert service.update_favorite("labfav_nope", {"name": "x"}, str(staff.id)) is None


def test_delete_by_id(make_staff):
    # Authorization lives in the API layer; the service deletes by id.
    me = make_staff(first_name="Me")
    service = FavoritesService()
    created = service.create_favorite(_payload(), str(me.id))

    assert service.delete_favorite(created["id"]) is True
    assert service.delete_favorite(created["id"]) is False  # already gone


def test_list_for_anonymous_sees_only_shared(make_staff):
    staff = make_staff()
    service = FavoritesService()
    service.create_favorite(_payload(name="Shared", is_shared=True), str(staff.id))
    service.create_favorite(_payload(name="Private", is_shared=False), str(staff.id))

    names = {f["name"] for f in service.list_favorites(None)}
    assert names == {"Shared"}


# --- pure helper coverage ---

def test_normalize_helpers():
    assert _normalize_tags(["A", "a", " b ", ""]) == ["a", "b"]
    assert _normalize_codes(["Z00.00", "  ", "E11.9"]) == ["Z00.00", "E11.9"]
    assert _normalize_tests([{"order_code": "1", "order_name": "G", "cpt_code": "9"}, "junk"]) == [
        {"order_code": "1", "order_name": "G", "cpt_code": "9"}
    ]


def test_update_all_optional_fields(make_staff):
    staff = make_staff()
    service = FavoritesService()
    created = service.create_favorite(_payload(), str(staff.id))

    updated = service.update_favorite(
        created["id"],
        {
            "lab_partner_id": "partner-2",
            "lab_partner_name": "Quest",
            "tags": ["NEW", "new"],
            "fasting_required": False,
            "comment": "  changed  ",
            "diagnosis_codes": ["E11.9", ""],
        },
        str(staff.id),
    )

    assert updated is not None
    assert updated["lab_partner_id"] == "partner-2"
    assert updated["lab_partner_name"] == "Quest"
    assert updated["tags"] == ["new"]
    assert updated["fasting_required"] is False
    assert updated["comment"] == "changed"
    assert updated["diagnosis_codes"] == ["E11.9"]


def test_list_is_mine_false_for_non_owner(make_staff):
    me = make_staff(first_name="Me")
    other = make_staff(first_name="Other")
    service = FavoritesService()
    service.create_favorite(_payload(name="Shared", is_shared=True), str(other.id))

    [fav] = service.list_favorites(str(me.id), search="Shared")
    assert fav["is_mine"] is False
    assert fav["created_by_name"] == "Other Provider"


def test_matches_helper():
    fav = {
        "name": "Panel",
        "lab_partner_name": "Quest",
        "created_by_name": "House",
        "tags": ["fasting"],
        "tests": [{"order_name": "Glucose", "order_code": "001"}],
    }
    assert _matches(fav, "glucose")
    assert _matches(fav, "quest")
    assert not _matches(fav, "zzz")
