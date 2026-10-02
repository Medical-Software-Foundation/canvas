"""Tests for campaign configuration service."""
import json

from pytest_mock import MockerFixture

from patient_notify.services.config import (
    CACHE_KEY_CONFIG,
    CACHE_TTL,
    CampaignConfig,
    NoteTypeCampaignConfig,
    NoteTypeReminderConfig,
    get_effective_campaign_config,
    get_effective_reminder_config,
    load_config,
    resolve_templates,
    save_config,
)


def test_campaign_config_defaults() -> None:
    """Test CampaignConfig has expected defaults."""
    config = CampaignConfig()

    assert config.day_out_send_time == "09:00"
    assert config.day_out_timezone == "America/New_York"
    assert config.confirmation_enabled is True
    assert config.reminders_enabled is True
    assert config.noshow_enabled is True
    assert config.cancellation_enabled is True
    assert config.telehealth_enabled is True
    assert config.reminder_intervals == [10080, 1440]
    assert config.telehealth_intervals == [60, 15]
    assert config.confirmation_channels == ["sms", "email"]
    assert config.reminder_channels == ["sms", "email"]
    assert config.noshow_channels == ["sms", "email"]
    assert config.cancellation_channels == ["sms", "email"]
    assert config.telehealth_channels == ["sms", "email"]
    assert config.note_type_campaigns == {}
    assert config.custom_variables == {}


def test_campaign_config_defaults_include_reminder_templates() -> None:
    """Test default config includes global reminder templates."""
    config = CampaignConfig()

    assert "{{patient_first_name}}" in config.reminder_sms_template
    assert "{{location_full_name}}" in config.reminder_sms_template
    assert "{{patient_first_name}}" in config.reminder_email_template


def test_campaign_config_defaults_use_location_variables() -> None:
    """Test default templates reference location variables instead of clinic variables."""
    config = CampaignConfig()

    assert "{{location_full_name}}" in config.confirmation_sms_template
    assert "{{location_phone}}" in config.confirmation_sms_template
    assert "{{location_full_name}}" in config.noshow_sms_template
    assert "{{location_phone}}" in config.cancellation_sms_template
    assert "clinic_name" not in config.confirmation_sms_template
    assert "clinic_phone" not in config.confirmation_sms_template


def test_campaign_config_to_dict() -> None:
    """Test CampaignConfig serialization includes all fields."""
    config = CampaignConfig()
    data = config.to_dict()

    assert "day_out_send_time" in data
    assert "day_out_timezone" in data
    assert "confirmation_enabled" in data
    assert "reminder_intervals" in data
    assert "reminder_sms_template" in data
    assert "reminder_email_template" in data
    assert "reminder_channels" in data
    assert "confirmation_sms_template" in data
    assert "confirmation_email_template" in data
    assert "confirmation_channels" in data
    assert "noshow_sms_template" in data
    assert "noshow_email_template" in data
    assert "cancellation_sms_template" in data
    assert "cancellation_email_template" in data
    assert "telehealth_enabled" in data
    assert "telehealth_sms_template" in data
    assert "telehealth_email_template" in data
    assert "telehealth_channels" in data
    assert "telehealth_intervals" in data
    assert "note_type_campaigns" in data
    assert "note_type_reminders" in data
    assert "custom_variables" in data


def test_campaign_config_from_dict() -> None:
    """Test CampaignConfig deserialization."""
    data = {"confirmation_enabled": False, "telehealth_enabled": True}
    config = CampaignConfig.from_dict(data)

    assert config.confirmation_enabled is False
    assert config.telehealth_enabled is True


def test_campaign_config_from_dict_strips_clinic_fields() -> None:
    """Test from_dict strips stale clinic_name and clinic_phone fields."""
    data = {
        "clinic_name": "Old Clinic",
        "clinic_phone": "555-1234",
        "confirmation_enabled": True,
    }
    config = CampaignConfig.from_dict(data)

    assert config.confirmation_enabled is True
    assert not hasattr(config, "clinic_name")


