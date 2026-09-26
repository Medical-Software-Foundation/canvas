"""Tests for FavoritesService."""

import datetime
from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from clinical_favorites.services import FavoritesService


@pytest.fixture
def mock_model() -> Iterator[MagicMock]:
    with patch("clinical_favorites.services.favorites_service.ClinicalFavorite") as m:
        queryset = MagicMock()
        queryset.__iter__ = MagicMock(return_value=iter([]))
        queryset.filter.return_value = queryset
        queryset.order_by.return_value = queryset
        queryset.all.return_value = queryset
        m.objects.select_related.return_value = queryset
        m.objects.all.return_value = queryset
        m.objects.filter.return_value = queryset
        yield m


@pytest.fixture
def mock_staff() -> Iterator[MagicMock]:
    with patch("clinical_favorites.services.favorites_service.CustomStaff") as m:
        yield m


def test_get_all_favorites_empty(mock_model: MagicMock) -> None:
    service = FavoritesService()
    favorites = service.get_all_favorites(staff_id="s1", visibility_filter="all")
    assert favorites == []


def test_is_custom_favorite_prefix_check() -> None:
    service = FavoritesService()
    assert service.is_custom_favorite("custom_abc123") is True
    assert service.is_custom_favorite("default_wegovy") is False


def test_save_medication_favorite_requires_fields(mock_model: MagicMock, mock_staff: MagicMock) -> None:
    service = FavoritesService()
    with pytest.raises(ValueError, match="Missing required fields"):
        service.save_favorite(
            favorite_type="medication",
            payload={"display_name": "Wegovy"},
            staff_id="s1",
        )


def test_save_condition_favorite_minimal_fields(mock_model: MagicMock, mock_staff: MagicMock) -> None:
    mock_staff.objects.get.return_value = MagicMock(dbid=1)
    created = MagicMock()
    mock_model.objects.create.return_value = created

    service = FavoritesService()
    result = service.save_favorite(
        favorite_type="condition",
        payload={"code": "E11.9", "display_name": "Type 2 diabetes"},
        staff_id="s1",
    )

    assert result is not None
    mock_model.objects.create.assert_called_once()
    kwargs = mock_model.objects.create.call_args.kwargs
    assert kwargs["favorite_type"] == "condition"
    assert kwargs["code"] == "E11.9"
    assert kwargs["fdb_code"] == ""


def test_update_favorite_applies_all_field_types(mock_model: MagicMock) -> None:
    existing = MagicMock()
    existing.quantity_to_dispense = None
    existing.created_at = None
    existing.created_by = None
    mock_model.objects.get.return_value = existing
    mock_model.objects.filter.return_value.get.return_value = existing

    service = FavoritesService()
    result = service.update_favorite(
        "custom_xyz",
        {
            "display_name": "New",
            "sig": "New sig",
            "days_supply": 20,
            "quantity_to_dispense": "2.5",
            "refills": 3,
            "generic_substitution_allowed": False,
            "search_terms": ["a", "b"],
            "is_shared": True,
        },
    )

    mock_model.objects.filter.assert_any_call(custom_id="custom_xyz")
    mock_model.objects.filter.return_value.update.assert_called_once()
    update_kwargs = mock_model.objects.filter.return_value.update.call_args.kwargs
    assert update_kwargs["display_name"] == "New"
    assert update_kwargs["sig"] == "New sig"
    assert update_kwargs["days_supply"] == 20
    assert update_kwargs["quantity_to_dispense"] == Decimal("2.5")
    assert update_kwargs["refills"] == 3
    assert update_kwargs["generic_substitution_allowed"] is False
    assert update_kwargs["search_terms"] == ["a", "b"]
    assert update_kwargs["is_shared"] is True
    assert result is not None


def test_update_favorite_empty_payload_skips_update_call(mock_model: MagicMock) -> None:
    existing = MagicMock()
    existing.quantity_to_dispense = None
    existing.created_at = None
    existing.created_by = None
    mock_model.objects.get.return_value = existing
    mock_model.objects.filter.return_value.get.return_value = existing

    service = FavoritesService()
    result = service.update_favorite("custom_xyz", {})

    mock_model.objects.filter.return_value.update.assert_not_called()
    assert result is not None


