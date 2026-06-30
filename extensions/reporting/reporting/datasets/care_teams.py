"""Care teams dataset. Counts care-team memberships by status / role / staff."""

from canvas_sdk.v1.data.care_team import CareTeamMembership

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="care_teams",
    label="Care teams",
    model=CareTeamMembership,
    date_field="created",
    fields={
        "status": Field(
            key="status", label="Status", type="category", orm_path="status",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="status",
        ),
        "role": Field(
            key="role", label="Role", type="category", orm_path="role_display",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="role_display",
        ),
        "staff": Field(
            key="staff", label="Staff member", type="person", orm_path="staff__id",
            filterable=True, operators=("is", "is_one_of"), groupable=True,
            options_value_path="staff__id",
            options_label_paths=("staff__first_name", "staff__last_name"),
        ),
    },
    dimensions={
        "status": Dimension(key="status", label="Status", group_path="status", display_paths=[]),
        "role": Dimension(key="role", label="Role", group_path="role_display", display_paths=[]),
        "staff": Dimension(
            key="staff", label="Staff member", group_path="staff__id",
            display_paths=["staff__first_name", "staff__last_name"],
        ),
    },
    measures={
        "memberships": CountMeasure(key="memberships", label="Care team memberships"),
    },
)
