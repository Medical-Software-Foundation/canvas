"""Note entity schema.

The spec lists an "Encounter" entity, but Canvas's `Encounter` model has no
direct `Patient` FK — it joins through `Note`. To stay inside the v1
one-hop-only constraint, we expose `Note` (which has the same clinical meaning
in Canvas — every encounter has exactly one note) and document the rename in
the README.
"""

from canvas_sdk.v1.data import Note

from report_builder.schemas.base import EntitySchema, FieldSchema, RelationshipSchema


NOTE_SCHEMA = EntitySchema(
    key="note",
    label="Note",
    plural_label="Notes",
    model=Note,
    primary_date_field="datetime_of_service",
    fields=(
        FieldSchema(name="datetime_of_service", label="Date of service", type="datetime"),
        FieldSchema(name="title", label="Title", type="string"),
        FieldSchema(name="place_of_service", label="Place of service", type="string"),
        FieldSchema(name="billing_note", label="Billing note", type="string"),
        FieldSchema(name="checksum", label="Checksum", type="string"),
        FieldSchema(name="created", label="Created", type="datetime"),
        FieldSchema(name="modified", label="Modified", type="datetime"),
    ),
    relationships=(
        RelationshipSchema(
            name="patient", label="Patient", target_entity="patient", orm_path="patient"
        ),
    ),
)