def test_campaign_config_from_dict_backward_compat_single_template() -> None:
    """Test from_dict migrates 0.2.x single-template keys to dual templates."""
    data = {"confirmation_template": "single content"}
    config = CampaignConfig.from_dict(data)

    assert config.confirmation_sms_template == "single content"
    assert config.confirmation_email_template == "single content"


def test_campaign_config_from_dict_strips_old_sender_fields() -> None:
    """Test from_dict drops old sender/fallback fields."""
    data = {
        "sender_staff_id": "old-staff",
        "sender_staff_display": "Dr. Old",
        "fallback_team_id": "old-team",
        "fallback_team_display": "Old Team",
        "sender_staff_last_name": "Smith",
        "fallback_team_name": "Front Desk",
    }
    config = CampaignConfig.from_dict(data)

    assert not hasattr(config, "sender_staff_id") or config.day_out_send_time == "09:00"


def test_campaign_config_from_dict_backward_compat_no_note_types() -> None:
    """Test from_dict works without note_type_reminders or note_type_campaigns keys."""
    data = {"confirmation_enabled": True}
    config = CampaignConfig.from_dict(data)

    assert config.note_type_reminders == {}
    assert config.note_type_campaigns == {}


def test_campaign_config_from_dict_filters_unknown_keys() -> None:
    """Test from_dict ignores unknown keys."""
    data = {
        "confirmation_enabled": True,
        "bogus_field": "should be dropped",
        "another_unknown": 42,
    }
    config = CampaignConfig.from_dict(data)

    assert config.confirmation_enabled is True


def test_campaign_config_from_dict_single_template_does_not_overwrite_dual() -> None:
    """Test single-template migration skips when dual fields already exist."""
    data = {
        "confirmation_template": "single",
        "confirmation_sms_template": "explicit sms",
        "confirmation_email_template": "explicit email",
    }
    config = CampaignConfig.from_dict(data)

    assert config.confirmation_sms_template == "explicit sms"
    assert config.confirmation_email_template == "explicit email"


def test_campaign_config_from_dict_migrates_note_type_reminders() -> None:
    """Test from_dict migrates note_type_reminders into note_type_campaigns when campaigns is empty."""
    nt_data = {
        "note_type_id": "nt-1",
        "reminders_enabled": True,
        "reminder_intervals": [120],
        "reminder_sms_template": "test",
        "reminder_email_template": "<p>test</p>",
    }
    data = {"note_type_reminders": {"nt-1": nt_data}}
    config = CampaignConfig.from_dict(data)

    assert "nt-1" in config.note_type_campaigns
    assert config.note_type_campaigns["nt-1"]["reminders_enabled"] is True


def test_campaign_config_from_dict_skips_migration_when_campaigns_exist() -> None:
    """Test from_dict does not overwrite note_type_campaigns with note_type_reminders."""
    campaign_data = {"note_type_id": "nt-1", "confirmation_enabled": True}
    reminder_data = {"note_type_id": "nt-1", "reminders_enabled": True}
    data = {
        "note_type_campaigns": {"nt-1": campaign_data},
        "note_type_reminders": {"nt-1": reminder_data},
    }
    config = CampaignConfig.from_dict(data)

    assert config.note_type_campaigns["nt-1"].get("confirmation_enabled") is True
    assert "reminders_enabled" not in config.note_type_campaigns["nt-1"]


def test_load_config_default(mocker: MockerFixture) -> None:
    """Test loading config returns defaults when cache is empty."""
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = None
    mocker.patch("patient_notify.services.config.get_cache", return_value=mock_cache)

    config = load_config()

    assert isinstance(config, CampaignConfig)
    mock_cache.get.assert_called_once_with(CACHE_KEY_CONFIG)


def test_load_config_from_cache(mocker: MockerFixture) -> None:
    """Test loading config from cache."""
    mock_cache = mocker.Mock()
    cached_data = json.dumps({"confirmation_enabled": True, "telehealth_enabled": True})
    mock_cache.get.return_value = cached_data
    mocker.patch("patient_notify.services.config.get_cache", return_value=mock_cache)

    config = load_config()

    assert config.confirmation_enabled is True
    assert config.telehealth_enabled is True


