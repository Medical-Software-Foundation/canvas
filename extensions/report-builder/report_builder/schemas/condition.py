"""Condition entity schema."""

from canvas_sdk.v1.data import Condition

from report_builder.schemas.base import EntitySchema, FieldSchema, RelationshipSchema

CLINICAL_STATUS_CHOICES = (
    ("active", "Active"),
    ("relapse", "Relapse"),
    ("remission", "Remission"),
    ("resolved", "Resolved"),
    ("investigative", "Investigative"),
)


CONDITION_SCHEMA = EntitySchema(
    key="condition",
    label="Condition",
    plural_label="Conditions",
    model=Condition,
    primary_date_field="onset_date",
    fields=(
        FieldSchema(name="onset_date", label="Onset date", type="date"),
        FieldSchema(name="resolution_date", label="Resolution date", type="date"),
        FieldSchema(
            name="clinical_status",
            label="Clinical status",
            type="choice",
            choices=CLINICAL_STATUS_CHOICES,
        ),
        FieldSchema(name="notes", label="Notes", type="string"),
        FieldSchema(name="surgical", label="Surgical", type="boolean"),
        FieldSchema(name="deleted", label="Deleted", type="boolean"),
    ),
    relationships=(
        RelationshipSchema(
            name="patient", label="Patient", target_entity="patient", orm_path="patient"
        ),
    ),
)
