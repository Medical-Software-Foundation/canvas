"""Conditions dataset. Counts conditions (problems) by clinical status over time."""

from canvas_sdk.v1.data.condition import Condition

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="conditions",
    label="Conditions",
    model=Condition,
    date_field="onset_date",
    fields={
        "clinical_status": Field(
            key="clinical_status", label="Clinical status", type="category",
            orm_path="clinical_status", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="clinical_status",
        ),
    },
    dimensions={
        "clinical_status": Dimension(key="clinical_status", label="Clinical status",
                                     group_path="clinical_status", display_paths=[]),
    },
    measures={
        "conditions": CountMeasure(key="conditions", label="Conditions",
                                   where={"deleted": False}),
        "active_conditions": CountMeasure(
            key="active_conditions", label="Active conditions",
            where={"deleted": False, "clinical_status": "active"},
        ),
    },
)
