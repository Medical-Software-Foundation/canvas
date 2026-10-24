"""Conditions dataset. Counts conditions by DIAGNOSIS (ICD-10/SNOMED) over time.

The primary breakdown is the coded diagnosis name (e.g. "Type 2 diabetes mellitus"),
so a grouped report lists diagnoses ranked by how often they occur. A record may carry
both an ICD-10 and a SNOMED coding; filter by "Coding system" to avoid mixing systems.
"""

from canvas_sdk.v1.data.condition import Condition

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="conditions",
    label="Conditions",
    model=Condition,
    date_field="onset_date",
    fields={
        "diagnosis": Field(
            key="diagnosis", label="Diagnosis", type="category",
            orm_path="codings__display", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="codings__display",
        ),
        "coding_system": Field(
            key="coding_system", label="Coding system", type="category",
            orm_path="codings__system", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="codings__system",
        ),
        "clinical_status": Field(
            key="clinical_status", label="Clinical status", type="category",
            orm_path="clinical_status", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="clinical_status",
        ),
    },
    dimensions={
        "diagnosis": Dimension(key="diagnosis", label="Diagnosis",
                               group_path="codings__display", display_paths=[]),
        "coding_system": Dimension(key="coding_system", label="Coding system",
                                   group_path="codings__system", display_paths=[]),
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