def test_update_favorite_returns_none_when_row_missing(mock_model: MagicMock) -> None:
    from clinical_favorites.models import ClinicalFavorite as RealModel

    mock_model.objects.get.side_effect = RealModel.DoesNotExist
    mock_model.DoesNotExist = RealModel.DoesNotExist

    service = FavoritesService()
    result = service.update_favorite("custom_missing", {"display_name": "x"})

    assert result is None
    mock_model.objects.filter.return_value.update.assert_not_called()


def test_save_medication_favorite_persists_group_name(
    mock_model: MagicMock, mock_staff: MagicMock
) -> None:
    mock_staff.objects.get.return_value = MagicMock(dbid=1)
    created = MagicMock()
    created.group_name = "GLP 1"
    mock_model.objects.create.return_value = created

    service = FavoritesService()
    service.save_favorite(
        favorite_type="medication",
        payload={
            "display_name": "Wegovy 0.25mg",
            "fdb_code": "1234",
            "sig": "take weekly",
            "days_supply": 30,
            "quantity_to_dispense": "1.0",
            "unit": "pen",
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "group_name": "GLP 1",
        },
        staff_id="s1",
    )

    kwargs = mock_model.objects.create.call_args.kwargs
    assert kwargs["group_name"] == "GLP 1"
    assert kwargs["favorite_type"] == "medication"


def test_save_condition_favorite_persists_group_name(
    mock_model: MagicMock, mock_staff: MagicMock
) -> None:
    mock_staff.objects.get.return_value = MagicMock(dbid=1)
    created = MagicMock()
    mock_model.objects.create.return_value = created

    service = FavoritesService()
    service.save_favorite(
        favorite_type="condition",
        payload={
            "code": "E11.9",
            "display_name": "Type 2 diabetes",
            "group_name": "Endocrine",
        },
        staff_id="s1",
    )

    kwargs = mock_model.objects.create.call_args.kwargs
    assert kwargs["group_name"] == "Endocrine"
    assert kwargs["favorite_type"] == "condition"


def test_update_favorite_changes_group_name(mock_model: MagicMock) -> None:
    existing = MagicMock()
    existing.quantity_to_dispense = None
    existing.created_at = None
    existing.created_by = None
    mock_model.objects.get.return_value = existing
    mock_model.objects.filter.return_value.get.return_value = existing

    service = FavoritesService()
    service.update_favorite("custom_xyz", {"group_name": "Antibiotics"})

    update_kwargs = mock_model.objects.filter.return_value.update.call_args.kwargs
    assert update_kwargs["group_name"] == "Antibiotics"


def test_update_favorite_clears_group_name_with_empty_string(mock_model: MagicMock) -> None:
    existing = MagicMock()
    existing.quantity_to_dispense = None
    existing.created_at = None
    existing.created_by = None
    mock_model.objects.get.return_value = existing
    mock_model.objects.filter.return_value.get.return_value = existing

    service = FavoritesService()
    service.update_favorite("custom_xyz", {"group_name": ""})

    update_kwargs = mock_model.objects.filter.return_value.update.call_args.kwargs
    assert update_kwargs["group_name"] == ""


def _valid_medication_payload() -> dict:
    return {
        "favorite_type": "medication",
        "display_name": "Wegovy",
        "fdb_code": "1234",
        "sig": "take once weekly",
        "days_supply": 30,
        "quantity_to_dispense": "1",
        "unit": "syringe",
        "representative_ndc": "ndc",
        "ncpdp_quantity_qualifier_code": "00",
    }


def test_validate_favorite_payload_accepts_valid_medication() -> None:
    service = FavoritesService()
    assert service.validate_favorite_payload("medication", _valid_medication_payload()) is None


def test_validate_favorite_payload_accepts_valid_condition() -> None:
    service = FavoritesService()
    payload = {"favorite_type": "condition", "code": "E11.9", "display_name": "Diabetes"}
    assert service.validate_favorite_payload("condition", payload) is None


def test_validate_favorite_payload_rejects_unknown_type() -> None:
    service = FavoritesService()
    reason = service.validate_favorite_payload("procedure", {"display_name": "Foo"})
    assert reason == "favorite_type must be medication or condition"


def test_validate_favorite_payload_rejects_missing_medication_field() -> None:
    service = FavoritesService()
    payload = _valid_medication_payload()
    payload.pop("sig")
    reason = service.validate_favorite_payload("medication", payload)
    assert reason is not None
    assert "Missing required fields" in reason
    assert "sig" in reason


