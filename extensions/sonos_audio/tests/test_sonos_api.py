"""Tests for the SonosApi SimpleAPI endpoints, the PlaybackScheduler.execute()
cron tick, and the CustomModel definitions.

The endpoints lazily import their models from ``sonos_audio.models.custom_data``
inside each method, so we patch the model classes there. ``PracticeLocation``
and ``http_requests`` are module-level imports in ``sonos_app`` and are patched
at that path.
"""
import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests as http_requests

import pytest

MODELS = "sonos_audio.models.custom_data"
APP = "sonos_audio.applications.sonos_app"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeQS:
    """Minimal stand-in for a Django QuerySet used by the endpoints."""

    def __init__(self, items=None, first=None, exists=None, count=None):
        self._items = list(items) if items is not None else []
        self._first = first if first is not None else (self._items[0] if self._items else None)
        self._exists = exists if exists is not None else bool(self._items)
        self._count = count if count is not None else len(self._items)
        self.updated = None

    def filter(self, *a, **k):
        return self

    def exclude(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self

    def first(self):
        return self._first

    def exists(self):
        return self._exists

    def count(self):
        return self._count

    def update(self, **k):
        self.updated = k
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, key):
        return self._items[key]


def fake_speaker(**over):
    base = dict(
        pk=1, location_id="loc1", location_name="Main", player_id="p1",
        group_id="g1", player_name="Kitchen", household_id="hh1",
        default_favorite_id="", default_favorite_name="", default_volume=25,
        active=True,
    )
    base.update(over)
    m = Mock(**base)
    m.save = Mock()
    return m


def fake_preset(**over):
    base = dict(
        pk=2, key="calm", match_type="default", match_value="",
        sonos_favorite_id="fav1", sonos_favorite_name="Spa", volume=20,
        priority=5, active=True,
    )
    base.update(over)
    # ``name`` is reserved by Mock's constructor, so set it after construction.
    name = base.pop("name", "Calm")
    m = Mock(**base)
    m.name = name
    return m


def make_api(secrets=None, query=None, body="{}", path_params=None, headers=None):
    from sonos_audio.applications.sonos_app import SonosApi

    api = SonosApi(event=Mock(context={"method": "GET", "path": "/__none__"}))
    api.secrets = secrets if secrets is not None else {}
    api.environment = {"CUSTOMER_IDENTIFIER": "demo"}
    api.request = Mock(
        query_params=query or {},
        body=body,
        path_params=path_params or {},
        headers=headers or {},
    )
    return api


def body_of(response):
    return json.loads(bytes(response.content).decode())


CONNECTED_SECRETS = {"SONOS_CLIENT_ID": "cid", "SONOS_CLIENT_SECRET": "csec"}


# ---------------------------------------------------------------------------
# Helpers / locations
# ---------------------------------------------------------------------------

def test_redirect_uri_uses_customer_identifier():
    api = make_api()
    assert api._sonos_redirect_uri() == (
        "https://demo.canvasmedical.com/plugin-io/api/sonos_audio/sonos/oauth/callback"
    )


def test_locations_lists_active():
    api = make_api()
    with patch(f"{APP}.PracticeLocation") as PL:
        PL.objects.filter.return_value.values.return_value.order_by.return_value = [
            {"id": "loc1", "full_name": "Main Clinic", "short_name": "MC"},
            {"id": "loc2", "full_name": "", "short_name": "Annex"},
        ]
        out = api.locations()
    data = body_of(out[0])
    assert data["locations"][0]["name"] == "Main Clinic"
    assert data["locations"][1]["name"] == "Annex"  # falls back to short_name


# ---------------------------------------------------------------------------
# status & OAuth
# ---------------------------------------------------------------------------

def test_status_demo_when_no_creds():
    api = make_api()
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Sp.objects.filter.return_value.count.return_value = 3
        Cr.objects.first.return_value = None
        out = api.sonos_status()
    data = body_of(out[0])
    assert data["demo_mode"] is True
    assert data["connected"] is False
    assert data["speaker_count"] == 3


