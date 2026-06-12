"""Canvas ClaimQueue ordinal codes used by the billing-dashboard queries.

Canvas stores claim queue state as a small integer on
`Claim.current_queue.queue_sort_ordering`. Naming the two ordinals the plugin
filters on keeps the query call sites self-explanatory.

Implemented as a plain class with int class attributes rather than
``enum.IntEnum`` because the plugin sandbox blocks ``from enum import IntEnum``
(verified 2026-05-26 via plugin-runner ImportError on corgi-sandbox).
"""

from __future__ import annotations


class ClaimQueueState:
    FILED = 5
    REJECTED = 6
    TRASH = 10
