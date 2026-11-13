"""Campaign configuration management using Cache API."""
import json
import re
from dataclasses import dataclass, field
from typing import Any

from canvas_sdk.caching.plugins import get_cache


_SAFE_TAGS = frozenset({
    "p", "br", "em", "strong", "b", "i", "u", "s",
    "a", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "span", "div", "blockquote", "hr", "sub", "sup", "small",
})

_SAFE_ATTRS = frozenset({"href", "title", "style", "class"})

_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.DOTALL)
_ATTR_RE = re.compile(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_EVENT_OR_JS = re.compile(r"^on|^javascript:", re.IGNORECASE)


def sanitize_html(html: str) -> str:
    """Strip dangerous tags and attributes, keep safe formatting HTML."""
    def replace_tag(m: re.Match[str]) -> str:
        slash, tag, attrs_str = m.group(1), m.group(2).lower(), m.group(3)
        if tag not in _SAFE_TAGS:
            return ""
        if slash:
            return f"</{tag}>"
        safe_attrs = []
        for attr_m in _ATTR_RE.finditer(attrs_str):
            name = attr_m.group(1).lower()
            value = attr_m.group(2) if attr_m.group(2) is not None else attr_m.group(3)
            if name not in _SAFE_ATTRS:
                continue
            if _EVENT_OR_JS.search(name) or _EVENT_OR_JS.search(value):
                continue
            safe_attrs.append(f'{name}="{value}"')
        attr_str = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        return f"<{tag}{attr_str}>"
    return _TAG_RE.sub(replace_tag, html)


# Known fields for backward compatibility filtering
_CAMPAIGN_CONFIG_FIELDS = {
    "day_out_send_time",
    "day_out_timezone",
    "confirmation_enabled",
    "confirmation_sms_template",
    "confirmation_email_template",
    "confirmation_channels",
    "reminders_enabled",
    "reminder_intervals",
    "reminder_sms_template",
    "reminder_email_template",
    "reminder_channels",
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
    "note_type_campaigns",
    "custom_variables",
}

_NOTE_TYPE_CAMPAIGN_FIELDS = {
    "note_type_id",
    "note_type_name",
    "master_enabled",

    "confirmation_enabled",
    "confirmation_override",
    "confirmation_sms_template",
    "confirmation_email_template",
    "confirmation_channels",
    "reminders_enabled",
    "reminder_override",
    "reminder_send_time",
    "reminder_intervals",
    "reminder_sms_template",
    "reminder_email_template",
    "reminder_channels",
    "noshow_enabled",
    "noshow_override",
    "noshow_sms_template",
    "noshow_email_template",
    "noshow_channels",
    "cancellation_enabled",
    "cancellation_override",
    "cancellation_sms_template",
    "cancellation_email_template",
    "cancellation_channels",
    "telehealth_enabled",
    "telehealth_override",
    "telehealth_intervals",
    "telehealth_sms_template",
    "telehealth_email_template",
    "telehealth_channels",
}

# Single-template keys from 0.2.x that map to dual template fields
_SINGLE_TO_DUAL = {
    "confirmation_template": ("confirmation_sms_template", "confirmation_email_template"),
    "reminder_template": ("reminder_sms_template", "reminder_email_template"),
    "noshow_template": ("noshow_sms_template", "noshow_email_template"),
    "cancellation_template": ("cancellation_sms_template", "cancellation_email_template"),
}

# Campaign type to field prefix mapping
_CAMPAIGN_PREFIXES = {
    "confirmation": "confirmation",
    "reminders": "reminder",
    "noshow": "noshow",
    "cancellation": "cancellation",
    "telehealth": "telehealth",
}


@dataclass
class NoteTypeCampaignConfig:
    """Per-note-type campaign configuration."""

    note_type_id: str = ""
    note_type_name: str = ""

    # Master gate. When False, no notifications fire for this visit type
    # regardless of per-campaign flags. Defaults to True so existing visit
    # types stay active under the new model.
    master_enabled: bool = True

    # Confirmation
    confirmation_enabled: bool | None = None
    confirmation_override: bool = False
    confirmation_sms_template: str = ""
    confirmation_email_template: str = ""
    confirmation_channels: list[str] = field(default_factory=list)

    # Reminders
    reminders_enabled: bool | None = None
    reminder_override: bool = False
    reminder_send_time: str = ""
    reminder_intervals: list[int] = field(default_factory=list)
    reminder_sms_template: str = ""
    reminder_email_template: str = ""
    reminder_channels: list[str] = field(default_factory=list)

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
    telehealth_intervals: list[int] = field(default_factory=list)
    telehealth_sms_template: str = ""
    telehealth_email_template: str = ""
    telehealth_channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {k: getattr(self, k) for k in _NOTE_TYPE_CAMPAIGN_FIELDS}

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

        # Migrate old activated field to per-campaign enabled values
        if "activated" in cleaned:
            if not cleaned["activated"]:
                for ek in (
                    "confirmation_enabled", "reminders_enabled", "noshow_enabled",
                    "cancellation_enabled", "telehealth_enabled",
                ):
                    cleaned[ek] = False
            cleaned.pop("activated")

        # Filter to known fields only
        filtered = {k: v for k, v in cleaned.items() if k in _NOTE_TYPE_CAMPAIGN_FIELDS}
        config = cls(**filtered)

        # Strip negative reminder intervals from old configs
        config.reminder_intervals = [i for i in config.reminder_intervals if i >= 0]

        return config


# Backward-compatible alias
NoteTypeReminderConfig = NoteTypeCampaignConfig


@dataclass
class CampaignConfig:
    """Campaign configuration for notifications."""

    # Timing controls for appointment reminders (send time and timezone)
    day_out_send_time: str = "09:00"
    day_out_timezone: str = "America/New_York"

    # Confirmation campaign
    confirmation_enabled: bool = True
    confirmation_sms_template: str = (
        "Hi {{patient_first_name}}, your appointment with {{provider_name}} at "
        "{{location_full_name}} is confirmed for {{appointment_date}} at {{appointment_time}}. "
        "Call {{location_phone}} to reschedule."
    )
    confirmation_email_template: str = (
        "Hi {{patient_first_name}}, your appointment with {{provider_name}} at "
        "{{location_full_name}} is confirmed for {{appointment_date}} at {{appointment_time}}.\n\n"
        "Call {{location_phone}} to reschedule."
    )
    confirmation_channels: list[str] = field(default_factory=lambda: ["sms", "email"])

    # Reminder campaign
    reminders_enabled: bool = True
    reminder_intervals: list[int] = field(default_factory=lambda: [10080, 1440])
    reminder_sms_template: str = (
        "Hi {{patient_first_name}}, this is a reminder about your appointment with "
        "{{provider_name}} at {{location_full_name}} on {{appointment_date}} at "
        "{{appointment_time}}. Call {{location_phone}} to reschedule."
    )
    reminder_email_template: str = (
        "Hi {{patient_first_name}}, this is a reminder about your appointment with "
        "{{provider_name}} at {{location_full_name}} on {{appointment_date}} at "
        "{{appointment_time}}.\n\n"
        "Call {{location_phone}} to reschedule."
    )
    reminder_channels: list[str] = field(default_factory=lambda: ["sms", "email"])

    # No-show campaign
    noshow_enabled: bool = True
    noshow_sms_template: str = (
        "We missed you today at {{location_full_name}}. Please call {{location_phone}} to "
        "reschedule your appointment with {{provider_name}}."
    )
    noshow_email_template: str = (
        "We missed you today at {{location_full_name}}.\n\n"
        "Please call {{location_phone}} to reschedule your appointment "
        "with {{provider_name}}."
    )
    noshow_channels: list[str] = field(default_factory=lambda: ["sms", "email"])

    # Cancellation campaign
    cancellation_enabled: bool = True
    cancellation_sms_template: str = (
        "Your appointment with {{provider_name}} on {{appointment_date}} at "
        "{{appointment_time}} has been cancelled. Call {{location_phone}} to rebook."
    )
    cancellation_email_template: str = (
        "Your appointment with {{provider_name}} on {{appointment_date}} at "
        "{{appointment_time}} has been cancelled.\n\n"
        "Call {{location_phone}} to rebook."
    )
    cancellation_channels: list[str] = field(default_factory=lambda: ["sms", "email"])

    # Telehealth campaign
    telehealth_enabled: bool = True
    telehealth_sms_template: str = (
        "Hi {{patient_first_name}}, your telehealth appointment with {{provider_name}} "
        "is in {{minutes_until}} minutes. Join here: {{telehealth_link}}"
    )
    telehealth_email_template: str = (
        "Hi {{patient_first_name}}, your telehealth appointment with {{provider_name}} "
        "is in {{minutes_until}} minutes.\n\n"
        "Join your telehealth visit: {{telehealth_link}}"
    )
    telehealth_channels: list[str] = field(default_factory=lambda: ["sms", "email"])
    telehealth_intervals: list[int] = field(default_factory=lambda: [60, 15])

    # Per-note-type campaign overrides (new format)
    note_type_campaigns: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Legacy per-note-type reminders (migrated into note_type_campaigns on load)
    note_type_reminders: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Custom template variables
    custom_variables: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "day_out_send_time": self.day_out_send_time,
            "day_out_timezone": self.day_out_timezone,
            "confirmation_enabled": self.confirmation_enabled,
            "confirmation_sms_template": self.confirmation_sms_template,
            "confirmation_email_template": self.confirmation_email_template,
            "confirmation_channels": self.confirmation_channels,
            "reminders_enabled": self.reminders_enabled,
            "reminder_intervals": self.reminder_intervals,
            "reminder_sms_template": self.reminder_sms_template,
            "reminder_email_template": self.reminder_email_template,
            "reminder_channels": self.reminder_channels,
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
            "note_type_campaigns": self.note_type_campaigns,
            "note_type_reminders": self.note_type_reminders,
            "custom_variables": self.custom_variables,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CampaignConfig":
        """Create from dictionary with backward compatibility."""
        cleaned = dict(data)

        if "note_type_reminders" not in cleaned:
            cleaned["note_type_reminders"] = {}
        if "note_type_campaigns" not in cleaned:
            cleaned["note_type_campaigns"] = {}
        if "custom_variables" not in cleaned:
            cleaned["custom_variables"] = {}

        # Migrate single-template keys from 0.2.x to dual template fields
        for single_key, (sms_key, email_key) in _SINGLE_TO_DUAL.items():
            if single_key in cleaned:
                single_val = cleaned.pop(single_key)
                if sms_key not in cleaned:
                    cleaned[sms_key] = single_val
                if email_key not in cleaned:
                    cleaned[email_key] = single_val

        # Remove stale keys from previous versions
        stale_keys = {
            "sender_staff_id", "sender_staff_display",
            "fallback_team_id", "fallback_team_display",
            "sender_staff_last_name", "fallback_team_name",
            "clinic_name", "clinic_phone",
        }
        for key in stale_keys:
            cleaned.pop(key, None)

        # Migrate note_type_reminders into note_type_campaigns when campaigns dict is empty
        if not cleaned["note_type_campaigns"] and cleaned["note_type_reminders"]:
            campaigns: dict[str, dict[str, Any]] = {}
            for nt_id, nt_data in cleaned["note_type_reminders"].items():
                campaigns[nt_id] = dict(nt_data)
            cleaned["note_type_campaigns"] = campaigns

        # Filter to known fields only
        filtered = {k: v for k, v in cleaned.items() if k in _CAMPAIGN_CONFIG_FIELDS}
        config = cls(**filtered)

        # Strip negative reminder intervals from old configs
        config.reminder_intervals = [i for i in config.reminder_intervals if i >= 0]

        return config


CACHE_KEY_CONFIG = "cr:config"
CACHE_TTL = 1209600  # 14 days in seconds


def load_config() -> CampaignConfig:
    """Load campaign configuration from cache."""
    cache = get_cache()
    data = cache.get(CACHE_KEY_CONFIG)
    if data is None:
        return CampaignConfig()
    return CampaignConfig.from_dict(json.loads(data))


def save_config(config: CampaignConfig) -> None:
    """Save campaign configuration to cache."""
    cache = get_cache()
    cache.set(CACHE_KEY_CONFIG, json.dumps(config.to_dict()), timeout_seconds=CACHE_TTL)


def patch_config(partial: dict[str, Any]) -> CampaignConfig:
    """Merge a partial update into the current config and save.

    Raises ValueError if any template field contains unsafe HTML.
    """
    unsafe_fields = []
    for key, value in partial.items():
        if key.endswith("_template") and isinstance(value, str):
            cleaned = sanitize_html(value)
            if cleaned != value:
                unsafe_fields.append(key.replace("_", " ").replace(" template", ""))
    nt_campaigns = partial.get("note_type_campaigns")
    if isinstance(nt_campaigns, dict):
        for nt_id, nt_data in nt_campaigns.items():
            if isinstance(nt_data, dict):
                for key, value in nt_data.items():
                    if key.endswith("_template") and isinstance(value, str):
                        cleaned = sanitize_html(value)
                        if cleaned != value:
                            unsafe_fields.append(key.replace("_", " ").replace(" template", ""))
    if unsafe_fields:
        raise ValueError(
            f"Unsafe HTML in templates: {', '.join(unsafe_fields)}. "
            "Only formatting tags (p, br, em, strong, b, i, u, a, ul, ol, li, h1-h6, span, div, blockquote, hr) "
            "and attributes (href, title, style, class) are allowed."
        )
    config = load_config()
    full = config.to_dict()

    # Deep-merge note_type_campaigns so a single-entry patch does not wipe
    # other visit type configs. All other top-level keys are scalars or lists
    # and can be replaced directly.
    if "note_type_campaigns" in partial:
        merged: dict[str, Any] = dict(full.get("note_type_campaigns") or {})
        for nt_id, nt_data in partial["note_type_campaigns"].items():
            existing_entry: dict[str, Any] = dict(merged.get(nt_id) or {})
            existing_entry.update(nt_data)
            merged[nt_id] = existing_entry
        full["note_type_campaigns"] = merged
        remaining = {k: v for k, v in partial.items() if k != "note_type_campaigns"}
        full.update(remaining)
    else:
        full.update(partial)

    updated = CampaignConfig.from_dict(full)
    save_config(updated)
    return updated


def get_effective_campaign_config(
    config: CampaignConfig, campaign_type: str, note_type_id: str | None
) -> tuple[bool, list[int], list[str], str, str, str]:
    """Return (enabled, intervals, channels, sms_template, email_template, send_time) for a campaign + note type.

    Resolution logic:
    - Visit types must have an entry in note_type_campaigns
    - Per-campaign enabled (bool|None) resolves None by inheriting the global enabled state
    - Per-campaign override replaces global templates, channels, and intervals
    - Missing visit types return disabled for all campaign types
    - send_time is only relevant for reminders. Empty string means use global default.
    """
    prefix = _CAMPAIGN_PREFIXES.get(campaign_type)
    if not prefix:
        return (False, [], [], "", "", "")

    has_intervals = campaign_type in ("reminders", "telehealth")
    global_send_time = config.day_out_send_time if campaign_type == "reminders" else ""

    # Gather global values
    global_channels: list[str] = getattr(config, f"{prefix}_channels")
    global_sms: str = getattr(config, f"{prefix}_sms_template")
    global_email: str = getattr(config, f"{prefix}_email_template")
    global_intervals = getattr(config, f"{prefix}_intervals") if has_intervals else []

    # Visit type must have a note_type_campaigns entry
    if not note_type_id:
        return (False, [], [], "", "", "")

    nt_cfg_data = config.note_type_campaigns.get(note_type_id)
    if nt_cfg_data is None:
        return (False, [], [], "", "", "")

    nt_cfg = NoteTypeCampaignConfig.from_dict(nt_cfg_data)

    # Master gate. If master is off for this visit type, no campaign fires
    # regardless of per-campaign flags or overrides.
    if not nt_cfg.master_enabled:
        return (False, [], [], "", "", "")

    # Resolve effective enabled state (None inherits from global)
    enabled_field = f"{prefix}_enabled" if prefix != "reminder" else "reminders_enabled"
    nt_enabled = getattr(nt_cfg, enabled_field)
    if nt_enabled is None:
        nt_enabled = getattr(config, enabled_field)
    if not nt_enabled:
        return (False, [], [], "", "", "")

    # Check for per-campaign override
    if getattr(nt_cfg, f"{prefix}_override", False):
        nt_channels = getattr(nt_cfg, f"{prefix}_channels")
        nt_sms = getattr(nt_cfg, f"{prefix}_sms_template")
        nt_email = getattr(nt_cfg, f"{prefix}_email_template")
        nt_intervals = getattr(nt_cfg, f"{prefix}_intervals") if has_intervals else []
        nt_send_time = nt_cfg.reminder_send_time if campaign_type == "reminders" else ""
        effective_send_time = nt_send_time if nt_send_time else global_send_time
        return (True, nt_intervals, nt_channels, nt_sms, nt_email, effective_send_time)

    # No override, use global defaults
    return (True, global_intervals, global_channels, global_sms, global_email, global_send_time)


def get_effective_reminder_config(
    config: CampaignConfig, note_type_id: str | None
) -> tuple[bool, list[int], list[str], str, str, str]:
    """Backward-compatible wrapper around get_effective_campaign_config for reminders."""
    return get_effective_campaign_config(config, "reminders", note_type_id)


def resolve_templates(
    config: CampaignConfig, campaign_type: str, note_type_id: str | None
) -> tuple[str, str]:
    """Return (sms_template, email_template) for a campaign and note type.

    Resolution order:
    1. Per-visit-type override templates (if override flag is set and templates are non-empty)
    2. Global campaign templates from CampaignConfig

    This function ignores enabled state. Templates are always available
    for preview and manual send regardless of whether automation is active.
    """
    prefix = _CAMPAIGN_PREFIXES.get(campaign_type)
    if not prefix:
        return ("", "")

    global_sms: str = getattr(config, f"{prefix}_sms_template")
    global_email: str = getattr(config, f"{prefix}_email_template")

    if not note_type_id:
        return (global_sms, global_email)

    nt_cfg_data = config.note_type_campaigns.get(note_type_id)
    if nt_cfg_data is None:
        return (global_sms, global_email)

    nt_cfg = NoteTypeCampaignConfig.from_dict(nt_cfg_data)

    if getattr(nt_cfg, f"{prefix}_override", False):
        nt_sms = getattr(nt_cfg, f"{prefix}_sms_template")
        nt_email = getattr(nt_cfg, f"{prefix}_email_template")
        return (nt_sms or global_sms, nt_email or global_email)

    return (global_sms, global_email)
