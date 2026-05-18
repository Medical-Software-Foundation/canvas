"""Tests for VitalsApp - the portal_menu_item entry point."""

from unittest.mock import MagicMock, patch

from canvas_sdk.effects import Effect

from patient_vitals.application import VitalsApp


def _make_app(context: dict) -> MagicMock:
    """Build a partial VitalsApp stand-in with the given event context."""
    app = MagicMock(spec=VitalsApp)
    app.event = MagicMock()
    app.event.context = context
    return app


def test_on_open_returns_launch_modal_with_user_context() -> None:
    """When event.context.user.id is set, on_open returns a LAUNCH_MODAL effect."""
    app = _make_app({"user": {"id": "patient-123"}})

    with patch("patient_vitals.application.log"):
        result = VitalsApp.on_open(app)

    assert isinstance(result, Effect)
    assert "LAUNCH_MODAL" in str(result)
    assert "/plugin-io/api/patient_vitals/page" in str(result)


def test_on_open_falls_back_to_patient_context() -> None:
    """When the user block is empty, the patient block is consulted as a fallback."""
    app = _make_app({"user": {}, "patient": {"id": "patient-456"}})

    with patch("patient_vitals.application.log"):
        result = VitalsApp.on_open(app)

    assert isinstance(result, Effect)
    assert "LAUNCH_MODAL" in str(result)


def test_on_open_returns_empty_when_no_patient_id() -> None:
    """No id in either context block → empty effect list, no modal."""
    app = _make_app({"user": {}, "patient": {}})

    with patch("patient_vitals.application.log"):
        result = VitalsApp.on_open(app)

    assert result == []


def test_on_open_handles_completely_missing_context() -> None:
    """A bare context dict should not raise; it returns the empty effect list."""
    app = _make_app({})

    with patch("patient_vitals.application.log"):
        result = VitalsApp.on_open(app)

    assert result == []


def test_on_open_handles_none_user_block() -> None:
    """A user block explicitly set to None should not crash the fallback chain."""
    app = _make_app({"user": None, "patient": {"id": "patient-789"}})

    with patch("patient_vitals.application.log"):
        result = VitalsApp.on_open(app)

    assert isinstance(result, Effect)
    assert "LAUNCH_MODAL" in str(result)
