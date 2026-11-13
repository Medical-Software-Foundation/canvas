"""Claims dataset definition.

Volume metrics only: claim COUNTS by queue / payer / provider over time. Dollar
measures (charges, payments, AR) are intentionally NOT included — the sandbox blocks
ORM Sum/Avg and claim amounts are computed properties, not columns, so financial-$
needs a separate aggregation path.
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
            key="queue", label="Queue", type="category",
            orm_path="current_queue__display_name", filterable=True,
            operators=("is", "is_one_of"), groupable=True,
            options_value_path="current_queue__display_name",
        ),
        "payer": Field(
            key="payer", label="Payer", type="category",
            orm_path="current_coverage__payer_name", filterable=True,
            operators=("is", "is_one_of"), groupable=True,
            options_value_path="current_coverage__payer_name",
        ),
        "provider": Field(
            key="provider", label="Provider", type="person",
            orm_path="note__provider__id", filterable=True,
            operators=("is", "is_one_of"), groupable=True,
            options_value_path="note__provider__id",
            options_label_paths=("note__provider__first_name", "note__provider__last_name"),
        ),
    },
    dimensions={
        "queue": Dimension(key="queue", label="Queue",
                           group_path="current_queue__display_name", display_paths=[]),
        "payer": Dimension(key="payer", label="Payer",
                           group_path="current_coverage__payer_name", display_paths=[]),
        "provider": Dimension(
            key="provider", label="Provider", group_path="note__provider__id",
            display_paths=["note__provider__first_name", "note__provider__last_name"],
        ),
    },
    measures={
        "claims": CountMeasure(key="claims", label="Claims"),
    },
)
