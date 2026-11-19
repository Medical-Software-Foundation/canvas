"""Observations dataset. Counts observations by MEASUREMENT (coded name) over time."""

from canvas_sdk.v1.data.observation import Observation

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="observations",
    label="Observations",
    model=Observation,
    date_field="effective_datetime",
    fields={
        "measurement": Field(
            key="measurement", label="Measurement", type="category",
            orm_path="codings__display", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="codings__display",
        ),
        "category": Field(
            key="category", label="Category", type="category", orm_path="category",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="category",
        ),
    },
    dimensions={
        "measurement": Dimension(key="measurement", label="Measurement",
                                 group_path="codings__display", display_paths=[]),
        "category": Dimension(key="category", label="Category",
                              group_path="category", display_paths=[]),
    },
    measures={
        "observations": CountMeasure(key="observations", label="Observations"),
    },
)
