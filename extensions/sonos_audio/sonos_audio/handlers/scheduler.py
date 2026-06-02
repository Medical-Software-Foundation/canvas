"""Cron-driven Sonos playback scheduler.

Runs once a minute. For each active PlaybackSchedule, it figures out the local
wall-clock time (UTC shifted by the schedule's ``utc_offset_minutes``) and, on a
matching weekday, starts playback at ``start_time`` and pauses at ``stop_time``.

Matching is to the minute, which lines up with the once-a-minute cron tick.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from logger import log

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from sonos_audio.services.sonos_client import SonosClient


class PlaybackScheduler(CronTask):
    """Starts/stops scheduled Sonos playback windows."""

    SCHEDULE = "* * * * *"  # every minute

    def _client(self) -> SonosClient | None:
        from sonos_audio.models.custom_data import SonosOAuthCredential

        client_id = self.secrets.get("SONOS_CLIENT_ID", "")
        client_secret = self.secrets.get("SONOS_CLIENT_SECRET", "")
        cred = SonosOAuthCredential.objects.first()
        refresh_token = str(cred.refresh_token) if (cred and cred.refresh_token) else ""
        if not all([client_id, client_secret, refresh_token]):
            return None
        return SonosClient(client_id, client_secret, refresh_token)

    @staticmethod
    def _parse_weekdays(raw: str) -> set[int]:
        out: set[int] = set()
        for part in (raw or "").split(","):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
        return out

    @classmethod
    def decide_action(
        cls, local_dt: datetime, weekdays: str, start_time: str, stop_time: str
    ) -> str | None:
        """Pure decision: what (if anything) should fire at this local minute.

        Returns "play" at start_time, "pause" at stop_time, else None. Only fires
        on weekdays in `weekdays` (Mon=0 .. Sun=6, matching datetime.weekday()).
        """
        if local_dt.weekday() not in cls._parse_weekdays(weekdays):
            return None
        hhmm = local_dt.strftime("%H:%M")
        if hhmm == start_time:
            return "play"
        if hhmm == stop_time:
            return "pause"
        return None

    def execute(self) -> list[Effect]:
        from sonos_audio.models.custom_data import (
            PlaybackSchedule,
            SonosPlaybackLog,
            SonosSpeaker,
        )

        now_utc = datetime.now(timezone.utc)

        # Decide which schedules fire this minute before touching speakers or Sonos.
        # Most minutes nothing fires, so we avoid all further work in that case.
        firing: list[tuple[Any, str]] = []
        for sched in PlaybackSchedule.objects.filter(active=True):
            local = now_utc + timedelta(minutes=int(sched.utc_offset_minutes or 0))
            action = self.decide_action(local, sched.weekdays, sched.start_time, sched.stop_time)
            if action is not None:
                firing.append((sched, action))
        if not firing:
            return []

        # One query for the speakers we need, grouped by location. A location may
        # have several speakers, so the schedule fans out to every one of them.
        location_ids = {sched.location_id for sched, _ in firing}
        speakers_by_location: dict[str, list[Any]] = {}
        for s in SonosSpeaker.objects.filter(location_id__in=location_ids, active=True):
            speakers_by_location.setdefault(s.location_id, []).append(s)

        client = self._client()
        demo = client is None

        for sched, action in firing:
            triggered_by = "schedule_start" if action == "play" else "schedule_stop"
            volume = max(0, min(100, int(sched.volume if sched.volume is not None else 25)))

            for speaker in speakers_by_location.get(sched.location_id, []):
                group_id = speaker.group_id or speaker.player_id

                error_message = ""
                if not demo and client is not None:
                    try:
                        if action == "play":
                            client.load_favorite(group_id, sched.favorite_id, play_on_completion=True)
                            client.set_volume(group_id, volume)
                        else:
                            client.pause(group_id)
                    except Exception as e:  # noqa: BLE001 - log and record, never crash the cron tick
                        error_message = str(e)
                        log.warning("[sonos_audio] schedule %s error: %s", action, e)

                SonosPlaybackLog.objects.create(
                    location_id=sched.location_id,
                    location_name=sched.location_name,
                    player_id=speaker.player_id,
                    action="error" if error_message else action,
                    volume=volume if action == "play" else 0,
                    triggered_by=triggered_by,
                    error_message=error_message,
                )

        return []
