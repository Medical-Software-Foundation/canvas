"""Tests for the live fetch against the plugin's real SQLite tables.

The Oura client is mocked; storage, OAuth rotation and normalization are real.
The central property: nothing fetched from Oura is ever written to the database.
"""

import datetime as dt
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from oura_ring_viewer.models import OuraOAuthToken, OuraSyncState
from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.fetch import (
    ERROR_ALL_FORBIDDEN,
    ERROR_API,
    ERROR_AUTH_FAILED,
    ERROR_NOT_CONNECTED,
    ERROR_REFRESH_FAILED,
    FetchResult,
    fetch_window,
)
from oura_ring_viewer.services.oauth import RefreshFailed, TokensNotFound
from oura_ring_viewer.services.oura_client import (
    OuraAPIError,
    OuraAuthError,
    OuraClient,
    OuraForbiddenError,
    TokenSet,
)
from oura_ring_viewer.services.settings import (
    FAMILY_ACTIVITY,
    FAMILY_READINESS,
    FAMILY_SLEEP,
    FAMILY_SPO2,
)
from oura_ring_viewer.services.storage import (
    delete_all_for_patient,
    get_sync_state,
    upsert_sync_state,
    upsert_tokens,
)

PATIENT = "patient-1"
OTHER = "patient-2"
NOW = dt.datetime(2026, 11, 2, 15, 0, tzinfo=dt.UTC)
TODAY = NOW.date()
START = TODAY - dt.timedelta(days=13)
DAY = (TODAY - dt.timedelta(days=1)).isoformat()


def _fixtures(day: str = DAY, *, score: int = 80) -> dict[str, list[dict[str, Any]]]:
    return {
        "daily_sleep": [{"day": day, "score": score}],
        "sleep": [
            {
                "day": day,
                "type": "long_sleep",
                "total_sleep_duration": 25_000,
                "efficiency": 90,
                "average_hrv": 45,
                "lowest_heart_rate": 50,
                "average_heart_rate": 55.0,
            }
        ],
        "daily_readiness": [{"day": day, "score": 75, "temperature_deviation": 0.1}],
        "daily_activity": [{"day": day, "score": 70, "steps": 9_000, "active_calories": 400}],
        "daily_spo2": [
            {"day": day, "spo2_percentage": {"average": 97.0}, "breathing_disturbance_index": 2}
        ],
    }


def _client(
    fixtures: dict[str, list[dict[str, Any]]] | None = None,
    *,
    fetch: Callable[..., Any] | None = None,
) -> MagicMock:
    client = MagicMock(spec=OuraClient)
    data = _fixtures() if fixtures is None else fixtures

    def default_fetch(access_token: str, endpoint: str, start: dt.date, end: dt.date) -> Any:
        return data.get(endpoint, [])

    client.fetch_collection.side_effect = fetch or default_fetch
    return client


def _raise(exc: Exception) -> Callable[..., Any]:
    def fetch(*args: Any) -> Any:
        raise exc

    return fetch


def _connect(patient_id: str = PATIENT, access: str = "AT", refresh: str = "RT") -> None:
    upsert_tokens(
        patient_id,
        access_token_ciphertext=access,
        refresh_token_ciphertext=refresh,
        expires_at=NOW + dt.timedelta(hours=1),
        scopes="daily spo2",
        now=NOW,
        is_initial_connection=True,
    )


def _fetch(client: MagicMock, *, patient_id: str = PATIENT, start: dt.date = START) -> FetchResult:
    return fetch_window(
        patient_id=patient_id, start_day=start, end_day=TODAY,
        client=client, cipher=TokenCipher(), now=NOW,
    )


def _families(result: FetchResult) -> set[str]:
    return {row.family for row in result.rows}


def _plugin_row_counts() -> dict[str, int]:
    """Row counts for every table this plugin owns (``models/__init__.py``)."""
    return {m.__name__: m.objects.count() for m in (OuraOAuthToken, OuraSyncState)}


class TestHappyPath:
    def test_returns_every_family_and_clears_errors(self) -> None:
        _connect()
        upsert_sync_state(PATIENT, last_error=ERROR_API, last_error_at=NOW)
        result = _fetch(_client())

        assert result.forbidden_endpoints == ()
        assert _families(result) == {FAMILY_SLEEP, FAMILY_READINESS, FAMILY_ACTIVITY, FAMILY_SPO2}
        sleep = next(r for r in result.rows if r.family == FAMILY_SLEEP)
        assert sleep.day == TODAY - dt.timedelta(days=1)
        assert sleep.payload["score"] == 80
        assert sleep.payload["average_hrv_ms"] == 45

        state = get_sync_state(PATIENT)
        assert state is not None
        assert state.last_synced_at == NOW
        assert state.last_error == ""
        assert state.last_error_at is None

    def test_requests_exactly_the_window(self) -> None:
        _connect()
        client = _client()
        _fetch(client)
        assert client.fetch_collection.call_count == 5
        for call in client.fetch_collection.call_args_list:
            assert call.args[2:] == (START, TODAY)

    def test_nothing_fetched_is_stored(self) -> None:
        _connect()
        upsert_sync_state(PATIENT, link_pending=False)
        before = _plugin_row_counts()
        _fetch(_client())
        assert _plugin_row_counts() == before
        state = OuraSyncState.objects.get(patient__id=PATIENT)
        stored_text = " ".join(str(getattr(state, f.name)) for f in state._meta.fields)
        assert "9000" not in stored_text and "97.0" not in stored_text

    def test_rows_outside_the_window_are_dropped(self) -> None:
        _connect()
        too_old = (START - dt.timedelta(days=1)).isoformat()
        tomorrow = (TODAY + dt.timedelta(days=1)).isoformat()
        fixtures = {
            "daily_readiness": [
                {"day": too_old, "score": 50},
                {"day": DAY, "score": 75},
                {"day": tomorrow, "score": 90},
            ]
        }
        result = _fetch(_client(fixtures))
        assert [r.day for r in result.rows] == [TODAY - dt.timedelta(days=1)]


