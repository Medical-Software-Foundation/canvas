"""Campaign configuration — persisted as a singleton CustomModel row.

The dataclasses below define the in-memory shape. Storage is a single row
in `CampaignConfigRecord` whose `data` JSONField holds the serialized
config. On first load after upgrading from cache-based storage, any
existing `cr:config` cache entry is migrated into the CustomModel row.
"""
import json
from dataclasses import dataclass, field
from typing import Any

from canvas_sdk.caching.plugins import get_cache

from appointment_reminders.models.config import CampaignConfigRecord


# Known fields for backward compatibility filtering
_CAMPAIGN_CONFIG_FIELDS = {
    "confirmation_enabled",
    "confirmation_sms_template",
    "confirmation_email_template",
    "confirmation_channels",
    "reminders_enabled",
    "reminder_intervals",
    "reminder_sms_template",
    "reminder_email_template",
    "reminder_channels",
    "reminder_send_time",
    "reminder_timezone",
    "noshow_enabled",
    "noshow_sms_template",
    "noshow_email_template",
    "noshow_channels",
    "cancellation_enabled",
    "cancellation_sms_template",
    "cancellation_email_template",
    "cancellation_channels",
    "telehealth_enabled",
    "telehealth_sms_template",
    "telehealth_email_template",
    "telehealth_channels",
    "telehealth_intervals",
    "note_type_reminders",
    "default_attribution",
    "business_line_overrides",
}

_NOTE_TYPE_FIELDS = {
    "note_type_id",
    "note_type_name",
    # Confirmation
    "confirmation_enabled",
    "confirmation_override",
    "confirmation_sms_template",
    "confirmation_email_template",
    "confirmation_channels",
    # Reminder
    "reminders_enabled",
    "reminder_override",
    "reminder_intervals",
    "reminder_sms_template",
    "reminder_email_template",
    "reminder_channels",
    "reminder_send_time",
    "reminder_timezone",
    # No-show
    "noshow_enabled",
    "noshow_override",
    "noshow_sms_template",
    "noshow_email_template",
    "noshow_channels",
    # Cancellation
    "cancellation_enabled",
    "cancellation_override",
    "cancellation_sms_template",
    "cancellation_email_template",
    "cancellation_channels",
    # Telehealth
    "telehealth_enabled",
    "telehealth_override",
    "telehealth_sms_template",
    "telehealth_email_template",
    "telehealth_channels",
    "telehealth_intervals",
}

# Single-template keys from 0.2.x that map to dual template fields
_SINGLE_TO_DUAL = {
    "confirmation_template": ("confirmation_sms_template", "confirmation_email_template"),
    "reminder_template": ("reminder_sms_template", "reminder_email_template"),
    "noshow_template": ("noshow_sms_template", "noshow_email_template"),
    "cancellation_template": ("cancellation_sms_template", "cancellation_email_template"),
}


