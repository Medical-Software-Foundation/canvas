"""Rule 1: When coverages exist, they must be sequential and have a single primary.

Health Gorilla rejects orders when the patient's coverage stack is missing a
primary or has duplicate ranks. A patient with zero active coverages is fine -
self-pay lab orders are allowed - so this rule is a no-op in that case.
"""

from collections import Counter

from lab_order_validation.rules._helpers import is_active_coverage


def _active_coverages(patient) -> list:
    return [c for c in patient.coverages.all() if is_active_coverage(c)]


def check(patient) -> list[str]:
    active = _active_coverages(patient)

    if not active:
        return []

    ranks = [c.coverage_rank for c in active if c.coverage_rank is not None]

    if 1 not in ranks:
        return ["Missing a primary coverage. Set one to rank 1 in the Coverages tab."]

    rank_counts = Counter(ranks)
    duplicate_ranks = sorted(rank for rank, count in rank_counts.items() if count > 1)
    if duplicate_ranks:
        rank_list = ", ".join(str(r) for r in duplicate_ranks)
        return [f"Duplicate coverage ranks ({rank_list}). Fix in the Coverages tab."]

    return []