def test_status_connected():
    api = make_api(secrets=CONNECTED_SECRETS)
    cred = Mock(refresh_token="rt", household_name="Home", household_id="hh1",
                connected_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.SonosOAuthCredential") as Cr, \
         patch(f"{APP}.SonosClient"):
        Sp.objects.filter.return_value.count.return_value = 1
        Cr.objects.first.return_value = cred
        out = api.sonos_status()
    data = body_of(out[0])
    assert data["connected"] is True
    assert data["has_app_keys"] is True
    assert data["household_name"] == "Home"
    assert data["connected_at"].startswith("2026-01-01")


def test_oauth_start_without_keys_returns_help_page():
    api = make_api()
    out = api.sonos_oauth_start()
    assert out[0].status_code == 200
    assert "app keys aren't set" in bytes(out[0].content).decode()


def test_oauth_start_creates_credential_when_none():
    api = make_api(secrets=CONNECTED_SECRETS)
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Cr.objects.create.return_value = Mock()
        out = api.sonos_oauth_start()
    Cr.objects.create.assert_called_once()
    html = bytes(out[0].content).decode()
    assert "api.sonos.com/login/v3/oauth" in html


def test_oauth_start_updates_existing_credential():
    api = make_api(secrets=CONNECTED_SECRETS)
    cred = Mock()
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = cred
        api.sonos_oauth_start()
    cred.save.assert_called_once()
    assert cred.pending_state


def test_oauth_callback_provider_error():
    api = make_api(query={"error": "access_denied"})
    out = api.sonos_oauth_callback()
    assert "access_denied" in bytes(out[0].content).decode()


def test_oauth_callback_missing_code():
    api = make_api(query={"state": "s"})
    out = api.sonos_oauth_callback()
    assert out[0].status_code == 400


def test_oauth_callback_state_mismatch():
    api = make_api(query={"code": "c", "state": "s"})
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = Mock(pending_state="different")
        out = api.sonos_oauth_callback()
    assert out[0].status_code == 400
    assert "State mismatch" in bytes(out[0].content).decode()


def test_oauth_callback_token_exchange_failure():
    api = make_api(secrets=CONNECTED_SECRETS, query={"code": "c", "state": "s"})
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.http_requests") as hr:
        Cr.objects.first.return_value = Mock(pending_state="s")
        hr.post.return_value = Mock(status_code=400, text="bad")
        out = api.sonos_oauth_callback()
    assert "rejected the authorization code" in bytes(out[0].content).decode()


def test_oauth_callback_no_refresh_token():
    api = make_api(secrets=CONNECTED_SECRETS, query={"code": "c", "state": "s"})
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.http_requests") as hr:
        Cr.objects.first.return_value = Mock(pending_state="s")
        hr.post.return_value = Mock(status_code=200, json=Mock(return_value={"access_token": "a"}))
        out = api.sonos_oauth_callback()
    assert "no refresh token" in bytes(out[0].content).decode()


def test_oauth_callback_success_stores_household():
    api = make_api(secrets=CONNECTED_SECRETS, query={"code": "c", "state": "s"},
                   headers={"canvas-logged-in-user-id": "staff9"})
    cred = Mock(pending_state="s")
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.http_requests") as hr:
        Cr.objects.first.return_value = cred
        token_resp = Mock(status_code=200,
                          json=Mock(return_value={"refresh_token": "rt", "access_token": "at"}))
        hh_resp = Mock(status_code=200,
                       json=Mock(return_value={"households": [{"id": "h1", "name": "Clinic"}]}))
        hr.post.return_value = token_resp
        hr.get.return_value = hh_resp
        out = api.sonos_oauth_callback()
    assert cred.refresh_token == "rt"
    assert cred.household_name == "Clinic"
    assert cred.connected_by_staff_id == "staff9"
    cred.save.assert_called_once()
    assert "Connected to Clinic" in bytes(out[0].content).decode()


def test_oauth_disconnect_clears_credential():
    api = make_api()
    cred = Mock()
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = cred
        out = api.sonos_oauth_disconnect()
    assert cred.refresh_token == ""
    cred.save.assert_called_once()
    assert body_of(out[0])["disconnected"] is True


def test_oauth_disconnect_noop_when_no_credential():
    api = make_api()
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        out = api.sonos_oauth_disconnect()
    assert body_of(out[0])["disconnected"] is True


# ---------------------------------------------------------------------------
# discovery (demo + connected + error)
# ---------------------------------------------------------------------------

def test_households_demo():
    api = make_api()
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        out = api.sonos_households()
    assert "households" in body_of(out[0])


def test_households_connected_success_and_error():
    api = make_api(secrets=CONNECTED_SECRETS)
    client = Mock()
    client.get_households.return_value = {"households": [{"id": "h"}]}
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        out = api.sonos_households()
        assert body_of(out[0])["households"][0]["id"] == "h"
        client.get_households.side_effect = http_requests.exceptions.RequestException("boom")
        out = api.sonos_households()
        assert out[0].status_code == 502


def test_players_requires_household_id():
    api = make_api(query={})
    out = api.sonos_players()
    assert out[0].status_code == 400


def test_players_demo():
    api = make_api(query={"household_id": "hh"})
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        out = api.sonos_players()
    assert "players" in body_of(out[0])


def test_players_connected_error():
    api = make_api(secrets=CONNECTED_SECRETS, query={"household_id": "hh"})
    client = Mock()
    client.get_groups.side_effect = http_requests.exceptions.RequestException("x")
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        out = api.sonos_players()
    assert out[0].status_code == 502


def test_favorites_requires_household_id():
    api = make_api(query={})
    out = api.sonos_favorites()
    assert out[0].status_code == 400


def test_favorites_demo_and_connected():
    api = make_api(query={"household_id": "hh"})
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        assert "items" in body_of(api.sonos_favorites()[0])

    api2 = make_api(secrets=CONNECTED_SECRETS, query={"household_id": "hh"})
    client = Mock()
    client.get_favorites.return_value = {"items": [{"id": "f"}]}
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        out = api2.sonos_favorites()
    assert body_of(out[0])["items"][0]["id"] == "f"


# ---------------------------------------------------------------------------
# speaker CRUD
# ---------------------------------------------------------------------------

def test_get_speakers_serializes():
    api = make_api()
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value.order_by.return_value = [fake_speaker()]
        out = api.get_sonos_speakers()
    assert body_of(out[0])["speakers"][0]["player_name"] == "Kitchen"


def test_create_speaker_invalid_json():
    api = make_api(body="not json")
    with patch(f"{MODELS}.SonosSpeaker"):
        out = api.create_sonos_speaker()
    assert out[0].status_code == 400


def test_create_speaker_missing_field():
    api = make_api(body=json.dumps({"location_id": "l"}))
    with patch(f"{MODELS}.SonosSpeaker"):
        out = api.create_sonos_speaker()
    assert out[0].status_code == 400


def test_create_speaker_updates_existing():
    payload = {"location_id": "loc1", "player_id": "p2", "player_name": "K2", "household_id": "hh"}
    api = make_api(body=json.dumps(payload))
    existing = fake_speaker()
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value.first.return_value = existing
        out = api.create_sonos_speaker()
    assert body_of(out[0])["updated"] is True
    existing.save.assert_called_once()


def test_create_speaker_creates_new():
    payload = {"location_id": "locX", "player_id": "p2", "player_name": "K2", "household_id": "hh"}
    api = make_api(body=json.dumps(payload))
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value.first.return_value = None
        Sp.objects.create.return_value = Mock(pk=7)
        out = api.create_sonos_speaker()
    assert out[0].status_code == 201
    assert body_of(out[0])["id"] == 7


def test_update_speaker_not_found():
    api = make_api(body=json.dumps({"player_name": "x"}), path_params={"player_id": "p1"})
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value = FakeQS(exists=False)
        out = api.update_sonos_speaker()
    assert out[0].status_code == 404


def test_update_speaker_success():
    api = make_api(body=json.dumps({"player_name": "x", "default_volume": 10, "location_id": "loc2"}),
                   path_params={"player_id": "p1"})
    qs = FakeQS(items=[fake_speaker()], exists=True)
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value = qs
        out = api.update_sonos_speaker()
    assert body_of(out[0])["success"] is True
    assert qs.updated == {"player_name": "x", "default_volume": 10, "location_id": "loc2"}


def test_update_speaker_invalid_json():
    api = make_api(body="x", path_params={"player_id": "p1"})
    with patch(f"{MODELS}.SonosSpeaker"):
        out = api.update_sonos_speaker()
    assert out[0].status_code == 400


def test_delete_speaker_not_found_and_success():
    api = make_api(path_params={"player_id": "p1"})
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value.first.return_value = None
        assert api.delete_sonos_speaker()[0].status_code == 404
        sp = fake_speaker()
        Sp.objects.filter.return_value.first.return_value = sp
        out = api.delete_sonos_speaker()
    assert sp.active is False
    assert body_of(out[0])["success"] is True


def test_create_speaker_allows_multiple_per_location():
    # A new player at an already-used location creates a second mapping (no upsert).
    payload = {"location_id": "loc1", "player_id": "pNEW", "player_name": "Hallway", "household_id": "hh"}
    api = make_api(body=json.dumps(payload))
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value.first.return_value = None  # no existing player_id=pNEW
        Sp.objects.create.return_value = Mock(pk=9)
        out = api.create_sonos_speaker()
    assert out[0].status_code == 201
    # upsert keyed on player_id, not location_id
    _, kwargs = Sp.objects.filter.call_args
    assert kwargs == {"player_id": "pNEW"}


# ---------------------------------------------------------------------------
# preset CRUD
# ---------------------------------------------------------------------------

def test_get_presets():
    api = make_api()
    with patch(f"{MODELS}.AudioPreset") as Ap:
        Ap.objects.filter.return_value.order_by.return_value = [fake_preset()]
        out = api.get_sonos_presets()
    assert body_of(out[0])["presets"][0]["key"] == "calm"


def test_create_preset_paths():
    # invalid json
    with patch(f"{MODELS}.AudioPreset"):
        assert make_api(body="x").create_sonos_preset()[0].status_code == 400
    # missing field
    with patch(f"{MODELS}.AudioPreset"):
        out = make_api(body=json.dumps({"key": "k"})).create_sonos_preset()
        assert out[0].status_code == 400
    # conflict
    api = make_api(body=json.dumps({"key": "k", "name": "n", "match_type": "default"}))
    with patch(f"{MODELS}.AudioPreset") as Ap:
        Ap.objects.filter.return_value.exists.return_value = True
        assert api.create_sonos_preset()[0].status_code == 409
    # create
    api = make_api(body=json.dumps({"key": "k2", "name": "n", "match_type": "default"}))
    with patch(f"{MODELS}.AudioPreset") as Ap:
        Ap.objects.filter.return_value.exists.return_value = False
        Ap.objects.create.return_value = Mock(pk=3)
        out = api.create_sonos_preset()
    assert out[0].status_code == 201


def test_update_preset_not_found_and_success():
    api = make_api(body=json.dumps({"name": "n2"}), path_params={"key": "calm"})
    with patch(f"{MODELS}.AudioPreset") as Ap:
        Ap.objects.filter.return_value = FakeQS(exists=False)
        assert api.update_sonos_preset()[0].status_code == 404
    qs = FakeQS(items=[fake_preset()], exists=True)
    with patch(f"{MODELS}.AudioPreset") as Ap:
        Ap.objects.filter.return_value = qs
        out = api.update_sonos_preset()
    assert qs.updated == {"name": "n2"}
    assert body_of(out[0])["success"] is True


def test_update_preset_invalid_json():
    api = make_api(body="x", path_params={"key": "calm"})
    with patch(f"{MODELS}.AudioPreset"):
        assert api.update_sonos_preset()[0].status_code == 400


def test_delete_preset_not_found_and_success():
    api = make_api(path_params={"key": "calm"})
    with patch(f"{MODELS}.AudioPreset") as Ap:
        Ap.objects.filter.return_value.first.return_value = None
        assert api.delete_sonos_preset()[0].status_code == 404
        p = fake_preset()
        Ap.objects.filter.return_value.first.return_value = p
        out = api.delete_sonos_preset()
    assert p.active is False
    assert body_of(out[0])["success"] is True


def test_seed_presets_counts_created():
    api = make_api()
    with patch(f"{MODELS}.AudioPreset") as Ap:
        Ap.objects.get_or_create.side_effect = [(Mock(), True), (Mock(), False)] * 10
        out = api.seed_sonos_presets()
    assert body_of(out[0])["success"] is True
    assert body_of(out[0])["presets_created"] >= 1


# ---------------------------------------------------------------------------
# playback control (fan-out by location, or single by player_id)
# ---------------------------------------------------------------------------

def test_play_invalid_json_and_missing_target():
    with patch(f"{MODELS}.AudioPreset"), patch(f"{MODELS}.SonosPlaybackLog"), \
         patch(f"{MODELS}.SonosSpeaker"), patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        assert make_api(body="x").sonos_play()[0].status_code == 400
        assert make_api(body=json.dumps({})).sonos_play()[0].status_code == 400


def test_play_no_speaker():
    api = make_api(body=json.dumps({"location_id": "loc1"}))
    with patch(f"{MODELS}.AudioPreset"), patch(f"{MODELS}.SonosPlaybackLog"), \
         patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[])
        out = api.sonos_play()
    assert out[0].status_code == 404


