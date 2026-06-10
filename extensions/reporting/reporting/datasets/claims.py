"""Claims dataset definition.

Volume metrics only: claim COUNTS by queue over time. Dollar measures (charges,
payments, AR) are intentionally NOT included — the sandbox blocks ORM Sum/Avg and
claim amounts are computed properties, not columns, so financial-$ needs a separate
aggregation path.
"""

from canvas_sdk.v1.data.claim import Claim

from reporting.datasets.base import Dataset, Dimension, Field
from reporting.query.measures import CountMeasure

DATASET = Dataset(
    key="claims",
    label="Claims",
    model=Claim,
    date_field="created",
    fields={
        "queue": Field(
            key="queue",
            label="Queue",
            type="category",
            orm_path="current_queue__display_name",
            filterable=True,
            operators=("is", "is_one_of"),
            groupable=True,
            options_value_path="current_queue__display_name",
        ),
    },
    dimensions={
        "queue": Dimension(
            key="queue", label="Queue",
            group_path="current_queue__display_name", display_paths=[],
        ),
    },
    measures={
        "claims": CountMeasure(key="claims", label="Claims"),
    },
)
