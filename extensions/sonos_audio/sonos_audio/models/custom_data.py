from typing import Any

from django.db.models import (
    BooleanField,
    DateTimeField,
    Index,
    IntegerField,
    TextField,
    UniqueConstraint,
)
from canvas_sdk.v1.data.base import CustomModel


class SonosSpeaker(CustomModel):
    """Maps a Sonos speaker/group to a Canvas practice location.

    A location can host exactly one speaker mapping. The mapped speaker is what
    play/pause/volume controls and schedules act on for that location.
    """

    location_id: Any = TextField()  # Canvas PracticeLocation UUID
    location_name: Any = TextField(default="")
    player_id: Any = TextField()  # Sonos player ID
    group_id: Any = TextField(default="")  # Sonos group ID (preferred for control)
    player_name: Any = TextField()  # human-readable name from Sonos
    household_id: Any = TextField()
    active: Any = BooleanField(default=True)
    # Remembered "default station" for this location — set to the last favorite
    # played here and pre-selected in the Play control. Staff can still pick another.
    default_favorite_id: Any = TextField(default="")
    default_favorite_name: Any = TextField(default="")
    default_volume: Any = IntegerField(default=25)  # 0-100

    class Meta:
        constraints = [
            UniqueConstraint(fields=["location_id"], name="uq_sonos_speaker_location"),
        ]
        indexes = [
            Index(fields=["location_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.player_name} -> {self.location_name or self.location_id}"


class AudioPreset(CustomModel):
    """A named ambient-music preset: a Sonos favorite + volume.

    Presets are reusable "stations" staff can apply to any speaker. A preset may
    optionally be bound to a location (match_type="location") so it surfaces as
    that location's suggested default, or be the global fallback (match_type="default").
    """

    key: Any = TextField()
    name: Any = TextField()
    match_type: Any = TextField(default="location")  # location, default
    match_value: Any = TextField(default="")  # location_id when match_type="location"
    sonos_favorite_id: Any = TextField(default="")
    sonos_favorite_name: Any = TextField(default="")
    volume: Any = IntegerField(default=25)  # 0-100
    priority: Any = IntegerField(default=0)  # higher wins when multiple match
    active: Any = BooleanField(default=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["key"], name="uq_sonos_audio_preset_key"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.match_type}={self.match_value})"


class SonosOAuthCredential(CustomModel):
    """Org-wide Sonos OAuth tokens (single row). Populated by the in-app Connect Sonos flow."""

    refresh_token: Any = TextField(default="")
    household_id: Any = TextField(default="")
    household_name: Any = TextField(default="")
    pending_state: Any = TextField(default="")  # CSRF nonce during in-flight authorization
    connected_by_staff_id: Any = TextField(default="")
    connected_at: Any = DateTimeField(null=True, blank=True)
    updated_at: Any = DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Sonos OAuth ({self.household_name or 'not connected'})"


class PlaybackSchedule(CustomModel):
    """A recurring playback window for a location.

    The scheduler starts `favorite_id` at `start_time` and pauses at `stop_time`
    on each weekday listed in `weekdays`. Times are wall-clock "HH:MM" interpreted
    in the schedule's own timezone via `utc_offset_minutes` (e.g. -420 for PDT),
    so the plugin needs no timezone database.
    """

    location_id: Any = TextField()
    location_name: Any = TextField(default="")
    favorite_id: Any = TextField(default="")
    favorite_name: Any = TextField(default="")
    volume: Any = IntegerField(default=25)  # 0-100
    weekdays: Any = TextField(default="0,1,2,3,4,5,6")  # CSV of 0=Mon ... 6=Sun
    start_time: Any = TextField(default="09:00")  # "HH:MM"
    stop_time: Any = TextField(default="17:00")  # "HH:MM"
    utc_offset_minutes: Any = IntegerField(default=0)  # local offset from UTC; 0 = times are UTC
    active: Any = BooleanField(default=True)

    class Meta:
        indexes = [
            Index(fields=["location_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.location_name or self.location_id}: {self.start_time}-{self.stop_time} ({self.favorite_name})"


class SonosPlaybackLog(CustomModel):
    """Append-only audit trail of Sonos playback actions."""

    location_id: Any = TextField()
    location_name: Any = TextField(default="")
    player_id: Any = TextField(default="")
    preset_key: Any = TextField(default="")
    action: Any = TextField()  # play, pause, volume_change, error
    volume: Any = IntegerField(default=0)
    triggered_by: Any = TextField()  # manual, schedule_start, schedule_stop, timer
    error_message: Any = TextField(default="")
    created_at: Any = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=["location_id"]),
            Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.location_name or self.location_id}: {self.action} ({self.triggered_by})"
