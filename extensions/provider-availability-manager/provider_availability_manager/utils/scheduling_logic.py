"""Pure slot/window math used by the slot filter protocol."""

from __future__ import annotations

import datetime


def _subtract_blocks(
    windows: list[tuple[datetime.datetime, datetime.datetime]],
    blocks: list[tuple[datetime.datetime, datetime.datetime]],
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Return ``windows`` with ``blocks`` carved out.

    For each input window, overlapping blocks are removed, leaving zero or
    more sub-windows representing the time the resource is actually free.
    """
    result: list[tuple[datetime.datetime, datetime.datetime]] = []
    for win_start, win_end in windows:
        win_blocks = sorted(
            [
                (max(b[0], win_start), min(b[1], win_end))
                for b in blocks
                if b[0] < win_end and b[1] > win_start
            ],
            key=lambda x: x[0],
        )
        cursor = win_start
        for block_start, block_end in win_blocks:
            if cursor < block_start:
                result.append((cursor, block_start))
            if block_end > cursor:
                cursor = block_end
        if cursor < win_end:
            result.append((cursor, win_end))
    return result


def _slot_in_windows(
    slot_start: datetime.datetime,
    slot_end: datetime.datetime,
    windows: list[tuple[datetime.datetime, datetime.datetime]],
) -> bool:
    """Return True if the slot fits entirely within at least one window."""
    for win_start, win_end in windows:
        if slot_start >= win_start and slot_end <= win_end:
            return True
    return False