def test_validate_favorite_payload_rejects_missing_condition_field() -> None:
    service = FavoritesService()
    reason = service.validate_favorite_payload("condition", {"display_name": "Diabetes"})
    assert reason is not None
    assert "code" in reason


def test_validate_favorite_payload_rejects_non_dict() -> None:
    service = FavoritesService()
    reason = service.validate_favorite_payload("medication", "not a dict")
    assert reason == "Row is not an object"


def test_validate_favorite_payload_rejects_non_integer_days_supply() -> None:
    service = FavoritesService()
    payload = _valid_medication_payload()
    payload["days_supply"] = "abc"
    reason = service.validate_favorite_payload("medication", payload)
    assert reason == "days_supply must be an integer"


def test_validate_favorite_payload_rejects_non_decimal_quantity() -> None:
    service = FavoritesService()
    payload = _valid_medication_payload()
    payload["quantity_to_dispense"] = "not-a-number"
    reason = service.validate_favorite_payload("medication", payload)
    assert reason == "quantity_to_dispense must be a decimal"


def test_save_favorite_uses_validator(mock_model: MagicMock, mock_staff: MagicMock) -> None:
    service = FavoritesService()
    with pytest.raises(ValueError, match="favorite_type must be medication or condition"):
        service.save_favorite(
            favorite_type="procedure",
            payload={"display_name": "Foo"},
            staff_id="s1",
        )


def test_get_all_favorites_with_type_filter(mock_model: MagicMock) -> None:
    service = FavoritesService()
    service.get_all_favorites(staff_id="s1", favorite_type="condition")

    queryset = mock_model.objects.select_related.return_value
    filter_calls = queryset.filter.call_args_list
    assert any(call.kwargs == {"favorite_type": "condition"} for call in filter_calls)


def test_get_all_favorites_visibility_mine_filters_by_creator(
    mock_model: MagicMock,
) -> None:
    service = FavoritesService()
    service.get_all_favorites(staff_id="s1", visibility_filter="mine")

    queryset = mock_model.objects.select_related.return_value
    filter_calls = queryset.filter.call_args_list
    assert any(call.kwargs == {"created_by__id": "s1"} for call in filter_calls)


def test_get_all_favorites_visibility_shared_filters_by_shared_flag(
    mock_model: MagicMock,
) -> None:
    service = FavoritesService()
    service.get_all_favorites(staff_id=None, visibility_filter="shared")

    queryset = mock_model.objects.select_related.return_value
    filter_calls = queryset.filter.call_args_list
    assert any(call.kwargs == {"is_shared": True} for call in filter_calls)


def test_validate_favorite_payload_rejects_non_integer_refills() -> None:
    service = FavoritesService()
    payload = _valid_medication_payload()
    payload["refills"] = "many"
    reason = service.validate_favorite_payload("medication", payload)
    assert reason == "refills must be an integer"


def test_validate_favorite_payload_allows_none_refills() -> None:
    service = FavoritesService()
    payload = _valid_medication_payload()
    payload["refills"] = None
    assert service.validate_favorite_payload("medication", payload) is None


def test_save_favorite_raises_when_staff_record_missing(
    mock_model: MagicMock, mock_staff: MagicMock
) -> None:
    from clinical_favorites.models import CustomStaff as RealStaff

    mock_staff.objects.get.side_effect = RealStaff.DoesNotExist
    mock_staff.DoesNotExist = RealStaff.DoesNotExist

    service = FavoritesService()
    with pytest.raises(ValueError, match="Staff record not found"):
        service.save_favorite(
            favorite_type="condition",
            payload={"code": "E11.9", "display_name": "Type 2 diabetes"},
            staff_id="s-missing",
        )


def test_update_favorite_clears_fdb_code_when_explicitly_set_to_none(
    mock_model: MagicMock,
) -> None:
    existing = MagicMock()
    existing.quantity_to_dispense = None
    existing.created_at = None
    existing.created_by = None
    mock_model.objects.get.return_value = existing
    mock_model.objects.filter.return_value.get.return_value = existing

    service = FavoritesService()
    service.update_favorite("custom_xyz", {"fdb_code": None})

    update_kwargs = mock_model.objects.filter.return_value.update.call_args.kwargs
    assert update_kwargs["fdb_code"] == ""


def test_delete_favorite_returns_true_when_row_exists(mock_model: MagicMock) -> None:
    queryset = mock_model.objects.filter.return_value
    queryset.delete.return_value = (1, {"clinical_favorites.ClinicalFavorite": 1})

    service = FavoritesService()
    assert service.delete_favorite("custom_abc") is True
    mock_model.objects.filter.assert_any_call(custom_id="custom_abc")
    queryset.delete.assert_called_once()