def test_play_no_favorite_resolvable():
    api = make_api(body=json.dumps({"location_id": "loc1"}))
    speaker = fake_speaker(default_favorite_id="")
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset") as Ap, \
         patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        Ap.objects.filter.return_value.exclude.return_value = []
        out = api.sonos_play()
    assert out[0].status_code == 404
    assert "Pick a station" in bytes(out[0].content).decode()


def test_play_demo_resolves_location_preset_and_logs():
    api = make_api(body=json.dumps({"location_id": "loc1"}))
    speaker = fake_speaker(default_favorite_id="")
    preset = fake_preset(match_type="location", match_value="loc1", sonos_favorite_id="favL", volume=33)
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset") as Ap, \
         patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        Ap.objects.filter.return_value.exclude.return_value = [preset]
        out = api.sonos_play()
    data = body_of(out[0])
    assert data["played_count"] == 1
    assert data["results"][0]["favorite_id"] == "favL"
    assert data["results"][0]["volume"] == 33
    Log.objects.create.assert_called_once()
    speaker.save.assert_called_once()  # remembered as default


def test_play_fans_out_to_all_speakers_in_location():
    api = make_api(body=json.dumps({"location_id": "loc1", "favorite_id": "fX", "volume": 40}))
    s1 = fake_speaker(player_id="p1", player_name="A")
    s2 = fake_speaker(player_id="p2", player_name="B")
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset"), \
         patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[s1, s2])
        out = api.sonos_play()
    data = body_of(out[0])
    assert data["played_count"] == 2
    assert {r["player_id"] for r in data["results"]} == {"p1", "p2"}
    assert Log.objects.create.call_count == 2


