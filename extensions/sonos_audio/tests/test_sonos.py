"""Unit tests for the sonos_audio plugin's pure logic.

These cover the pieces that don't require the Canvas runtime/DB: the Sonos API
client, the OAuth result page, the Application.on_open effect, and the
scheduler's time-matching decision.
"""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from sonos_audio.handlers.scheduler import PlaybackScheduler
from sonos_audio.services.sonos_client import SonosClient, oauth_message_page


class DummyEvent:
    def __init__(self, context: dict | None = None) -> None:
        self.context = context or {}


# ---------------------------------------------------------------------------
# SonosClient
# ---------------------------------------------------------------------------

def _resp(status=200, json_data=None, content=b"{}"):
    r = Mock()
    r.status_code = status
    r.content = content
    r.json.return_value = json_data if json_data is not None else {}
    r.raise_for_status.return_value = None
    return r


def test_basic_auth_is_base64_of_id_secret():
    client = SonosClient("id", "secret", "refresh")
    # base64("id:secret") == "aWQ6c2VjcmV0"
    assert client._get_basic_auth() == "aWQ6c2VjcmV0"


def test_get_token_refreshes_then_caches():
    client = SonosClient("id", "secret", "refresh")
    with patch("sonos_audio.services.sonos_client.http_requests.post",
               return_value=_resp(json_data={"access_token": "abc"})) as post:
        assert client._get_token() == "abc"
        assert client._get_token() == "abc"  # cached, no second call
    post.assert_called_once()


def test_request_retries_once_on_401():
    client = SonosClient("id", "secret", "refresh")
    client._access_token = "stale"
    seq = [_resp(status=401), _resp(status=200, json_data={"ok": True})]
    with patch("sonos_audio.services.sonos_client.http_requests.request", side_effect=seq) as req, \
         patch.object(client, "_refresh_access_token", return_value="fresh") as refresh:
        out = client._request("GET", "/households")
    assert out == {"ok": True}
    assert req.call_count == 2
    refresh.assert_called_once()


def test_load_favorite_posts_expected_payload():
    client = SonosClient("id", "secret", "refresh")
    with patch.object(client, "_request", return_value={"status": 200}) as req:
        client.load_favorite("group-1", "fav-9", play_on_completion=True)
    req.assert_called_once_with(
        "POST", "/groups/group-1/favorites",
        json={"favoriteId": "fav-9", "playOnCompletion": True},
    )


def test_set_volume_clamps_nothing_but_posts_volume():
    client = SonosClient("id", "secret", "refresh")
    with patch.object(client, "_request", return_value={"status": 200}) as req:
        client.set_volume("group-1", 40)
    req.assert_called_once_with("POST", "/groups/group-1/groupVolume", json={"volume": 40})


# ---------------------------------------------------------------------------
# OAuth result page
# ---------------------------------------------------------------------------

def test_oauth_page_success_posts_connected_message():
    html = oauth_message_page(True, "Connected to Demo")
    assert "sonos-connected" in html
    assert "Connected to Demo" in html
    assert "window.close" in html


def test_oauth_page_failure_escapes_and_signals_failed():
    html = oauth_message_page(False, "bad <script>alert(1)</script>")
    assert "sonos-failed" in html
    # The injected message is HTML-escaped, so it can't break out as real markup.
    assert "bad <script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ---------------------------------------------------------------------------
# Application.on_open
# ---------------------------------------------------------------------------

def test_on_open_returns_launch_modal_effect():
    from sonos_audio.applications.sonos_app import SonosApp

    app = SonosApp(event=DummyEvent({"event_type": "on_open"}))  # type: ignore[arg-type]
    effect = Mock()
    effect.apply.return_value = effect
    with patch("sonos_audio.applications.sonos_app.LaunchModalEffect", return_value=effect) as lm, \
         patch("sonos_audio.applications.sonos_app.render_to_string", return_value="<html></html>"):
        result = app.on_open()
    lm.assert_called_once()
    effect.apply.assert_called_once()
    assert result == effect


# ---------------------------------------------------------------------------
# Scheduler decision logic
# ---------------------------------------------------------------------------

WEEKDAYS_ALL = "0,1,2,3,4,5,6"


def test_parse_weekdays_handles_spaces_and_junk():
    assert PlaybackScheduler._parse_weekdays("0, 1 ,2,x,") == {0, 1, 2}
    assert PlaybackScheduler._parse_weekdays("") == set()


def test_decide_action_play_at_start():
    # 2026-06-01 is a Monday (weekday 0)
    dt = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    assert PlaybackScheduler.decide_action(dt, WEEKDAYS_ALL, "09:00", "17:00") == "play"


def test_decide_action_pause_at_stop():
    dt = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)
    assert PlaybackScheduler.decide_action(dt, WEEKDAYS_ALL, "09:00", "17:00") == "pause"


def test_decide_action_none_off_minute():
    dt = datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc)
    assert PlaybackScheduler.decide_action(dt, WEEKDAYS_ALL, "09:00", "17:00") is None


def test_decide_action_skips_non_scheduled_weekday():
    # Monday excluded; only weekends (5=Sat, 6=Sun)
    dt = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)  # Monday
    assert PlaybackScheduler.decide_action(dt, "5,6", "09:00", "17:00") is None