def test_save_config(mocker: MockerFixture) -> None:
    """Test saving config to cache."""
    mock_cache = mocker.Mock()
    mocker.patch("patient_notify.services.config.get_cache", return_value=mock_cache)

    config = CampaignConfig(confirmation_enabled=True, custom_variables={"org": "Acme"})
    save_config(config)

    mock_cache.set.assert_called_once()
    call_args = mock_cache.set.call_args
    assert call_args[0][0] == CACHE_KEY_CONFIG
    assert call_args[1]["timeout_seconds"] == CACHE_TTL

    saved_data = json.loads(call_args[0][1])
    assert saved_data["confirmation_enabled"] is True
    assert saved_data["custom_variables"] == {"org": "Acme"}


def test_note_type_campaign_config_defaults() -> None:
    """Test NoteTypeCampaignConfig has expected defaults."""
    cfg = NoteTypeCampaignConfig()
    assert cfg.note_type_id == ""
    assert cfg.confirmation_enabled is None
    assert cfg.reminders_enabled is None
    assert cfg.noshow_enabled is None
    assert cfg.cancellation_enabled is None
    assert cfg.telehealth_enabled is None
    assert cfg.reminder_intervals == []
    assert cfg.reminder_sms_template == ""
    assert cfg.reminder_email_template == ""
    assert cfg.reminder_channels == []
    assert cfg.confirmation_override is False
    assert cfg.telehealth_override is False


def test_note_type_campaign_config_round_trip() -> None:
    """Test NoteTypeCampaignConfig to_dict/from_dict round-trip."""
    cfg = NoteTypeCampaignConfig(
        note_type_id="abc-123",
        note_type_name="Telehealth",
        reminders_enabled=False,
        reminder_override=True,
        reminder_intervals=[4320],
        reminder_sms_template="sms msg",
        reminder_email_template="<p>email msg</p>",
        reminder_channels=["sms"],
        confirmation_enabled=True,
        confirmation_override=True,
        confirmation_sms_template="confirm sms",
        confirmation_email_template="<p>confirm</p>",
        telehealth_enabled=True,
        telehealth_override=False,
        telehealth_intervals=[30],
    )
    data = cfg.to_dict()
    restored = NoteTypeCampaignConfig.from_dict(data)
    assert restored.note_type_id == "abc-123"
    assert restored.note_type_name == "Telehealth"
    assert restored.reminders_enabled is False
    assert restored.reminder_override is True
    assert restored.reminder_intervals == [4320]
    assert restored.reminder_sms_template == "sms msg"
    assert restored.reminder_email_template == "<p>email msg</p>"
    assert restored.reminder_channels == ["sms"]
    assert restored.confirmation_enabled is True
    assert restored.confirmation_override is True
    assert restored.telehealth_enabled is True
    assert restored.telehealth_intervals == [30]


def test_note_type_reminder_config_alias() -> None:
    """Test NoteTypeReminderConfig is an alias for NoteTypeCampaignConfig."""
    assert NoteTypeReminderConfig is NoteTypeCampaignConfig


def test_note_type_from_dict_backward_compat_single_template() -> None:
    """Test NoteTypeCampaignConfig.from_dict migrates 0.2.x single reminder_template."""
    data = {
        "note_type_id": "nt-1",
        "reminders_enabled": True,
        "reminder_intervals": [120],
        "reminder_template": "old single template",
    }
    cfg = NoteTypeCampaignConfig.from_dict(data)

    assert cfg.reminder_sms_template == "old single template"
    assert cfg.reminder_email_template == "old single template"
    assert cfg.reminders_enabled is True


def test_note_type_from_dict_activated_false_migration() -> None:
    """Test from_dict migrates activated=False by setting all enabled fields to False."""
    data = {"note_type_id": "nt-1", "activated": False, "reminders_enabled": True}
    cfg = NoteTypeCampaignConfig.from_dict(data)
    assert cfg.confirmation_enabled is False
    assert cfg.reminders_enabled is False
    assert cfg.noshow_enabled is False
    assert cfg.cancellation_enabled is False
    assert cfg.telehealth_enabled is False


