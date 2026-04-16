"""Tests for CustomFavorite model."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _make_favorite(**overrides: Any) -> MagicMock:
    """Build a CustomFavorite-like mock with default field values."""
    defaults = {
        "dbid": 1,
        "custom_id": "custom_abc123",
        "display_name": "Test Med",
        "label": "",
        "label_color": "",
        "medication_name": "test medication 10mg tablet",
        "fdb_code": "123456",
        "sig": "Take 1 tablet daily",
        "days_supply": 30,
        "quantity_to_dispense": 30.0,
        "unit": "Tablet",
        "refills": 0,
        "representative_ndc": "12345678901",
        "ncpdp_quantity_qualifier_code": "C48542",
        "generic_substitution_allowed": True,
        "search_terms": ["test"],
        "default_pharmacy_ncpdp_id": "",
        "default_pharmacy_name": "",
    }
    defaults.update(overrides)
    mock = MagicMock(**defaults)
    # Make attribute access work for dict-style conversion
    for key, val in defaults.items():
        setattr(mock, key, val)
    return mock


def test_custom_favorite_imports() -> None:
    """Test that CustomFavorite can be imported."""
    from prescription_favorites.models import CustomFavorite

    assert CustomFavorite is not None


def test_custom_favorite_has_expected_fields() -> None:
    """Test that CustomFavorite defines all expected fields."""
    from prescription_favorites.models.custom_favorite import CustomFavorite

    expected_fields = [
        "custom_id",
        "display_name",
        "label",
        "label_color",
        "medication_name",
        "fdb_code",
        "sig",
        "days_supply",
        "quantity_to_dispense",
        "unit",
        "refills",
        "representative_ndc",
        "ncpdp_quantity_qualifier_code",
        "generic_substitution_allowed",
        "search_terms",
        "default_pharmacy_ncpdp_id",
        "default_pharmacy_name",
    ]
    model_field_names = [f.name for f in CustomFavorite._meta.get_fields()]
    for field in expected_fields:
        assert field in model_field_names, f"Missing field: {field}"


def test_custom_favorite_has_unique_constraint() -> None:
    """Test that CustomFavorite has a unique constraint on custom_id."""
    from prescription_favorites.models.custom_favorite import CustomFavorite

    constraint_names = [c.name for c in CustomFavorite._meta.constraints]
    assert "uq_custom_favorite_custom_id" in constraint_names


def test_custom_favorite_has_timestamp_fields() -> None:
    """Test that CustomFavorite includes created_at and updated_at fields."""
    from prescription_favorites.models.custom_favorite import CustomFavorite

    model_field_names = [f.name for f in CustomFavorite._meta.get_fields()]
    assert "created_at" in model_field_names
    assert "updated_at" in model_field_names
