"""Tests for business-line routing, attribution, and placeholders."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

from appointment_reminders.services.business_line import (
    get_business_line_from_number,
    get_business_line_name,
    resolve_attribution,
)
from appointment_reminders.services.config import (
    CampaignConfig,
    get_effective_campaign_config,
)
from appointment_reminders.services.templates import _business_line_vars


def _patient_with_business_line(name: str | None):
    patient = MagicMock()
    if name is None:
        patient.business_line = None
    else:
        bl = MagicMock()
        bl.name = name
        patient.business_line = bl
    return patient


# ---- get_business_line_name ----

def test_get_business_line_name_returns_name() -> None:
    assert get_business_line_name(_patient_with_business_line("Northwind Health")) == "Northwind Health"


def test_get_business_line_name_none_when_unset() -> None:
    assert get_business_line_name(_patient_with_business_line(None)) == ""


def test_get_business_line_name_empty_when_access_raises() -> None:
    patient = MagicMock()
    type(patient).business_line = PropertyMock(side_effect=RuntimeError("boom"))
    assert get_business_line_name(patient) == ""


def test_get_business_line_name_empty_when_name_blank() -> None:
    assert get_business_line_name(_patient_with_business_line("")) == ""


# ---- resolve_attribution ----

def test_resolve_attribution_uses_override() -> None:
    config = CampaignConfig(
        default_attribution="Your Care Team",
        business_line_overrides={"Northwind Health": {"attribution": "Acme on behalf of Northwind Health"}},
    )
    assert resolve_attribution(config, "Northwind Health") == "Acme on behalf of Northwind Health"


def test_resolve_attribution_defaults_when_no_business_line() -> None:
    config = CampaignConfig(default_attribution="Your Care Team")
    assert resolve_attribution(config, "") == "Your Care Team"


def test_resolve_attribution_defaults_when_business_line_unmapped() -> None:
    config = CampaignConfig(default_attribution="Your Care Team")
    assert resolve_attribution(config, "Humana") == "Your Care Team"


def test_resolve_attribution_defaults_when_override_has_no_attribution() -> None:
    config = CampaignConfig(
        default_attribution="Your Care Team",
        business_line_overrides={"Northwind Health": {"reminder_override": True}},
    )
    assert resolve_attribution(config, "Northwind Health") == "Your Care Team"


# ---- get_business_line_from_number ----

def test_get_business_line_from_number_returns_configured() -> None:
    config = CampaignConfig(
        business_line_overrides={"Northwind Health": {"from_number": "  +15555550199  "}},
    )
    assert get_business_line_from_number(config, "Northwind Health") == "+15555550199"


def test_get_business_line_from_number_empty_when_no_entry() -> None:
    assert get_business_line_from_number(CampaignConfig(), "Northwind Health") == ""


def test_get_business_line_from_number_empty_when_entry_lacks_number() -> None:
    config = CampaignConfig(business_line_overrides={"Northwind Health": {"attribution": "x"}})
    assert get_business_line_from_number(config, "Northwind Health") == ""


def test_get_business_line_from_number_empty_when_no_business_line() -> None:
    config = CampaignConfig(business_line_overrides={"Northwind Health": {"from_number": "+1555"}})
    assert get_business_line_from_number(config, "") == ""


# ---- _business_line_vars (placeholder rendering) ----

def test_business_line_vars_with_config_resolves_both() -> None:
    config = CampaignConfig(
        business_line_overrides={"Northwind Health": {"attribution": "Acme on behalf of Northwind Health"}},
    )
    variables = _business_line_vars(_patient_with_business_line("Northwind Health"), config)
    assert variables == {
        "business_line": "Northwind Health",
        "business_line_attribution": "Acme on behalf of Northwind Health",
    }


def test_business_line_vars_null_patient_falls_back_to_default() -> None:
    config = CampaignConfig(default_attribution="Your Care Team")
    variables = _business_line_vars(_patient_with_business_line(None), config)
    assert variables["business_line"] == ""
    assert variables["business_line_attribution"] == "Your Care Team"


def test_business_line_vars_without_config_leaves_attribution_empty() -> None:
    variables = _business_line_vars(_patient_with_business_line("Northwind Health"), config=None)
    assert variables == {"business_line": "Northwind Health", "business_line_attribution": ""}


# ---- get_effective_campaign_config: business-line override layer ----

def test_business_line_override_replaces_template() -> None:
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global copy",
        reminder_channels=["sms"],
        business_line_overrides={
            "Northwind Health": {"reminder_override": True, "reminder_sms_template": "northwind copy"},
        },
    )
    enabled, _channels, sms, _email, *_ = get_effective_campaign_config(
        config, None, "reminder", business_line="Northwind Health"
    )
    assert enabled is True
    assert sms == "northwind copy"


def test_business_line_none_uses_global_template() -> None:
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global copy",
        business_line_overrides={
            "Northwind Health": {"reminder_override": True, "reminder_sms_template": "northwind copy"},
        },
    )
    _enabled, _channels, sms, *_ = get_effective_campaign_config(
        config, None, "reminder", business_line=None
    )
    assert sms == "global copy"


def test_unmapped_business_line_uses_global_template() -> None:
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global copy",
        business_line_overrides={
            "Northwind Health": {"reminder_override": True, "reminder_sms_template": "northwind copy"},
        },
    )
    _enabled, _channels, sms, *_ = get_effective_campaign_config(
        config, None, "reminder", business_line="Humana"
    )
    assert sms == "global copy"


def test_business_line_opt_out_disables_campaign() -> None:
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global copy",
        business_line_overrides={"Northwind Health": {"reminders_enabled": False}},
    )
    enabled, *_ = get_effective_campaign_config(
        config, None, "reminder", business_line="Northwind Health"
    )
    assert enabled is False


def test_business_line_override_without_flag_keeps_global_template() -> None:
    # An entry with a template but no *_override flag should NOT swap the template.
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global copy",
        business_line_overrides={"Northwind Health": {"reminder_sms_template": "ignored copy"}},
    )
    _enabled, _channels, sms, *_ = get_effective_campaign_config(
        config, None, "reminder", business_line="Northwind Health"
    )
    assert sms == "global copy"


def test_business_line_wins_over_note_type_override() -> None:
    # Both a note-type override and a business-line override target reminders;
    # business line is applied last, so it wins.
    config = CampaignConfig(
        reminders_enabled=True,
        reminder_sms_template="global copy",
        note_type_reminders={
            "nt-1": {
                "note_type_id": "nt-1",
                "reminder_override": True,
                "reminder_sms_template": "note-type copy",
            }
        },
        business_line_overrides={
            "Northwind Health": {"reminder_override": True, "reminder_sms_template": "northwind copy"},
        },
    )
    _enabled, _channels, sms, *_ = get_effective_campaign_config(
        config, "nt-1", "reminder", business_line="Northwind Health"
    )
    assert sms == "northwind copy"


def test_global_disabled_ignores_business_line() -> None:
    config = CampaignConfig(
        reminders_enabled=False,
        business_line_overrides={
            "Northwind Health": {"reminder_override": True, "reminder_sms_template": "northwind copy"},
        },
    )
    enabled, *_ = get_effective_campaign_config(
        config, None, "reminder", business_line="Northwind Health"
    )
    assert enabled is False


def test_config_roundtrip_preserves_business_line_fields() -> None:
    config = CampaignConfig(
        default_attribution="Your Care Team",
        business_line_overrides={"Northwind Health": {"attribution": "Acme on behalf of Northwind Health"}},
    )
    restored = CampaignConfig.from_dict(config.to_dict())
    assert restored.default_attribution == "Your Care Team"
    assert restored.business_line_overrides == {
        "Northwind Health": {"attribution": "Acme on behalf of Northwind Health"}
    }
