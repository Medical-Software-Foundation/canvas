"""Sonos Control API client plus demo data and small HTML helpers.

This module is intra-plugin shared code: both the SimpleAPI (sonos_app) and the
CronTask scheduler import ``SonosClient`` from here.
"""
import base64
from typing import Any

import requests as http_requests  # type: ignore[import-untyped]

APP_ID = "com.canvasmedical.sonos_audio"


class SonosClient:
    """Lightweight client for the Sonos Control API."""

    API_BASE = "https://api.ws.sonos.com/control/api/v1"
    TOKEN_URL = "https://api.sonos.com/login/v3/oauth/access"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token: str | None = None

    def _get_basic_auth(self) -> str:
        creds = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(creds.encode()).decode()

    def _refresh_access_token(self) -> str:
        resp = http_requests.post(
            self.TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._get_basic_auth()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        return self._access_token

    def _get_token(self) -> str:
        if self._access_token:
            return self._access_token
        return self._refresh_access_token()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make a Sonos API request with automatic token refresh on 401."""
        url = f"{self.API_BASE}{path}"
        resp = http_requests.request(
            method, url, headers=self._headers(), timeout=15, **kwargs
        )
        if resp.status_code == 401:
            self._refresh_access_token()
            resp = http_requests.request(
                method, url, headers=self._headers(), timeout=15, **kwargs
            )
        resp.raise_for_status()
        if resp.status_code == 200 and resp.content:
            return dict(resp.json())
        return {"status": resp.status_code}

    # -- Discovery --

    def get_households(self) -> dict:
        return self._request("GET", "/households")

    def get_groups(self, household_id: str) -> dict:
        return self._request("GET", f"/households/{household_id}/groups")

    def get_favorites(self, household_id: str) -> dict:
        return self._request("GET", f"/households/{household_id}/favorites")

    # -- Playback --

    def load_favorite(self, group_id: str, favorite_id: str, play_on_completion: bool = True) -> dict:
        return self._request(
            "POST",
            f"/groups/{group_id}/favorites",
            json={"favoriteId": favorite_id, "playOnCompletion": play_on_completion},
        )

    def play(self, group_id: str) -> dict:
        return self._request("POST", f"/groups/{group_id}/playback/play")

    def pause(self, group_id: str) -> dict:
        return self._request("POST", f"/groups/{group_id}/playback/pause")

    def set_volume(self, group_id: str, volume: int) -> dict:
        return self._request(
            "POST",
            f"/groups/{group_id}/groupVolume",
            json={"volume": volume},
        )


# ---------------------------------------------------------------------------
# Demo data — used when Sonos OAuth credentials are not configured, so the UI
# is fully explorable without a live Sonos account.
# ---------------------------------------------------------------------------

SONOS_DEMO_HOUSEHOLD = {"id": "demo-household-001", "name": "Demo Household"}
SONOS_DEMO_PLAYERS = [
    {"id": "demo-player-1", "name": "Front Desk Sonos", "capabilities": ["PLAYBACK", "AUDIO_CLIP"]},
    {"id": "demo-player-2", "name": "Waiting Room Sonos", "capabilities": ["PLAYBACK", "AUDIO_CLIP"]},
    {"id": "demo-player-3", "name": "Treatment Room Sonos", "capabilities": ["PLAYBACK", "AUDIO_CLIP"]},
    {"id": "demo-player-4", "name": "Exam Room Sonos", "capabilities": ["PLAYBACK", "AUDIO_CLIP"]},
]
SONOS_DEMO_GROUPS = [
    {"id": "demo-group-1", "name": "Front Desk", "playerIds": ["demo-player-1"]},
    {"id": "demo-group-2", "name": "Waiting Room", "playerIds": ["demo-player-2"]},
    {"id": "demo-group-3", "name": "Treatment Room", "playerIds": ["demo-player-3"]},
    {"id": "demo-group-4", "name": "Exam Room", "playerIds": ["demo-player-4"]},
]
SONOS_DEMO_FAVORITES = [
    {"id": "demo-fav-ocean", "name": "Ocean Waves", "description": "Calming ocean sounds"},
    {"id": "demo-fav-forest", "name": "Forest Rain", "description": "Gentle rain on leaves"},
    {"id": "demo-fav-bowls", "name": "Singing Bowls", "description": "Tibetan bowl meditation"},
    {"id": "demo-fav-ambient", "name": "Ambient Wellness", "description": "Soft ambient piano & nature"},
    {"id": "demo-fav-spa", "name": "Spa Relaxation", "description": "Classic spa background music"},
    {"id": "demo-fav-lofi", "name": "Lo-Fi Calm", "description": "Chill lo-fi beats"},
    {"id": "demo-fav-classical", "name": "Soft Classical", "description": "Quiet classical strings"},
    {"id": "demo-fav-jazz", "name": "Easy Jazz", "description": "Low-key lobby jazz"},
]

# Generic starter presets seeded on demand. They have no favorite bound yet —
# staff pick a Sonos favorite for each after connecting.
DEFAULT_AUDIO_PRESETS = [
    {"key": "waiting-room", "name": "Waiting Room Ambient", "match_type": "default", "match_value": "", "volume": 25, "priority": 5},
    {"key": "treatment-calm", "name": "Treatment Room Calm", "match_type": "default", "match_value": "", "volume": 20, "priority": 0},
    {"key": "lobby-upbeat", "name": "Lobby Background", "match_type": "default", "match_value": "", "volume": 30, "priority": 0},
]


def oauth_message_page(ok: bool, message: str) -> str:
    """Render the page Sonos redirects to after authorization.

    Posts a message to the opener (the Connect tab) so it can refresh the
    connected status and auto-close the popup.
    """
    title = "Sonos connected" if ok else "Sonos connection failed"
    accent = "#1a7f6b" if ok else "#c0392b"
    safe_message = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    msg_type = "sonos-connected" if ok else "sonos-failed"
    return (
        '<!doctype html><html><head>'
        f'<title>{title}</title>'
        '<style>'
        'body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f7fa;color:#1f2933;'
        'display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}'
        '.card{background:#fff;border:1px solid #e4e7eb;border-radius:16px;padding:32px 40px;max-width:480px;text-align:center;'
        'box-shadow:0 4px 12px rgba(0,0,0,0.06)}'
        f'.dot{{width:48px;height:48px;border-radius:50%;background:{accent};margin:0 auto 16px;'
        'display:flex;align-items:center;justify-content:center;color:#fff;font-size:24px;font-weight:600}}'
        'h1{font-size:18px;margin:0 0 8px;color:#1f2933}'
        'p{font-size:14px;margin:0;color:#52606d;line-height:1.5}'
        '.close-hint{font-size:12px;color:#9aa5b1;margin-top:18px}'
        '</style>'
        '</head><body>'
        f'<div class="card"><div class="dot">{"&check;" if ok else "!"}</div>'
        f'<h1>{title}</h1><p>{safe_message}</p>'
        '<p class="close-hint">This window will close automatically.</p></div>'
        '<script>'
        'try{if(window.opener&&!window.opener.closed){'
        f'window.opener.postMessage({{type:"{msg_type}"}},"*");'
        '}}catch(e){}'
        'setTimeout(function(){try{window.close()}catch(e){}},1800);'
        '</script>'
        '</body></html>'
    )
