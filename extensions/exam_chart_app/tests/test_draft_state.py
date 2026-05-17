"""Unit tests for draft_state module (Checkpoint 8)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from exam_chart_app.data import draft_state


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_set_draft_stores_json_payload(mock_hub_model):
    hub = MagicMock()
    mock_hub_model.objects.get_or_create.return_value = (hub, True)
    draft_state.set_draft("note-1", {"rfv": {"comment": "Annual"}, "hpi": {}})
    mock_hub_model.objects.get_or_create.assert_called_once_with(
        type="canvas__exam_chart_app", id="draft:note-1"
    )
    hub.set_attribute.assert_called_once()
    args = hub.set_attribute.call_args.args
    assert args[0] == "payload"
    assert json.loads(args[1]) == {"rfv": {"comment": "Annual"}, "hpi": {}}


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_set_draft_noop_for_empty_note_uuid(mock_hub_model):
    draft_state.set_draft("", {"any": "thing"})
    mock_hub_model.objects.get_or_create.assert_not_called()


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_get_draft_returns_empty_when_no_row(mock_hub_model):
    mock_hub_model.objects.filter.return_value.first.return_value = None
    state, finalized = draft_state.get_draft("note-1")
    assert state == {}
    assert finalized is False


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_get_draft_decodes_payload_and_reads_finalized(mock_hub_model):
    hub = MagicMock()
    hub.get_attribute.side_effect = lambda name: {
        "payload": json.dumps({"rfv": {"comment": "x"}}),
        "finalized": "1",
    }.get(name)
    mock_hub_model.objects.filter.return_value.first.return_value = hub
    state, finalized = draft_state.get_draft("note-1")
    assert state == {"rfv": {"comment": "x"}}
    assert finalized is True


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_get_draft_handles_malformed_payload(mock_hub_model):
    hub = MagicMock()
    hub.get_attribute.side_effect = lambda name: {"payload": "not-json{"}.get(name)
    mock_hub_model.objects.filter.return_value.first.return_value = hub
    state, finalized = draft_state.get_draft("note-1")
    assert state == {}
    assert finalized is False


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_mark_finalized_sets_flag(mock_hub_model):
    hub = MagicMock()
    mock_hub_model.objects.get_or_create.return_value = (hub, False)
    draft_state.mark_finalized("note-1")
    hub.set_attribute.assert_called_once_with("finalized", "1")


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_clear_draft_deletes_row(mock_hub_model):
    qs = MagicMock()
    mock_hub_model.objects.filter.return_value = qs
    draft_state.clear_draft("note-1")
    mock_hub_model.objects.filter.assert_called_once_with(
        type="canvas__exam_chart_app", id="draft:note-1"
    )
    qs.delete.assert_called_once()


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_set_draft_raises_when_payload_exceeds_cap(mock_hub_model):
    huge = {"blob": "x" * (draft_state.DRAFT_MAX_BYTES + 1)}
    with pytest.raises(draft_state.DraftTooLargeError):
        draft_state.set_draft("note-1", huge)
    # Never wrote anything for an oversize payload.
    mock_hub_model.objects.get_or_create.assert_not_called()


# ----- meta:<uuid> persistent "ever finalized" marker (orphan-banner fix) -----


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_mark_ever_finalized_writes_to_meta_row(mock_hub_model):
    """The marker must live on the `meta:` row, NOT the `draft:` row,
    so clear_draft doesn't wipe it during delete/undelete cycles."""
    hub = MagicMock()
    mock_hub_model.objects.get_or_create.return_value = (hub, True)
    draft_state.mark_ever_finalized("note-1")
    mock_hub_model.objects.get_or_create.assert_called_once_with(
        type="canvas__exam_chart_app", id="meta:note-1",
    )
    hub.set_attribute.assert_called_once_with("ever_finalized", "1")


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_mark_ever_finalized_noop_for_empty_note_uuid(mock_hub_model):
    draft_state.mark_ever_finalized("")
    mock_hub_model.objects.get_or_create.assert_not_called()


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_was_ever_finalized_returns_true_when_marker_set(mock_hub_model):
    hub = MagicMock()
    hub.get_attribute.return_value = "1"
    mock_hub_model.objects.filter.return_value.first.return_value = hub
    assert draft_state.was_ever_finalized("note-1") is True
    mock_hub_model.objects.filter.assert_called_once_with(
        type="canvas__exam_chart_app", id="meta:note-1",
    )


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_was_ever_finalized_returns_false_when_no_meta_row(mock_hub_model):
    mock_hub_model.objects.filter.return_value.first.return_value = None
    assert draft_state.was_ever_finalized("note-1") is False


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_was_ever_finalized_returns_false_for_empty_note_uuid(mock_hub_model):
    assert draft_state.was_ever_finalized("") is False
    mock_hub_model.objects.filter.assert_not_called()


@patch("exam_chart_app.data.draft_state.AttributeHub")
def test_clear_draft_does_not_touch_meta_row(mock_hub_model):
    """The whole point of the meta row: surviving clear_draft so the
    orphan-commands banner can fire after a delete/undelete cycle."""
    qs = MagicMock()
    mock_hub_model.objects.filter.return_value = qs
    draft_state.clear_draft("note-1")
    # Only the draft: row is deleted, never meta:
    mock_hub_model.objects.filter.assert_called_once_with(
        type="canvas__exam_chart_app", id="draft:note-1",
    )
