"""Labs dataset. Counts lab reports by transmission type over time (by date performed)."""

from canvas_sdk.v1.data.lab import LabReport

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="labs",
    label="Labs",
    model=LabReport,
    date_field="date_performed",
    fields={
        "transmission_type": Field(
            key="transmission_type", label="Transmission type", type="category",
            orm_path="transmission_type", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="transmission_type",
        ),
    },
    dimensions={
        "transmission_type": Dimension(key="transmission_type", label="Transmission type",
                                       group_path="transmission_type", display_paths=[]),
    },
    measures={
        "lab_reports": CountMeasure(key="lab_reports", label="Lab reports"),
    },
)
