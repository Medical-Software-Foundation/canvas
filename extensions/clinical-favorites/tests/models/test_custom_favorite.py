"""Tests for ClinicalFavorite and HiddenDefault custom models."""

from clinical_favorites.models import ClinicalFavorite, CustomStaff, HiddenDefault


def test_clinical_favorite_model_imports() -> None:
    assert ClinicalFavorite is not None
    assert HiddenDefault is not None
    assert CustomStaff is not None


def test_clinical_favorite_has_expected_fields() -> None:
    fields = {f.name for f in ClinicalFavorite._meta.get_fields()}
    required = {
        "custom_id",
        "favorite_type",
        "code",
        "display_name",
        "label",
        "label_color",
        "group_name",
        "is_shared",
        "created_by",
        "created_at",
        "updated_at",
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
        "note_to_pharmacist",
    }
    assert required.issubset(fields), f"Missing fields {required - fields}"


def test_clinical_favorite_unique_constraints() -> None:
    names = {c.name for c in ClinicalFavorite._meta.constraints}
    assert "uq_clinical_favorite_custom_id" in names
    assert "uq_clinical_favorite_owner_type_code" in names


def test_hidden_default_has_favorite_type() -> None:
    fields = {f.name for f in HiddenDefault._meta.get_fields()}
    assert "default_id" in fields
    assert "favorite_type" in fields
    assert "hidden_by" in fields