@dataclass
class NoteTypeCampaignConfig:
    """Per-note-type campaign configuration for all 4 campaign types."""

    note_type_id: str = ""
    note_type_name: str = ""

    # Confirmation (enabled=active for this type, override=use custom templates)
    confirmation_enabled: bool | None = None
    confirmation_override: bool = False
    confirmation_sms_template: str = ""
    confirmation_email_template: str = ""
    confirmation_channels: list[str] = field(default_factory=list)

    # Reminder
    reminders_enabled: bool | None = None
    reminder_override: bool = False
    reminder_intervals: list[int] = field(default_factory=list)
    reminder_sms_template: str = ""
    reminder_email_template: str = ""
    reminder_channels: list[str] = field(default_factory=list)
    reminder_send_time: str = ""  # empty = inherit global
    reminder_timezone: str = ""  # empty = inherit global

    # No-show
    noshow_enabled: bool | None = None
    noshow_override: bool = False
    noshow_sms_template: str = ""
    noshow_email_template: str = ""
    noshow_channels: list[str] = field(default_factory=list)

    # Cancellation
    cancellation_enabled: bool | None = None
    cancellation_override: bool = False
    cancellation_sms_template: str = ""
    cancellation_email_template: str = ""
    cancellation_channels: list[str] = field(default_factory=list)

    # Telehealth
    telehealth_enabled: bool | None = None
    telehealth_override: bool = False
    telehealth_sms_template: str = ""
    telehealth_email_template: str = ""
    telehealth_channels: list[str] = field(default_factory=list)
    telehealth_intervals: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "note_type_id": self.note_type_id,
            "note_type_name": self.note_type_name,
            "confirmation_enabled": self.confirmation_enabled,
            "confirmation_override": self.confirmation_override,
            "confirmation_sms_template": self.confirmation_sms_template,
            "confirmation_email_template": self.confirmation_email_template,
            "confirmation_channels": self.confirmation_channels,
            "reminders_enabled": self.reminders_enabled,
            "reminder_override": self.reminder_override,
            "reminder_intervals": self.reminder_intervals,
            "reminder_sms_template": self.reminder_sms_template,
            "reminder_email_template": self.reminder_email_template,
            "reminder_channels": self.reminder_channels,
            "reminder_send_time": self.reminder_send_time,
            "reminder_timezone": self.reminder_timezone,
            "noshow_enabled": self.noshow_enabled,
            "noshow_override": self.noshow_override,
            "noshow_sms_template": self.noshow_sms_template,
            "noshow_email_template": self.noshow_email_template,
            "noshow_channels": self.noshow_channels,
            "cancellation_enabled": self.cancellation_enabled,
            "cancellation_override": self.cancellation_override,
            "cancellation_sms_template": self.cancellation_sms_template,
            "cancellation_email_template": self.cancellation_email_template,
            "cancellation_channels": self.cancellation_channels,
            "telehealth_enabled": self.telehealth_enabled,
            "telehealth_override": self.telehealth_override,
            "telehealth_sms_template": self.telehealth_sms_template,
            "telehealth_email_template": self.telehealth_email_template,
            "telehealth_channels": self.telehealth_channels,
            "telehealth_intervals": self.telehealth_intervals,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NoteTypeCampaignConfig":
        """Create from dictionary with backward compatibility."""
        cleaned = dict(data)

        # Migrate single reminder_template from 0.2.x to dual fields
        if "reminder_template" in cleaned:
            single = cleaned.pop("reminder_template")
            if "reminder_sms_template" not in cleaned:
                cleaned["reminder_sms_template"] = single
            if "reminder_email_template" not in cleaned:
                cleaned["reminder_email_template"] = single

        # Filter to known fields only
        filtered = {k: v for k, v in cleaned.items() if k in _NOTE_TYPE_FIELDS}
        return cls(**filtered)


# Backward-compatible alias
NoteTypeReminderConfig = NoteTypeCampaignConfig


