"""Failure handling, revocation, time zones and static files."""

import datetime as dt
import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from oura_ring_viewer.models import OuraOAuthToken
from oura_ring_viewer.protocols.chart_api import OuraChartAPI
from oura_ring_viewer.protocols.portal_api import OuraPortalAPI
from oura_ring_viewer.services.chart_data import STATUS_CONNECTED, connection_status
from oura_ring_viewer.services.config import (
    FETCH_SECRETS,
    config_problems,
    is_sandbox,
)
from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.disconnect import stop_sharing
from oura_ring_viewer.services.fetch import (
    ERROR_API,
    ERROR_REFRESH_FAILED,
    fetch_window,
)
from oura_ring_viewer.services.oauth import (
    RefreshFailed,
    load_tokens,
    refresh_and_persist,
    revoke_at_oura,
)
from oura_ring_viewer.services.oura_client import (
    OuraAPIError,
    OuraAuthError,
    OuraClient,
    TokenSet,
    _TimedHttp,
)
from oura_ring_viewer.services.settings import REQUEST_TIMEOUT_SECONDS
from oura_ring_viewer.services.storage import (
    PatientNotFound,
    delete_all_for_patient,
    get_sync_state,
    upsert_sync_state,
    upsert_tokens,
)
from oura_ring_viewer.services.time_utils import local_today

PATIENT = "patient-1"
NOW = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.UTC)
SECRETS = {
    "OURA_CLIENT_ID": "cid",
    "OURA_CLIENT_SECRET": "sec",
    "OURA_REDIRECT_URI": "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/callback",
    "OURA_ENVIRONMENT": "sandbox",
    "OURA_MAGIC_LINK_SECRET": "m" * 40,
}
STAFF = {"canvas-logged-in-user-type": "Staff", "canvas-logged-in-user-id": "s1"}
ROTATED = TokenSet("AT2", "RT2", 3600, "bearer", "daily spo2")


def _store(access: str = "AT", refresh: str = "RT", patient_id: str = PATIENT) -> None:
    upsert_tokens(patient_id, access_token_ciphertext=access, refresh_token_ciphertext=refresh,
                  expires_at=NOW, scopes="daily spo2", now=NOW, is_initial_connection=True)


def _oura(http: MagicMock | None = None) -> tuple[OuraClient, MagicMock]:
    fake = http or MagicMock()
    return OuraClient("sandbox", "cid", "sec", "https://x/cb", http=fake), fake


class _Request:
    def __init__(self, query: dict[str, str], headers: dict[str, str],
                 path_params: dict[str, str] | None = None) -> None:
        self.query_params = query
        self.headers = headers
        self.path_params = path_params or {}


class _Event:
    def __init__(self, path: str) -> None:
        self.context = {"method": "GET", "path": path}


def _chart(path: str, *, secrets: dict[str, str] | None = None, tz: str | None = None,
           params: dict[str, str] | None = None, query: dict[str, str] | None = None) -> OuraChartAPI:
    handler = OuraChartAPI(event=_Event(path))
    handler.request = _Request({"patient_id": "abc123", **(query or {})}, STAFF, params)
    handler.secrets = SECRETS if secrets is None else secrets
    if tz:
        handler.environment = {"INSTALLATION_TIME_ZONE": tz}
    return handler


def _portal(params: dict[str, str] | None = None, secrets: dict[str, str] | None = None) -> OuraPortalAPI:
    handler = OuraPortalAPI(event=_Event("/portal/static"))
    handler.request = _Request({}, {"canvas-logged-in-user-id": "pat123"}, params)
    handler.secrets = SECRETS if secrets is None else secrets
    return handler


