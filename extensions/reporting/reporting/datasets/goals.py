"""Goals dataset. Counts care goals by lifecycle/achievement status and priority."""

from canvas_sdk.v1.data.goal import Goal

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="goals",
    label="Goals",
    model=Goal,
    date_field="start_date",
    fields={
        "lifecycle_status": Field(
            key="lifecycle_status", label="Lifecycle status", type="category",
            orm_path="lifecycle_status", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="lifecycle_status",
        ),
        "achievement_status": Field(
            key="achievement_status", label="Achievement status", type="category",
            orm_path="achievement_status", filterable=True, operators=("is", "is_one_of"),
            groupable=True, options_value_path="achievement_status",
        ),
        "priority": Field(
            key="priority", label="Priority", type="category", orm_path="priority",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="priority",
        ),
    },
    dimensions={
        "lifecycle_status": Dimension(key="lifecycle_status", label="Lifecycle status",
                                      group_path="lifecycle_status", display_paths=[]),
        "achievement_status": Dimension(key="achievement_status", label="Achievement status",
                                        group_path="achievement_status", display_paths=[]),
        "priority": Dimension(key="priority", label="Priority",
                              group_path="priority", display_paths=[]),
    },
    measures={
        "goals": CountMeasure(key="goals", label="Goals"),
    },
)
