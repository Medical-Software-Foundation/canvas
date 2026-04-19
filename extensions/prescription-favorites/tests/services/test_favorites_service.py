"""Tests for FavoritesService."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from prescription_favorites.medications import FAVORITE_MEDICATIONS
from prescription_favorites.models.custom_favorite import CustomFavorite


def _mock_staff(staff_uuid: str = "staff-uuid-123", first_name: str = "", last_name: str = "") -> MagicMock:
    """Create a mock Staff/CustomStaff object."""
    staff = MagicMock()
    staff.id = staff_uuid
    staff.first_name = first_name
    staff.last_name = last_name
    return staff


def _mock_favorite(**overrides: Any) -> MagicMock:
    """Create a mock CustomFavorite instance.

    If created_by is not explicitly provided, defaults to None (no creator).
    Pass created_by=_mock_staff("some-uuid") to simulate a creator.
    """
    defaults = {
        "dbid": 1,
        "custom_id": "custom_test123",
        "display_name": "Custom Med",
        "label": "",
        "label_color": "",
        "medication_name": "custom medication 10mg",
        "fdb_code": "999999",
        "sig": "Take as directed",
        "days_supply": 30,
        "quantity_to_dispense": Decimal("30.00"),
        "unit": "Tablet",
        "refills": 0,
        "representative_ndc": "12345678901",
        "ncpdp_quantity_qualifier_code": "EA",
        "generic_substitution_allowed": True,
        "search_terms": [],
        "default_pharmacy_ncpdp_id": "",
        "default_pharmacy_name": "",
        "is_shared": True,
        "created_by": None,
        "created_at": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, val in defaults.items():
        setattr(mock, key, val)
    return mock


def _qs_mock(items: list[MagicMock] | None = None) -> MagicMock:
    """Create a mock queryset that supports select_related().all().order_by() chaining.

    The terminal mock supports iteration (for list()) and .filter() for further chaining.
    """
    qs = MagicMock()
    final = items if items is not None else []
    # Terminal queryset mock that supports both iteration and .filter()
    terminal = MagicMock()
    terminal.__iter__ = MagicMock(return_value=iter(final))
    terminal.filter.return_value = final
    qs.select_related.return_value.all.return_value.order_by.return_value = terminal
    return qs


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_all_favorites_returns_hardcoded_and_custom(mock_model: MagicMock) -> None:
    """Test get_all_favorites returns both hardcoded and custom favorites."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_model.objects = _qs_mock([_mock_favorite()])

    service = FavoritesService()
    result = service.get_all_favorites()

    assert len(result) == len(FAVORITE_MEDICATIONS) + 1
    custom_results = [r for r in result if r.get("is_custom") is True]
    assert len(custom_results) == 1
    assert custom_results[0]["id"] == "custom_test123"


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_all_favorites_with_no_custom(mock_model: MagicMock) -> None:
    """Test get_all_favorites with no custom favorites."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_model.objects = _qs_mock([])

    service = FavoritesService()
    result = service.get_all_favorites()

    assert len(result) == len(FAVORITE_MEDICATIONS)
    for fav in result:
        assert fav["is_custom"] is False


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_custom_favorites_returns_only_custom(mock_model: MagicMock) -> None:
    """Test get_custom_favorites returns only custom favorites."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_model.objects = _qs_mock([
        _mock_favorite(custom_id="custom_1", display_name="Custom 1"),
        _mock_favorite(custom_id="custom_2", display_name="Custom 2"),
    ])

    service = FavoritesService()
    result = service.get_custom_favorites()

    assert len(result) == 2
    display_names = {r["display_name"] for r in result}
    assert display_names == {"Custom 1", "Custom 2"}