def test_delete_favorite_returns_false_when_row_missing(mock_model: MagicMock) -> None:
    queryset = mock_model.objects.filter.return_value
    queryset.delete.return_value = (0, {})

    service = FavoritesService()
    assert service.delete_favorite("custom_missing") is False
    queryset.delete.assert_called_once()


def test_get_favorite_by_id_returns_none_when_missing(mock_model: MagicMock) -> None:
    from clinical_favorites.models import ClinicalFavorite as RealModel

    mock_model.objects.select_related.return_value.get.side_effect = (
        RealModel.DoesNotExist
    )
    mock_model.DoesNotExist = RealModel.DoesNotExist

    service = FavoritesService()
    assert service.get_favorite_by_id("custom_missing") is None


def test_get_favorite_by_id_returns_dict_when_present(mock_model: MagicMock) -> None:
    favorite = MagicMock()
    favorite.custom_id = "custom_abc"
    favorite.favorite_type = "condition"
    favorite.code = "E11.9"
    favorite.display_name = "Type 2 diabetes"
    favorite.label = ""
    favorite.label_color = ""
    favorite.group_name = ""
    favorite.is_shared = True
    favorite.created_by = None
    favorite.created_at = None
    favorite.medication_name = ""
    favorite.fdb_code = ""
    favorite.sig = ""
    favorite.days_supply = None
    favorite.quantity_to_dispense = None
    favorite.unit = ""
    favorite.refills = 0
    favorite.representative_ndc = ""
    favorite.ncpdp_quantity_qualifier_code = ""
    favorite.generic_substitution_allowed = True
    favorite.search_terms = []
    favorite.default_pharmacy_ncpdp_id = ""
    favorite.default_pharmacy_name = ""
    favorite.note_to_pharmacist = ""
    mock_model.objects.select_related.return_value.get.return_value = favorite

    service = FavoritesService()
    result = service.get_favorite_by_id("custom_abc")
    assert result is not None
    assert result["id"] == "custom_abc"
    assert result["favorite_type"] == "condition"


def test_get_favorites_by_ids_filters_by_staff_visibility(mock_model: MagicMock) -> None:
    queryset = mock_model.objects.select_related.return_value
    queryset.filter.return_value = queryset
    queryset.__iter__.return_value = iter([])

    service = FavoritesService()
    result = service.get_favorites_by_ids(["a", "b"], staff_id="s1")
    assert result == {}

    filter_calls = [c for c in queryset.filter.call_args_list]
    assert any(c.kwargs == {"custom_id__in": ["a", "b"]} for c in filter_calls)


def test_get_favorites_by_ids_without_staff_filters_shared_only(
    mock_model: MagicMock,
) -> None:
    queryset = mock_model.objects.select_related.return_value
    queryset.filter.return_value = queryset
    queryset.__iter__.return_value = iter([])

    service = FavoritesService()
    result = service.get_favorites_by_ids(["a"], staff_id=None)
    assert result == {}

    filter_calls = queryset.filter.call_args_list
    assert any(c.kwargs == {"is_shared": True} for c in filter_calls)


def test_hide_default_returns_error_when_staff_missing(mock_staff: MagicMock) -> None:
    from clinical_favorites.models import CustomStaff as RealStaff

    mock_staff.objects.get.side_effect = RealStaff.DoesNotExist
    mock_staff.DoesNotExist = RealStaff.DoesNotExist

    service = FavoritesService()
    result = service.hide_default("wegovy_0.25mg", "medication", "s-missing")
    assert result == "Staff record not found"


def test_hide_default_creates_or_gets_record_for_known_staff(
    mock_staff: MagicMock,
) -> None:
    staff_obj = MagicMock()
    mock_staff.objects.get.return_value = staff_obj

    with patch(
        "clinical_favorites.services.favorites_service.HiddenDefault"
    ) as mock_hidden:
        mock_hidden.objects.get_or_create.return_value = (MagicMock(), True)

        service = FavoritesService()
        result = service.hide_default("wegovy_0.25mg", "medication", "s1")

        assert result is True
        mock_hidden.objects.get_or_create.assert_called_once_with(
            default_id="wegovy_0.25mg",
            favorite_type="medication",
            hidden_by=staff_obj,
        )