class TestNoUsableResponse:
    @pytest.mark.parametrize("exc", [
        requests.Timeout("https://api.ouraring.com/oauth/revoke?access_token=SECRET"),
        requests.ConnectionError("reset"),
        requests.exceptions.SSLError("bad cert"),
        TimeoutError("slow"),
    ])
    def test_a_transport_failure_becomes_an_oura_error_without_its_text(self, exc: Exception) -> None:
        client, http = _oura()
        http.get.side_effect = exc
        http.post.side_effect = exc
        calls = (
            lambda: client.fetch_collection("t", "daily_sleep", NOW.date(), NOW.date()),
            lambda: client.exchange_code("c"),
            lambda: client.refresh("r"),
            lambda: client.revoke("t"),
        )
        for call in calls:
            with pytest.raises(OuraAPIError) as caught:
                call()
            assert "SECRET" not in str(caught.value)

    @pytest.mark.parametrize("exc", [ValueError("no"), requests.exceptions.JSONDecodeError("no", "", 0)])
    def test_a_200_that_is_not_json(self, exc: Exception) -> None:
        client, http = _oura()
        response = MagicMock(status_code=200)
        response.json.side_effect = exc
        http.get.return_value = response
        http.post.return_value = response
        with pytest.raises(OuraAPIError):
            client.fetch_collection("t", "daily_sleep", NOW.date(), NOW.date())
        with pytest.raises(OuraAPIError):
            client.refresh("r")

    def test_requests_use_the_short_timeout(self) -> None:
        with patch("oura_ring_viewer.services.oura_client.requests") as lib:
            _TimedHttp().get("/v2/x", headers={"a": "b"})
            _TimedHttp().post("/oauth/token", data={"c": "d"})
        assert lib.get.call_args.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS
        assert lib.get.call_args.args[0] == "https://api.ouraring.com/v2/x"
        assert lib.post.call_args.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS

    def test_the_real_client_uses_the_timed_transport(self) -> None:
        assert isinstance(OuraClient("sandbox", "c", "s", "https://x")._http, _TimedHttp)


class TestRevokeCall:
    def test_posts_the_access_token(self) -> None:
        client, http = _oura()
        http.post.return_value = MagicMock(status_code=200)
        client.revoke("a/b")
        url = urlparse(http.post.call_args.args[0])
        assert url.path == "/oauth/revoke"
        assert parse_qs(url.query) == {"access_token": ["a/b"]}

    def test_a_dead_access_token(self) -> None:
        client, http = _oura()
        http.post.return_value = MagicMock(status_code=401)
        with pytest.raises(OuraAuthError):
            client.revoke("t")

    def test_a_server_error(self) -> None:
        client, http = _oura()
        http.post.return_value = MagicMock(status_code=500, text="down")
        with pytest.raises(OuraAPIError):
            client.revoke("t")


class TestRefreshRace:
    def _refresh(self, client: MagicMock) -> Any:
        return refresh_and_persist(PATIENT, client, TokenCipher(), "RT", now=NOW)

    def test_losing_after_the_winner_saved_uses_the_winners_tokens(self) -> None:
        _store(access="AT-winner", refresh="RT-winner")
        client = MagicMock(spec=OuraClient)
        client.refresh.side_effect = OuraAuthError("used")
        tokens = self._refresh(client)
        assert (tokens.access_token, tokens.refresh_token) == ("AT-winner", "RT-winner")

    def test_losing_just_before_the_winner_saves_looks_again(self) -> None:
        _store()
        client = MagicMock(spec=OuraClient)
        client.refresh.side_effect = OuraAuthError("used")
        with patch("oura_ring_viewer.services.oauth.time.sleep",
                   side_effect=lambda _: _store(access="AT-winner", refresh="RT-winner")) as sleep:
            tokens = self._refresh(client)
        sleep.assert_called_once()
        assert tokens.access_token == "AT-winner"

    def test_a_truly_dead_token_still_fails(self) -> None:
        _store()
        client = MagicMock(spec=OuraClient)
        client.refresh.side_effect = OuraAuthError("dead")
        with pytest.raises(RefreshFailed):
            self._refresh(client)

    def test_disconnected_during_the_refresh(self) -> None:
        client = MagicMock(spec=OuraClient)
        client.refresh.side_effect = OuraAuthError("dead")
        with pytest.raises(RefreshFailed):
            self._refresh(client)

    def test_the_loser_does_not_mark_the_patient_as_needing_to_reconnect(self) -> None:
        _store(access="AT-old", refresh="RT-old")
        client = MagicMock(spec=OuraClient)

        def fetch(access_token: str, *_: Any) -> list[dict[str, Any]]:
            if access_token == "AT-old":
                raise OuraAuthError("expired")
            return []

        def refresh(_: str) -> TokenSet:
            _store(access="AT-winner", refresh="RT-winner")
            raise OuraAuthError("used")

        client.fetch_collection.side_effect = fetch
        client.refresh.side_effect = refresh
        fetch_window(patient_id=PATIENT, start_day=NOW.date(), end_day=NOW.date(), client=client,
                     cipher=TokenCipher(), now=NOW)
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error != ERROR_REFRESH_FAILED
        assert connection_status(PATIENT)[0] == STATUS_CONNECTED

    def test_oura_being_down_during_a_refresh_is_not_a_dead_connection(self) -> None:
        _store()
        client = MagicMock(spec=OuraClient)
        client.fetch_collection.side_effect = OuraAuthError("expired")
        client.refresh.side_effect = OuraAPIError(503, "timeout")
        with pytest.raises(OuraAPIError):
            fetch_window(patient_id=PATIENT, start_day=NOW.date(), end_day=NOW.date(), client=client,
                         cipher=TokenCipher(), now=NOW)
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_error == ERROR_API
        assert connection_status(PATIENT)[0] == STATUS_CONNECTED
        assert load_tokens(PATIENT, TokenCipher()).refresh_token == "RT"