def test_play_single_speaker_by_player_id_non_demo_clamps_volume():
    api = make_api(secrets=CONNECTED_SECRETS,
                   body=json.dumps({"player_id": "p1", "favorite_id": "fX", "volume": 200}))
    speaker = fake_speaker(player_id="p1")
    client = Mock()
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset"), \
         patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosOAuthCredential") as Cr, \
         patch(f"{APP}.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        out = api.sonos_play()
    data = body_of(out[0])
    assert data["results"][0]["volume"] == 100  # clamped
    client.load_favorite.assert_called_once()
    client.set_volume.assert_called_once()
    Log.objects.create.assert_called_once()


def test_play_non_demo_all_error_returns_502():
    api = make_api(secrets=CONNECTED_SECRETS,
                   body=json.dumps({"location_id": "loc1", "favorite_id": "fX"}))
    speaker = fake_speaker()
    client = Mock()
    client.load_favorite.side_effect = http_requests.exceptions.RequestException("net")
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset"), \
         patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosOAuthCredential") as Cr, \
         patch(f"{APP}.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        out = api.sonos_play()
    assert out[0].status_code == 502


def test_play_uses_preset_key_and_bad_volume_falls_back():
    api = make_api(body=json.dumps({"location_id": "loc1", "preset_key": "calm", "volume": "abc"}))
    speaker = fake_speaker(default_volume=42)
    preset = fake_preset(sonos_favorite_id="favP", volume=None)
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset") as Ap, \
         patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        Ap.objects.filter.return_value.first.return_value = preset
        out = api.sonos_play()
    data = body_of(out[0])
    assert data["results"][0]["favorite_id"] == "favP"
    assert data["results"][0]["volume"] == 42  # bad volume -> speaker default


def test_play_volume_zero_is_preserved_not_defaulted():
    # volume 0 (mute) must not be coerced to 25 by a falsy-zero fallback.
    api = make_api(body=json.dumps({"location_id": "loc1", "favorite_id": "fX", "volume": 0}))
    speaker = fake_speaker(default_volume=0)
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset"), \
         patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        out = api.sonos_play()
    assert body_of(out[0])["results"][0]["volume"] == 0

    # No requested volume + a speaker whose remembered default is 0 → stays 0.
    api = make_api(body=json.dumps({"location_id": "loc1", "favorite_id": "fX"}))
    speaker = fake_speaker(default_volume=0)
    with patch(f"{MODELS}.SonosSpeaker") as Sp, patch(f"{MODELS}.AudioPreset"), \
         patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        out = api.sonos_play()
    assert body_of(out[0])["results"][0]["volume"] == 0


def test_get_speakers_preserves_zero_default_volume():
    api = make_api()
    with patch(f"{MODELS}.SonosSpeaker") as Sp:
        Sp.objects.filter.return_value.order_by.return_value = [fake_speaker(default_volume=0)]
        out = api.get_sonos_speakers()
    assert body_of(out[0])["speakers"][0]["default_volume"] == 0


def test_pause_paths():
    with patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosSpeaker"), \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        assert make_api(body="x").sonos_pause()[0].status_code == 400
        assert make_api(body=json.dumps({})).sonos_pause()[0].status_code == 400
    api = make_api(body=json.dumps({"location_id": "loc1"}))
    with patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[])
        assert api.sonos_pause()[0].status_code == 404
    # demo success — two speakers in the location, both paused
    api = make_api(body=json.dumps({"location_id": "loc1"}))
    with patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[fake_speaker(player_id="p1"), fake_speaker(player_id="p2")])
        out = api.sonos_pause()
    data = body_of(out[0])
    assert data["paused"] is True
    assert data["paused_count"] == 2
    assert Log.objects.create.call_count == 2