@patch("prescription_favorites.services.favorites_service.CustomStaff")
@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_save_custom_favorite_creates_new(mock_model: MagicMock, mock_custom_staff: MagicMock) -> None:
    """Test save_custom_favorite creates a new favorite."""
    from prescription_favorites.services.favorites_service import FavoritesService

    created = _mock_favorite()
    mock_model.objects.create.return_value = created
    mock_custom_staff.objects.get.return_value = _mock_staff()

    service = FavoritesService()
    med_config = {
        "display_name": "Test Med",
        "fdb_code": "123456",
        "sig": "Take daily",
        "days_supply": 30,
        "quantity_to_dispense": 30,
        "unit": "Tablet",
        "refills": 2,
        "representative_ndc": "12345678901",
        "ncpdp_quantity_qualifier_code": "EA",
    }

    result = service.save_custom_favorite(med_config)

    mock_model.objects.create.assert_called_once()
    assert result["is_custom"] is True
    assert result["display_name"] == "Custom Med"


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_update_custom_favorite_updates_existing(mock_model: MagicMock) -> None:
    """Test update_custom_favorite updates an existing favorite."""
    from prescription_favorites.services.favorites_service import FavoritesService

    existing = _mock_favorite(custom_id="custom_existing", display_name="Old Name")
    mock_model.objects.select_related.return_value.get.return_value = existing

    service = FavoritesService()
    result = service.update_custom_favorite("custom_existing", {
        "display_name": "New Name",
        "sig": "Updated sig",
    })

    assert result is not None
    existing.save.assert_called_once()


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_update_custom_favorite_returns_none_for_nonexistent(mock_model: MagicMock) -> None:
    """Test update_custom_favorite returns None for non-existent ID."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_model.DoesNotExist = CustomFavorite.DoesNotExist
    mock_model.objects.select_related.return_value.get.side_effect = CustomFavorite.DoesNotExist

    service = FavoritesService()
    result = service.update_custom_favorite("custom_nonexistent", {"display_name": "X"})

    assert result is None


def test_update_non_custom_favorite_returns_none() -> None:
    """Test update_custom_favorite returns None for non-custom IDs."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    result = service.update_custom_favorite("wegovy_0.25mg", {"display_name": "X"})

    assert result is None


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_delete_custom_favorite_removes_favorite(mock_model: MagicMock) -> None:
    """Test delete_custom_favorite removes the favorite."""
    from prescription_favorites.services.favorites_service import FavoritesService

    existing = _mock_favorite(custom_id="custom_2")
    mock_model.objects.get.return_value = existing

    service = FavoritesService()
    result = service.delete_custom_favorite("custom_2")

    assert result is True
    existing.delete.assert_called_once()


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_delete_custom_favorite_returns_false_for_nonexistent(mock_model: MagicMock) -> None:
    """Test delete_custom_favorite returns False for non-existent ID."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_model.DoesNotExist = CustomFavorite.DoesNotExist
    mock_model.objects.get.side_effect = CustomFavorite.DoesNotExist

    service = FavoritesService()
    result = service.delete_custom_favorite("custom_nonexistent")

    assert result is False


def test_delete_non_custom_favorite_returns_false() -> None:
    """Test delete_custom_favorite returns False for non-custom IDs."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    result = service.delete_custom_favorite("wegovy_0.25mg")

    assert result is False


def test_is_custom_favorite_returns_true_for_custom() -> None:
    """Test is_custom_favorite returns True for custom IDs."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    assert service.is_custom_favorite("custom_123") is True
    assert service.is_custom_favorite("custom_abc") is True


def test_is_custom_favorite_returns_false_for_hardcoded() -> None:
    """Test is_custom_favorite returns False for hardcoded IDs."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    assert service.is_custom_favorite("wegovy_0.25mg") is False
    assert service.is_custom_favorite("ondansetron_4mg") is False


