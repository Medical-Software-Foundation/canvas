"""Patients dataset definition.

Measures are windowed by the patient's `created` date (the period range applies to
when the patient record was created), so this dataset reports NEW patients over time.
"""

from canvas_sdk.v1.data.patient import Patient, SexAtBirth

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="patients",
    label="Patients",
    model=Patient,
    date_field="created",
    fields={
        "sex_at_birth": Field(
            key="sex_at_birth",
            label="Sex at birth",
            type="category",
            orm_path="sex_at_birth",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
            choices=(
                (SexAtBirth.FEMALE, "Female"),
                (SexAtBirth.MALE, "Male"),
                (SexAtBirth.OTHER, "Other"),
                (SexAtBirth.UNKNOWN, "Unknown"),
            ),
        ),
        "business_line": Field(
            key="business_line",
            label="Business line",
            type="category",
            orm_path="business_line__name",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
            options_value_path="business_line__name",
        ),
    },
    dimensions={
        "sex_at_birth": Dimension(
            key="sex_at_birth", label="Sex at birth",
            group_path="sex_at_birth", display_paths=[],
        ),
        "business_line": Dimension(
            key="business_line", label="Business line",
            group_path="business_line__name", display_paths=[],
        ),
    },
    measures={
        "new_patients": CountMeasure(key="new_patients", label="New patients"),
    },
)
