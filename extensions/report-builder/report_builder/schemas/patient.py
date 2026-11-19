"""Patient entity schema — root of most clinical reports."""

from canvas_sdk.v1.data import Patient

from report_builder.schemas.base import EntitySchema, FieldSchema, RelationshipSchema

SEX_AT_BIRTH_CHOICES = (
    ("M", "Male"),
    ("F", "Female"),
    ("O", "Other"),
    ("UNK", "Unknown"),
)


PATIENT_SCHEMA = EntitySchema(
    key="patient",
    label="Patient",
    plural_label="Patients",
    model=Patient,
    primary_date_field="created",
    fields=(
        FieldSchema(name="first_name", label="First name", type="string"),
        FieldSchema(name="last_name", label="Last name", type="string"),
        FieldSchema(name="birth_date", label="Birth date", type="date"),
        FieldSchema(name="sex_at_birth", label="Sex at birth", type="choice", choices=SEX_AT_BIRTH_CHOICES),
        FieldSchema(name="active", label="Active", type="boolean"),
        FieldSchema(name="deceased", label="Deceased", type="boolean"),
        FieldSchema(name="mrn", label="MRN", type="string"),
        FieldSchema(name="nickname", label="Nickname", type="string"),
        FieldSchema(name="preferred_pronouns", label="Preferred pronouns", type="string"),
        FieldSchema(name="created", label="Registered date", type="datetime"),
    ),
    relationships=(
        RelationshipSchema(
            name="appointments",
            label="Appointments",
            target_entity="appointment",
            orm_path="appointments",
        ),
        RelationshipSchema(
            name="conditions",
            label="Conditions",
            target_entity="condition",
            orm_path="conditions",
        ),
        RelationshipSchema(
            name="notes",
            label="Notes",
            target_entity="note",
            orm_path="notes",
        ),
        RelationshipSchema(
            name="lab_orders",
            label="Lab orders",
            target_entity="lab_order",
            orm_path="lab_orders",
        ),
    ),
)
