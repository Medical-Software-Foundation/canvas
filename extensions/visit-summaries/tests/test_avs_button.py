"""Tests for visit_summaries.protocols.avs_button."""
from unittest.mock import MagicMock, patch

import pytest


def _make_handler(patient_id="patient-333", note_id="note-ccc"):
    from visit_summaries.protocols.avs_button import GenerateAvsButton

    handler = GenerateAvsButton.__new__(GenerateAvsButton)
    handler.event = MagicMock()
    handler.event.target.id = patient_id
    handler.event.context = {"note_id": note_id, "user": {"id": "staff-3"}}
    return handler


# ---------------------------------------------------------------------------
# visible()
# ---------------------------------------------------------------------------

def test_visible_avs_enabled():
    handler = _make_handler()
    with patch("visit_summaries.protocols.avs_button.is_feature_enabled", return_value=True):
        assert handler.visible() is True


def test_visible_avs_disabled():
    handler = _make_handler()
    with patch("visit_summaries.protocols.avs_button.is_feature_enabled", return_value=False):
        assert handler.visible() is False


# ---------------------------------------------------------------------------
# handle()
# ---------------------------------------------------------------------------

def test_handle_returns_single_effect():
    handler = _make_handler()
    effects = handler.handle()
    assert len(effects) == 1


def test_handle_url_contains_note_and_patient_ids():
    handler = _make_handler(patient_id="p-xyz", note_id="n-789")
    effects = handler.handle()
    effect = effects[0]
    assert "n-789" in str(effect)
    assert "p-xyz" in str(effect)
