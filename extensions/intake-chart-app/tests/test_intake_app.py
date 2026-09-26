"""Tests for the IntakeApp NoteApplication.

The handler reads ``self.event`` (visibility + handle context) and
``self.secrets`` (note-type allowlist); both are normally wired by the
Canvas SDK at request time. These tests build IntakeApp instances via
``object.__new__`` so the runtime base-class plumbing is bypassed and the
handler logic can be exercised directly.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from intake_chart_app.applications.intake_app import (
    INTAKE_NOTE_TYPES_SECRET,
    IntakeApp,
    _allowed_keywords,
    _note_type_name,
    _safe_chart_review,
    is_intake_note,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_allowed_keywords_empty_for_blank_secret():
    assert _allowed_keywords("") == []
    assert _allowed_keywords(None) == []
    assert _allowed_keywords("   ") == []


def test_allowed_keywords_lowercases_and_strips():
    assert _allowed_keywords("Office Visit, Intake , New Patient") == [
        "office visit",
        "intake",
        "new patient",
    ]


def test_allowed_keywords_drops_empty_tokens():
    assert _allowed_keywords("intake,,new patient,") == ["intake", "new patient"]


# ---------------------------------------------------------------------------
# _note_type_name — Note lookup helper
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_note_class():
    """Patch ``intake_app.Note`` with a MagicMock so DB lookups are
    deterministic. Yields the mock for per-test wiring."""
    with patch("intake_chart_app.applications.intake_app.Note") as mock:
        # The DoesNotExist sentinel must remain a real exception class for
        # the except clause to catch it.
        mock.DoesNotExist = type("DoesNotExist", (Exception,), {})
        yield mock


def test_note_type_name_returns_empty_when_dbid_blank(mock_note_class):
    assert _note_type_name("") == ""
    assert _note_type_name(None) == ""
    mock_note_class.objects.select_related.assert_not_called()


def test_note_type_name_returns_empty_when_note_missing(mock_note_class):
    mock_note_class.objects.select_related.return_value.get.side_effect = (
        mock_note_class.DoesNotExist()
    )
    assert _note_type_name("abc") == ""


def test_note_type_name_returns_lowercased_name(mock_note_class):
    note = MagicMock()
    note.note_type_version.name = "Office Visit"
    mock_note_class.objects.select_related.return_value.get.return_value = note
    assert _note_type_name("123") == "office visit"


def test_note_type_name_returns_empty_when_name_none(mock_note_class):
    """Defensive: a note_type_version with name=None must not blow up."""
    note = MagicMock()
    note.note_type_version.name = None
    mock_note_class.objects.select_related.return_value.get.return_value = note
    assert _note_type_name("123") == ""


# ---------------------------------------------------------------------------
# is_intake_note — combines _note_type_name + _allowed_keywords
# ---------------------------------------------------------------------------


def test_is_intake_note_defaults_wide_open_when_secret_blank(mock_note_class):
    """Blank secret → tab visible on every note type (wide-open default)."""
    assert is_intake_note("123", "") is True
    assert is_intake_note("123", None) is True
    # No Note lookup should have happened — short-circuited on the secret.
    mock_note_class.objects.select_related.assert_not_called()


def test_is_intake_note_false_when_no_note_context(mock_note_class):
    """The global app drawer queries visible() with no note_id; the tab
    must hide there regardless of whether the secret is set."""
    assert is_intake_note("", "") is False
    assert is_intake_note("", "intake") is False
    assert is_intake_note(None, None) is False
    assert is_intake_note(None, "intake,follow up") is False
    # Drawer path must not hit the Note table.
    mock_note_class.objects.select_related.assert_not_called()


def test_is_intake_note_false_when_note_missing(mock_note_class):
    """Secret restricts to keywords; missing note → invisible."""
    mock_note_class.objects.select_related.return_value.get.side_effect = (
        mock_note_class.DoesNotExist()
    )
    assert is_intake_note("123", "intake") is False


def test_is_intake_note_substring_match_case_insensitive(mock_note_class):
    note = MagicMock()
    note.note_type_version.name = "New Patient Intake"
    mock_note_class.objects.select_related.return_value.get.return_value = note
    assert is_intake_note("123", "intake") is True
    assert is_intake_note("123", "INTAKE") is True


def test_is_intake_note_false_when_no_keyword_matches(mock_note_class):
    note = MagicMock()
    note.note_type_version.name = "Telephone Encounter"
    mock_note_class.objects.select_related.return_value.get.return_value = note
    assert is_intake_note("123", "intake,new patient") is False


# ---------------------------------------------------------------------------
# _safe_chart_review — pre-fill aggregator with per-source error swallowing
# ---------------------------------------------------------------------------


def test_safe_chart_review_returns_empty_skeleton_for_blank_patient():
    out = _safe_chart_review("")
    assert out == {
        "patient_id": "",
        "active_conditions": [],
        "active_allergies": [],
        "active_medications": [],
        "prior_medical_history": [],
        "prior_surgical_history": [],
        "prior_family_history": [],
    }


def test_safe_chart_review_aggregates_from_helpers():
    with patch(
        "intake_chart_app.applications.intake_app._active_conditions",
        return_value=[{"id": "c1"}],
    ), patch(
        "intake_chart_app.applications.intake_app._active_allergies",
        return_value=[{"id": "a1"}],
    ), patch(
        "intake_chart_app.applications.intake_app._active_medications",
        return_value=[{"id": "m1"}],
    ), patch(
        "intake_chart_app.applications.intake_app._prior_medical_history",
        return_value=[{"id": "h1"}],
    ), patch(
        "intake_chart_app.applications.intake_app._prior_surgical_history",
        return_value=[{"id": "s1"}],
    ):
        out = _safe_chart_review("p1")
    assert out["patient_id"] == "p1"
    assert out["active_conditions"] == [{"id": "c1"}]
    assert out["active_allergies"] == [{"id": "a1"}]
    assert out["active_medications"] == [{"id": "m1"}]
    assert out["prior_medical_history"] == [{"id": "h1"}]
    assert out["prior_surgical_history"] == [{"id": "s1"}]
    assert out["prior_family_history"] == []  # intentionally empty — no Family History pre-fill


def test_safe_chart_review_swallows_db_errors_only():
    """One source raising a DatabaseError (the narrowed catch) must not
    block the modal: that source returns its skeleton default and the
    others still populate. Errors outside the DatabaseError hierarchy
    (AttributeError after a refactor, ImportError, TypeError from SDK
    drift) must NOT be swallowed — they should reach Sentry."""
    from django.db import DatabaseError, OperationalError
    with patch(
        "intake_chart_app.applications.intake_app._active_conditions",
        side_effect=OperationalError("connection reset"),
    ), patch(
        "intake_chart_app.applications.intake_app._active_allergies",
        return_value=[{"id": "a1"}],
    ), patch(
        "intake_chart_app.applications.intake_app._active_medications",
        side_effect=DatabaseError("query failed"),
    ), patch(
        "intake_chart_app.applications.intake_app._prior_medical_history",
        return_value=[{"id": "h1"}],
    ), patch(
        "intake_chart_app.applications.intake_app._prior_surgical_history",
        side_effect=DatabaseError("deadlock"),
    ):
        out = _safe_chart_review("p1")
    assert out["active_conditions"] == []  # DB error → skeleton default
    assert out["active_allergies"] == [{"id": "a1"}]
    assert out["active_medications"] == []
    assert out["prior_medical_history"] == [{"id": "h1"}]
    assert out["prior_surgical_history"] == []


def test_safe_chart_review_does_not_swallow_non_db_errors():
    """REVIEW.md §55: non-DB errors must propagate so Sentry pages on
    real bugs (AttributeError after a refactor, ImportError, TypeError
    from SDK drift). The narrowed DatabaseError catch only handles the
    flaky-chart case, not blanket failure suppression."""
    with patch(
        "intake_chart_app.applications.intake_app._active_conditions",
        side_effect=AttributeError("for_patient was renamed"),
    ), patch(
        "intake_chart_app.applications.intake_app._active_allergies",
        return_value=[],
    ), patch(
        "intake_chart_app.applications.intake_app._active_medications",
        return_value=[],
    ), patch(
        "intake_chart_app.applications.intake_app._prior_medical_history",
        return_value=[],
    ), patch(
        "intake_chart_app.applications.intake_app._prior_surgical_history",
        return_value=[],
    ):
        import pytest
        with pytest.raises(AttributeError):
            _safe_chart_review("p1")


# ---------------------------------------------------------------------------
# IntakeApp.visible / handle — instance-level handler tests. NoteApplication's
# base __init__ requires SDK wiring; ``object.__new__`` lets us instantiate
# without it and inject the attributes the handler reads.
# ---------------------------------------------------------------------------


def _make_app(*, event_context: dict, secret: str | None = "intake") -> IntakeApp:
    app = object.__new__(IntakeApp)
    app.event = SimpleNamespace(  # type: ignore[attr-defined]
        context=event_context,
        target=SimpleNamespace(id=event_context.get("patient_id", "") or "p1"),
    )
    secrets_dict = {INTAKE_NOTE_TYPES_SECRET: secret} if secret is not None else {}
    app.secrets = secrets_dict  # type: ignore[attr-defined]
    return app


def test_intakeapp_visible_true_when_secret_unset(mock_note_class):
    """Empty secret → wide-open default."""
    app = _make_app(event_context={"note_id": "n-1"}, secret="")
    assert app.visible() is True


def test_intakeapp_visible_false_when_note_missing(mock_note_class):
    mock_note_class.objects.select_related.return_value.get.side_effect = (
        mock_note_class.DoesNotExist()
    )
    app = _make_app(event_context={"note_id": "n-1"}, secret="intake")
    assert app.visible() is False


def test_intakeapp_visible_true_when_keyword_matches(mock_note_class):
    note = MagicMock()
    note.note_type_version.name = "New Patient Intake"
    mock_note_class.objects.select_related.return_value.get.return_value = note
    app = _make_app(event_context={"note_id": "n-1"}, secret="intake")
    assert app.visible() is True


def test_intakeapp_visible_false_when_no_note_in_event_context(mock_note_class):
    """Global app drawer invokes visible() with no note_id; the tab must
    hide there. Without this guard the icon leaks into the drawer
    alongside global apps (a NoteApplication should never appear there)."""
    # Secret unset — the wide-open default would have returned True before
    # the is_intake_note guard was added.
    app = _make_app(event_context={}, secret="")
    assert app.visible() is False
    # Note table must not be queried for the drawer path.
    mock_note_class.objects.select_related.assert_not_called()


def test_intakeapp_handle_returns_launch_modal_effect(mock_note_class):
    """Handle pre-fetches the note for note_uuid + note_type_name, asks
    _safe_chart_review for the pre-fill, renders the template, and wraps
    the HTML in a LaunchModalEffect."""
    note = MagicMock()
    note.id = "note-uuid-1"
    note.note_type_version.name = "Intake"
    mock_note_class.objects.select_related.return_value.get.return_value = note

    with patch(
        "intake_chart_app.applications.intake_app._safe_chart_review",
        return_value={
            "patient_id": "p1",
            "active_conditions": [],
            "active_allergies": [],
            "active_medications": [],
            "prior_medical_history": [],
            "prior_surgical_history": [],
            "prior_family_history": [],
        },
    ) as mock_chart, patch(
        "intake_chart_app.applications.intake_app.build_intake_context",
        return_value={"some": "context"},
    ) as mock_context, patch(
        "intake_chart_app.applications.intake_app.render_to_string",
        return_value="<html>ok</html>",
    ) as mock_render, patch(
        "intake_chart_app.applications.intake_app.LaunchModalEffect"
    ) as MockLaunch:
        applied = MagicMock(name="applied-effect")
        MockLaunch.return_value.apply.return_value = applied

        app = _make_app(
            event_context={"note_id": "dbid-1", "patient_id": "p1"},
            secret="intake",
        )
        result = app.handle()

    assert result == [applied]
    mock_chart.assert_called_once_with("p1")
    mock_context.assert_called_once_with(
        note_uuid="note-uuid-1",
        patient_id="p1",
        note_type_name="Intake",
        chart=mock_chart.return_value,
    )
    mock_render.assert_called_once_with(
        "templates/intake.html", {"some": "context"},
    )
    call_kwargs = MockLaunch.call_args.kwargs
    assert call_kwargs["content"] == "<html>ok</html>"
    assert call_kwargs["title"] == "Intake"


def test_intakeapp_handle_when_note_missing_falls_back_to_event_patient(
    mock_note_class,
):
    """If the note dbid doesn't resolve, ``handle`` still renders — but
    with an empty note_uuid + note_type_name; the patient_id comes from
    event context."""
    mock_note_class.objects.select_related.return_value.get.side_effect = (
        mock_note_class.DoesNotExist()
    )
    with patch(
        "intake_chart_app.applications.intake_app._safe_chart_review",
        return_value={"patient_id": "p1"},
    ), patch(
        "intake_chart_app.applications.intake_app.build_intake_context",
        return_value={},
    ) as mock_context, patch(
        "intake_chart_app.applications.intake_app.render_to_string",
        return_value="<html/>",
    ), patch(
        "intake_chart_app.applications.intake_app.LaunchModalEffect"
    ) as MockLaunch:
        MockLaunch.return_value.apply.return_value = "ok"
        app = _make_app(
            event_context={"note_id": "missing", "patient_id": "p1"},
        )
        result = app.handle()

    assert result == ["ok"]
    kwargs = mock_context.call_args.kwargs
    assert kwargs["note_uuid"] == ""
    assert kwargs["note_type_name"] == ""
    assert kwargs["patient_id"] == "p1"


def test_intakeapp_handle_uses_event_target_when_patient_id_missing(
    mock_note_class,
):
    """If the event context omits patient_id, fall back to event.target.id."""
    note = MagicMock()
    note.id = "note-uuid-2"
    note.note_type_version.name = "Intake"
    mock_note_class.objects.select_related.return_value.get.return_value = note

    with patch(
        "intake_chart_app.applications.intake_app._safe_chart_review",
        return_value={"patient_id": "p-fallback"},
    ), patch(
        "intake_chart_app.applications.intake_app.build_intake_context",
        return_value={},
    ) as mock_context, patch(
        "intake_chart_app.applications.intake_app.render_to_string",
        return_value="<html/>",
    ), patch(
        "intake_chart_app.applications.intake_app.LaunchModalEffect"
    ) as MockLaunch:
        MockLaunch.return_value.apply.return_value = "ok"
        # Build the app directly so event.target.id is set independently.
        app = object.__new__(IntakeApp)
        app.event = SimpleNamespace(
            context={"note_id": "dbid-1"},
            target=SimpleNamespace(id="p-fallback"),
        )
        app.secrets = {INTAKE_NOTE_TYPES_SECRET: "intake"}
        app.handle()

    assert mock_context.call_args.kwargs["patient_id"] == "p-fallback"


def test_intakeapp_handle_skips_note_lookup_when_dbid_blank(mock_note_class):
    """No note_id in the event → no DB lookup; handler still renders."""
    with patch(
        "intake_chart_app.applications.intake_app._safe_chart_review",
        return_value={"patient_id": "p1"},
    ), patch(
        "intake_chart_app.applications.intake_app.build_intake_context",
        return_value={},
    ), patch(
        "intake_chart_app.applications.intake_app.render_to_string",
        return_value="<html/>",
    ), patch(
        "intake_chart_app.applications.intake_app.LaunchModalEffect"
    ) as MockLaunch:
        MockLaunch.return_value.apply.return_value = "ok"
        app = _make_app(
            event_context={"note_id": "", "patient_id": "p1"},
        )
        app.handle()
    mock_note_class.objects.select_related.assert_not_called()