def test_note_type_from_dict_activated_true_migration() -> None:
    """Test from_dict migrates activated=True by preserving existing enabled values."""
    data = {"note_type_id": "nt-1", "activated": True, "reminders_enabled": True}
    cfg = NoteTypeCampaignConfig.from_dict(data)
    assert cfg.reminders_enabled is True
    assert cfg.confirmation_enabled is None


def test_campaign_config_with_note_type_campaigns() -> None:
    """Test CampaignConfig serialization includes note_type_campaigns."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        note_type_name="Annual",
        reminder_intervals=[20160],
        confirmation_enabled=True,
    ).to_dict()
    config = CampaignConfig(note_type_campaigns={"nt-1": nt_data})
    data = config.to_dict()

    assert "note_type_campaigns" in data
    assert "nt-1" in data["note_type_campaigns"]
    assert data["note_type_campaigns"]["nt-1"]["reminder_intervals"] == [20160]
    assert data["note_type_campaigns"]["nt-1"]["confirmation_enabled"] is True


def test_campaign_config_custom_variables_round_trip() -> None:
    """Test custom_variables survive to_dict/from_dict."""
    config = CampaignConfig(custom_variables={"office_hours": "9am-5pm", "website": "example.com"})
    data = config.to_dict()
    restored = CampaignConfig.from_dict(data)

    assert restored.custom_variables == {"office_hours": "9am-5pm", "website": "example.com"}


# get_effective_campaign_config tests (activation model)

def test_effective_config_null_note_type() -> None:
    """Test disabled when note_type_id is None."""
    config = CampaignConfig()
    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "reminders", None
    )

    assert enabled is False
    assert intervals == []
    assert channels == []
    assert sms_tpl == ""
    assert email_tpl == ""


def test_effective_config_unconfigured_note_type_global_disabled() -> None:
    """Test disabled for unconfigured note type when global campaign is disabled."""
    config = CampaignConfig(reminders_enabled=False)
    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "reminders", "unknown-type-id"
    )

    assert enabled is False
    assert intervals == []


def test_effective_config_unconfigured_note_type_global_enabled_stays_off() -> None:
    """A note_type with no note_type_campaigns entry must stay disabled even when the global flag is on. Visit types are off by default."""
    config = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="global sms",
        confirmation_email_template="<p>global</p>",
        confirmation_channels=["sms", "email"],
        note_type_campaigns={},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "unknown-type-id"
    )

    assert enabled is False
    assert intervals == []
    assert channels == []
    assert sms_tpl == ""
    assert email_tpl == ""


def test_effective_config_explicit_false_disables() -> None:
    """Test disabled when visit type has explicit enabled=False for a campaign."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        confirmation_enabled=False,
    ).to_dict()
    config = CampaignConfig(
        confirmation_enabled=True,
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "nt-1"
    )
    assert enabled is False


def test_effective_config_none_enabled_inherits_global() -> None:
    """Test visit type with None enabled inherits global defaults."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
    ).to_dict()
    config = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="global sms",
        confirmation_email_template="<p>global</p>",
        confirmation_channels=["email"],
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "nt-1"
    )

    assert enabled is True
    assert intervals == []
    assert channels == ["email"]
    assert sms_tpl == "global sms"
    assert email_tpl == "<p>global</p>"


def test_effective_config_reminders_inherits_global() -> None:
    """Test visit type uses global reminder templates and intervals when enabled is None."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
    ).to_dict()
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global reminder sms",
        reminder_email_template="<p>global reminder</p>",
        reminder_channels=["sms"],
        reminder_intervals=[10080, 1440],
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "reminders", "nt-1"
    )

    assert enabled is True
    assert intervals == [10080, 1440]
    assert channels == ["sms"]
    assert sms_tpl == "global reminder sms"
    assert email_tpl == "<p>global reminder</p>"


