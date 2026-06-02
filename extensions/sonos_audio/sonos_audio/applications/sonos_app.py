import base64
import json
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

import requests as http_requests  # type: ignore[import-untyped]
from logger import log

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.application import Application
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.practicelocation import PracticeLocation

from sonos_audio.services.sonos_client import (
    DEFAULT_AUDIO_PRESETS,
    SONOS_DEMO_FAVORITES,
    SONOS_DEMO_GROUPS,
    SONOS_DEMO_HOUSEHOLD,
    SONOS_DEMO_PLAYERS,
    SonosClient,
    oauth_message_page,
)


class SonosApp(Application):
    """Sonos Audio — control ambient music on Sonos speakers from Canvas."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            content=render_to_string("templates/sonos.html"),
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()


class SonosApi(StaffSessionAuthMixin, SimpleAPI):
    """REST API for Sonos OAuth, speaker mapping, presets, playback, and schedules."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sonos_refresh_token(self) -> str:
        """Refresh token from the in-app Connect Sonos flow (SonosOAuthCredential row)."""
        from sonos_audio.models.custom_data import SonosOAuthCredential

        cred = SonosOAuthCredential.objects.first()
        if cred and cred.refresh_token:
            return str(cred.refresh_token)
        return ""

    def _sonos_client(self) -> SonosClient | None:
        client_id = self.secrets.get("SONOS_CLIENT_ID", "")
        client_secret = self.secrets.get("SONOS_CLIENT_SECRET", "")
        refresh_token = self._sonos_refresh_token()
        if not all([client_id, client_secret, refresh_token]):
            return None
        return SonosClient(client_id, client_secret, refresh_token)

    def _sonos_demo_mode(self) -> bool:
        """True when Sonos credentials are not configured (use demo data)."""
        return self._sonos_client() is None

    def _sonos_redirect_uri(self) -> str:
        """Canonical OAuth callback URL. Must match what's registered in the Sonos dev portal."""
        instance = self.environment.get("CUSTOMER_IDENTIFIER", "")
        return f"https://{instance}.canvasmedical.com/plugin-io/api/sonos_audio/sonos/oauth/callback"

    def _resolve_location_preset(self, location_id: str) -> Any:
        """Best preset for a location: a location-bound preset (highest priority),
        else the global default. Only presets with a Sonos favorite count."""
        from sonos_audio.models.custom_data import AudioPreset

        active = list(AudioPreset.objects.filter(active=True).exclude(sonos_favorite_id=""))
        location_matches = [
            p for p in active if p.match_type == "location" and p.match_value == location_id
        ]
        if location_matches:
            return max(location_matches, key=lambda p: p.priority)
        defaults = [p for p in active if p.match_type == "default"]
        if defaults:
            return max(defaults, key=lambda p: p.priority)
        return None

    def _target_speakers(self, body: dict) -> tuple[list[Any], str]:
        """Speakers a playback action targets, and the location they belong to.

        A request may name a single speaker (``player_id``) or a whole location
        (``location_id``), in which case the action fans out to every active
        speaker mapped there. Returns ``(speakers, location_id)``; ``location_id``
        is "" when only a player_id was given and no speaker matched.
        """
        from sonos_audio.models.custom_data import SonosSpeaker

        player_id = body.get("player_id", "")
        if player_id:
            speakers = list(SonosSpeaker.objects.filter(player_id=player_id, active=True))
            return speakers, (speakers[0].location_id if speakers else "")
        location_id = body.get("location_id", "")
        if location_id:
            return list(SonosSpeaker.objects.filter(location_id=location_id, active=True)), location_id
        return [], ""

    # ------------------------------------------------------------------
    # Practice locations (mapping targets)
    # ------------------------------------------------------------------

    @api.get("/locations")
    def locations(self) -> list[Response | Effect]:
        """List active practice locations, used to map speakers."""
        locations = PracticeLocation.objects.filter(active=True).values(
            "id", "full_name", "short_name"
        ).order_by("full_name")
        return [JSONResponse({
            "locations": [
                {
                    "id": str(loc["id"]),
                    "name": loc["full_name"] or loc["short_name"] or str(loc["id"]),
                    "short_name": loc["short_name"] or "",
                }
                for loc in locations
            ]
        }, status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------------
    # Sonos - status & OAuth
    # ------------------------------------------------------------------

    @api.get("/sonos/status")
    def sonos_status(self) -> list[Response | Effect]:
        """Health check: configured, connected, household, speaker count."""
        from sonos_audio.models.custom_data import SonosOAuthCredential, SonosSpeaker

        demo = self._sonos_demo_mode()
        speaker_count = SonosSpeaker.objects.filter(active=True).count()
        cred = SonosOAuthCredential.objects.first()
        connected = bool(cred and cred.refresh_token)
        has_app_keys = bool(
            self.secrets.get("SONOS_CLIENT_ID", "") and self.secrets.get("SONOS_CLIENT_SECRET", "")
        )
        return [JSONResponse({
            "configured": True,  # always true so the UI is usable (demo mode fills gaps)
            "demo_mode": demo,
            "connected": connected,
            "has_app_keys": has_app_keys,
            "household_name": (cred.household_name if cred else ""),
            "household_id": (cred.household_id if cred else ""),
            "connected_at": cred.connected_at.isoformat() if (cred and cred.connected_at) else None,
            "redirect_uri": self._sonos_redirect_uri(),
            "speaker_count": speaker_count,
        }, status_code=HTTPStatus.OK)]

    @api.get("/sonos/oauth/start")
    def sonos_oauth_start(self) -> list[Response | Effect]:
        """Redirect the staff member to Sonos' OAuth consent page (opened in a popup)."""
        from sonos_audio.models.custom_data import SonosOAuthCredential

        client_id = self.secrets.get("SONOS_CLIENT_ID", "")
        if not client_id or not self.secrets.get("SONOS_CLIENT_SECRET", ""):
            return [HTMLResponse(
                oauth_message_page(
                    False,
                    "Sonos app keys aren't set yet. Add SONOS_CLIENT_ID and SONOS_CLIENT_SECRET in "
                    "Settings -> Plugins -> sonos_audio -> Secrets, then come back to this page.",
                ),
                status_code=HTTPStatus.OK,
            )]

        state = uuid.uuid4().hex
        cred = SonosOAuthCredential.objects.first()
        if cred is None:
            cred = SonosOAuthCredential.objects.create(pending_state=state)
        else:
            cred.pending_state = state
            cred.save()

        params = {
            "client_id": client_id,
            "response_type": "code",
            "state": state,
            "scope": "playback-control-all",
            "redirect_uri": self._sonos_redirect_uri(),
        }
        authorize_url = f"https://api.sonos.com/login/v3/oauth?{urlencode(params)}"

        html = (
            '<!doctype html><html><head>'
            f'<meta http-equiv="refresh" content="0;url={authorize_url}">'
            '<title>Connecting to Sonos...</title>'
            '</head><body style="font-family:-apple-system,sans-serif;padding:2rem;text-align:center">'
            '<p>Redirecting to Sonos...</p>'
            f'<p><a href="{authorize_url}">Tap here if the page does not redirect automatically.</a></p>'
            '</body></html>'
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/sonos/oauth/callback")
    def sonos_oauth_callback(self) -> list[Response | Effect]:
        """OAuth redirect target. Exchanges the code for a refresh token and persists it."""
        from sonos_audio.models.custom_data import SonosOAuthCredential

        code = self.request.query_params.get("code", "")
        state = self.request.query_params.get("state", "")
        error = self.request.query_params.get("error", "")
        if error:
            return [HTMLResponse(
                oauth_message_page(False, f"Sonos reported: {error}"),
                status_code=HTTPStatus.OK,
            )]
        if not code or not state:
            return [HTMLResponse(
                oauth_message_page(False, "Missing code or state in the callback URL."),
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        cred = SonosOAuthCredential.objects.first()
        if not cred or not cred.pending_state or cred.pending_state != state:
            return [HTMLResponse(
                oauth_message_page(False, "State mismatch - the connect link expired or didn't originate from this Canvas. Try again."),
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        client_id = self.secrets.get("SONOS_CLIENT_ID", "")
        client_secret = self.secrets.get("SONOS_CLIENT_SECRET", "")
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        resp = http_requests.post(
            SonosClient.TOKEN_URL,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._sonos_redirect_uri(),
            },
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("[sonos_audio] token exchange failed: %s %s", resp.status_code, resp.text[:200])
            return [HTMLResponse(
                oauth_message_page(False, f"Sonos rejected the authorization code (HTTP {resp.status_code}). Re-check the redirect URI in the Sonos dev portal matches: {self._sonos_redirect_uri()}"),
                status_code=HTTPStatus.OK,
            )]

        token_data = resp.json()
        refresh_token = token_data.get("refresh_token", "")
        if not refresh_token:
            return [HTMLResponse(
                oauth_message_page(False, "Sonos returned no refresh token. This usually means the developer app isn't a Control Integration."),
                status_code=HTTPStatus.OK,
            )]

        cred.refresh_token = refresh_token
        cred.pending_state = ""
        cred.connected_by_staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        cred.connected_at = datetime.now(timezone.utc)

        household_name = ""
        household_id = ""
        access_token = token_data.get("access_token", "")
        if access_token:
            hh_resp = http_requests.get(
                f"{SonosClient.API_BASE}/households",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if hh_resp.status_code == 200:
                households = hh_resp.json().get("households", [])
                if households:
                    household_id = households[0].get("id", "")
                    household_name = households[0].get("name", "") or household_id
        cred.household_id = household_id
        cred.household_name = household_name
        cred.save()

        return [HTMLResponse(
            oauth_message_page(True, f"Connected to {household_name or 'your Sonos household'}. You can close this window."),
            status_code=HTTPStatus.OK,
        )]

    @api.post("/sonos/oauth/disconnect")
    def sonos_oauth_disconnect(self) -> list[Response | Effect]:
        """Clear the stored OAuth credential. The plugin reverts to demo mode."""
        from sonos_audio.models.custom_data import SonosOAuthCredential

        cred = SonosOAuthCredential.objects.first()
        if cred:
            cred.refresh_token = ""
            cred.household_id = ""
            cred.household_name = ""
            cred.pending_state = ""
            cred.connected_at = None
            cred.save()
        return [JSONResponse({"disconnected": True}, status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------------
    # Sonos - discovery
    # ------------------------------------------------------------------

    @api.get("/sonos/households")
    def sonos_households(self) -> list[Response | Effect]:
        if self._sonos_demo_mode():
            return [JSONResponse({"households": [SONOS_DEMO_HOUSEHOLD]}, status_code=HTTPStatus.OK)]
        sonos = self._sonos_client()
        assert sonos is not None
        try:
            return [JSONResponse(sonos.get_households(), status_code=HTTPStatus.OK)]
        except Exception as e:
            log.warning("[sonos_audio] households error: %s", e)
            return [JSONResponse({"error": str(e)}, status_code=HTTPStatus.BAD_GATEWAY)]

    @api.get("/sonos/players")
    def sonos_players(self) -> list[Response | Effect]:
        household_id = self.request.query_params.get("household_id", "")
        if not household_id:
            return [JSONResponse({"error": "household_id query param required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if self._sonos_demo_mode():
            return [JSONResponse({"players": SONOS_DEMO_PLAYERS, "groups": SONOS_DEMO_GROUPS}, status_code=HTTPStatus.OK)]
        sonos = self._sonos_client()
        assert sonos is not None
        try:
            return [JSONResponse(sonos.get_groups(household_id), status_code=HTTPStatus.OK)]
        except Exception as e:
            log.warning("[sonos_audio] players error: %s", e)
            return [JSONResponse({"error": str(e)}, status_code=HTTPStatus.BAD_GATEWAY)]

    @api.get("/sonos/favorites")
    def sonos_favorites(self) -> list[Response | Effect]:
        household_id = self.request.query_params.get("household_id", "")
        if not household_id:
            return [JSONResponse({"error": "household_id query param required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if self._sonos_demo_mode():
            return [JSONResponse({"items": SONOS_DEMO_FAVORITES}, status_code=HTTPStatus.OK)]
        sonos = self._sonos_client()
        assert sonos is not None
        try:
            return [JSONResponse(sonos.get_favorites(household_id), status_code=HTTPStatus.OK)]
        except Exception as e:
            log.warning("[sonos_audio] favorites error: %s", e)
            return [JSONResponse({"error": str(e)}, status_code=HTTPStatus.BAD_GATEWAY)]

    # ------------------------------------------------------------------
    # Sonos - speaker mapping CRUD (keyed by practice location)
    # ------------------------------------------------------------------

    @api.get("/sonos/speakers")
    def get_sonos_speakers(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import SonosSpeaker

        speakers = SonosSpeaker.objects.filter(active=True).order_by("location_name")
        return [JSONResponse({
            "speakers": [
                {
                    "id": s.pk,
                    "location_id": s.location_id,
                    "location_name": s.location_name or "",
                    "player_id": s.player_id,
                    "group_id": s.group_id or "",
                    "player_name": s.player_name,
                    "household_id": s.household_id,
                    "default_favorite_id": s.default_favorite_id or "",
                    "default_favorite_name": s.default_favorite_name or "",
                    "default_volume": s.default_volume if s.default_volume is not None else 25,
                }
                for s in speakers
            ]
        }, status_code=HTTPStatus.OK)]

    @api.post("/sonos/speakers")
    def create_sonos_speaker(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import SonosSpeaker

        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        for field in ("location_id", "player_id", "player_name", "household_id"):
            if not body.get(field):
                return [JSONResponse({"error": f"{field} is required"}, status_code=HTTPStatus.BAD_REQUEST)]

        # Upsert by player: a physical Sonos player maps to exactly one location,
        # but a location may host many players. Re-mapping a player moves it.
        existing = SonosSpeaker.objects.filter(player_id=body["player_id"]).first()
        if existing:
            existing.location_id = body["location_id"]
            existing.location_name = body.get("location_name", existing.location_name)
            existing.group_id = body.get("group_id", "")
            existing.player_name = body["player_name"]
            existing.household_id = body["household_id"]
            existing.active = True
            existing.save()
            return [JSONResponse({"success": True, "id": existing.pk, "updated": True}, status_code=HTTPStatus.OK)]

        speaker = SonosSpeaker.objects.create(
            location_id=body["location_id"],
            location_name=body.get("location_name", ""),
            player_id=body["player_id"],
            group_id=body.get("group_id", ""),
            player_name=body["player_name"],
            household_id=body["household_id"],
        )
        return [JSONResponse({"success": True, "id": speaker.pk}, status_code=HTTPStatus.CREATED)]

    @api.put("/sonos/speakers/<player_id>")
    def update_sonos_speaker(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import SonosSpeaker

        player_id = self.request.path_params["player_id"]
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        qs = SonosSpeaker.objects.filter(player_id=player_id, active=True)
        if not qs.exists():
            return [JSONResponse({"error": "Speaker mapping not found"}, status_code=HTTPStatus.NOT_FOUND)]

        update_fields = {}
        for field in ("location_id", "location_name", "group_id", "player_name", "household_id",
                      "default_favorite_id", "default_favorite_name", "default_volume"):
            if field in body:
                update_fields[field] = body[field]
        if update_fields:
            qs.update(**update_fields)
        return [JSONResponse({"success": True}, status_code=HTTPStatus.OK)]

    @api.delete("/sonos/speakers/<player_id>")
    def delete_sonos_speaker(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import SonosSpeaker

        player_id = self.request.path_params["player_id"]
        speaker = SonosSpeaker.objects.filter(player_id=player_id).first()
        if not speaker:
            return [JSONResponse({"error": "Speaker mapping not found"}, status_code=HTTPStatus.NOT_FOUND)]
        speaker.active = False
        speaker.save()
        return [JSONResponse({"success": True}, status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------------
    # Sonos - preset CRUD
    # ------------------------------------------------------------------

    @api.get("/sonos/presets")
    def get_sonos_presets(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import AudioPreset

        presets = AudioPreset.objects.filter(active=True).order_by("-priority", "key")
        return [JSONResponse({
            "presets": [
                {
                    "id": p.pk,
                    "key": p.key,
                    "name": p.name,
                    "match_type": p.match_type,
                    "match_value": p.match_value,
                    "sonos_favorite_id": p.sonos_favorite_id or "",
                    "sonos_favorite_name": p.sonos_favorite_name or "",
                    "volume": p.volume,
                    "priority": p.priority,
                }
                for p in presets
            ]
        }, status_code=HTTPStatus.OK)]

    @api.post("/sonos/presets")
    def create_sonos_preset(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import AudioPreset

        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        for field in ("key", "name", "match_type"):
            if not body.get(field):
                return [JSONResponse({"error": f"{field} is required"}, status_code=HTTPStatus.BAD_REQUEST)]

        if AudioPreset.objects.filter(key=body["key"]).exists():
            return [JSONResponse({"error": "Preset key already exists"}, status_code=HTTPStatus.CONFLICT)]

        preset = AudioPreset.objects.create(
            key=body["key"],
            name=body["name"],
            match_type=body["match_type"],
            match_value=body.get("match_value", ""),
            sonos_favorite_id=body.get("sonos_favorite_id", ""),
            sonos_favorite_name=body.get("sonos_favorite_name", ""),
            volume=body.get("volume", 25),
            priority=body.get("priority", 0),
        )
        return [JSONResponse({"success": True, "id": preset.pk}, status_code=HTTPStatus.CREATED)]

    @api.put("/sonos/presets/<key>")
    def update_sonos_preset(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import AudioPreset

        key = self.request.path_params["key"]
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        qs = AudioPreset.objects.filter(key=key, active=True)
        if not qs.exists():
            return [JSONResponse({"error": "Preset not found"}, status_code=HTTPStatus.NOT_FOUND)]

        update_fields = {}
        for field in ("name", "match_type", "match_value", "sonos_favorite_id",
                      "sonos_favorite_name", "volume", "priority"):
            if field in body:
                update_fields[field] = body[field]
        if update_fields:
            qs.update(**update_fields)
        return [JSONResponse({"success": True}, status_code=HTTPStatus.OK)]

    @api.delete("/sonos/presets/<key>")
    def delete_sonos_preset(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import AudioPreset

        key = self.request.path_params["key"]
        preset = AudioPreset.objects.filter(key=key).first()
        if not preset:
            return [JSONResponse({"error": "Preset not found"}, status_code=HTTPStatus.NOT_FOUND)]
        preset.active = False
        preset.save()
        return [JSONResponse({"success": True}, status_code=HTTPStatus.OK)]

    @api.post("/sonos/presets/seed")
    def seed_sonos_presets(self) -> list[Response | Effect]:
        """Idempotent seed of generic starter presets (no favorite bound yet)."""
        from sonos_audio.models.custom_data import AudioPreset

        created = 0
        for p in DEFAULT_AUDIO_PRESETS:
            _, was_created = AudioPreset.objects.get_or_create(
                key=p["key"],
                defaults={
                    "name": p["name"],
                    "match_type": p["match_type"],
                    "match_value": p["match_value"],
                    "volume": p["volume"],
                    "priority": p["priority"],
                },
            )
            if was_created:
                created += 1
        return [JSONResponse({"success": True, "presets_created": created}, status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------------
    # Sonos - playback control
    # ------------------------------------------------------------------

    @api.post("/sonos/play")
    def sonos_play(self) -> list[Response | Effect]:
        """Play a station on one speaker (``player_id``) or a whole location
        (``location_id``, fanning out to every speaker mapped there)."""
        from sonos_audio.models.custom_data import AudioPreset, SonosPlaybackLog

        demo = self._sonos_demo_mode()
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        if not body.get("location_id") and not body.get("player_id"):
            return [JSONResponse({"error": "location_id or player_id is required"}, status_code=HTTPStatus.BAD_REQUEST)]

        speakers, location_id = self._target_speakers(body)
        if not speakers:
            return [JSONResponse({"error": "No speaker mapped for that location/player"}, status_code=HTTPStatus.NOT_FOUND)]

        preset_key = body.get("preset_key", "")
        triggered_by = body.get("triggered_by", "manual")

        # Resolve a location-level station that applies to every target speaker:
        #   1. explicit favorite_id in the request (staff picked a station)
        #   2. a preset (explicit preset_key, else the location's matched preset)
        # If neither resolves, each speaker falls back to its own remembered default.
        req_favorite_id = body.get("favorite_id", "")
        req_favorite_name = body.get("favorite_name", "")
        req_volume = body.get("volume")
        preset = None
        if not req_favorite_id:
            if preset_key:
                preset = AudioPreset.objects.filter(key=preset_key, active=True).first()
            elif location_id:
                preset = self._resolve_location_preset(location_id)
            if preset and preset.sonos_favorite_id:
                req_favorite_id = preset.sonos_favorite_id
                req_favorite_name = preset.sonos_favorite_name or preset.name
                if req_volume is None:
                    req_volume = preset.volume

        sonos = None if demo else self._sonos_client()
        results: list[dict] = []
        for speaker in speakers:
            favorite_id = req_favorite_id or speaker.default_favorite_id
            favorite_name = req_favorite_name or (speaker.default_favorite_name if not req_favorite_id else "")
            if not favorite_id:
                results.append({"player_id": speaker.player_id, "speaker": speaker.player_name,
                                "played": False, "reason": "no station"})
                continue

            speaker_default_volume = speaker.default_volume if speaker.default_volume is not None else 25
            try:
                volume = int(req_volume) if req_volume is not None else speaker_default_volume
            except (TypeError, ValueError):
                volume = speaker_default_volume
            volume = max(0, min(100, volume))
            group_id = speaker.group_id or speaker.player_id

            error_message = ""
            if not demo and sonos is not None:
                try:
                    sonos.load_favorite(group_id, favorite_id, play_on_completion=True)
                    sonos.set_volume(group_id, volume)
                except Exception as e:
                    error_message = str(e)
                    log.warning("[sonos_audio] play error: %s", e)

            # Remember this station as the speaker's default for next time.
            if not error_message and (speaker.default_favorite_id != favorite_id or speaker.default_volume != volume):
                speaker.default_favorite_id = favorite_id
                speaker.default_favorite_name = favorite_name or ""
                speaker.default_volume = volume
                speaker.save()

            SonosPlaybackLog.objects.create(
                location_id=speaker.location_id,
                location_name=speaker.location_name,
                player_id=speaker.player_id,
                preset_key=preset.key if preset else "",
                action="error" if error_message else "play",
                volume=volume,
                triggered_by=triggered_by,
                error_message=error_message,
            )
            results.append({"player_id": speaker.player_id, "speaker": speaker.player_name,
                            "played": not error_message, "favorite_id": favorite_id,
                            "favorite_name": favorite_name, "volume": volume,
                            "error": error_message or None})

        played = [r for r in results if r.get("played")]
        if not played and all(r.get("reason") == "no station" for r in results):
            return [JSONResponse(
                {"error": "Pick a station to play, or set a default for these speakers."},
                status_code=HTTPStatus.NOT_FOUND,
            )]
        if not demo and not played:
            return [JSONResponse({"error": "Playback failed on all speakers", "results": results},
                                 status_code=HTTPStatus.BAD_GATEWAY)]
        return [JSONResponse({
            "success": True, "playing": True, "demo_mode": demo, "location_id": location_id,
            "preset": preset.key if preset else "", "played_count": len(played), "results": results,
        }, status_code=HTTPStatus.OK)]

    @api.post("/sonos/pause")
    def sonos_pause(self) -> list[Response | Effect]:
        """Pause one speaker (``player_id``) or every speaker in a location
        (``location_id``)."""
        from sonos_audio.models.custom_data import SonosPlaybackLog

        demo = self._sonos_demo_mode()
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        if not body.get("location_id") and not body.get("player_id"):
            return [JSONResponse({"error": "location_id or player_id is required"}, status_code=HTTPStatus.BAD_REQUEST)]

        speakers, _ = self._target_speakers(body)
        if not speakers:
            return [JSONResponse({"error": "No speaker mapped for that location/player"}, status_code=HTTPStatus.NOT_FOUND)]

        triggered_by = body.get("triggered_by", "manual")
        sonos = None if demo else self._sonos_client()
        results: list[dict] = []
        for speaker in speakers:
            error_message = ""
            if not demo and sonos is not None:
                try:
                    sonos.pause(speaker.group_id or speaker.player_id)
                except Exception as e:
                    error_message = str(e)
                    log.warning("[sonos_audio] pause error: %s", e)
            SonosPlaybackLog.objects.create(
                location_id=speaker.location_id,
                location_name=speaker.location_name,
                player_id=speaker.player_id,
                action="error" if error_message else "pause",
                triggered_by=triggered_by,
                error_message=error_message,
            )
            results.append({"player_id": speaker.player_id, "speaker": speaker.player_name,
                            "paused": not error_message, "error": error_message or None})

        paused = [r for r in results if r.get("paused")]
        if not demo and not paused:
            return [JSONResponse({"error": "Pause failed on all speakers", "results": results},
                                 status_code=HTTPStatus.BAD_GATEWAY)]
        return [JSONResponse({"success": True, "paused": True, "demo_mode": demo,
                              "paused_count": len(paused), "results": results}, status_code=HTTPStatus.OK)]

    @api.post("/sonos/volume")
    def sonos_volume(self) -> list[Response | Effect]:
        """Set volume on one speaker (``player_id``) or every speaker in a
        location (``location_id``)."""
        from sonos_audio.models.custom_data import SonosPlaybackLog

        demo = self._sonos_demo_mode()
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        volume = body.get("volume")
        if (not body.get("location_id") and not body.get("player_id")) or volume is None:
            return [JSONResponse({"error": "location_id or player_id, and volume, are required"}, status_code=HTTPStatus.BAD_REQUEST)]

        try:
            volume = max(0, min(100, int(volume)))
        except (TypeError, ValueError):
            return [JSONResponse({"error": "volume must be an integer 0-100"}, status_code=HTTPStatus.BAD_REQUEST)]

        speakers, _ = self._target_speakers(body)
        if not speakers:
            return [JSONResponse({"error": "No speaker mapped for that location/player"}, status_code=HTTPStatus.NOT_FOUND)]

        sonos = None if demo else self._sonos_client()
        results: list[dict] = []
        for speaker in speakers:
            error_message = ""
            if not demo and sonos is not None:
                try:
                    sonos.set_volume(speaker.group_id or speaker.player_id, volume)
                except Exception as e:
                    error_message = str(e)
                    log.warning("[sonos_audio] volume error: %s", e)
            # Persist as the speaker's default volume so it sticks.
            if not error_message and speaker.default_volume != volume:
                speaker.default_volume = volume
                speaker.save()
            SonosPlaybackLog.objects.create(
                location_id=speaker.location_id,
                location_name=speaker.location_name,
                player_id=speaker.player_id,
                action="error" if error_message else "volume_change",
                volume=volume,
                triggered_by="manual",
                error_message=error_message,
            )
            results.append({"player_id": speaker.player_id, "speaker": speaker.player_name,
                            "ok": not error_message, "error": error_message or None})

        ok = [r for r in results if r.get("ok")]
        if not demo and not ok:
            return [JSONResponse({"error": "Volume change failed on all speakers", "results": results},
                                 status_code=HTTPStatus.BAD_GATEWAY)]
        return [JSONResponse({"success": True, "volume": volume, "demo_mode": demo,
                              "count": len(ok), "results": results}, status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------------
    # Sonos - playback schedules
    # ------------------------------------------------------------------

    @api.get("/sonos/schedules")
    def get_schedules(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import PlaybackSchedule

        schedules = PlaybackSchedule.objects.filter(active=True).order_by("location_name", "start_time")
        return [JSONResponse({
            "schedules": [
                {
                    "id": s.pk,
                    "location_id": s.location_id,
                    "location_name": s.location_name or "",
                    "favorite_id": s.favorite_id or "",
                    "favorite_name": s.favorite_name or "",
                    "volume": s.volume,
                    "weekdays": s.weekdays,
                    "start_time": s.start_time,
                    "stop_time": s.stop_time,
                    "utc_offset_minutes": s.utc_offset_minutes,
                }
                for s in schedules
            ]
        }, status_code=HTTPStatus.OK)]

    @api.post("/sonos/schedules")
    def create_schedule(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import PlaybackSchedule

        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        for field in ("location_id", "favorite_id", "start_time", "stop_time"):
            if not body.get(field):
                return [JSONResponse({"error": f"{field} is required"}, status_code=HTTPStatus.BAD_REQUEST)]

        schedule = PlaybackSchedule.objects.create(
            location_id=body["location_id"],
            location_name=body.get("location_name", ""),
            favorite_id=body["favorite_id"],
            favorite_name=body.get("favorite_name", ""),
            volume=body.get("volume", 25),
            weekdays=body.get("weekdays", "0,1,2,3,4,5,6"),
            start_time=body["start_time"],
            stop_time=body["stop_time"],
            utc_offset_minutes=body.get("utc_offset_minutes", 0),
        )
        return [JSONResponse({"success": True, "id": schedule.pk}, status_code=HTTPStatus.CREATED)]

    @api.put("/sonos/schedules/<schedule_id>")
    def update_schedule(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import PlaybackSchedule

        try:
            pk = int(self.request.path_params["schedule_id"])
        except (TypeError, ValueError):
            return [JSONResponse({"error": "Invalid schedule id"}, status_code=HTTPStatus.BAD_REQUEST)]
        try:
            body = json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        qs = PlaybackSchedule.objects.filter(dbid=pk, active=True)
        if not qs.exists():
            return [JSONResponse({"error": "Schedule not found"}, status_code=HTTPStatus.NOT_FOUND)]

        update_fields = {}
        for field in ("location_id", "location_name", "favorite_id", "favorite_name",
                      "volume", "weekdays", "start_time", "stop_time", "utc_offset_minutes"):
            if field in body:
                update_fields[field] = body[field]
        if update_fields:
            qs.update(**update_fields)
        return [JSONResponse({"success": True}, status_code=HTTPStatus.OK)]

    @api.delete("/sonos/schedules/<schedule_id>")
    def delete_schedule(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import PlaybackSchedule

        try:
            pk = int(self.request.path_params["schedule_id"])
        except (TypeError, ValueError):
            return [JSONResponse({"error": "Invalid schedule id"}, status_code=HTTPStatus.BAD_REQUEST)]
        schedule = PlaybackSchedule.objects.filter(dbid=pk).first()
        if not schedule:
            return [JSONResponse({"error": "Schedule not found"}, status_code=HTTPStatus.NOT_FOUND)]
        schedule.active = False
        schedule.save()
        return [JSONResponse({"success": True}, status_code=HTTPStatus.OK)]

    # ------------------------------------------------------------------
    # Sonos - activity log
    # ------------------------------------------------------------------

    @api.get("/sonos/log")
    def sonos_log(self) -> list[Response | Effect]:
        from sonos_audio.models.custom_data import SonosPlaybackLog

        location_id = self.request.query_params.get("location_id", "")
        qs = SonosPlaybackLog.objects.all().order_by("-created_at")
        if location_id:
            qs = qs.filter(location_id=location_id)
        entries = qs[:50]
        return [JSONResponse({
            "log": [
                {
                    "id": e.pk,
                    "location_id": e.location_id,
                    "location_name": e.location_name,
                    "player_id": e.player_id,
                    "preset_key": e.preset_key,
                    "action": e.action,
                    "volume": e.volume,
                    "triggered_by": e.triggered_by,
                    "error_message": e.error_message,
                    "created_at": e.created_at.isoformat() if e.created_at else "",
                }
                for e in entries
            ]
        }, status_code=HTTPStatus.OK)]
