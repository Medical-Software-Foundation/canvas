"""Patients dataset definition.

Measures are windowed by the patient's `created` date (the period range applies to
when the patient record was created), so this dataset reports NEW patients over time.
"""

from canvas_sdk.v1.data.patient import Patient, SexAtBirth

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

_SEX_CHOICES = (
    (SexAtBirth.FEMALE, "Female"),
    (SexAtBirth.MALE, "Male"),
    (SexAtBirth.OTHER, "Other"),
    (SexAtBirth.UNKNOWN, "Unknown"),
)

DATASET = Dataset(
    key="patients",
    label="Patients",
    model=Patient,
    date_field="created",
    fields={
        "sex_at_birth": Field(
            key="sex_at_birth", label="Sex at birth", type="category",
            orm_path="sex_at_birth", filterable=True, operators=("is", "is_one_of"),
            groupable=True, choices=_SEX_CHOICES,
        ),
        "business_line": Field(
            key="business_line", label="Business line", type="category",
            orm_path="business_line__name", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="business_line__name",
        ),
        "default_location": Field(
            key="default_location", label="Default location", type="place",
            orm_path="default_location__full_name", filterable=True,
            operators=("is", "is_one_of"), groupable=True,
            options_value_path="default_location__full_name",
        ),
        "default_provider": Field(
            key="default_provider", label="Default provider", type="person",
            orm_path="default_provider__id", filterable=True,
            operators=("is", "is_one_of"), groupable=True,
            options_value_path="default_provider__id",
            options_label_paths=("default_provider__first_name", "default_provider__last_name"),
        ),
    },
    dimensions={
        "sex_at_birth": Dimension(key="sex_at_birth", label="Sex at birth",
                                  group_path="sex_at_birth", display_paths=[]),
        "business_line": Dimension(key="business_line", label="Business line",
                                   group_path="business_line__name", display_paths=[]),
        "default_location": Dimension(key="default_location", label="Default location",
                                      group_path="default_location__full_name", display_paths=[]),
        "default_provider": Dimension(
            key="default_provider", label="Default provider",
            group_path="default_provider__id",
            display_paths=["default_provider__first_name", "default_provider__last_name"],
        ),
    },
    measures={
        "new_patients": CountMeasure(key="new_patients", label="New patients"),
        "deceased": CountMeasure(key="deceased", label="Deceased (new records)",
                                 where={"deceased": True}),
    },
)