class TestRevocation:
    def _client(self) -> MagicMock:
        return MagicMock(spec=OuraClient)

    def test_confirmed(self) -> None:
        _store()
        client = self._client()
        assert revoke_at_oura(PATIENT, client, TokenCipher(), now=NOW) is True
        client.revoke.assert_called_once_with("AT")

    def test_an_expired_access_token_is_refreshed_first(self) -> None:
        _store()
        client = self._client()
        client.revoke.side_effect = [OuraAuthError("expired"), None]
        client.refresh.return_value = ROTATED
        assert revoke_at_oura(PATIENT, client, TokenCipher(), now=NOW) is True
        assert client.revoke.call_args.args == ("AT2",)

    @pytest.mark.parametrize("error", [OuraAPIError(503, "down"), OuraAuthError("still no")])
    def test_not_confirmed(self, error: Exception) -> None:
        _store()
        client = self._client()
        client.revoke.side_effect = [OuraAuthError("expired"), error]
        client.refresh.return_value = ROTATED
        assert revoke_at_oura(PATIENT, client, TokenCipher(), now=NOW) is False

    def test_refresh_refused(self) -> None:
        _store()
        client = self._client()
        client.revoke.side_effect = OuraAuthError("expired")
        client.refresh.side_effect = OuraAuthError("dead")
        assert revoke_at_oura(PATIENT, client, TokenCipher(), now=NOW) is False

    def test_nothing_to_revoke_counts_as_done(self) -> None:
        client = self._client()
        assert revoke_at_oura(PATIENT, client, TokenCipher(), now=NOW) is True
        client.revoke.assert_not_called()


class TestStopSharing:
    def test_revokes_before_removing_the_tokens(self) -> None:
        _store()
        with patch("oura_ring_viewer.services.disconnect.build_client") as build:
            build.return_value.revoke.side_effect = lambda _: self._still_stored()
            assert stop_sharing(PATIENT, SECRETS, NOW) is True
        assert not OuraOAuthToken.objects.filter(patient__id=PATIENT).exists()

    @staticmethod
    def _still_stored() -> None:
        assert OuraOAuthToken.objects.filter(patient__id=PATIENT).exists()

    def test_the_local_connection_goes_even_when_oura_does_not_confirm(self) -> None:
        _store()
        with patch("oura_ring_viewer.services.disconnect.build_client") as build:
            build.return_value.revoke.side_effect = OuraAPIError(503, "down")
            assert stop_sharing(PATIENT, SECRETS, NOW) is False
        assert not OuraOAuthToken.objects.filter(patient__id=PATIENT).exists()

    @pytest.mark.parametrize("secrets", [None, {}])
    def test_unusable_settings_still_remove_the_connection(self, secrets: dict[str, str] | None) -> None:
        _store()
        assert stop_sharing(PATIENT, secrets, NOW) is False
        assert not OuraOAuthToken.objects.filter(patient__id=PATIENT).exists()


class TestEnvironmentSetting:
    def test_a_typo_is_a_named_problem(self) -> None:
        problems = config_problems({**SECRETS, "OURA_ENVIRONMENT": "prod"}, FETCH_SECRETS)
        assert problems == ["OURA_ENVIRONMENT (must be one of: production, sandbox)"]

    @pytest.mark.parametrize("value", ["sandbox", "production", " Production "])
    def test_recognized_values(self, value: str) -> None:
        assert config_problems({**SECRETS, "OURA_ENVIRONMENT": value}, FETCH_SECRETS) == []

    def test_unset_is_a_named_problem(self) -> None:
        assert config_problems({**SECRETS, "OURA_ENVIRONMENT": ""}, FETCH_SECRETS) == ["OURA_ENVIRONMENT"]

    def test_is_sandbox(self) -> None:
        assert is_sandbox({"OURA_ENVIRONMENT": " sandbox "}) is True
        assert is_sandbox({"OURA_ENVIRONMENT": "production"}) is False
        assert is_sandbox({"OURA_ENVIRONMENT": "prod"}) is False
        assert is_sandbox(None) is False

    @pytest.mark.parametrize("env, shown", [("sandbox", True), ("production", False)])
    def test_the_chart_is_told_when_it_is_showing_sample_data(self, env: str, shown: bool) -> None:
        handler = _chart("/data", secrets={**SECRETS, "OURA_ENVIRONMENT": env})
        with patch("oura_ring_viewer.protocols.chart_api._gate") as gate:
            gate.return_value = MagicMock(patient_id="abc123", staff_id="s1")
            body = json.loads(handler.chart_data()[0].content)
        assert body["sandbox"] is shown