def test_get_favorite_by_id_returns_hardcoded() -> None:
    """Test get_favorite_by_id returns hardcoded favorites."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    result = service.get_favorite_by_id("wegovy_0.25mg")

    assert result is not None
    assert result["id"] == "wegovy_0.25mg"
    assert result["fdb_code"] == "606783"
    assert result["is_custom"] is False


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_favorite_by_id_returns_custom(mock_model: MagicMock) -> None:
    """Test get_favorite_by_id returns custom favorites."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_model.objects.select_related.return_value.get.return_value = _mock_favorite(
        custom_id="custom_xyz", display_name="Custom Med"
    )

    service = FavoritesService()
    result = service.get_favorite_by_id("custom_xyz")

    assert result is not None
    assert result["id"] == "custom_xyz"
    assert result["display_name"] == "Custom Med"
    assert result["is_custom"] is True


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_favorite_by_id_returns_none_for_nonexistent(mock_model: MagicMock) -> None:
    """Test get_favorite_by_id returns None for non-existent ID."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_model.DoesNotExist = CustomFavorite.DoesNotExist
    mock_model.objects.select_related.return_value.get.side_effect = CustomFavorite.DoesNotExist

    service = FavoritesService()
    result = service.get_favorite_by_id("nonexistent_id")

    assert result is None


# ---------------------------------------------------------------------------
# get_all_favorites - staff_id and visibility filtering
# ---------------------------------------------------------------------------


def _mock_hidden_default(default_id: str, staff_uuid: str = "staff-uuid-123", first_name: str = "Jane", last_name: str = "Doe") -> MagicMock:
    """Create a mock HiddenDefault with a related hidden_by staff object."""
    hd = MagicMock()
    hd.default_id = default_id
    hd.hidden_by = _mock_staff(staff_uuid, first_name=first_name, last_name=last_name)
    return hd


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_get_all_favorites_with_staff_id_queries_hidden_defaults(mock_hidden: MagicMock, mock_model: MagicMock) -> None:
    """Test that get_all_favorites queries HiddenDefault when staff_id is provided."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_hidden.objects.select_related.return_value.filter.return_value = []
    qs_mock = MagicMock()
    qs_mock.filter.return_value = []
    mock_model.objects.select_related.return_value.all.return_value.order_by.return_value = qs_mock

    service = FavoritesService()
    result = service.get_all_favorites(staff_id="staff-uuid-123")

    mock_hidden.objects.select_related.return_value.filter.assert_called_once_with(hidden_by__id="staff-uuid-123")


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_get_all_favorites_hides_hidden_defaults(mock_hidden: MagicMock, mock_model: MagicMock) -> None:
    """Test that hidden defaults are excluded when include_hidden is False."""
    from prescription_favorites.services.favorites_service import FavoritesService

    first_id = next(iter(FAVORITE_MEDICATIONS.keys()))
    mock_hidden.objects.select_related.return_value.filter.return_value = [
        _mock_hidden_default(first_id),
    ]
    qs_mock = MagicMock()
    qs_mock.filter.return_value = []
    mock_model.objects.select_related.return_value.all.return_value.order_by.return_value = qs_mock

    service = FavoritesService()
    result = service.get_all_favorites(staff_id="staff-uuid-123", include_hidden=False)

    result_ids = [r["id"] for r in result if not r.get("is_custom")]
    assert first_id not in result_ids


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_get_all_favorites_includes_hidden_when_flag_set(mock_hidden: MagicMock, mock_model: MagicMock) -> None:
    """Test that hidden defaults are included with is_hidden=True and hidden_by_name when include_hidden=True."""
    from prescription_favorites.services.favorites_service import FavoritesService

    first_id = next(iter(FAVORITE_MEDICATIONS.keys()))
    mock_hidden.objects.select_related.return_value.filter.return_value = [
        _mock_hidden_default(first_id, first_name="Jane", last_name="Doe"),
    ]
    qs_mock = MagicMock()
    qs_mock.filter.return_value = []
    mock_model.objects.select_related.return_value.all.return_value.order_by.return_value = qs_mock

    service = FavoritesService()
    result = service.get_all_favorites(staff_id="staff-uuid-123", include_hidden=True)

    hidden_results = [r for r in result if r.get("id") == first_id and not r.get("is_custom")]
    assert len(hidden_results) == 1
    assert hidden_results[0]["is_hidden"] is True
    assert hidden_results[0]["hidden_by_name"] == "Jane Doe"


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_get_all_favorites_visibility_filter_mine(mock_hidden: MagicMock, mock_model: MagicMock) -> None:
    """Test get_all_favorites with visibility_filter='mine' skips hardcoded defaults."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_hidden.objects.select_related.return_value.filter.return_value = []
    staff = _mock_staff("staff-uuid-123")
    fav = _mock_favorite(custom_id="custom_mine", created_by=staff)
    qs_mock = MagicMock()
    qs_mock.filter.return_value = [fav]
    mock_model.objects.select_related.return_value.all.return_value.order_by.return_value = qs_mock

    service = FavoritesService()
    result = service.get_all_favorites(staff_id="staff-uuid-123", visibility_filter="mine")

    hardcoded = [r for r in result if not r.get("is_custom")]
    assert len(hardcoded) == 0
    custom = [r for r in result if r.get("is_custom")]
    assert len(custom) == 1
    assert custom[0]["id"] == "custom_mine"


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_get_all_favorites_visibility_filter_shared(mock_hidden: MagicMock, mock_model: MagicMock) -> None:
    """Test get_all_favorites with visibility_filter='shared' filters to shared custom favorites."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_hidden.objects.select_related.return_value.filter.return_value = []
    fav = _mock_favorite(custom_id="custom_shared", is_shared=True)
    qs_mock = MagicMock()
    qs_mock.filter.return_value = [fav]
    mock_model.objects.select_related.return_value.all.return_value.order_by.return_value = qs_mock

    service = FavoritesService()
    result = service.get_all_favorites(visibility_filter="shared")

    custom = [r for r in result if r.get("is_custom")]
    assert len(custom) == 1
    assert custom[0]["id"] == "custom_shared"


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_get_all_favorites_visibility_filter_all_with_staff_id(mock_hidden: MagicMock, mock_model: MagicMock) -> None:
    """Test get_all_favorites with visibility_filter='all' and staff_id uses Q filter."""
    from prescription_favorites.services.favorites_service import FavoritesService

    mock_hidden.objects.select_related.return_value.filter.return_value = []
    staff = _mock_staff("staff-uuid-456")
    fav = _mock_favorite(custom_id="custom_all", created_by=staff)
    qs_mock = MagicMock()
    qs_mock.filter.return_value = [fav]
    mock_model.objects.select_related.return_value.all.return_value.order_by.return_value = qs_mock

    service = FavoritesService()
    result = service.get_all_favorites(staff_id="staff-uuid-456", visibility_filter="all")

    qs_mock.filter.assert_called_once()
    custom = [r for r in result if r.get("is_custom")]
    assert len(custom) == 1