def test_pause_non_demo_error():
    api = make_api(secrets=CONNECTED_SECRETS, body=json.dumps({"location_id": "loc1"}))
    client = Mock()
    client.pause.side_effect = http_requests.exceptions.RequestException("x")
    with patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        Sp.objects.filter.return_value = FakeQS(items=[fake_speaker()])
        out = api.sonos_pause()
    assert out[0].status_code == 502


def test_volume_paths():
    with patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosSpeaker"), \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        assert make_api(body="x").sonos_volume()[0].status_code == 400
        assert make_api(body=json.dumps({"location_id": "loc1"})).sonos_volume()[0].status_code == 400
    api = make_api(body=json.dumps({"location_id": "loc1", "volume": 50}))
    with patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[])
        assert api.sonos_volume()[0].status_code == 404
    # bad volume value (validated before speaker lookup)
    api = make_api(body=json.dumps({"location_id": "loc1", "volume": "abc"}))
    with patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosSpeaker"), \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        assert api.sonos_volume()[0].status_code == 400
    # demo success + persists default
    api = make_api(body=json.dumps({"location_id": "loc1", "volume": 60}))
    speaker = fake_speaker(default_volume=10)
    with patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        out = api.sonos_volume()
    assert body_of(out[0])["volume"] == 60
    assert speaker.default_volume == 60
    Log.objects.create.assert_called_once()


