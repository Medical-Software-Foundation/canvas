"""LabOrder entity schema."""

from canvas_sdk.v1.data.lab import LabOrder

from report_builder.schemas.base import EntitySchema, FieldSchema, RelationshipSchema

SPECIMEN_COLLECTION_CHOICES = (
    ("L", "On location"),
    ("P", "Patient service center"),
    ("O", "Other"),
)


LAB_ORDER_SCHEMA = EntitySchema(
    key="lab_order",
    label="Lab order",
    plural_label="Lab orders",
    model=LabOrder,
    primary_date_field="date_ordered",
    fields=(
        FieldSchema(name="date_ordered", label="Date ordered", type="datetime"),
        FieldSchema(name="requisition_number", label="Requisition number", type="string"),
        FieldSchema(name="ontology_lab_partner", label="Lab partner", type="string"),
        FieldSchema(name="comment", label="Comment", type="string"),
        FieldSchema(name="fasting_status", label="Fasting", type="boolean"),
        FieldSchema(name="is_patient_bill", label="Patient bill", type="boolean"),
        FieldSchema(
            name="specimen_collection_type",
            label="Specimen collection",
            type="choice",
            choices=SPECIMEN_COLLECTION_CHOICES,
        ),
    ),
    relationships=(
        RelationshipSchema(
            name="patient", label="Patient", target_entity="patient", orm_path="patient"
        ),
    ),
)
