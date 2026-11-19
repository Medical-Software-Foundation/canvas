"""Referrals dataset. Counts referrals by priority over time (by date referred)."""

from canvas_sdk.v1.data.referral import Referral

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="referrals",
    label="Referrals",
    model=Referral,
    date_field="date_referred",
    fields={
        "priority": Field(
            key="priority", label="Priority", type="category", orm_path="priority",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="priority",
        ),
    },
    dimensions={
        "priority": Dimension(key="priority", label="Priority",
                              group_path="priority", display_paths=[]),
    },
    measures={
        "referrals": CountMeasure(key="referrals", label="Referrals"),
    },
)