def test_volume_non_demo_error():
    api = make_api(secrets=CONNECTED_SECRETS, body=json.dumps({"location_id": "loc1", "volume": 30}))
    client = Mock()
    client.set_volume.side_effect = http_requests.exceptions.RequestException("x")
    with patch(f"{MODELS}.SonosPlaybackLog"), patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosOAuthCredential") as Cr, patch(f"{APP}.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        Sp.objects.filter.return_value = FakeQS(items=[fake_speaker()])
        out = api.sonos_volume()
    assert out[0].status_code == 502


# ---------------------------------------------------------------------------
# schedules CRUD
# ---------------------------------------------------------------------------

def test_get_schedules():
    api = make_api()
    sched = Mock(pk=1, location_id="loc1", location_name="Main", favorite_id="f",
                 favorite_name="Spa", volume=20, weekdays="0,1", start_time="09:00",
                 stop_time="17:00", utc_offset_minutes=-420)
    with patch(f"{MODELS}.PlaybackSchedule") as Ps:
        Ps.objects.filter.return_value.order_by.return_value = [sched]
        out = api.get_schedules()
    assert body_of(out[0])["schedules"][0]["start_time"] == "09:00"


def test_create_schedule_paths():
    with patch(f"{MODELS}.PlaybackSchedule"):
        assert make_api(body="x").create_schedule()[0].status_code == 400
        assert make_api(body=json.dumps({"location_id": "l"})).create_schedule()[0].status_code == 400
    payload = {"location_id": "l", "favorite_id": "f", "start_time": "09:00", "stop_time": "17:00"}
    api = make_api(body=json.dumps(payload))
    with patch(f"{MODELS}.PlaybackSchedule") as Ps:
        Ps.objects.create.return_value = Mock(pk=11)
        out = api.create_schedule()
    assert out[0].status_code == 201
    assert body_of(out[0])["id"] == 11


