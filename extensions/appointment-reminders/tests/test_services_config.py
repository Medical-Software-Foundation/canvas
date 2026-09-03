"""Tests for services/config.py — campaign configuration dataclasses,
serialization, migrations, and effective-config resolution.

`load_config` and `save_config` touch the DB via `CampaignConfigRecord`, so
those are tested with `CampaignConfigRecord.objects` patched. Everything
else (`from_dict`/`to_dict`, single-template migration, stale-key cleanup,
`get_effective_campaign_config`) is pure-Python and runs without mocks.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from appointment_reminders.services.config import (
    CampaignConfig,
    NoteTypeCampaignConfig,
    NoteTypeReminderConfig,
    _LEGACY_CACHE_KEY_CONFIG,
    _migrate_from_cache,
    collect_templates,
    get_effective_campaign_config,
    get_effective_reminder_config,
    load_config,
    save_config,
    templates_locked,
)


# ---- NoteTypeCampaignConfig ----

def test_note_type_campaign_config_round_trip() -> None:
    """to_dict → from_dict round-trips faithfully."""
    cfg = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        note_type_name="Initial visit",
        confirmation_enabled=True,
        confirmation_override=True,
        confirmation_sms_template="custom sms",
        confirmation_email_template="custom email",
        confirmation_channels=["sms"],
        reminders_enabled=False,
        reminder_intervals=[1440, 60],
        telehealth_intervals=[15, 30],
    )
    rebuilt = NoteTypeCampaignConfig.from_dict(cfg.to_dict())
    assert rebuilt == cfg


def test_note_type_campaign_config_filters_unknown_keys() -> None:
    """Unknown keys are silently dropped — protects against future schema drift."""
    cfg = NoteTypeCampaignConfig.from_dict({
        "note_type_id": "nt-1",
        "ancient_field": "should be ignored",
        "future_field": 42,
    })
    assert cfg.note_type_id == "nt-1"
    assert not hasattr(cfg, "ancient_field")


def test_note_type_campaign_config_migrates_single_reminder_template() -> None:
    """A 0.2.x `reminder_template` should populate both sms and email fields."""
    cfg = NoteTypeCampaignConfig.from_dict({
        "note_type_id": "nt-1",
        "reminder_template": "shared template",
    })
    assert cfg.reminder_sms_template == "shared template"
    assert cfg.reminder_email_template == "shared template"


def test_note_type_campaign_config_single_reminder_template_does_not_overwrite_explicit() -> None:
    """If both reminder_template AND the dual fields are present, dual fields win."""
    cfg = NoteTypeCampaignConfig.from_dict({
        "note_type_id": "nt-1",
        "reminder_template": "old shared",
        "reminder_sms_template": "explicit sms",
    })
    assert cfg.reminder_sms_template == "explicit sms"
    # Email field still gets the old shared one because it wasn't explicitly set
    assert cfg.reminder_email_template == "old shared"


def test_note_type_reminder_config_alias() -> None:
    """`NoteTypeReminderConfig` is a backward-compat alias for `NoteTypeCampaignConfig`."""
    assert NoteTypeReminderConfig is NoteTypeCampaignConfig


# ---- CampaignConfig ----

def test_campaign_config_defaults_have_all_campaigns_disabled() -> None:
    """Out of the box, no campaigns send anything — ops must opt-in explicitly."""
    cfg = CampaignConfig()
    assert cfg.confirmation_enabled is False
    assert cfg.reminders_enabled is False
    assert cfg.noshow_enabled is False
    assert cfg.cancellation_enabled is False
    assert cfg.telehealth_enabled is False


def test_campaign_config_round_trip() -> None:
    cfg = CampaignConfig(
        confirmation_enabled=True,
        reminders_enabled=True,
        reminder_intervals=[10080, 1440],
        note_type_reminders={"nt-1": {"note_type_id": "nt-1", "confirmation_enabled": False}},
    )
    rebuilt = CampaignConfig.from_dict(cfg.to_dict())
    assert rebuilt == cfg


def test_campaign_config_from_dict_fills_in_missing_dicts() -> None:
    """An old payload missing the per-note-type maps gets defaulted to {}."""
    cfg = CampaignConfig.from_dict({"confirmation_enabled": True})
    assert cfg.note_type_reminders == {}


def test_campaign_config_migrates_single_to_dual_templates() -> None:
    """0.2.x single-template keys must populate both sms and email fields."""
    cfg = CampaignConfig.from_dict({
        "confirmation_template": "old shared confirmation",
        "reminder_template": "old shared reminder",
        "noshow_template": "old shared noshow",
        "cancellation_template": "old shared cancellation",
    })
    assert cfg.confirmation_sms_template == "old shared confirmation"
    assert cfg.confirmation_email_template == "old shared confirmation"
    assert cfg.reminder_sms_template == "old shared reminder"
    assert cfg.reminder_email_template == "old shared reminder"
    assert cfg.noshow_sms_template == "old shared noshow"
    assert cfg.cancellation_sms_template == "old shared cancellation"


def test_campaign_config_single_template_does_not_overwrite_explicit_dual() -> None:
    cfg = CampaignConfig.from_dict({
        "confirmation_template": "old shared",
        "confirmation_sms_template": "new sms",
    })
    assert cfg.confirmation_sms_template == "new sms"
    assert cfg.confirmation_email_template == "old shared"


def test_campaign_config_strips_stale_keys() -> None:
    """Stale keys from older versions must not blow up `from_dict`."""
    cfg = CampaignConfig.from_dict({
        "confirmation_enabled": True,
        "sender_staff_last_name": "Smith",
        "fallback_team_name": "X",
        "sender_staff_id": "s-1",
        "sender_staff_display": "Dr. X",
        "fallback_team_id": "t-1",
        "fallback_team_display": "T",
        "form_assignment_reminder_intervals": [60],
        "form_assignment_send_time": "09:00",
        "form_assignment_timezone": "America/New_York",
    })
    assert cfg.confirmation_enabled is True


def test_campaign_config_filters_unknown_keys() -> None:
    cfg = CampaignConfig.from_dict({
        "confirmation_enabled": True,
        "totally_unknown_key": "whatever",
    })
    assert cfg.confirmation_enabled is True
    assert not hasattr(cfg, "totally_unknown_key")


# ---- _migrate_from_cache ----

def test_migrate_from_cache_returns_none_when_empty() -> None:
    with patch("appointment_reminders.services.config.get_cache") as mock_cache:
        mock_cache.return_value.get.return_value = None
        assert _migrate_from_cache() is None
        mock_cache.return_value.get.assert_called_once_with(_LEGACY_CACHE_KEY_CONFIG)


def test_migrate_from_cache_parses_existing_legacy_payload() -> None:
    legacy = {"confirmation_enabled": True, "reminders_enabled": True}
    with patch("appointment_reminders.services.config.get_cache") as mock_cache:
        mock_cache.return_value.get.return_value = json.dumps(legacy)
        cfg = _migrate_from_cache()

    assert cfg is not None
    assert cfg.confirmation_enabled is True
    assert cfg.reminders_enabled is True


# ---- load_config / save_config ----

def test_load_config_returns_existing_record() -> None:
    record = MagicMock()
    record.data = {"confirmation_enabled": True}
    with patch(
        "appointment_reminders.services.config.CampaignConfigRecord"
    ) as mock_record_cls:
        mock_record_cls.objects.first.return_value = record
        cfg = load_config()
    assert cfg.confirmation_enabled is True


def test_load_config_migrates_from_cache_and_creates_record() -> None:
    """No record AND cache present: parse cache, write a record, return parsed config."""
    with patch(
        "appointment_reminders.services.config.CampaignConfigRecord"
    ) as mock_record_cls, patch(
        "appointment_reminders.services.config.get_cache"
    ) as mock_cache:
        mock_record_cls.objects.first.return_value = None
        mock_cache.return_value.get.return_value = json.dumps(
            {"reminders_enabled": True}
        )
        cfg = load_config()

    assert cfg.reminders_enabled is True
    mock_record_cls.objects.create.assert_called_once()


def test_load_config_returns_default_when_nothing_stored() -> None:
    with patch(
        "appointment_reminders.services.config.CampaignConfigRecord"
    ) as mock_record_cls, patch(
        "appointment_reminders.services.config.get_cache"
    ) as mock_cache:
        mock_record_cls.objects.first.return_value = None
        mock_cache.return_value.get.return_value = None
        cfg = load_config()
    assert cfg == CampaignConfig()


def test_save_config_creates_when_no_record() -> None:
    cfg = CampaignConfig(reminders_enabled=True)
    with patch(
        "appointment_reminders.services.config.CampaignConfigRecord"
    ) as mock_record_cls:
        mock_record_cls.objects.first.return_value = None
        save_config(cfg)
    mock_record_cls.objects.create.assert_called_once()
    kwargs = mock_record_cls.objects.create.call_args.kwargs
    assert kwargs["data"]["reminders_enabled"] is True


def test_save_config_updates_existing_record() -> None:
    record = MagicMock()
    record.data = {"reminders_enabled": False}
    cfg = CampaignConfig(reminders_enabled=True)
    with patch(
        "appointment_reminders.services.config.CampaignConfigRecord"
    ) as mock_record_cls:
        mock_record_cls.objects.first.return_value = record
        save_config(cfg)
    assert record.data["reminders_enabled"] is True
    record.save.assert_called_once()


# ---- get_effective_campaign_config ----

def test_get_effective_campaign_config_unknown_campaign_type_returns_disabled() -> None:
    cfg = CampaignConfig(confirmation_enabled=True)
    assert get_effective_campaign_config(cfg, None, "unknown") == (
        False, [], "", "", [], "", "",
    )


def test_get_effective_campaign_config_master_off_blocks_everything() -> None:
    cfg = CampaignConfig(confirmation_enabled=False)
    enabled, *_ = get_effective_campaign_config(cfg, "nt-1", "confirmation")
    assert enabled is False


def test_get_effective_campaign_config_global_when_no_note_type() -> None:
    cfg = CampaignConfig(
        reminders_enabled=True,
        reminder_channels=["sms"],
        reminder_intervals=[1440],
    )
    enabled, channels, sms, email, intervals, send_time, tz = (
        get_effective_campaign_config(cfg, None, "reminder")
    )
    assert enabled is True
    assert channels == ["sms"]
    assert intervals == [1440]


def test_get_effective_campaign_config_note_type_opt_out_returns_disabled() -> None:
    """Per-note-type *_enabled=False overrides the global enabled flag."""
    cfg = CampaignConfig(
        confirmation_enabled=True,
        note_type_reminders={
            "nt-1": {"note_type_id": "nt-1", "confirmation_enabled": False},
        },
    )
    enabled, *_ = get_effective_campaign_config(cfg, "nt-1", "confirmation")
    assert enabled is False


def test_get_effective_campaign_config_note_type_inherits_when_no_record() -> None:
    cfg = CampaignConfig(
        confirmation_enabled=True,
        confirmation_channels=["sms", "email"],
    )
    enabled, channels, *_ = get_effective_campaign_config(cfg, "nt-missing", "confirmation")
    assert enabled is True
    assert channels == ["sms", "email"]


def test_get_effective_campaign_config_note_type_refines_intervals_without_override_flag() -> None:
    """Intervals/send_time/timezone are structural — they apply even when override
    flag is not set (because they aren't 'template customization')."""
    cfg = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[10080, 1440],
        reminder_send_time="09:00",
        reminder_timezone="America/New_York",
        note_type_reminders={
            "nt-1": {
                "note_type_id": "nt-1",
                "reminder_intervals": [120],
                "reminder_send_time": "08:00",
                "reminder_timezone": "America/Chicago",
            },
        },
    )
    enabled, _channels, _sms, _email, intervals, send_time, tz = (
        get_effective_campaign_config(cfg, "nt-1", "reminder")
    )
    assert enabled is True
    assert intervals == [120]
    assert send_time == "08:00"
    assert tz == "America/Chicago"


