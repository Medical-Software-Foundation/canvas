"""Tests for vitals_dashboard/commands/vitals_summary.py."""

from vitals_dashboard.commands.vitals_summary import VitalsSummaryCommand


class TestVitalsSummaryCommand:
    def test_meta_key(self):
        assert VitalsSummaryCommand.Meta.key == "customCommand"

    def test_meta_schema_key(self):
        assert VitalsSummaryCommand.Meta.schema_key == "vitalsSummary"

    def test_is_custom_command_subclass(self):
        from canvas_sdk.commands.commands.custom_command import CustomCommand
        assert issubclass(VitalsSummaryCommand, CustomCommand)
