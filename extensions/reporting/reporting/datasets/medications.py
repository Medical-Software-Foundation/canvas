"""Medications dataset. Counts medications by DRUG (RxNorm/coded name) over time.

Primary breakdown is the coded medication name, so a grouped report ranks the most
frequently recorded medications.
"""

from canvas_sdk.v1.data.medication import Medication

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="medications",
    label="Medications",
    model=Medication,
    date_field="start_date",
    fields={
        "medication": Field(
            key="medication", label="Medication", type="category",
            orm_path="codings__display", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="codings__display",
        ),
        "coding_system": Field(
            key="coding_system", label="Coding system", type="category",
            orm_path="codings__system", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="codings__system",
        ),
        "status": Field(
            key="status", label="Status", type="category", orm_path="status",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="status",
        ),
    },
    dimensions={
        "medication": Dimension(key="medication", label="Medication",
                                group_path="codings__display", display_paths=[]),
        "coding_system": Dimension(key="coding_system", label="Coding system",
                                   group_path="codings__system", display_paths=[]),
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