def test_get_effective_campaign_config_note_type_override_replaces_templates() -> None:
    cfg = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="GLOBAL SMS",
        confirmation_email_template="GLOBAL EMAIL",
        confirmation_channels=["sms", "email"],
        note_type_reminders={
            "nt-1": {
                "note_type_id": "nt-1",
                "confirmation_override": True,
                "confirmation_sms_template": "PER-TYPE SMS",
                "confirmation_email_template": "PER-TYPE EMAIL",
                "confirmation_channels": ["email"],
            },
        },
    )
    _enabled, channels, sms, email, *_ = get_effective_campaign_config(
        cfg, "nt-1", "confirmation"
    )
    assert sms == "PER-TYPE SMS"
    assert email == "PER-TYPE EMAIL"
    assert channels == ["email"]


def test_get_effective_campaign_config_override_flag_without_values_keeps_global() -> None:
    """Override flag set but per-type values empty: fall back to globals."""
    cfg = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="GLOBAL SMS",
        confirmation_email_template="GLOBAL EMAIL",
        confirmation_channels=["sms"],
        note_type_reminders={
            "nt-1": {
                "note_type_id": "nt-1",
                "confirmation_override": True,
            },
        },
    )
    _enabled, channels, sms, email, *_ = get_effective_campaign_config(
        cfg, "nt-1", "confirmation"
    )
    assert sms == "GLOBAL SMS"
    assert email == "GLOBAL EMAIL"
    assert channels == ["sms"]