def test_effective_config_per_type_override_true() -> None:
    """Test per-type override=True uses per-type templates and channels."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        confirmation_enabled=True,
        confirmation_override=True,
        confirmation_sms_template="custom sms",
        confirmation_email_template="<p>custom</p>",
        confirmation_channels=["sms"],
    ).to_dict()
    config = CampaignConfig(
        confirmation_sms_template="global sms",
        confirmation_email_template="<p>global</p>",
        confirmation_channels=["sms", "email"],
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "nt-1"
    )

    assert enabled is True
    assert channels == ["sms"]
    assert sms_tpl == "custom sms"
    assert email_tpl == "<p>custom</p>"


def test_effective_config_per_type_override_false_uses_global() -> None:
    """Test per-type without override uses global templates."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        confirmation_enabled=True,
        confirmation_override=False,
    ).to_dict()
    config = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="global sms",
        confirmation_email_template="<p>global</p>",
        confirmation_channels=["sms", "email"],
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "nt-1"
    )

    assert enabled is True
    assert channels == ["sms", "email"]
    assert sms_tpl == "global sms"


def test_effective_config_telehealth_inherits_global() -> None:
    """Test telehealth uses global config when enabled is None and global is enabled."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-tele",
    ).to_dict()
    config = CampaignConfig(
        telehealth_enabled=True,
        telehealth_sms_template="global telehealth sms",
        telehealth_email_template="<p>global telehealth</p>",
        telehealth_channels=["sms"],
        telehealth_intervals=[60, 15],
        note_type_campaigns={"nt-tele": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "telehealth", "nt-tele"
    )

    assert enabled is True
    assert intervals == [60, 15]
    assert channels == ["sms"]
    assert sms_tpl == "global telehealth sms"


def test_effective_config_telehealth_per_type_override() -> None:
    """Test telehealth per-type override uses per-type values."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-tele",
        telehealth_enabled=True,
        telehealth_override=True,
        telehealth_intervals=[30],
        telehealth_sms_template="custom tele sms",
        telehealth_email_template="<p>custom tele</p>",
        telehealth_channels=["sms"],
    ).to_dict()
    config = CampaignConfig(
        telehealth_intervals=[60, 15],
        note_type_campaigns={"nt-tele": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "telehealth", "nt-tele"
    )

    assert enabled is True
    assert intervals == [30]
    assert channels == ["sms"]
    assert sms_tpl == "custom tele sms"


def test_effective_config_unconfigured_confirmation_global_disabled() -> None:
    """Test confirmation returns disabled for visit types without entry when global is disabled."""
    config = CampaignConfig(
        confirmation_enabled=False,
        confirmation_sms_template="global sms",
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "unconfigured-nt"
    )

    assert enabled is False


def test_effective_config_unknown_campaign_type() -> None:
    """Test unknown campaign type returns disabled."""
    config = CampaignConfig()
    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "bogus", None
    )

    assert enabled is False
    assert intervals == []


