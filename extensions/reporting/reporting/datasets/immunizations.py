"""Immunizations dataset. Counts immunizations by VACCINE (coded name) over time."""

from canvas_sdk.v1.data.immunization import Immunization

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="immunizations",
    label="Immunizations",
    model=Immunization,
    date_field="date_ordered",
    fields={
        "vaccine": Field(
            key="vaccine", label="Vaccine", type="category",
            orm_path="codings__display", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="codings__display",
        ),
        "status": Field(
            key="status", label="Status", type="category", orm_path="status",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="status",
        ),
        "provider": Field(
            key="provider", label="Administered by", type="person",
            orm_path="given_by__id", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="given_by__id",
            options_label_paths=("given_by__first_name", "given_by__last_name"),
        ),
    },
    dimensions={
        "vaccine": Dimension(key="vaccine", label="Vaccine",
                             group_path="codings__display", display_paths=[]),
        "status": Dimension(key="status", label="Status", group_path="status", display_paths=[]),
        "provider": Dimension(
            key="provider", label="Administered by", group_path="given_by__id",
            display_paths=["given_by__first_name", "given_by__last_name"],
        ),
    },
    measures={
        "immunizations": CountMeasure(key="immunizations", label="Immunizations",
                                      where={"deleted": False}),
    },
)