# ---- get_effective_reminder_config ----

def test_get_effective_reminder_config_returns_5_tuple() -> None:
    cfg = CampaignConfig(
        reminders_enabled=True,
        reminder_intervals=[60],
        reminder_channels=["sms"],
        reminder_sms_template="sms",
        reminder_email_template="email",
    )
    result = get_effective_reminder_config(cfg, None)
    assert result == (True, [60], ["sms"], "sms", "email")


def test_get_effective_reminder_config_disabled_returns_falsy_tuple() -> None:
    cfg = CampaignConfig(reminders_enabled=False)
    enabled, intervals, channels, sms, email = get_effective_reminder_config(cfg, "nt-1")
    assert enabled is False
    assert intervals == []
    assert channels == []


# ---- message-copy lock ----

def test_templates_locked_off_by_default() -> None:
    """A fresh install with no secret set stays editable."""
    assert templates_locked(None) is False
    assert templates_locked({}) is False
    assert templates_locked({"LOCK_MESSAGE_TEMPLATES": ""}) is False


def test_templates_locked_accepts_truthy_spellings() -> None:
    for raw in ("1", "true", "TRUE", "yes", "on", "  true  "):
        assert templates_locked({"LOCK_MESSAGE_TEMPLATES": raw}) is True, raw


def test_templates_locked_rejects_other_values() -> None:
    """Anything unrecognized leaves copy editable rather than silently locking."""
    for raw in ("0", "false", "no", "off", "locked", "maybe"):
        assert templates_locked({"LOCK_MESSAGE_TEMPLATES": raw}) is False, raw