# ---------------------------------------------------------------------------
# update_custom_favorite - individual field updates
# ---------------------------------------------------------------------------


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_update_custom_favorite_updates_all_fields(mock_model: MagicMock) -> None:
    """Test update_custom_favorite updates every supported field individually."""
    from prescription_favorites.services.favorites_service import FavoritesService

    existing = _mock_favorite(custom_id="custom_full")
    mock_model.objects.select_related.return_value.get.return_value = existing

    service = FavoritesService()
    config = {
        "label": "New Label",
        "label_color": "blue",
        "medication_name": "Updated Med Name",
        "fdb_code": "111111",
        "sig": "Take twice daily",
        "days_supply": 60,
        "quantity_to_dispense": 60.0,
        "unit": "Capsule",
        "refills": 3,
        "representative_ndc": "99999999999",
        "ncpdp_quantity_qualifier_code": "C62",
        "generic_substitution_allowed": False,
        "search_terms": ["test", "terms"],
        "default_pharmacy_ncpdp_id": "7654321",
        "default_pharmacy_name": "Test Pharmacy",
        "is_shared": False,
    }

    result = service.update_custom_favorite("custom_full", config)

    assert result is not None
    assert existing.label == "New Label"
    assert existing.label_color == "blue"
    assert existing.medication_name == "Updated Med Name"
    assert existing.fdb_code == "111111"
    assert existing.sig == "Take twice daily"
    assert existing.days_supply == 60
    assert existing.quantity_to_dispense == Decimal("60.0")
    assert existing.unit == "Capsule"
    assert existing.refills == 3
    assert existing.representative_ndc == "99999999999"
    assert existing.ncpdp_quantity_qualifier_code == "C62"
    assert existing.generic_substitution_allowed is False
    assert existing.search_terms == ["test", "terms"]
    assert existing.default_pharmacy_ncpdp_id == "7654321"
    assert existing.default_pharmacy_name == "Test Pharmacy"
    assert existing.is_shared is False
    existing.save.assert_called_once()


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_update_custom_favorite_clears_optional_fields(mock_model: MagicMock) -> None:
    """Test update_custom_favorite clears label and pharmacy fields when set to None/empty."""
    from prescription_favorites.services.favorites_service import FavoritesService

    existing = _mock_favorite(custom_id="custom_clear", label="Old Label", default_pharmacy_ncpdp_id="123")
    mock_model.objects.select_related.return_value.get.return_value = existing

    service = FavoritesService()
    result = service.update_custom_favorite("custom_clear", {
        "label": None,
        "default_pharmacy_ncpdp_id": None,
        "default_pharmacy_name": None,
    })

    assert result is not None
    assert existing.label == ""
    assert existing.default_pharmacy_ncpdp_id == ""
    assert existing.default_pharmacy_name == ""