def test_effective_reminder_config_wrapper() -> None:
    """Test get_effective_reminder_config delegates to get_effective_campaign_config."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        reminders_enabled=True,
        reminder_override=True,
        reminder_intervals=[4320],
        reminder_sms_template="sms msg",
        reminder_email_template="<p>email msg</p>",
        reminder_channels=["sms"],
    ).to_dict()
    config = CampaignConfig(note_type_campaigns={"nt-1": nt_data})

    result = get_effective_reminder_config(config, "nt-1")
    expected = get_effective_campaign_config(config, "reminders", "nt-1")

    assert result == expected


def test_campaign_config_timing_fields_round_trip() -> None:
    """Test day_out_send_time and day_out_timezone survive to_dict/from_dict."""
    config = CampaignConfig(
        day_out_send_time="10:30",
        day_out_timezone="America/Chicago",
    )
    data = config.to_dict()
    restored = CampaignConfig.from_dict(data)

    assert restored.day_out_send_time == "10:30"
    assert restored.day_out_timezone == "America/Chicago"


def test_campaign_config_channels_round_trip() -> None:
    """Test channel lists survive to_dict/from_dict."""
    config = CampaignConfig(
        confirmation_channels=["sms"],
        reminder_channels=["email"],
        noshow_channels=["email"],
        cancellation_channels=["sms", "email"],
        telehealth_channels=["sms"],
    )
    data = config.to_dict()
    restored = CampaignConfig.from_dict(data)

    assert restored.confirmation_channels == ["sms"]
    assert restored.reminder_channels == ["email"]
    assert restored.noshow_channels == ["email"]
    assert restored.cancellation_channels == ["sms", "email"]
    assert restored.telehealth_channels == ["sms"]


def test_campaign_config_reminder_templates_round_trip() -> None:
    """Test global reminder templates survive to_dict/from_dict."""
    config = CampaignConfig(
        reminder_sms_template="custom reminder sms",
        reminder_email_template="<p>custom reminder</p>",
    )
    data = config.to_dict()
    restored = CampaignConfig.from_dict(data)

    assert restored.reminder_sms_template == "custom reminder sms"
    assert restored.reminder_email_template == "<p>custom reminder</p>"


def test_patch_config_merges_and_saves(mocker: MockerFixture) -> None:
    """Test patch_config loads current config, merges partial update, and saves."""
    from patient_notify.services.config import patch_config

    existing = CampaignConfig(confirmation_enabled=False)
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = json.dumps(existing.to_dict())
    mocker.patch("patient_notify.services.config.get_cache", return_value=mock_cache)

    result = patch_config({"confirmation_enabled": True})

    assert result.confirmation_enabled is True
    mock_cache.set.assert_called_once()


def test_campaign_config_from_dict_filters_negative_reminder_intervals() -> None:
    """Test from_dict strips negative reminder intervals but keeps 0 and positive."""
    data = {"reminder_intervals": [10080, 1440, 0, -60]}
    config = CampaignConfig.from_dict(data)

    assert config.reminder_intervals == [10080, 1440, 0]


def test_note_type_config_from_dict_filters_negative_reminder_intervals() -> None:
    """Test NoteTypeCampaignConfig.from_dict strips negative reminder intervals."""
    data = {
        "note_type_id": "nt-1",
        "reminder_intervals": [4320, 0, -30],
    }
    cfg = NoteTypeCampaignConfig.from_dict(data)

    assert cfg.reminder_intervals == [4320, 0]


def test_effective_config_missing_entry_global_enabled_stays_disabled() -> None:
    """A visit type with no note_type_campaigns entry stays disabled even when the global flag is on. Spec rule, visit types are off until activated."""
    config = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="global confirm sms",
        confirmation_email_template="<p>global confirm</p>",
        confirmation_channels=["sms", "email"],
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "no-entry-nt"
    )

    assert enabled is False
    assert intervals == []
    assert channels == []
    assert sms_tpl == ""
    assert email_tpl == ""


def test_effective_config_missing_entry_global_disabled_returns_disabled() -> None:
    """Test visit type with no note_type_campaigns entry returns disabled when global is disabled."""
    config = CampaignConfig(
        confirmation_enabled=False,
        confirmation_sms_template="global confirm sms",
        confirmation_email_template="<p>global confirm</p>",
        confirmation_channels=["sms", "email"],
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "no-entry-nt"
    )

    assert enabled is False
    assert intervals == []
    assert channels == []
    assert sms_tpl == ""
    assert email_tpl == ""


def test_effective_config_missing_entry_reminders_global_enabled_stays_disabled() -> None:
    """Reminders for a note type with no note_type_campaigns entry stay disabled even when the global flag is on. Spec rule, visit types are off until activated."""
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global reminder sms",
        reminder_email_template="<p>global reminder</p>",
        reminder_channels=["sms"],
        reminder_intervals=[10080, 1440],
        day_out_send_time="10:00",
    )

    enabled, intervals, channels, sms_tpl, email_tpl, send_time = get_effective_campaign_config(
        config, "reminders", "no-entry-nt"
    )

    assert enabled is False
    assert intervals == []
    assert channels == []
    assert sms_tpl == ""
    assert email_tpl == ""
    assert send_time == ""


def test_resolve_templates_returns_global_defaults() -> None:
    """Test resolve_templates returns global templates when no visit type override."""
    config = CampaignConfig()
    sms, email = resolve_templates(config, "confirmation", None)
    assert "confirmed" in sms.lower()
    assert "confirmed" in email.lower()


def test_resolve_templates_unknown_campaign() -> None:
    """Test resolve_templates returns empty strings for unknown campaign type."""
    config = CampaignConfig()
    sms, email = resolve_templates(config, "nonexistent", "nt-1")
    assert sms == ""
    assert email == ""


def test_resolve_templates_note_type_without_override() -> None:
    """Test resolve_templates returns global templates when visit type has no override."""
    config = CampaignConfig(
        confirmation_sms_template="Global SMS",
        confirmation_email_template="Global Email",
        note_type_campaigns={
            "nt-1": NoteTypeCampaignConfig(
                confirmation_override=False,
                confirmation_sms_template="Override SMS",
                confirmation_email_template="Override Email",
            ).to_dict(),
        },
    )
    sms, email = resolve_templates(config, "confirmation", "nt-1")
    assert sms == "Global SMS"
    assert email == "Global Email"


def test_resolve_templates_note_type_with_override() -> None:
    """Test resolve_templates returns override templates when visit type has override."""
    config = CampaignConfig(
        confirmation_sms_template="Global SMS",
        confirmation_email_template="Global Email",
        note_type_campaigns={
            "nt-1": NoteTypeCampaignConfig(
                confirmation_override=True,
                confirmation_sms_template="Override SMS",
                confirmation_email_template="Override Email",
            ).to_dict(),
        },
    )
    sms, email = resolve_templates(config, "confirmation", "nt-1")
    assert sms == "Override SMS"
    assert email == "Override Email"


def test_resolve_templates_override_with_empty_falls_back() -> None:
    """Test resolve_templates falls back to global when override templates are empty."""
    config = CampaignConfig(
        confirmation_sms_template="Global SMS",
        confirmation_email_template="Global Email",
        note_type_campaigns={
            "nt-1": NoteTypeCampaignConfig(
                confirmation_override=True,
                confirmation_sms_template="",
                confirmation_email_template="",
            ).to_dict(),
        },
    )
    sms, email = resolve_templates(config, "confirmation", "nt-1")
    assert sms == "Global SMS"
    assert email == "Global Email"


def test_resolve_templates_no_note_type_entry() -> None:
    """Test resolve_templates returns global templates when note type has no config entry."""
    config = CampaignConfig(
        confirmation_sms_template="Global SMS",
        confirmation_email_template="Global Email",
    )
    sms, email = resolve_templates(config, "confirmation", "unknown-nt")
    assert sms == "Global SMS"
    assert email == "Global Email"


def test_resolve_templates_ignores_enabled_state() -> None:
    """Test resolve_templates returns templates even when campaign is disabled."""
    config = CampaignConfig(
        confirmation_enabled=False,
        confirmation_sms_template="SMS despite disabled",
        confirmation_email_template="Email despite disabled",
    )
    sms, email = resolve_templates(config, "confirmation", None)
    assert sms == "SMS despite disabled"
    assert email == "Email despite disabled"


def test_note_type_campaign_config_master_enabled_default() -> None:
    """master_enabled defaults to True so existing visit types stay active."""
    cfg = NoteTypeCampaignConfig()
    assert cfg.master_enabled is True


def test_note_type_from_dict_missing_master_enabled_defaults_true() -> None:
    """from_dict on data without master_enabled keeps the True default."""
    data = {"note_type_id": "nt-1", "confirmation_enabled": True}
    cfg = NoteTypeCampaignConfig.from_dict(data)
    assert cfg.master_enabled is True


def test_note_type_master_enabled_round_trip() -> None:
    """master_enabled survives to_dict/from_dict round trip."""
    cfg = NoteTypeCampaignConfig(note_type_id="nt-1", master_enabled=False)
    restored = NoteTypeCampaignConfig.from_dict(cfg.to_dict())
    assert restored.master_enabled is False


def test_effective_config_master_off_disables_per_campaign_on() -> None:
    """Master off short circuits the resolver even when per-campaign flag is True."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        master_enabled=False,
        confirmation_enabled=True,
    ).to_dict()
    config = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="global sms",
        confirmation_email_template="<p>global</p>",
        confirmation_channels=["email"],
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, intervals, channels, sms_tpl, email_tpl, _send_time = get_effective_campaign_config(
        config, "confirmation", "nt-1"
    )

    assert enabled is False
    assert intervals == []
    assert channels == []
    assert sms_tpl == ""
    assert email_tpl == ""