def test_collect_templates_covers_all_three_scopes() -> None:
    cfg = CampaignConfig(
        confirmation_sms_template="global sms",
        note_type_reminders={"nt-1": {"reminder_email_template": "per-type email"}},
        business_line_overrides={"Northwind Health": {"noshow_sms_template": "per-line sms"}},
    )
    found = collect_templates(cfg)
    assert found["confirmation_sms_template"] == "global sms"
    assert found["note_type:nt-1:reminder_email_template"] == "per-type email"
    assert found["business_line:Northwind Health:noshow_sms_template"] == "per-line sms"


def test_collect_templates_ignores_non_template_fields() -> None:
    """Attribution and from-number live alongside copy but aren't locked."""
    cfg = CampaignConfig(
        default_attribution="Acme",
        business_line_overrides={"Northwind Health": {"attribution": "Acme", "from_number": "+15551234567"}},
    )
    found = collect_templates(cfg)
    assert not any("attribution" in key or "from_number" in key for key in found)










# ---- testing mode (moved out of plugin secrets into admin-editable config) ----

def test_testing_mode_round_trips_through_to_dict() -> None:
    config = CampaignConfig(
        testing_mode=True,
        testing_mode_patients=["pat-1", "pat-2"],
        testing_mode_recipients=["+14155551234", "me@example.com"],
    )
    restored = CampaignConfig.from_dict(config.to_dict())
    assert restored.testing_mode is True
    assert restored.testing_mode_patients == ["pat-1", "pat-2"]
    assert restored.testing_mode_recipients == ["+14155551234", "me@example.com"]