@dataclass
class CampaignConfig:
    """Campaign configuration for notifications."""

    # Confirmation campaign
    confirmation_enabled: bool = False
    # NOTE: defaults follow HIPAA information-minimization for unsecure SMS/email —
    # no provider name/credentials, no visit type, short (not billing) names. SMS
    # carries the STOP opt-out (a carrier keyword); email opt-out is via SendGrid
    # Subscription Tracking / ASM, not the body.
    confirmation_sms_template: str = (
        "Hi {{patient_first_name}}, this is {{business_line_attribution}}. Your visit at "
        "{{location_short_name}} on {{appointment_date}} at {{appointment_time}} is confirmed. "
        "Call {{location_phone}} to reschedule. Reply STOP to opt out."
    )
    confirmation_email_template: str = (
        "<p>Hi {{patient_first_name}}, this is {{business_line_attribution}}. Your visit at "
        "{{location_short_name}} on {{appointment_date}} at {{appointment_time}} is confirmed.</p>"
        "<p>Call {{location_phone}} to reschedule.</p>"
    )
    confirmation_channels: list[str] = field(default_factory=lambda: ["sms", "email"])

    # Reminder campaign
    reminders_enabled: bool = False
    # Default cadence preset: 3 days out (4320 min, day-out at reminder_send_time)
    # and 45 minutes out (time-relative). Fully configurable per install/note type.
    reminder_intervals: list[int] = field(default_factory=lambda: [4320, 45])
    # SMS reminder carries the two-way confirm CTA ("1 to confirm") — inbound is
    # Twilio-SMS-only, so email must NOT ask the patient to reply.
    reminder_sms_template: str = (
        "Hi {{patient_first_name}}, this is {{business_line_attribution}}. You have a visit at "
        "{{location_short_name}} on {{appointment_date}} at {{appointment_time}}. "
        "Reply 1 to confirm or 2 to cancel. Reply STOP to opt out."
    )
    reminder_email_template: str = (
        "<p>Hi {{patient_first_name}}, this is {{business_line_attribution}}. You have an "
        "upcoming visit at {{location_short_name}} on {{appointment_date}} at {{appointment_time}}.</p>"
        "<p>Call {{location_phone}} to confirm or reschedule.</p>"
    )
    reminder_channels: list[str] = field(default_factory=lambda: ["sms", "email"])
    reminder_send_time: str = "09:00"  # HH:MM in 24h format for day-out reminders
    reminder_timezone: str = "America/New_York"

    # No-show campaign
    noshow_enabled: bool = False
    noshow_sms_template: str = (
        "Hi {{patient_first_name}}, we missed you at {{location_short_name}} today. "
        "Call {{location_phone}} to reschedule. Reply STOP to opt out."
    )
    noshow_email_template: str = (
        "<p>Hi {{patient_first_name}}, we missed you at {{location_short_name}} today.</p>"
        "<p>Please call {{location_phone}} to reschedule.</p>"
    )
    noshow_channels: list[str] = field(default_factory=lambda: ["sms", "email"])

    # Cancellation campaign
    cancellation_enabled: bool = False
    cancellation_sms_template: str = (
        "Hi {{patient_first_name}}, your visit at {{location_short_name}} on "
        "{{appointment_date}} at {{appointment_time}} has been cancelled. "
        "Call {{location_phone}} to rebook. Reply STOP to opt out."
    )
    cancellation_email_template: str = (
        "<p>Hi {{patient_first_name}}, your visit at {{location_short_name}} on "
        "{{appointment_date}} at {{appointment_time}} has been cancelled.</p>"
        "<p>Call {{location_phone}} to rebook.</p>"
    )
    cancellation_channels: list[str] = field(default_factory=lambda: ["sms", "email"])

    # Telehealth join campaign
    telehealth_enabled: bool = False
    telehealth_sms_template: str = (
        "Hi {{patient_first_name}}, this is {{business_line_attribution}}. Your telehealth visit "
        "on {{appointment_date}} at {{appointment_time}} is coming up. "
        "Join: {{telehealth_link}} Reply STOP to opt out."
    )
    telehealth_email_template: str = (
        "<p>Hi {{patient_first_name}}, this is {{business_line_attribution}}. Your telehealth visit "
        "on {{appointment_date}} at {{appointment_time}} is coming up.</p>"
        "<p><a href=\"{{telehealth_link}}\">Join your telehealth visit</a></p>"
    )
    telehealth_channels: list[str] = field(default_factory=lambda: ["sms", "email"])
    telehealth_intervals: list[int] = field(default_factory=lambda: [15])  # 15min before

    # Per-note-type overrides (keyed by note_type_id)
    note_type_reminders: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Patient-facing attribution used by the {{business_line_attribution}}
    # placeholder when a patient's business line has no explicit override.
    default_attribution: str = "Your Care Team"

    # Per-business-line overrides (keyed by business line NAME, e.g. "Northwind Health").
    # Each entry may hold an "attribution" string (e.g. "Acme on behalf of
    # Northwind Health") and/or the same per-campaign override fields as a note-type record
    # ("{campaign}_enabled" opt-out, "{campaign}_override" + templates/channels).
    # Layered on top of note-type resolution — business line wins for templates.
    business_line_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "confirmation_enabled": self.confirmation_enabled,
            "confirmation_sms_template": self.confirmation_sms_template,
            "confirmation_email_template": self.confirmation_email_template,
            "confirmation_channels": self.confirmation_channels,
            "reminders_enabled": self.reminders_enabled,
            "reminder_intervals": self.reminder_intervals,
            "reminder_sms_template": self.reminder_sms_template,
            "reminder_email_template": self.reminder_email_template,
            "reminder_channels": self.reminder_channels,
            "reminder_send_time": self.reminder_send_time,
            "reminder_timezone": self.reminder_timezone,
            "noshow_enabled": self.noshow_enabled,
            "noshow_sms_template": self.noshow_sms_template,
            "noshow_email_template": self.noshow_email_template,
            "noshow_channels": self.noshow_channels,
            "cancellation_enabled": self.cancellation_enabled,
            "cancellation_sms_template": self.cancellation_sms_template,
            "cancellation_email_template": self.cancellation_email_template,
            "cancellation_channels": self.cancellation_channels,
            "telehealth_enabled": self.telehealth_enabled,
            "telehealth_sms_template": self.telehealth_sms_template,
            "telehealth_email_template": self.telehealth_email_template,
            "telehealth_channels": self.telehealth_channels,
            "telehealth_intervals": self.telehealth_intervals,
            "note_type_reminders": self.note_type_reminders,
            "default_attribution": self.default_attribution,
            "business_line_overrides": self.business_line_overrides,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CampaignConfig":
        """Create from dictionary with backward compatibility."""
        cleaned = dict(data)

        if "note_type_reminders" not in cleaned:
            cleaned["note_type_reminders"] = {}
        if "business_line_overrides" not in cleaned:
            cleaned["business_line_overrides"] = {}

        # Migrate single-template keys from 0.2.x to dual template fields
        for single_key, (sms_key, email_key) in _SINGLE_TO_DUAL.items():
            if single_key in cleaned:
                single_val = cleaned.pop(single_key)
                if sms_key not in cleaned:
                    cleaned[sms_key] = single_val
                if email_key not in cleaned:
                    cleaned[email_key] = single_val

        # Remove stale keys from older versions
        stale_keys = {
            "sender_staff_last_name", "fallback_team_name",
            "sender_staff_id", "sender_staff_display",
            "fallback_team_id", "fallback_team_display",
        }
        for key in stale_keys:
            cleaned.pop(key, None)

        # Filter to known fields only
        filtered = {k: v for k, v in cleaned.items() if k in _CAMPAIGN_CONFIG_FIELDS}
        return cls(**filtered)


