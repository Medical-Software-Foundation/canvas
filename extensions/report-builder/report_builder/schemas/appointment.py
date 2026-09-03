"""Appointment entity schema."""

from canvas_sdk.v1.data import Appointment

from report_builder.schemas.base import EntitySchema, FieldSchema, RelationshipSchema

APPOINTMENT_STATUS_CHOICES = (
    ("unconfirmed", "Unconfirmed"),
    ("attempted", "Attempted"),
    ("confirmed", "Confirmed"),
    ("arrived", "Arrived"),
    ("roomed", "Roomed"),
    ("exited", "Exited"),
    ("noshowed", "No-showed"),
    ("cancelled", "Cancelled"),
)


APPOINTMENT_SCHEMA = EntitySchema(
    key="appointment",
    label="Appointment",
    plural_label="Appointments",
    model=Appointment,
    primary_date_field="start_time",
    fields=(
        FieldSchema(name="start_time", label="Start time", type="datetime"),
        FieldSchema(name="duration_minutes", label="Duration (minutes)", type="integer"),
        FieldSchema(
            name="status", label="Status", type="choice", choices=APPOINTMENT_STATUS_CHOICES
        ),
        FieldSchema(name="comment", label="Comment", type="string"),
        FieldSchema(name="description", label="Description", type="string"),
        FieldSchema(
            name="telehealth_instructions_sent",
            label="Telehealth instructions sent",
            type="boolean",
        ),
    ),
    relationships=(
        RelationshipSchema(
            name="patient", label="Patient", target_entity="patient", orm_path="patient"
        ),
    ),
)
