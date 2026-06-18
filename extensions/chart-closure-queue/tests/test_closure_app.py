"""Tests for chart_closure_queue.applications.closure_app."""

import json
from unittest.mock import MagicMock

from chart_closure_queue.applications.closure_app import ChartClosureApp


def _make_app() -> ChartClosureApp:
    """Create a ChartClosureApp with a mocked event."""
    mock_event = MagicMock()
    mock_event.target.id = (
        "chart_closure_queue.applications.closure_app:ChartClosureApp"
    )
    mock_event.type = 0  # APPLICATION__ON_OPEN numeric value
    return ChartClosureApp(mock_event)


def _effect_data(result: object) -> dict[str, object]:
    """Parse the payload from an applied Effect."""
    raw: dict[str, object] = json.loads(result.payload)  # type: ignore[attr-defined]
    data = raw.get("data", raw)
    assert isinstance(data, dict)
    return data


def test_on_open_returns_an_effect() -> None:
    """on_open() must return a single applied Effect."""
    app = _make_app()
    result = app.on_open()
    assert result.__class__.__name__ == "Effect"


def test_on_open_effect_targets_default_modal() -> None:
    """The modal must target DEFAULT_MODAL so it renders inside Canvas."""
    app = _make_app()
    data = _effect_data(app.on_open())
    assert data.get("target") == "default_modal"


def test_on_open_effect_url_points_at_closure_api() -> None:
    """The URL must route to the ClosureAPI endpoint."""
    app = _make_app()
    data = _effect_data(app.on_open())
    url = data.get("url", "")
    assert isinstance(url, str)
    assert "/plugin-io/api/chart_closure_queue/app/" in url


def test_on_open_effect_url_contains_cache_bust() -> None:
    """The URL must carry a cache-busting query parameter."""
    app = _make_app()
    data = _effect_data(app.on_open())
    url = data.get("url", "")
    assert isinstance(url, str)
    assert "?v=" in url


def test_on_open_modal_title() -> None:
    """The modal title must identify the plugin."""
    app = _make_app()
    data = _effect_data(app.on_open())
    assert data.get("title") == "Chart-Closure Queue"