# Legacy cache key — only read once per instance to migrate pre-existing
# admin config into the CustomModel row. Safe to remove after every
# instance has been upgraded past this version.
_LEGACY_CACHE_KEY_CONFIG = "cr:config"


def _migrate_from_cache() -> CampaignConfig | None:
    """Read an existing cache-stored config, if any, for one-time migration."""
    cache = get_cache()
    data = cache.get(_LEGACY_CACHE_KEY_CONFIG)
    if data is None:
        return None
    return CampaignConfig.from_dict(json.loads(data))


def load_config() -> CampaignConfig:
    """Load campaign configuration from the CustomModel singleton."""
    record = CampaignConfigRecord.objects.first()
    if record is not None:
        return CampaignConfig.from_dict(record.data or {})

    legacy = _migrate_from_cache()
    if legacy is not None:
        CampaignConfigRecord.objects.create(data=legacy.to_dict())
        return legacy

    return CampaignConfig()


def save_config(config: CampaignConfig) -> None:
    """Persist campaign configuration to the CustomModel singleton."""
    record = CampaignConfigRecord.objects.first()
    if record is None:
        CampaignConfigRecord.objects.create(data=config.to_dict())
        return
    record.data = config.to_dict()
    record.save()


# ---- message-copy lock ----------------------------------------------------

_LOCK_TRUE = {"1", "true", "yes", "on"}

# Suffixes identifying an editable message body on either the global config or
# a per-note-type / per-business-line override record.
_TEMPLATE_SUFFIXES = ("_sms_template", "_email_template")


def templates_locked(secrets: dict[str, str] | None) -> bool:
    """Whether message copy is frozen by the ``LOCK_MESSAGE_TEMPLATES`` secret.

    Off by default so a fresh install is editable. Deployments that ship
    compliance-approved copy turn it on; staff can then still read every
    template and control scheduling, channels, and opt-outs, but the wording
    itself only changes by changing the secret.
    """
    if not secrets:
        return False
    return (secrets.get("LOCK_MESSAGE_TEMPLATES") or "").strip().lower() in _LOCK_TRUE