def test_update_schedule_paths():
    # bad id
    api = make_api(body="{}", path_params={"schedule_id": "abc"})
    with patch(f"{MODELS}.PlaybackSchedule"):
        assert api.update_schedule()[0].status_code == 400
    # invalid json
    api = make_api(body="x", path_params={"schedule_id": "5"})
    with patch(f"{MODELS}.PlaybackSchedule"):
        assert api.update_schedule()[0].status_code == 400
    # not found
    api = make_api(body=json.dumps({"volume": 5}), path_params={"schedule_id": "5"})
    with patch(f"{MODELS}.PlaybackSchedule") as Ps:
        Ps.objects.filter.return_value = FakeQS(exists=False)
        assert api.update_schedule()[0].status_code == 404
    # success
    api = make_api(body=json.dumps({"volume": 5}), path_params={"schedule_id": "5"})
    qs = FakeQS(items=[Mock()], exists=True)
    with patch(f"{MODELS}.PlaybackSchedule") as Ps:
        Ps.objects.filter.return_value = qs
        out = api.update_schedule()
    assert qs.updated == {"volume": 5}
    assert body_of(out[0])["success"] is True


def test_delete_schedule_paths():
    api = make_api(path_params={"schedule_id": "abc"})
    with patch(f"{MODELS}.PlaybackSchedule"):
        assert api.delete_schedule()[0].status_code == 400
    api = make_api(path_params={"schedule_id": "5"})
    with patch(f"{MODELS}.PlaybackSchedule") as Ps:
        Ps.objects.filter.return_value.first.return_value = None
        assert api.delete_schedule()[0].status_code == 404
        sched = Mock()
        Ps.objects.filter.return_value.first.return_value = sched
        out = api.delete_schedule()
    assert sched.active is False
    assert body_of(out[0])["success"] is True


# ---------------------------------------------------------------------------
# activity log
# ---------------------------------------------------------------------------

