"""Verify every entity schema is consistent with its SDK model and registry."""

from typing import Any

from report_builder.schemas.base import EntitySchema, FieldSchema, RelationshipSchema
from report_builder.schemas.registry import ENTITY_REGISTRY, serialize_registry


def _all_fields(model_cls: Any) -> set[str]:
    """Return every concrete attribute name on a Django model."""
    return {f.name for f in model_cls._meta.get_fields()}


def test_registry_has_all_five_entities() -> None:
    assert set(ENTITY_REGISTRY) == {"patient", "appointment", "condition", "note", "lab_order"}


def test_each_entity_is_an_entity_schema() -> None:
    for entity in ENTITY_REGISTRY.values():
        assert isinstance(entity, EntitySchema)
        assert entity.key
        assert entity.label
        assert entity.plural_label
        assert entity.model is not None
        assert isinstance(entity.fields, tuple)
        assert all(isinstance(f, FieldSchema) for f in entity.fields)
        assert all(isinstance(r, RelationshipSchema) for r in entity.relationships)


def test_each_entity_has_primary_date_field_in_fields() -> None:
    for entity in ENTITY_REGISTRY.values():
        if entity.primary_date_field is not None:
            assert entity.field(entity.primary_date_field) is not None, (
                f"{entity.key}: primary_date_field '{entity.primary_date_field}' not in fields"
            )


def test_each_field_name_resolves_on_model() -> None:
    for entity in ENTITY_REGISTRY.values():
        model_fields = _all_fields(entity.model)
        for f in entity.fields:
            assert f.name in model_fields, (
                f"{entity.key}: field '{f.name}' does not exist on model "
                f"{entity.model.__name__}"
            )


def test_each_relationship_target_is_registered() -> None:
    for entity in ENTITY_REGISTRY.values():
        for rel in entity.relationships:
            assert rel.target_entity in ENTITY_REGISTRY, (
                f"{entity.key}.{rel.name} -> '{rel.target_entity}' is not in the registry"
            )


def test_each_relationship_orm_path_resolves_on_model() -> None:
    for entity in ENTITY_REGISTRY.values():
        for rel in entity.relationships:
            # Accept either a direct attribute (forward FK) or a queryset (reverse).
            try:
                attr = getattr(entity.model, rel.orm_path)
            except AttributeError as exc:  # pragma: no cover - failure surfaces below
                raise AssertionError(
                    f"{entity.key}.{rel.name}: orm_path '{rel.orm_path}' "
                    f"does not exist on {entity.model.__name__}"
                ) from exc
            assert attr is not None


def test_serialize_registry_includes_choices_for_choice_fields() -> None:
    data = serialize_registry()
    entity_map = {e["key"]: e for e in data["entities"]}
    patient_fields = {f["name"]: f for f in entity_map["patient"]["fields"]}
    assert "choices" in patient_fields["sex_at_birth"]
    assert any(c["value"] == "M" for c in patient_fields["sex_at_birth"]["choices"])


def test_serialize_registry_strips_model_class() -> None:
    data = serialize_registry()
    for entity in data["entities"]:
        assert "model" not in entity