def collect_templates(config: CampaignConfig) -> dict[str, str]:
    """Flatten every message body in a config into ``path -> copy``.

    Covers the five global campaign templates plus any per-note-type and
    per-business-line overrides. Values are stripped so that whitespace-only
    differences don't read as edits.
    """
    found: dict[str, str] = {}

    for name, value in config.to_dict().items():
        if name.endswith(_TEMPLATE_SUFFIXES) and isinstance(value, str):
            found[name] = value.strip()

    # Typed loosely on purpose: the override maps are deserialized from a
    # JSONField, so their declared shape isn't guaranteed at runtime and the
    # isinstance guards below are load-bearing.
    scoped: list[tuple[str, Any]] = [
        ("note_type", config.note_type_reminders),
        ("business_line", config.business_line_overrides),
    ]
    for scope, records in scoped:
        if not isinstance(records, dict):
            continue
        for key, record in records.items():
            if not isinstance(record, dict):
                continue
            for name, value in record.items():
                if name.endswith(_TEMPLATE_SUFFIXES) and isinstance(value, str):
                    found[f"{scope}:{key}:{name}"] = value.strip()

    return found


# Maps campaign_type → CampaignConfig/NoteTypeCampaignConfig attribute names.
# `override` identifies the per-note-type "customize templates" flag.
_CAMPAIGN_SPEC = {
    "confirmation": {
        "enabled": "confirmation_enabled",
        "channels": "confirmation_channels",
        "sms": "confirmation_sms_template",
        "email": "confirmation_email_template",
        "override": "confirmation_override",
    },
    "reminder": {
        "enabled": "reminders_enabled",
        "channels": "reminder_channels",
        "sms": "reminder_sms_template",
        "email": "reminder_email_template",
        "override": "reminder_override",
        "intervals": "reminder_intervals",
        "send_time": "reminder_send_time",
        "timezone": "reminder_timezone",
    },
    "noshow": {
        "enabled": "noshow_enabled",
        "channels": "noshow_channels",
        "sms": "noshow_sms_template",
        "email": "noshow_email_template",
        "override": "noshow_override",
    },
    "cancellation": {
        "enabled": "cancellation_enabled",
        "channels": "cancellation_channels",
        "sms": "cancellation_sms_template",
        "email": "cancellation_email_template",
        "override": "cancellation_override",
    },
    "telehealth": {
        "enabled": "telehealth_enabled",
        "channels": "telehealth_channels",
        "sms": "telehealth_sms_template",
        "email": "telehealth_email_template",
        "override": "telehealth_override",
        "intervals": "telehealth_intervals",
    },
}

_DISABLED: tuple[bool, list[str], str, str, list[int], str, str] = (
    False, [], "", "", [], "", "",
)


def get_effective_campaign_config(
    config: CampaignConfig,
    note_type_id: str | None,
    campaign_type: str,
    business_line: str | None = None,
) -> tuple[bool, list[str], str, str, list[int], str, str]:
    """Return effective (enabled, channels, sms, email, intervals, send_time, tz).

    Resolution layers, outermost wins for templates/channels:
    ``global → per-note-type override → per-business-line override``. Business
    line is applied last because messaging is segmented by referral source
    (business line), so a business-line override should beat a note-type one.
    Any layer's explicit ``*_enabled=False`` is an opt-out that disables the
    campaign for that appointment.
    """
    base = _effective_note_type_config(config, note_type_id, campaign_type)
    if not base[0] or not business_line:
        return base
    return _apply_business_line_override(config, campaign_type, business_line, base)