class TestLocalDate:
    @pytest.mark.parametrize("now, tz, expected", [
        (dt.datetime(2026, 11, 6, 3, 30, tzinfo=dt.UTC), "America/New_York", dt.date(2026, 11, 5)),
        (dt.datetime(2026, 11, 6, 7, 59, tzinfo=dt.UTC), "America/Los_Angeles", dt.date(2026, 11, 5)),
        (dt.datetime(2026, 11, 6, 8, 0, tzinfo=dt.UTC), "America/Los_Angeles", dt.date(2026, 11, 6)),
        (dt.datetime(2026, 11, 6, 5, 0, tzinfo=dt.UTC), "America/New_York", dt.date(2026, 11, 6)),
        (dt.datetime(2026, 11, 5, 23, 59, tzinfo=dt.UTC), "Asia/Tokyo", dt.date(2026, 11, 6)),
    ])
    def test_midnight_is_the_practices_midnight(self, now: dt.datetime, tz: str, expected: dt.date) -> None:
        assert local_today(now, {"INSTALLATION_TIME_ZONE": tz}) == expected

    @pytest.mark.parametrize("environment", [None, {}, {"INSTALLATION_TIME_ZONE": ""}])
    def test_falls_back_to_utc(self, environment: Any) -> None:
        now = dt.datetime(2026, 11, 6, 3, 30, tzinfo=dt.UTC)
        assert local_today(now, environment) == dt.date(2026, 11, 6)

    def test_a_us_evening_does_not_run_a_day_ahead(self) -> None:
        handler = _chart("/data", tz="America/Los_Angeles", query={"range": "7d"})
        evening = dt.datetime(2026, 11, 6, 3, 30, tzinfo=dt.UTC)
        with (
            patch("oura_ring_viewer.protocols.chart_api._gate") as gate,
            patch("oura_ring_viewer.protocols.chart_api._now", return_value=evening),
        ):
            gate.return_value = MagicMock(patient_id="abc123", staff_id="s1")
            body = json.loads(handler.chart_data()[0].content)
        assert body["days"][-1] == "2026-11-05"


class TestStaticFiles:
    @pytest.mark.parametrize("name, kind", [("chart.js", "text/javascript"), ("chart.css", "text/css")])
    def test_chart_assets(self, name: str, kind: str) -> None:
        effect = _chart("/static", params={"asset": name}).static_asset()[0]
        assert effect.status_code == HTTPStatus.OK
        assert effect.headers["Content-Type"] == kind
        assert effect.content

    @pytest.mark.parametrize("name, kind", [
        ("portal.js", "text/javascript"), ("portal.css", "text/css"), ("shared.css", "text/css"),
    ])
    def test_portal_assets(self, name: str, kind: str) -> None:
        effect = _portal({"asset": name}).static_asset()[0]
        assert effect.status_code == HTTPStatus.OK
        assert effect.headers["Content-Type"] == kind

    @pytest.mark.parametrize("name", ["../CANVAS_MANIFEST.json", "portal.js", "nope.js", ""])
    def test_the_chart_serves_only_its_own_files(self, name: str) -> None:
        assert _chart("/static", params={"asset": name}).static_asset()[0].status_code == HTTPStatus.NOT_FOUND

    def test_the_portal_serves_only_its_own_files(self) -> None:
        assert _portal({"asset": "chart.js"}).static_asset()[0].status_code == HTTPStatus.NOT_FOUND


def test_portal_start_names_the_unusable_setting_in_the_log() -> None:
    from oura_ring_viewer.protocols import portal_api

    handler = _portal(secrets={})
    with patch.object(portal_api, "log") as log:
        effect = handler.start()[0]
    assert effect.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert "OURA_CLIENT_ID" in log.error.call_args[0][0]


class TestPatientReference:
    def test_rows_cannot_exist_without_a_real_patient(self) -> None:
        with pytest.raises(PatientNotFound):
            upsert_sync_state("no-such-patient", link_pending=True)

    def test_delete_leaves_other_patients(self) -> None:
        _store()
        _store(patient_id="patient-2")
        delete_all_for_patient(PATIENT)
        assert OuraOAuthToken.objects.filter(patient__id="patient-2").exists()