def test_log_lists_with_and_without_location_filter():
    entry = Mock(pk=1, location_id="loc1", location_name="Main", player_id="p1",
                 preset_key="calm", action="play", volume=20, triggered_by="manual",
                 error_message="", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    api = make_api(query={})
    with patch(f"{MODELS}.SonosPlaybackLog") as Log:
        Log.objects.all.return_value.order_by.return_value = FakeQS(items=[entry])
        out = api.sonos_log()
    assert body_of(out[0])["log"][0]["action"] == "play"

    api = make_api(query={"location_id": "loc1"})
    with patch(f"{MODELS}.SonosPlaybackLog") as Log:
        qs = FakeQS(items=[entry])
        Log.objects.all.return_value.order_by.return_value = qs
        out = api.sonos_log()
    assert len(body_of(out[0])["log"]) == 1


# ---------------------------------------------------------------------------
# scheduler.execute()
# ---------------------------------------------------------------------------

def _scheduler():
    from sonos_audio.handlers.scheduler import PlaybackScheduler

    sch = PlaybackScheduler(event=Mock(context={}))
    sch.secrets = {}
    return sch


def test_execute_no_firing_returns_empty():
    sch = _scheduler()
    # A schedule that never matches the current minute.
    sched = Mock(active=True, utc_offset_minutes=0, weekdays="0,1,2,3,4,5,6",
                 start_time="00:00", stop_time="00:00", location_id="loc1")
    with patch(f"{MODELS}.PlaybackSchedule") as Ps, patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosPlaybackLog") as Log:
        Ps.objects.filter.return_value = FakeQS(items=[sched])
        with patch.object(type(sch), "decide_action", return_value=None):
            assert sch.execute() == []
        Sp.objects.filter.assert_not_called()
        Log.objects.create.assert_not_called()


def test_execute_demo_logs_play():
    sch = _scheduler()
    sched = Mock(active=True, utc_offset_minutes=0, weekdays="0,1,2,3,4,5,6",
                 start_time="09:00", stop_time="17:00", location_id="loc1",
                 location_name="Main", volume=30, favorite_id="f1")
    speaker = fake_speaker()
    with patch(f"{MODELS}.PlaybackSchedule") as Ps, patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Ps.objects.filter.return_value = FakeQS(items=[sched])
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        with patch.object(type(sch), "decide_action", return_value="play"):
            assert sch.execute() == []
        Log.objects.create.assert_called_once()


def test_execute_skips_when_no_speaker():
    sch = _scheduler()
    sched = Mock(active=True, utc_offset_minutes=0, weekdays="0,1,2,3,4,5,6",
                 start_time="09:00", stop_time="17:00", location_id="locZ", volume=10)
    with patch(f"{MODELS}.PlaybackSchedule") as Ps, patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        Ps.objects.filter.return_value = FakeQS(items=[sched])
        Sp.objects.filter.return_value = FakeQS(items=[])  # no matching speaker
        with patch.object(type(sch), "decide_action", return_value="play"):
            sch.execute()
        Log.objects.create.assert_not_called()


def test_execute_non_demo_play_and_error():
    sch = _scheduler()
    sch.secrets = CONNECTED_SECRETS
    sched = Mock(active=True, utc_offset_minutes=0, weekdays="0,1,2,3,4,5,6",
                 start_time="09:00", stop_time="17:00", location_id="loc1",
                 location_name="Main", volume=30, favorite_id="f1")
    speaker = fake_speaker()
    client = Mock()
    client.load_favorite.side_effect = http_requests.exceptions.RequestException("boom")
    with patch(f"{MODELS}.PlaybackSchedule") as Ps, patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosOAuthCredential") as Cr, \
         patch("sonos_audio.handlers.scheduler.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        Ps.objects.filter.return_value = FakeQS(items=[sched])
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        with patch.object(type(sch), "decide_action", return_value="play"):
            sch.execute()
        # error recorded
        _, kwargs = Log.objects.create.call_args
        assert kwargs["action"] == "error"


def test_execute_non_demo_pause():
    sch = _scheduler()
    sch.secrets = CONNECTED_SECRETS
    sched = Mock(active=True, utc_offset_minutes=0, weekdays="0,1,2,3,4,5,6",
                 start_time="09:00", stop_time="17:00", location_id="loc1",
                 location_name="Main", volume=30, favorite_id="f1")
    speaker = fake_speaker()
    client = Mock()
    with patch(f"{MODELS}.PlaybackSchedule") as Ps, patch(f"{MODELS}.SonosSpeaker") as Sp, \
         patch(f"{MODELS}.SonosPlaybackLog") as Log, patch(f"{MODELS}.SonosOAuthCredential") as Cr, \
         patch("sonos_audio.handlers.scheduler.SonosClient", return_value=client):
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        Ps.objects.filter.return_value = FakeQS(items=[sched])
        Sp.objects.filter.return_value = FakeQS(items=[speaker])
        with patch.object(type(sch), "decide_action", return_value="pause"):
            sch.execute()
        client.pause.assert_called_once()
        _, kwargs = Log.objects.create.call_args
        assert kwargs["action"] == "pause"


def test_client_none_without_secrets():
    sch = _scheduler()
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr:
        Cr.objects.first.return_value = None
        assert sch._client() is None


def test_client_built_with_secrets():
    sch = _scheduler()
    sch.secrets = CONNECTED_SECRETS
    with patch(f"{MODELS}.SonosOAuthCredential") as Cr, \
         patch("sonos_audio.handlers.scheduler.SonosClient") as SC:
        Cr.objects.first.return_value = Mock(refresh_token="rt")
        sch._client()
    SC.assert_called_once_with("cid", "csec", "rt")


# ---------------------------------------------------------------------------
# CustomModel definitions (__str__ + field defaults)
# ---------------------------------------------------------------------------

def test_model_str_reprs():
    from sonos_audio.models.custom_data import (
        AudioPreset,
        PlaybackSchedule,
        SonosOAuthCredential,
        SonosPlaybackLog,
        SonosSpeaker,
    )

    assert "->" in str(SonosSpeaker(player_name="Kitchen", location_name="Main"))
    assert "default" in str(AudioPreset(name="Calm", match_type="default", match_value=""))
    assert "not connected" in str(SonosOAuthCredential(household_name=""))
    assert "09:00" in str(PlaybackSchedule(location_name="Main", start_time="09:00",
                                           stop_time="17:00", favorite_name="Spa"))
    assert "play" in str(SonosPlaybackLog(location_name="Main", action="play",
                                          triggered_by="manual"))


def test_models_importable_via_package():
    import sonos_audio.models as m

    assert {"AudioPreset", "PlaybackSchedule", "SonosOAuthCredential",
            "SonosPlaybackLog", "SonosSpeaker"} <= set(m.__all__)
