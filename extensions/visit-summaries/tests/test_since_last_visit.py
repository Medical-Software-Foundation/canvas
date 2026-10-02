"""Tests for visit_summaries.applications.since_last_visit."""
from unittest.mock import MagicMock, patch

import pytest


def _make_handler(patient_id="patient-222", note_id="note-bbb"):
    from visit_summaries.applications.since_last_visit import SinceLastVisitApp

    handler = SinceLastVisitApp.__new__(SinceLastVisitApp)
    handler.event = MagicMock()
    handler.event.target.id = patient_id
    handler.event.context = {"note_id": note_id, "user": {"id": "staff-2"}}
    return handler


# ---------------------------------------------------------------------------
# visible()
# ---------------------------------------------------------------------------

def test_visible_returns_false_when_disabled():
    handler = _make_handler()
    with patch("visit_summaries.applications.since_last_visit.is_feature_enabled", return_value=False):
        assert handler.visible() is False


def test_visible_returns_false_when_no_locked_note():
    handler = _make_handler()
    with (
        patch("visit_summaries.applications.since_last_visit.is_feature_enabled", return_value=True),
        patch("visit_summaries.applications.since_last_visit.get_most_recent_locked_note", return_value=None),
    ):
        assert handler.visible() is False


def test_visible_returns_false_when_no_interim_activity():
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-01-01T09:00:00"
    handler = _make_handler()
    with (
        patch("visit_summaries.applications.since_last_visit.is_feature_enabled", return_value=True),
        patch("visit_summaries.applications.since_last_visit.get_most_recent_locked_note", return_value=mock_note),
        patch("visit_summaries.applications.since_last_visit.has_interim_activity", return_value=False),
    ):
        assert handler.visible() is False


def test_visible_returns_true_when_locked_note_and_activity_exist():
    mock_note = MagicMock()
    mock_note.datetime_of_service = "2025-01-01T09:00:00"
    handler = _make_handler()
    with (
        patch("visit_summaries.applications.since_last_visit.is_feature_enabled", return_value=True),
        patch("visit_summaries.applications.since_last_visit.get_most_recent_locked_note", return_value=mock_note),
        patch("visit_summaries.applications.since_last_visit.has_interim_activity", return_value=True),
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
    handler = _make_handler(patient_id="p-abc", note_id="n-def")
    effects = handler.handle()
    effect = effects[0]
    assert "n-def" in str(effect)
    assert "p-abc" in str(effect)
