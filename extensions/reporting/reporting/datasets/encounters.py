"""Encounters dataset definition. Counts encounters by medium/state over time."""

from canvas_sdk.v1.data.encounter import Encounter, EncounterMedium, EncounterState

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="encounters",
    label="Encounters",
    model=Encounter,
    date_field="start_time",
    fields={
        "medium": Field(
            key="medium",
            label="Medium",
            type="category",
            orm_path="medium",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
            choices=(
                (EncounterMedium.OFFICE, "Office visit"),
                (EncounterMedium.VIDEO, "Video visit"),
                (EncounterMedium.VOICE, "Telephone visit"),
                (EncounterMedium.HOME, "Home visit"),
                (EncounterMedium.OFFSITE, "Other offsite visit"),
                (EncounterMedium.LAB, "Lab visit"),
            ),
        ),
        "state": Field(
            key="state",
            label="State",
            type="category",
            orm_path="state",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
            choices=(
                (EncounterState.STARTED, "Started"),
                (EncounterState.PLANNED, "Planned"),
                (EncounterState.CONCLUDED, "Concluded"),
                (EncounterState.CANCELLED, "Cancelled"),
            ),
        ),
    },
    dimensions={
        "medium": Dimension(key="medium", label="Medium", group_path="medium", display_paths=[]),
        "state": Dimension(key="state", label="State", group_path="state", display_paths=[]),
    },
    measures={
        "encounters": CountMeasure(key="encounters", label="Encounters"),
    },
)
