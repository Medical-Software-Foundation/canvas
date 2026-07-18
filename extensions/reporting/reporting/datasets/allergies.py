"""Allergies dataset. Counts allergy/intolerance records by ALLERGEN (coded name)."""

from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="allergies",
    label="Allergies",
    model=AllergyIntolerance,
    date_field="recorded_date",
    fields={
        "allergen": Field(
            key="allergen", label="Allergen", type="category",
            orm_path="codings__display", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="codings__display",
        ),
        "severity": Field(
            key="severity", label="Severity", type="category", orm_path="severity",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="severity",
        ),
        "status": Field(
            key="status", label="Status", type="category", orm_path="status",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="status",
        ),
    },
    dimensions={
        "allergen": Dimension(key="allergen", label="Allergen",
                              group_path="codings__display", display_paths=[]),
        "severity": Dimension(key="severity", label="Severity",
                              group_path="severity", display_paths=[]),
        "status": Dimension(key="status", label="Status", group_path="status", display_paths=[]),
    },
    measures={
        "allergies": CountMeasure(key="allergies", label="Allergies",
                                  where={"deleted": False}),
    },
)