def test_testing_mode_defaults_on_for_a_config_row_that_predates_it() -> None:
    """The upgrade path that matters.

    An instance whose stored config was written before this setting existed
    must land with the gate shut. Defaulting off would silently start texting
    every patient the moment the TESTING_MODE secret stopped being read.
    """
    restored = CampaignConfig.from_dict({"reminders_enabled": True})
    assert restored.testing_mode is True
    assert restored.testing_mode_patients == []


def test_testing_mode_allowlists_accept_text() -> None:
    """The admin textareas post newlines; operators paste commas."""
    restored = CampaignConfig.from_dict({
        "testing_mode_patients": "pat-1, pat-2 ,,",
        "testing_mode_recipients": "+14155551234\nme@example.com\n",
    })
    assert restored.testing_mode_patients == ["pat-1", "pat-2"]
    assert restored.testing_mode_recipients == ["+14155551234", "me@example.com"]


def test_testing_mode_allowlists_tolerate_junk() -> None:
    restored = CampaignConfig.from_dict({
        "testing_mode_patients": None,
        "testing_mode_recipients": 42,
    })
    assert restored.testing_mode_patients == []
    assert restored.testing_mode_recipients == []


def test_decline_task_team_round_trips() -> None:
    restored = CampaignConfig.from_dict(
        CampaignConfig(decline_task_team_id="team-7").to_dict()
    )
    assert restored.decline_task_team_id == "team-7"


def test_decline_task_team_defaults_to_unassigned() -> None:
    """Matches what the plugin did before this was configurable."""
    assert CampaignConfig().decline_task_team_id == ""
    assert CampaignConfig.from_dict({"reminders_enabled": True}).decline_task_team_id == ""


def test_decline_task_due_defaults_to_no_due_date() -> None:
    """Absent means undated, so an existing install is unchanged."""
    assert CampaignConfig().decline_task_due_days is None
    assert CampaignConfig.from_dict({}).decline_task_due_days is None
    assert CampaignConfig().decline_task_due_time == "23:59"


def test_decline_task_due_rule_round_trips() -> None:
    restored = CampaignConfig.from_dict(
        CampaignConfig(decline_task_due_days=2, decline_task_due_time="09:00").to_dict()
    )
    assert restored.decline_task_due_days == 2
    assert restored.decline_task_due_time == "09:00"


def test_decline_task_due_migrates_the_0_12_0_boolean() -> None:
    """That flag meant "end of the day the patient replied" — 0 days at 23:59."""
    restored = CampaignConfig.from_dict({"decline_task_due_end_of_day": True})
    assert restored.decline_task_due_days == 0
    assert restored.decline_task_due_time == "23:59"

    off = CampaignConfig.from_dict({"decline_task_due_end_of_day": False})
    assert off.decline_task_due_days is None

    # An explicit new-style value wins over the legacy flag.
    both = CampaignConfig.from_dict(
        {"decline_task_due_end_of_day": True, "decline_task_due_days": 3}
    )
    assert both.decline_task_due_days == 3


def test_decline_task_due_days_coerces_and_fails_to_undated() -> None:
    """A malformed offset must not silently start dating every task."""
    for raw, expected in (
        ("2", 2), (0, 0), ("0", 0), (-5, 0),
        ("", None), (None, None), ("abc", None), ({}, None),
    ):
        got = CampaignConfig.from_dict({"decline_task_due_days": raw}).decline_task_due_days
        assert got == expected, f"{raw!r} -> {got!r}, expected {expected!r}"


def test_parse_hhmm_falls_back_rather_than_raising() -> None:
    from appointment_reminders.services.config import parse_hhmm

    assert parse_hhmm("09:30", (23, 59)) == (9, 30)
    assert parse_hhmm("", (23, 59)) == (23, 59)
    assert parse_hhmm("9", (23, 59)) == (23, 59)       # no colon
    assert parse_hhmm("abc", (23, 59)) == (23, 59)
    assert parse_hhmm("25:00", (23, 59)) == (23, 59)   # out of range
    assert parse_hhmm("09:99", (23, 59)) == (23, 59)
