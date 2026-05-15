"""Tests for the pure slot/window math helpers."""

import datetime

from provider_availability_manager.utils.scheduling_logic import (
    _slot_in_windows,
    _subtract_blocks,
)


def _dt(h, m=0):
    return datetime.datetime(2026, 5, 15, h, m)


class TestSlotInWindows:
    def test_slot_inside_window_fits(self):
        windows = [(_dt(9), _dt(12))]
        assert _slot_in_windows(_dt(10), _dt(11), windows) is True

    def test_slot_exactly_on_window_edges_fits(self):
        windows = [(_dt(9), _dt(12))]
        assert _slot_in_windows(_dt(9), _dt(12), windows) is True

    def test_slot_starting_before_window_rejected(self):
        windows = [(_dt(9), _dt(12))]
        assert _slot_in_windows(_dt(8, 30), _dt(11), windows) is False

    def test_slot_ending_after_window_rejected(self):
        windows = [(_dt(9), _dt(12))]
        assert _slot_in_windows(_dt(10), _dt(13), windows) is False

    def test_slot_spanning_two_windows_rejected(self):
        windows = [(_dt(9), _dt(10)), (_dt(11), _dt(12))]
        assert _slot_in_windows(_dt(9, 30), _dt(11, 30), windows) is False

    def test_no_windows_means_no_fit(self):
        assert _slot_in_windows(_dt(10), _dt(11), []) is False


class TestSubtractBlocks:
    def test_no_blocks_returns_original_window(self):
        windows = [(_dt(9), _dt(17))]
        assert _subtract_blocks(windows, []) == windows

    def test_block_in_middle_splits_window(self):
        windows = [(_dt(9), _dt(17))]
        blocks = [(_dt(12), _dt(13))]
        result = _subtract_blocks(windows, blocks)
        assert result == [(_dt(9), _dt(12)), (_dt(13), _dt(17))]

    def test_block_at_start_trims_left(self):
        windows = [(_dt(9), _dt(17))]
        blocks = [(_dt(9), _dt(10))]
        assert _subtract_blocks(windows, blocks) == [(_dt(10), _dt(17))]

    def test_block_at_end_trims_right(self):
        windows = [(_dt(9), _dt(17))]
        blocks = [(_dt(16), _dt(17))]
        assert _subtract_blocks(windows, blocks) == [(_dt(9), _dt(16))]

    def test_block_covers_whole_window_empties_it(self):
        windows = [(_dt(9), _dt(17))]
        blocks = [(_dt(8), _dt(18))]
        assert _subtract_blocks(windows, blocks) == []

    def test_block_outside_window_ignored(self):
        windows = [(_dt(9), _dt(12))]
        blocks = [(_dt(13), _dt(14))]
        assert _subtract_blocks(windows, blocks) == windows
