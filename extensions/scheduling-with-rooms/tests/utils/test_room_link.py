"""Tests for utils/room_link.py."""

from unittest.mock import MagicMock, patch

from scheduling_with_rooms.utils.room_link import (
    ROOM_STAFF_KEY,
    record_room,
    room_staff_key_for_note,
)

MODULE = "scheduling_with_rooms.utils.room_link"


def test_key_is_namespaced_to_this_plugin():
    """Note metadata is shared, so the key must not be able to collide."""
    assert ROOM_STAFF_KEY.startswith("scheduling_with_rooms:")


# record_room -----------------------------------------------------------

def test_record_room_upserts_metadata_on_the_note():
    with patch(f"{MODULE}.Note") as mock_note:
        mock_note.return_value.upsert_metadata.return_value = MagicMock(name="effect")

        effects = record_room("note-1", "rr-1")

        assert len(effects) == 1
        assert mock_note.call_args.kwargs["instance_id"] == "note-1"
        mock_note.return_value.upsert_metadata.assert_called_once_with(
            ROOM_STAFF_KEY, "rr-1"
        )


def test_record_room_is_a_no_op_without_a_note_or_room():
    with patch(f"{MODULE}.Note") as mock_note:
        assert record_room("", "rr-1") == []
        assert record_room("note-1", "") == []
        mock_note.assert_not_called()


# room_staff_key_for_note -----------------------------------------------

def _metadata(value):
    patcher = patch(f"{MODULE}.NoteMetadata")
    mock = patcher.start()
    mock.objects.filter.return_value.values.return_value.first.return_value = (
        {"value": value} if value is not None else None
    )
    return patcher, mock


def test_reads_the_recorded_room():
    patcher, mock = _metadata("rr-1")
    try:
        assert room_staff_key_for_note("note-1") == "rr-1"

        kwargs = mock.objects.filter.call_args.kwargs
        assert kwargs["note__id"] == "note-1"
        assert kwargs["key"] == ROOM_STAFF_KEY
    finally:
        patcher.stop()


def test_missing_metadata_returns_empty_string():
    patcher, _ = _metadata(None)
    try:
        assert room_staff_key_for_note("note-1") == ""
    finally:
        patcher.stop()


def test_blank_value_returns_empty_string():
    patcher, _ = _metadata("   ")
    try:
        assert room_staff_key_for_note("note-1") == ""
    finally:
        patcher.stop()


def test_no_note_skips_the_query():
    patcher, mock = _metadata("rr-1")
    try:
        assert room_staff_key_for_note("") == ""
        mock.objects.filter.assert_not_called()
    finally:
        patcher.stop()