class TestTokenRotation:
    def test_refreshes_once_then_reuses_the_rotated_token(self) -> None:
        _connect(access="AT1", refresh="RT1")
        data = _fixtures()
        seen: list[str] = []

        def fetch(access_token: str, endpoint: str, start: dt.date, end: dt.date) -> Any:
            seen.append(access_token)
            if access_token == "AT1":
                raise OuraAuthError("expired")
            return data[endpoint]

        client = _client(fetch=fetch)
        client.refresh.return_value = TokenSet("AT2", "RT2", 86_400, "bearer", "daily spo2")
        result = _fetch(client)

        client.refresh.assert_called_once_with("RT1")
        assert seen == ["AT1"] + ["AT2"] * 5
        assert len(result.rows) == 4
        stored = OuraOAuthToken.objects.get(patient__id=PATIENT)
        assert (stored.access_token, stored.refresh_token) == ("AT2", "RT2")
        assert stored.last_refresh_at == NOW

    def test_failed_refresh_records_error_and_keeps_old_tokens(self) -> None:
        _connect(access="AT1", refresh="RT1")
        client = _client(fetch=_raise(OuraAuthError("expired")))
        client.refresh.side_effect = OuraAuthError("invalid_grant")

        with pytest.raises(RefreshFailed):
            _fetch(client)

        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error == ERROR_REFRESH_FAILED
        assert OuraOAuthToken.objects.get(patient__id=PATIENT).refresh_token == "RT1"

    def test_still_rejected_after_refresh_is_an_auth_failure(self) -> None:
        _connect()
        client = _client(fetch=_raise(OuraAuthError("nope")))
        client.refresh.return_value = TokenSet("AT2", "RT2", 86_400, "bearer")

        with pytest.raises(OuraAuthError):
            _fetch(client)
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error == ERROR_AUTH_FAILED


class TestPartialAccess:
    def test_a_forbidden_family_is_skipped_not_fatal(self) -> None:
        _connect()
        data = _fixtures()

        def fetch(access_token: str, endpoint: str, start: dt.date, end: dt.date) -> Any:
            if endpoint == "daily_spo2":
                raise OuraForbiddenError(403, "scope not granted")
            return data[endpoint]

        client = _client(fetch=fetch)
        result = _fetch(client)

        assert result.forbidden_endpoints == ("daily_spo2",)
        assert _families(result) == {FAMILY_SLEEP, FAMILY_READINESS, FAMILY_ACTIVITY}
        client.refresh.assert_not_called()
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error == ""

    def test_sleep_survives_losing_one_of_its_two_endpoints(self) -> None:
        _connect()
        data = _fixtures()

        def fetch(access_token: str, endpoint: str, start: dt.date, end: dt.date) -> Any:
            if endpoint == "sleep":
                raise OuraForbiddenError(403, "")
            return data[endpoint]

        result = _fetch(_client(fetch=fetch))
        sleep = next(r for r in result.rows if r.family == FAMILY_SLEEP)
        assert sleep.payload["score"] == 80

    def test_everything_forbidden_records_an_error_and_returns_nothing(self) -> None:
        _connect()
        client = _client(fetch=_raise(OuraForbiddenError(403, "")))
        result = _fetch(client)

        assert result.rows == []
        assert len(result.forbidden_endpoints) == 5
        client.refresh.assert_not_called()
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error == ERROR_ALL_FORBIDDEN
        assert state.last_synced_at is None


class TestFailures:
    def test_never_connected(self) -> None:
        client = _client()
        with pytest.raises(TokensNotFound):
            _fetch(client)
        client.fetch_collection.assert_not_called()
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error == ERROR_NOT_CONNECTED

    def test_server_error_records_api_error(self) -> None:
        _connect()
        with pytest.raises(OuraAPIError):
            _fetch(_client(fetch=_raise(OuraAPIError(500, "down"))))
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error == ERROR_API
        assert state.last_error_at == NOW


class TestDisconnect:
    def test_removes_tokens_and_status_for_the_patient_only(self) -> None:
        _connect(PATIENT)
        _connect(OTHER)
        _fetch(_client(), patient_id=PATIENT)
        _fetch(_client(), patient_id=OTHER)

        delete_all_for_patient(PATIENT)

        assert not OuraOAuthToken.objects.filter(patient__id=PATIENT).exists()
        assert get_sync_state(PATIENT) is None
        assert OuraOAuthToken.objects.filter(patient__id=OTHER).exists()
        assert get_sync_state(OTHER) is not None
