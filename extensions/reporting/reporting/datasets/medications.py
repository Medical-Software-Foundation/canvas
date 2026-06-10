"""Medications dataset. Counts medications by status over time (by start date)."""

from canvas_sdk.v1.data.medication import Medication

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="medications",
    label="Medications",
    model=Medication,
    date_field="start_date",
    fields={
        "status": Field(
            key="status", label="Status", type="category", orm_path="status",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="status",
        ),
    },
    dimensions={
        "status": Dimension(key="status", label="Status", group_path="status", display_paths=[]),
    },
    measures={
        "medications": CountMeasure(key="medications", label="Medications",
                                    where={"deleted": False}),
        "active_medications": CountMeasure(
            key="active_medications", label="Active medications",
            where={"deleted": False, "status": "active"},
        ),
    },
)
