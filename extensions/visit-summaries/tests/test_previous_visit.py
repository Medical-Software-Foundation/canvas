"""Tests for visit_summaries.applications.previous_visit."""
from unittest.mock import MagicMock, patch

import pytest


def _make_handler(patient_id="patient-111", note_id="note-aaa"):
    """Return a PreviousVisitApp instance with mocked event/context."""
    from visit_summaries.applications.previous_visit import PreviousVisitApp

    handler = PreviousVisitApp.__new__(PreviousVisitApp)
    handler.event = MagicMock()
    handler.event.target.id = patient_id
    handler.event.context = {"note_id": note_id, "user": {"id": "staff-1"}}
    return handler


# ---------------------------------------------------------------------------
# visible()
# ---------------------------------------------------------------------------

def test_visible_returns_false_when_feature_disabled():
    handler = _make_handler()
    with patch("visit_summaries.applications.previous_visit.is_feature_enabled", return_value=False):
        assert handler.visible() is False


def test_visible_returns_false_when_no_locked_note():
    handler = _make_handler()
    with (
        patch("visit_summaries.applications.previous_visit.is_feature_enabled", return_value=True),
        patch("visit_summaries.applications.previous_visit.get_most_recent_locked_note", return_value=None),
    ):
        assert handler.visible() is False


def test_visible_returns_true_when_locked_note_exists():
    handler = _make_handler()
    with (
        patch("visit_summaries.applications.previous_visit.is_feature_enabled", return_value=True),
        patch("visit_summaries.applications.previous_visit.get_most_recent_locked_note", return_value=MagicMock()),
    ):
        assert handler.visible() is True


# ---------------------------------------------------------------------------
# handle()
# ---------------------------------------------------------------------------

def test_handle_returns_single_effect():
    handler = _make_handler()
    effects = handler.handle()
    assert len(effects) == 1


def test_handle_url_contains_note_and_patient_ids():
    handler = _make_handler(patient_id="p-123", note_id="n-456")
    effects = handler.handle()
    effect = effects[0]
    assert "n-456" in str(effect)
    assert "p-123" in str(effect)
