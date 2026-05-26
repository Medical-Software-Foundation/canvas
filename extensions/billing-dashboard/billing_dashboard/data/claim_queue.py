"""Canvas ClaimQueue ordinal codes used by the billing-dashboard queries.

Canvas stores claim queue state as a small integer on
`Claim.current_queue.queue_sort_ordering`. Naming the two ordinals the plugin
filters on keeps the query call sites self-explanatory.
"""

from __future__ import annotations

from enum import IntEnum


class ClaimQueueState(IntEnum):
    FILED = 5
    REJECTED = 6
