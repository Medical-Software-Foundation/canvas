"""NUCC taxonomy seed loader.

Upserts the bundled NUCC Healthcare Provider Taxonomy snapshot into
`NuccTaxonomyCode`. Idempotent: rows are matched by `code` — existing rows
are left untouched, and any new rows added to the bundled snapshot get
inserted on the next install.

The snapshot is a Python module (`nucc_taxonomy.py`) rather than a JSON file
because Canvas's plugin runtime restricts file-system access.
"""

from __future__ import annotations

from staff_directory.data.nucc_taxonomy import CODES
from staff_directory.services.nucc import seed_nucc_codes

_seeded_once = False


def _load_seed_rows() -> list[dict]:
    return list(CODES)


def ensure_nucc_seed() -> tuple[int, int]:
    """Run the NUCC seed if it hasn't already run in this process.

    Cheap to call repeatedly: after the first successful call it becomes a no-op.
    """
    global _seeded_once
    if _seeded_once:
        return (0, 0)

    from staff_directory.models.nucc import NuccTaxonomyCode

    if NuccTaxonomyCode.objects.exists():
        _seeded_once = True
        return (0, 0)

    rows = _load_seed_rows()
    result = seed_nucc_codes(rows)
    _seeded_once = True
    return result


def reset_seed_memo() -> None:
    """Test helper — forget that we already seeded, so the next call runs again."""
    global _seeded_once
    _seeded_once = False
