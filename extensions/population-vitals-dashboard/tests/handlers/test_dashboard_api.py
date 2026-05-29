"""Tests for DashboardAPI SimpleAPI handler.

Covers: auth rejection, static asset routes, stats param validation,
small-cohort passthrough, no-data passthrough, and a successful stats response.
"""

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

from population_vitals_dashboard.handlers.dashboard_api import (
    _CACHE_BUST,
    DashboardAPI,
    _parse_optional_datetime,
    _parse_optional_int,
)

# ── auth ──────────────────────────────────────────────────────────────────────


def test_staff_session_auth_mixin_accepts_staff(mock_staff_credentials: MagicMock) -> None:
    """StaffSessionAuthMixin accepts a staff session."""
    api = MagicMock()
    # Call the authenticate method directly via the mixin's class
    result = DashboardAPI.authenticate(api, mock_staff_credentials)
    assert result is True


def test_staff_session_auth_mixin_rejects_patient(mock_patient_credentials: MagicMock) -> None:
    """StaffSessionAuthMixin rejects a patient session (fail closed)."""
    api = MagicMock()
    with pytest.raises(InvalidCredentialsError):
        DashboardAPI.authenticate(api, mock_patient_credentials)


# ── static asset routes ───────────────────────────────────────────────────────


def test_get_html_returns_200_html_response() -> None:
    """GET /app/ returns an HTMLResponse with HTTP 200."""
    mock_self = MagicMock()
    mock_self.request.headers.get.return_value = "staff-abc"
    mock_self.secrets = {}

    with patch(
        "population_vitals_dashboard.handlers.dashboard_api.render_to_string",
        return_value="<html></html>",
    ) as mock_render:
        result = DashboardAPI.get_html(mock_self)

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    mock_render.assert_called_once()
    call_args = mock_render.call_args
    assert call_args[0][0] == "templates/index.html"
    ctx = call_args[0][1]
    assert ctx["cache_bust"] == _CACHE_BUST
    assert "api_prefix" in ctx


def test_get_js_returns_200_js_response() -> None:
    """GET /app/main.js returns a JS content response with HTTP 200."""
    mock_self = MagicMock()
    mock_self.secrets = {}

    with patch(
        "population_vitals_dashboard.handlers.dashboard_api.render_to_string",
        return_value="/* js */",
    ):
        result = DashboardAPI.get_js(mock_self)

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    assert b"js" in response.content


def test_get_css_returns_200_css_response() -> None:
    """GET /app/styles.css returns a CSS content response with HTTP 200."""
    mock_self = MagicMock()
    mock_self.secrets = {}

    with patch(
        "population_vitals_dashboard.handlers.dashboard_api.render_to_string",
        return_value="body {}",
    ):
        result = DashboardAPI.get_css(mock_self)

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    assert b"body" in response.content


# ── /app/stats — parameter validation ─────────────────────────────────────────


def _make_api_with_params(params: dict[str, str]) -> MagicMock:
    mock_self = MagicMock()
    mock_self.request.query_params = params
    mock_self.secrets = {}
    return mock_self


def test_stats_missing_metric_returns_400() -> None:
    """Omitting the metric parameter returns HTTP 400."""
    api = _make_api_with_params({})
    result = DashboardAPI.get_stats(api)
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_stats_unknown_metric_returns_400() -> None:
    """An unknown metric name returns HTTP 400."""
    api = _make_api_with_params({"metric": "heartrate_invalid"})
    result = DashboardAPI.get_stats(api)
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_stats_start_after_end_returns_400() -> None:
    """start >= end returns HTTP 400."""
    api = _make_api_with_params({"metric": "weight", "start": "2025-06-01", "end": "2025-01-01"})
    result = DashboardAPI.get_stats(api)
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


# ── /app/stats — business logic ───────────────────────────────────────────────


