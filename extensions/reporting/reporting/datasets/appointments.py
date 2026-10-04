"""Appointments dataset definition."""

from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.patient import SexAtBirth

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure, RatioMeasure

_NO_SHOW_STATUS = AppointmentProgressStatus.NOSHOWED
_CANCELLED = AppointmentProgressStatus.CANCELLED
_ARRIVED = AppointmentProgressStatus.ARRIVED

_STATUS_CHOICES = (
    (AppointmentProgressStatus.UNCONFIRMED, "Unconfirmed"),
    (AppointmentProgressStatus.ATTEMPTED, "Attempted"),
    (AppointmentProgressStatus.CONFIRMED, "Confirmed"),
    (AppointmentProgressStatus.ARRIVED, "Arrived"),
    (AppointmentProgressStatus.ROOMED, "Roomed"),
    (AppointmentProgressStatus.EXITED, "Checked out"),
    (AppointmentProgressStatus.NOSHOWED, "No-show"),
    (AppointmentProgressStatus.CANCELLED, "Cancelled"),
)

_SEX_CHOICES = (
    (SexAtBirth.FEMALE, "Female"),
    (SexAtBirth.MALE, "Male"),
    (SexAtBirth.OTHER, "Other"),
    (SexAtBirth.UNKNOWN, "Unknown"),
)

DATASET = Dataset(
    key="appointments",
    label="Appointments",
    model=Appointment,
    date_field="start_time",
    fields={
        "status": Field(
            key="status", label="Status", type="category", orm_path="status",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            choices=_STATUS_CHOICES,
        ),
        "provider": Field(
            key="provider", label="Provider", type="person", orm_path="provider__id",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="provider__id",
            options_label_paths=("provider__first_name", "provider__last_name"),
        ),
        "location": Field(
            key="location", label="Location", type="place", orm_path="location__id",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="location__id",
            options_label_paths=("location__full_name",),
        ),
        "visit_type": Field(
            key="visit_type", label="Visit type", type="category",
            orm_path="note_type__name",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="note_type__name",
        ),
        "patient_sex": Field(
            key="patient_sex", label="Patient sex", type="category",
            orm_path="patient__sex_at_birth",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            choices=_SEX_CHOICES,
        ),
        "duration_minutes": Field(
            key="duration_minutes", label="Duration (minutes)", type="number",
            orm_path="duration_minutes",
            filterable=True, operators=("gte", "gt", "lte", "lt"), groupable=False,
        ),
    },
    dimensions={
        "provider": Dimension(
            key="provider", label="Provider", group_path="provider__id",
            display_paths=["provider__first_name", "provider__last_name"],
        ),
        "location": Dimension(
            key="location", label="Location", group_path="location__id",
            display_paths=["location__full_name"],
        ),
        "status": Dimension(key="status", label="Status", group_path="status", display_paths=[]),
        "visit_type": Dimension(
            key="visit_type", label="Visit type",
            group_path="note_type__name", display_paths=[],
        ),
        "patient_sex": Dimension(
            key="patient_sex", label="Patient sex",
            group_path="patient__sex_at_birth", display_paths=[],
        ),
    },
    measures={
        "total": CountMeasure(key="total", label="Total appointments"),
        "no_shows": CountMeasure(key="no_shows", label="No-shows", where={"status": _NO_SHOW_STATUS}),
        "no_show_rate": RatioMeasure(
            key="no_show_rate", label="No-show rate (%)",
            numerator_where={"status": _NO_SHOW_STATUS}, as_percent=True,
        ),
        "cancellations": CountMeasure(
            key="cancellations", label="Cancellations", where={"status": _CANCELLED}
        ),
        "cancellation_rate": RatioMeasure(
            key="cancellation_rate", label="Cancellation rate (%)",
            numerator_where={"status": _CANCELLED}, as_percent=True,
        ),
        "arrived": CountMeasure(key="arrived", label="Arrived", where={"status": _ARRIVED}),
    },
)
