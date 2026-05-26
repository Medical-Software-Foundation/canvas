"""Tests for pre_visit_brief.applications.prep_app."""

from unittest.mock import MagicMock

from pre_visit_brief.applications.prep_app import PreVisitBriefApp


def _make_app() -> PreVisitBriefApp:
    """Create a PreVisitBriefApp with a mocked event."""
    mock_event = MagicMock()
    mock_event.target.id = "pre_visit_brief.applications.prep_app:PreVisitBriefApp"
    mock_event.type = 0  # APPLICATION__ON_OPEN numeric value
    return PreVisitBriefApp(mock_event)


def test_on_open_returns_an_effect() -> None:
    """on_open() must return a single Effect (an applied LaunchModalEffect)."""
    app = _make_app()
    result = app.on_open()
    # The applied effect is an Effect instance; check by class name to avoid
    # importing the internal Effect class.
    assert result.__class__.__name__ == "Effect"


def _effect_data(result: object) -> dict[str, object]:
    """Parse the payload from an applied Effect.

    Applied effects store their data in payload as JSON; the structure may be
    ``{"data": {...}}`` or the dict directly depending on SDK version.
    """
    import json

    raw: dict[str, object] = json.loads(result.payload)  # type: ignore[attr-defined]
    # SDK wraps the actual values under a "data" key in some versions.
    data = raw.get("data", raw)
    assert isinstance(data, dict)
    return data


def test_on_open_effect_targets_default_modal() -> None:
    """The modal must target DEFAULT_MODAL so it renders inside Canvas."""
    app = _make_app()
    result = app.on_open()
    data = _effect_data(result)
    assert data.get("target") == "default_modal"


def test_on_open_effect_url_points_at_brief_api() -> None:
    """The URL must route to the BriefAPI endpoint."""
    app = _make_app()
    result = app.on_open()
    data = _effect_data(result)
    url = data.get("url", "")
    assert isinstance(url, str)
    assert "/plugin-io/api/pre_visit_brief/" in url


def test_on_open_effect_url_contains_cache_bust() -> None:
    """The URL must carry a cache-busting query parameter."""
    app = _make_app()
    result = app.on_open()
    data = _effect_data(result)
    url = data.get("url", "")
    assert isinstance(url, str)
    assert "?v=" in url


def test_on_open_modal_title() -> None:
    """The modal title must identify the plugin."""
    app = _make_app()
    result = app.on_open()
    data = _effect_data(result)
    assert data.get("title") == "Pre-Visit Brief"
