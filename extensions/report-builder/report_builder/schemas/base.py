"""Schema primitives for the report builder.

Each entity exposed in the UI is described by an `EntitySchema`, which is a
white-list of the fields and one-hop relationships the report builder is
allowed to reference. The query builder consults this registry to translate
user-built reports into ORM queries — values never reach the ORM unless the
field/relationship/op they reference resolves through the schema.
"""

from dataclasses import dataclass
from typing import Any, Literal

FieldType = Literal["string", "integer", "decimal", "boolean", "date", "datetime", "choice"]


@dataclass(frozen=True)
class FieldSchema:
    """A single filterable / selectable field on an entity."""

    name: str
    label: str
    type: FieldType
    choices: tuple[tuple[str, str], ...] | None = None
    selectable_column: bool = True
    filterable: bool = True


@dataclass(frozen=True)
class RelationshipSchema:
    """A one-hop relationship from a root entity to a target entity."""

    name: str
    label: str
    target_entity: str
    orm_path: str


@dataclass(frozen=True)
class EntitySchema:
    """An entity (Django model) that a report can target."""

    key: str
    label: str
    plural_label: str
    model: Any
    primary_date_field: str | None
    fields: tuple[FieldSchema, ...]
    relationships: tuple[RelationshipSchema, ...] = ()

    def field(self, name: str) -> FieldSchema | None:
        """Return the FieldSchema for `name`, or None if it isn't whitelisted."""
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def relationship(self, name: str) -> RelationshipSchema | None:
        """Return the RelationshipSchema for `name`, or None if it isn't whitelisted."""
        for r in self.relationships:
            if r.name == name:
                return r
        return None
