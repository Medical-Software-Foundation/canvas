"""Encounters dataset definition. Counts encounters by medium/state/provider over time."""

from canvas_sdk.v1.data.encounter import Encounter, EncounterMedium, EncounterState

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

_MEDIUM_CHOICES = (
    (EncounterMedium.OFFICE, "Office visit"),
    (EncounterMedium.VIDEO, "Video visit"),
    (EncounterMedium.VOICE, "Telephone visit"),
    (EncounterMedium.HOME, "Home visit"),
    (EncounterMedium.OFFSITE, "Other offsite visit"),
    (EncounterMedium.LAB, "Lab visit"),
)

_STATE_CHOICES = (
    (EncounterState.STARTED, "Started"),
    (EncounterState.PLANNED, "Planned"),
    (EncounterState.CONCLUDED, "Concluded"),
    (EncounterState.CANCELLED, "Cancelled"),
)

DATASET = Dataset(
    key="encounters",
    label="Encounters",
    model=Encounter,
    date_field="start_time",
    fields={
        "medium": Field(
            key="medium", label="Medium", type="category", orm_path="medium",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            choices=_MEDIUM_CHOICES,
        ),
        "state": Field(
            key="state", label="State", type="category", orm_path="state",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            choices=_STATE_CHOICES,
        ),
        "provider": Field(
            key="provider", label="Provider", type="person",
            orm_path="note__provider__id", filterable=True,
            operators=("is", "is_one_of"), groupable=True,
            options_value_path="note__provider__id",
            options_label_paths=("note__provider__first_name", "note__provider__last_name"),
        ),
        "location": Field(
            key="location", label="Location", type="place",
            orm_path="note__location__full_name", filterable=True,
            operators=("is", "is_one_of"), groupable=True,
            options_value_path="note__location__full_name",
        ),
    },
    dimensions={
        "medium": Dimension(key="medium", label="Medium", group_path="medium", display_paths=[]),
        "state": Dimension(key="state", label="State", group_path="state", display_paths=[]),
        "provider": Dimension(
            key="provider", label="Provider", group_path="note__provider__id",
            display_paths=["note__provider__first_name", "note__provider__last_name"],
        ),
        "location": Dimension(
            key="location", label="Location",
            group_path="note__location__full_name", display_paths=[],
        ),
    },
    measures={
        "encounters": CountMeasure(key="encounters", label="Encounters"),
    },
)
