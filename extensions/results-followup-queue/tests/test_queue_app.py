"""Tests for results_followup_queue.applications.queue_app."""

import json
from unittest.mock import MagicMock

from results_followup_queue.applications.queue_app import ResultsQueueApp


def _make_app() -> ResultsQueueApp:
    """Create a ResultsQueueApp with a mocked event."""
    mock_event = MagicMock()
    mock_event.target.id = (
        "results_followup_queue.applications.queue_app:ResultsQueueApp"
    )
    mock_event.type = 0  # APPLICATION__ON_OPEN numeric value
    return ResultsQueueApp(mock_event)


def _effect_data(result: object) -> dict[str, object]:
    """Parse the payload from an applied Effect."""
    raw: dict[str, object] = json.loads(result.payload)  # type: ignore[attr-defined]
    data = raw.get("data", raw)
    assert isinstance(data, dict)
    return data


def test_on_open_returns_an_effect() -> None:
    """on_open() must return a single applied Effect."""
    result = _make_app().on_open()
    assert result.__class__.__name__ == "Effect"


def test_on_open_targets_default_modal() -> None:
    """The modal must target DEFAULT_MODAL so it renders inside Canvas."""
    data = _effect_data(_make_app().on_open())
    assert data.get("target") == "default_modal"


def test_on_open_url_points_at_queue_api() -> None:
    """The URL must route to the QueueAPI endpoint with a cache-bust param."""
    data = _effect_data(_make_app().on_open())
    url = data.get("url", "")
    assert isinstance(url, str)
    assert "/plugin-io/api/results_followup_queue/app/" in url
    assert "?v=" in url


def test_on_open_modal_title() -> None:
    """The modal title must identify the plugin."""
    data = _effect_data(_make_app().on_open())
    assert data.get("title") == "Results Follow-Up Queue"