def _effective_note_type_config(
    config: CampaignConfig, note_type_id: str | None, campaign_type: str
) -> tuple[bool, list[str], str, str, list[int], str, str]:
    """Resolve global + per-note-type layers (see get_effective_campaign_config)."""
    spec = _CAMPAIGN_SPEC.get(campaign_type)
    if spec is None:
        return _DISABLED

    # Master switch: if globally disabled, the campaign never fires.
    if not getattr(config, spec["enabled"], False):
        return _DISABLED

    # Global defaults.
    channels = list(getattr(config, spec["channels"], []) or [])
    sms_tpl = getattr(config, spec["sms"], "") or ""
    email_tpl = getattr(config, spec["email"], "") or ""
    intervals_attr = spec.get("intervals")
    intervals = list(getattr(config, intervals_attr, []) or []) if intervals_attr else []
    send_time_attr = spec.get("send_time")
    send_time = getattr(config, send_time_attr, "") if send_time_attr else ""
    timezone_attr = spec.get("timezone")
    timezone = getattr(config, timezone_attr, "") if timezone_attr else ""

    # Campaigns without a per-note-type UI short-circuit here.
    override_attr = spec.get("override")
    if not override_attr or not note_type_id:
        return (True, channels, sms_tpl, email_tpl, intervals, send_time, timezone)

    nt_raw = config.note_type_reminders.get(note_type_id)
    if not nt_raw:
        return (True, channels, sms_tpl, email_tpl, intervals, send_time, timezone)

    nt_cfg = NoteTypeCampaignConfig.from_dict(nt_raw)

    # Opt-out: explicit False on the per-note-type record.
    if getattr(nt_cfg, spec["enabled"]) is False:
        return _DISABLED

    # Per-note-type may refine intervals/send_time/timezone even without the
    # "customize templates" flag — these are structural scheduling config.
    if intervals_attr:
        nt_intervals = getattr(nt_cfg, intervals_attr, None)
        if nt_intervals:
            intervals = list(nt_intervals)
    if send_time_attr:
        nt_st = getattr(nt_cfg, send_time_attr, "") or ""
        if nt_st:
            send_time = nt_st
    if timezone_attr:
        nt_tz = getattr(nt_cfg, timezone_attr, "") or ""
        if nt_tz:
            timezone = nt_tz

    # Template/channel customization applies only when the override flag is set.
    if getattr(nt_cfg, override_attr, False):
        nt_channels = getattr(nt_cfg, spec["channels"], []) or []
        nt_sms = getattr(nt_cfg, spec["sms"], "") or ""
        nt_email = getattr(nt_cfg, spec["email"], "") or ""
        if nt_channels:
            channels = list(nt_channels)
        if nt_sms:
            sms_tpl = nt_sms
        if nt_email:
            email_tpl = nt_email

    return (True, channels, sms_tpl, email_tpl, intervals, send_time, timezone)


def _apply_business_line_override(
    config: CampaignConfig,
    campaign_type: str,
    business_line: str,
    base: tuple[bool, list[str], str, str, list[int], str, str],
) -> tuple[bool, list[str], str, str, list[int], str, str]:
    """Layer a per-business-line override on top of an already-resolved config.

    A business-line entry reuses the note-type override fields: ``*_enabled``
    (an explicit ``False`` opts the campaign out for this business line) and,
    when ``*_override`` is set, custom templates/channels. Intervals/send-time/
    timezone are left to the note-type layer — business line only refines copy,
    channels, and opt-out.
    """
    spec = _CAMPAIGN_SPEC.get(campaign_type)
    if spec is None:
        return base

    bl_raw = config.business_line_overrides.get(business_line)
    if not bl_raw:
        return base

    enabled, channels, sms_tpl, email_tpl, intervals, send_time, timezone = base
    bl_cfg = NoteTypeCampaignConfig.from_dict(bl_raw)

    # Opt-out: explicit False on the business-line record.
    if getattr(bl_cfg, spec["enabled"], None) is False:
        return _DISABLED

    override_attr = spec.get("override")
    if override_attr and getattr(bl_cfg, override_attr, False):
        bl_channels = getattr(bl_cfg, spec["channels"], []) or []
        bl_sms = getattr(bl_cfg, spec["sms"], "") or ""
        bl_email = getattr(bl_cfg, spec["email"], "") or ""
        if bl_channels:
            channels = list(bl_channels)
        if bl_sms:
            sms_tpl = bl_sms
        if bl_email:
            email_tpl = bl_email

    return (enabled, channels, sms_tpl, email_tpl, intervals, send_time, timezone)


def get_effective_reminder_config(
    config: CampaignConfig, note_type_id: str | None
) -> tuple[bool, list[int], list[str], str, str]:
    """Return (enabled, intervals, channels, sms_template, email_template) for a note type.

    Backward-compatible wrapper around get_effective_campaign_config for reminders.
    """
    enabled, channels, sms_tpl, email_tpl, intervals, _st, _tz = (
        get_effective_campaign_config(config, note_type_id, "reminder")
    )
    return (enabled, intervals, channels, sms_tpl, email_tpl)