def test_unhide_default_returns_true_when_row_present() -> None:
    with patch(
        "clinical_favorites.services.favorites_service.HiddenDefault"
    ) as mock_hidden:
        hidden_row = MagicMock()
        mock_hidden.objects.get.return_value = hidden_row

        service = FavoritesService()
        assert service.unhide_default("wegovy_0.25mg", "s1") is True
        hidden_row.delete.assert_called_once()


def test_unhide_default_returns_false_when_row_missing() -> None:
    from clinical_favorites.models import HiddenDefault as RealHidden

    with patch(
        "clinical_favorites.services.favorites_service.HiddenDefault"
    ) as mock_hidden:
        mock_hidden.objects.get.side_effect = RealHidden.DoesNotExist
        mock_hidden.DoesNotExist = RealHidden.DoesNotExist

        service = FavoritesService()
        assert service.unhide_default("wegovy_0.25mg", "s1") is False


def test_save_favorite_coerces_explicit_null_refills_to_zero(
    mock_model: MagicMock, mock_staff: MagicMock
) -> None:
    mock_staff.objects.get.return_value = MagicMock(dbid=1)
    mock_model.objects.create.return_value = MagicMock()

    service = FavoritesService()
    payload = _valid_medication_payload()
    payload["refills"] = None

    service.save_favorite(
        favorite_type="medication",
        payload=payload,
        staff_id="s1",
    )

    create_kwargs = mock_model.objects.create.call_args.kwargs
    assert create_kwargs["refills"] == 0


def test_update_favorite_coerces_explicit_null_refills_to_zero(
    mock_model: MagicMock,
) -> None:
    existing = MagicMock()
    existing.quantity_to_dispense = None
    existing.created_at = None
    existing.created_by = None
    mock_model.objects.get.return_value = existing
    mock_model.objects.filter.return_value.get.return_value = existing

    service = FavoritesService()
    service.update_favorite("custom_x", {"refills": None})

    update_kwargs = (
        mock_model.objects.filter.return_value.update.call_args.kwargs
    )
    assert update_kwargs["refills"] == 0


def test_update_favorite_refreshes_updated_at_field(
    mock_model: MagicMock,
) -> None:
    existing = MagicMock()
    existing.quantity_to_dispense = None
    existing.created_at = None
    existing.created_by = None
    mock_model.objects.get.return_value = existing
    mock_model.objects.filter.return_value.get.return_value = existing

    service = FavoritesService()
    service.update_favorite("custom_x", {"display_name": "New name"})

    update_kwargs = (
        mock_model.objects.filter.return_value.update.call_args.kwargs
    )
    assert "updated_at" in update_kwargs
    assert isinstance(update_kwargs["updated_at"], datetime.datetime)
    assert update_kwargs["updated_at"].tzinfo is not None


def test_to_dict_includes_creator_metadata_when_creator_present(
    mock_model: MagicMock,
) -> None:
    creator = MagicMock()
    creator.id = "s1"
    creator.first_name = "Jane"
    creator.last_name = "Doe"

    favorite = MagicMock()
    favorite.custom_id = "custom_abc"
    favorite.favorite_type = "medication"
    favorite.code = "1234"
    favorite.display_name = "Wegovy"
    favorite.label = "GLP1"
    favorite.label_color = "blue"
    favorite.group_name = "GLP 1"
    favorite.is_shared = False
    favorite.created_by = creator
    favorite.created_at.isoformat.return_value = "2026-04-21T00:00:00"
    favorite.medication_name = "Wegovy"
    favorite.fdb_code = "1234"
    favorite.sig = "weekly"
    favorite.days_supply = 28
    favorite.quantity_to_dispense = 4
    favorite.unit = "pen"
    favorite.refills = 0
    favorite.representative_ndc = "ndc"
    favorite.ncpdp_quantity_qualifier_code = "00"
    favorite.generic_substitution_allowed = True
    favorite.search_terms = ["a"]
    favorite.default_pharmacy_ncpdp_id = ""
    favorite.default_pharmacy_name = ""
    favorite.note_to_pharmacist = ""
    mock_model.objects.select_related.return_value.get.return_value = favorite

    service = FavoritesService()
    result = service.get_favorite_by_id("custom_abc")
    assert result is not None
    assert result["created_by_id"] == "s1"
    assert result["created_by_name"] == "Jane Doe"
    assert result["created_at"] == "2026-04-21T00:00:00"
