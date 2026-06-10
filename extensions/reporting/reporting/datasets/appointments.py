"""Appointments dataset definition."""

from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure, RatioMeasure

# A no-show is strictly a missed appointment. Cancellations are a separate event
# and are intentionally NOT counted here.
_NO_SHOW_STATUS = AppointmentProgressStatus.NOSHOWED

DATASET = Dataset(
    key="appointments",
    label="Appointments",
    model=Appointment,
    date_field="start_time",
    fields={
        "status": Field(
            key="status",
            label="Status",
            type="category",
            orm_path="status",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
            choices=(
                (AppointmentProgressStatus.UNCONFIRMED, "Unconfirmed"),
                (AppointmentProgressStatus.ATTEMPTED, "Attempted"),
                (AppointmentProgressStatus.CONFIRMED, "Confirmed"),
                (AppointmentProgressStatus.ARRIVED, "Arrived"),
                (AppointmentProgressStatus.ROOMED, "Roomed"),
                (AppointmentProgressStatus.EXITED, "Checked out"),
                (AppointmentProgressStatus.NOSHOWED, "No-show"),
                (AppointmentProgressStatus.CANCELLED, "Cancelled"),
            ),
        ),
        "provider": Field(
            key="provider",
            label="Provider",
            type="person",
            orm_path="provider__id",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
        ),
        "location": Field(
            key="location",
            label="Location",
            type="place",
            orm_path="location__id",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
        ),
    },
    dimensions={
        "provider": Dimension(
            key="provider",
            label="Provider",
            group_path="provider__id",
            display_paths=["provider__first_name", "provider__last_name"],
        ),
        "location": Dimension(
            key="location",
            label="Location",
            group_path="location__id",
            display_paths=["location__full_name"],
        ),
    },
    measures={
        "total": CountMeasure(key="total", label="Total appointments"),
        "no_shows": CountMeasure(
            key="no_shows", label="No-shows", where={"status": _NO_SHOW_STATUS}
        ),
        "no_show_rate": RatioMeasure(
            key="no_show_rate",
            label="No-show rate (%)",
            numerator_where={"status": _NO_SHOW_STATUS},
            as_percent=True,
        ),
    },
)