def test_effective_config_master_off_disables_override_path() -> None:
    """Master off short circuits even when per-campaign override is set."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        master_enabled=False,
        confirmation_enabled=True,
        confirmation_override=True,
        confirmation_sms_template="override sms",
        confirmation_email_template="<p>override</p>",
        confirmation_channels=["sms"],
    ).to_dict()
    config = CampaignConfig(
        confirmation_enabled=True,
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, _intervals, _channels, _sms_tpl, _email_tpl, _send_time = (
        get_effective_campaign_config(config, "confirmation", "nt-1")
    )

    assert enabled is False


def test_effective_config_master_on_resolves_normally() -> None:
    """Master on with per-campaign True returns enabled and the resolved config."""
    nt_data = NoteTypeCampaignConfig(
        note_type_id="nt-1",
        master_enabled=True,
        confirmation_enabled=True,
    ).to_dict()
    config = CampaignConfig(
        confirmation_enabled=True,
        confirmation_sms_template="global sms",
        confirmation_email_template="<p>global</p>",
        confirmation_channels=["email"],
        note_type_campaigns={"nt-1": nt_data},
    )

    enabled, _intervals, channels, sms_tpl, _email_tpl, _send_time = (
        get_effective_campaign_config(config, "confirmation", "nt-1")
    )

    assert enabled is True
    assert channels == ["email"]
    assert sms_tpl == "global sms"


def test_patch_config_preserves_other_note_types_when_patching_one(mocker: MockerFixture) -> None:
    """Patching a single note type must not wipe other note types from the config."""
    from patient_notify.services.config import patch_config

    existing = CampaignConfig(
        note_type_campaigns={
            "nt-1": {"note_type_id": "nt-1", "master_enabled": True},
            "nt-2": {"note_type_id": "nt-2", "master_enabled": True},
        }
    )
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = json.dumps(existing.to_dict())
    mocker.patch("patient_notify.services.config.get_cache", return_value=mock_cache)

    patch_config({"note_type_campaigns": {"nt-1": {"master_enabled": False}}})

    saved_json = mock_cache.set.call_args[0][1]
    saved = json.loads(saved_json)
    assert "nt-2" in saved["note_type_campaigns"], "nt-2 must survive a single-entry patch"
    assert saved["note_type_campaigns"]["nt-1"]["master_enabled"] is False
    assert saved["note_type_campaigns"]["nt-2"]["master_enabled"] is True


def test_patch_config_merges_fields_within_a_note_type(mocker: MockerFixture) -> None:
    """Patching one field inside a note type must preserve other fields of that entry."""
    from patient_notify.services.config import patch_config

    existing = CampaignConfig(
        note_type_campaigns={
            "nt-1": {
                "note_type_id": "nt-1",
                "master_enabled": True,
                "confirmation_sms_template": "original template",
            }
        }
    )
    mock_cache = mocker.Mock()
    mock_cache.get.return_value = json.dumps(existing.to_dict())
    mocker.patch("patient_notify.services.config.get_cache", return_value=mock_cache)

    patch_config({"note_type_campaigns": {"nt-1": {"master_enabled": False}}})

    saved_json = mock_cache.set.call_args[0][1]
    saved = json.loads(saved_json)
    nt1 = saved["note_type_campaigns"]["nt-1"]
    assert nt1["master_enabled"] is False
    assert nt1["confirmation_sms_template"] == "original template", "unrelated field must survive"