# ---------------------------------------------------------------------------
# get_favorites_by_ids
# ---------------------------------------------------------------------------


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_favorites_by_ids_returns_hardcoded_from_memory(mock_model: MagicMock) -> None:
    """Test get_favorites_by_ids returns hardcoded favorites without a DB query."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    first_id = next(iter(FAVORITE_MEDICATIONS.keys()))
    result = service.get_favorites_by_ids([first_id])

    assert first_id in result
    assert result[first_id]["is_custom"] is False
    mock_model.objects.select_related.return_value.filter.assert_not_called()


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_favorites_by_ids_returns_custom_from_db(mock_model: MagicMock) -> None:
    """Test get_favorites_by_ids fetches custom favorites in a single DB query."""
    from prescription_favorites.services.favorites_service import FavoritesService

    fav = _mock_favorite(custom_id="custom_batch1")
    # Chain: .filter(custom_id__in=...).filter(is_shared=True) returns iterable
    inner_qs = MagicMock()
    inner_qs.filter.return_value = [fav]
    inner_qs.__iter__ = lambda self: iter([fav])
    mock_model.objects.select_related.return_value.filter.return_value = inner_qs

    service = FavoritesService()
    result = service.get_favorites_by_ids(["custom_batch1"])

    assert "custom_batch1" in result
    assert result["custom_batch1"]["is_custom"] is True


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_favorites_by_ids_mixes_hardcoded_and_custom(mock_model: MagicMock) -> None:
    """Test get_favorites_by_ids handles a list containing both kinds of IDs."""
    from prescription_favorites.services.favorites_service import FavoritesService

    fav = _mock_favorite(custom_id="custom_mix")
    inner_qs = MagicMock()
    inner_qs.filter.return_value = [fav]
    inner_qs.__iter__ = lambda self: iter([fav])
    mock_model.objects.select_related.return_value.filter.return_value = inner_qs

    first_id = next(iter(FAVORITE_MEDICATIONS.keys()))
    service = FavoritesService()
    result = service.get_favorites_by_ids([first_id, "custom_mix"])

    assert first_id in result
    assert "custom_mix" in result
    assert result[first_id]["is_custom"] is False
    assert result["custom_mix"]["is_custom"] is True


@patch("prescription_favorites.services.favorites_service.CustomFavorite")
def test_get_favorites_by_ids_empty_list_returns_empty_dict(mock_model: MagicMock) -> None:
    """Test get_favorites_by_ids with an empty list returns an empty dict."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    result = service.get_favorites_by_ids([])

    assert result == {}


