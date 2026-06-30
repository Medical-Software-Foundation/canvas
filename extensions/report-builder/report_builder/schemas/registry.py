"""Central registry of entities the report builder can target.

Adding a new entity to v1+ is a two-line change: define the schema in its own
file, then add it here. The UI introspects this registry; no UI changes are
required.
"""

from typing import Any

from report_builder.schemas.appointment import APPOINTMENT_SCHEMA
from report_builder.schemas.base import EntitySchema
from report_builder.schemas.condition import CONDITION_SCHEMA
from report_builder.schemas.lab_order import LAB_ORDER_SCHEMA
from report_builder.schemas.note import NOTE_SCHEMA
from report_builder.schemas.patient import PATIENT_SCHEMA

_ENTITY_LIST: tuple[EntitySchema, ...] = (
    PATIENT_SCHEMA,
    APPOINTMENT_SCHEMA,
    CONDITION_SCHEMA,
    NOTE_SCHEMA,
    LAB_ORDER_SCHEMA,
)

ENTITY_REGISTRY: dict[str, EntitySchema] = {e.key: e for e in _ENTITY_LIST}


def serialize_field(field: Any) -> dict[str, Any]:
    """Serialize a FieldSchema for the wire."""
    out: dict[str, Any] = {
        "name": field.name,
        "label": field.label,
        "type": field.type,
        "selectable_column": field.selectable_column,
        "filterable": field.filterable,
    }
    if field.choices is not None:
        out["choices"] = [{"value": v, "label": label} for v, label in field.choices]
    return out


def serialize_relationship(rel: Any) -> dict[str, Any]:
    """Serialize a RelationshipSchema for the wire."""
    return {
        "name": rel.name,
        "label": rel.label,
        "target_entity": rel.target_entity,
    }


def serialize_entity(entity: EntitySchema) -> dict[str, Any]:
    """Serialize an EntitySchema for the wire (excludes the model class)."""
    return {
        "key": entity.key,
        "label": entity.label,
        "plural_label": entity.plural_label,
        "primary_date_field": entity.primary_date_field,
        "fields": [serialize_field(f) for f in entity.fields],
        "relationships": [serialize_relationship(r) for r in entity.relationships],
    }


def serialize_registry() -> dict[str, Any]:
    """Serialize the full ENTITY_REGISTRY for the /entities endpoint."""
    return {
        "entities": [serialize_entity(e) for e in _ENTITY_LIST],
    }