def test_stats_small_cohort_returns_200_with_error_key() -> None:
    """A cohort_too_small result from get_stats maps to HTTP 200 with error field."""
    api = _make_api_with_params({"metric": "weight"})

    with patch(
        "population_vitals_dashboard.handlers.dashboard_api.get_stats",
        return_value={
            "error": "cohort_too_small",
            "cohort_count": 3,
            "min_cohort_size": 11,
        },
    ):
        result = DashboardAPI.get_stats(api)

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    import json as _json

    body = _json.loads(response.content)
    assert body["error"] == "cohort_too_small"
    assert "message" in body


def test_stats_no_data_returns_200_with_error_key() -> None:
    """A no_data result from get_stats maps to HTTP 200 with error field."""
    api = _make_api_with_params({"metric": "bmi"})

    with patch(
        "population_vitals_dashboard.handlers.dashboard_api.get_stats",
        return_value={"error": "no_data", "cohort_count": 50},
    ):
        result = DashboardAPI.get_stats(api)

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    import json as _json

    body = _json.loads(response.content)
    assert body["error"] == "no_data"


def test_stats_success_returns_200_with_data() -> None:
    """A successful aggregation result returns HTTP 200 with a data key."""
    api = _make_api_with_params({"metric": "weight", "sex": "F", "min_age": "30", "max_age": "50"})

    fake_stats: dict[str, object] = {
        "data": {
            "metric": "weight",
            "display_name": "Weight",
            "cohort_count": 120,
            "count": 450,
            "mean": 165.3,
            "median": 162.0,
            "unit": "oz",
            "histogram": [{"min": 100.0, "max": 200.0, "count": 450}],
            "monthly_trend": [{"month": "2025-01", "median": 162.0, "count": 40}],
        }
    }

    with patch(
        "population_vitals_dashboard.handlers.dashboard_api.get_stats",
        return_value=fake_stats,
    ) as mock_get_stats:
        result = DashboardAPI.get_stats(api)

    assert len(result) == 1
    response = result[0]
    assert response.status_code == HTTPStatus.OK
    import json as _json

    body = _json.loads(response.content)
    assert "data" in body
    assert body["data"]["metric"] == "weight"

    # Verify get_stats was called with the correct cohort arguments.
    mock_get_stats.assert_called_once()
    call_kwargs = mock_get_stats.call_args.kwargs
    assert call_kwargs["metric"] == "weight"
    assert call_kwargs["sex"] == "F"
    assert call_kwargs["min_age"] == 30
    assert call_kwargs["max_age"] == 50


def test_stats_passes_secrets_to_get_stats() -> None:
    """The handler forwards self.secrets to get_stats so min cohort size can be read."""
    api = _make_api_with_params({"metric": "height"})
    api.secrets = {"MIN_COHORT_SIZE": "20"}

    with patch(
        "population_vitals_dashboard.handlers.dashboard_api.get_stats",
        return_value={"error": "no_data", "cohort_count": 5},
    ) as mock_get_stats:
        DashboardAPI.get_stats(api)

    call_kwargs = mock_get_stats.call_args.kwargs
    assert call_kwargs["secrets"] == {"MIN_COHORT_SIZE": "20"}


# ── parsing helpers ───────────────────────────────────────────────────────────


def test_parse_optional_int_valid() -> None:
    assert _parse_optional_int("42") == 42


def test_parse_optional_int_none() -> None:
    assert _parse_optional_int(None) is None


def test_parse_optional_int_empty() -> None:
    assert _parse_optional_int("") is None


def test_parse_optional_int_invalid() -> None:
    assert _parse_optional_int("abc") is None


def test_parse_optional_datetime_date_string() -> None:
    result = _parse_optional_datetime("2024-03-15")
    assert result is not None
    assert result.year == 2024
    assert result.month == 3
    assert result.day == 15
    assert result.tzinfo is not None


def test_parse_optional_datetime_iso_string() -> None:
    result = _parse_optional_datetime("2024-03-15T10:30:00")
    assert result is not None
    assert result.hour == 10


def test_parse_optional_datetime_none() -> None:
    assert _parse_optional_datetime(None) is None


def test_parse_optional_datetime_invalid() -> None:
    assert _parse_optional_datetime("not-a-date") is None