# ---------------------------------------------------------------------------
# hide_default / unhide_default
# ---------------------------------------------------------------------------


@patch("prescription_favorites.services.favorites_service.CustomStaff")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_hide_default_calls_get_or_create(mock_hidden: MagicMock, mock_custom_staff: MagicMock) -> None:
    """Test hide_default resolves staff by UUID and calls get_or_create."""
    from prescription_favorites.services.favorites_service import FavoritesService

    staff = _mock_staff("staff-abc")
    mock_custom_staff.objects.get.return_value = staff
    mock_hidden.objects.get_or_create.return_value = (MagicMock(), True)

    service = FavoritesService()
    first_id = next(iter(FAVORITE_MEDICATIONS.keys()))
    result = service.hide_default(first_id, "staff-abc")

    assert result is True
    mock_custom_staff.objects.get.assert_called_once_with(id="staff-abc")
    mock_hidden.objects.get_or_create.assert_called_once_with(
        default_id=first_id, hidden_by=staff
    )


@patch("prescription_favorites.services.favorites_service.CustomStaff")
@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_hide_default_returns_false_for_unknown_id(mock_hidden: MagicMock, mock_custom_staff: MagicMock) -> None:
    """Test hide_default returns False when the ID is not a default favorite."""
    from prescription_favorites.services.favorites_service import FavoritesService

    service = FavoritesService()
    result = service.hide_default("not_a_default_id", "staff-abc")

    assert result == "Not a default favorite"
    mock_hidden.objects.get_or_create.assert_not_called()


@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_unhide_default_deletes_hidden_record(mock_hidden: MagicMock) -> None:
    """Test unhide_default deletes the HiddenDefault record when it exists."""
    from prescription_favorites.services.favorites_service import FavoritesService

    hidden_record = MagicMock()
    mock_hidden.objects.get.return_value = hidden_record

    service = FavoritesService()
    first_id = next(iter(FAVORITE_MEDICATIONS.keys()))
    result = service.unhide_default(first_id, "staff-abc")

    assert result is True
    mock_hidden.objects.get.assert_called_once_with(default_id=first_id, hidden_by__id="staff-abc")
    hidden_record.delete.assert_called_once()


@patch("prescription_favorites.services.favorites_service.HiddenDefault")
def test_unhide_default_returns_false_when_not_hidden(mock_hidden: MagicMock) -> None:
    """Test unhide_default returns False when no record exists (already visible)."""
    from prescription_favorites.services.favorites_service import FavoritesService
    from prescription_favorites.models import HiddenDefault

    mock_hidden.DoesNotExist = HiddenDefault.DoesNotExist
    mock_hidden.objects.get.side_effect = HiddenDefault.DoesNotExist

    service = FavoritesService()
    result = service.unhide_default("wegovy_0.25mg", "staff-abc")

    assert result is False


# ---------------------------------------------------------------------------
# _to_dict - staff name from select_related
# ---------------------------------------------------------------------------


def test_to_dict_includes_creator_name_from_related_object() -> None:
    """Test _to_dict extracts creator UUID and name from the related Staff object."""
    from prescription_favorites.services.favorites_service import FavoritesService

    staff = _mock_staff("uuid-staff-1", first_name="Jane", last_name="Smith")
    fav = _mock_favorite(created_by=staff)

    service = FavoritesService()
    result = service._to_dict(fav, staff_id="uuid-staff-1")

    assert result["created_by_id"] == "uuid-staff-1"
    assert result["created_by_name"] == "Jane Smith"
    assert result["is_mine"] is True


def test_to_dict_handles_no_creator() -> None:
    """Test _to_dict handles a favorite with no creator (legacy data)."""
    from prescription_favorites.services.favorites_service import FavoritesService

    fav = _mock_favorite(created_by=None)

    service = FavoritesService()
    result = service._to_dict(fav, staff_id="some-staff-id")

    assert result["created_by_id"] is None
    assert result["created_by_name"] is None
    assert result["is_mine"] is False
