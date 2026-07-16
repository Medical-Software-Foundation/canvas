"""Tests for provider_availability.protocols.staff_lifecycle."""

from unittest.mock import MagicMock, call, patch

from provider_availability.protocols.staff_lifecycle import (
    OnPluginInstalled,
    OnStaffActivated,
    OnStaffDeactivated,
)


SL_MODULE = "provider_availability.protocols.staff_lifecycle"


class TestOnStaffActivated:
    def test_creates_clinic_calendar_for_provider(self):
        mock_staff = MagicMock()
        mock_staff.id = "p1"
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"
        mock_staff.full_name = "Jane Doe"

        mock_event = MagicMock()
        mock_event.target.id = "p1"
        handler = OnStaffActivated(mock_event)

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects, \
             patch(f"{SL_MODULE}.get_schedulable_codes", return_value={"MD"}), \
             patch(f"{SL_MODULE}.is_schedulable_staff", return_value=True) as mock_sched, \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal:
            mock_objects.get.return_value = mock_staff
            mock_cal.for_calendar_name.return_value.first.return_value = None

            result = handler.compute()

            assert mock_objects.mock_calls == [call.get(id="p1")]
            assert mock_sched.mock_calls == [call(mock_staff, {"MD"})]
            assert len(result) == 1  # Calendar create effect

    def test_skips_non_provider_role(self):
        mock_staff = MagicMock()
        mock_staff.id = "s1"

        mock_event = MagicMock()
        mock_event.target.id = "s1"
        handler = OnStaffActivated(mock_event)

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects, \
             patch(f"{SL_MODULE}.get_schedulable_codes", return_value={"MD", "DO", "NP", "PA"}), \
             patch(f"{SL_MODULE}.is_schedulable_staff", return_value=False):
            mock_objects.get.return_value = mock_staff

            result = handler.compute()

            assert result == []

    def test_creates_calendar_for_non_clinical_role(self):
        """A non-clinical staff member in a configured role gets a calendar."""
        mock_staff = MagicMock()
        mock_staff.id = "cc1"
        mock_staff.first_name = "Casey"
        mock_staff.last_name = "Coordinator"
        mock_staff.full_name = "Casey Coordinator"

        mock_event = MagicMock()
        mock_event.target.id = "cc1"
        handler = OnStaffActivated(mock_event)

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects, \
             patch(f"{SL_MODULE}.get_schedulable_codes", return_value={"CC"}), \
             patch(f"{SL_MODULE}.is_schedulable_staff", return_value=True), \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal:
            mock_objects.get.return_value = mock_staff
            mock_cal.for_calendar_name.return_value.first.return_value = None

            result = handler.compute()

            assert len(result) == 1

    def test_skips_existing_calendar(self):
        mock_staff = MagicMock()
        mock_staff.id = "p1"
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"
        mock_staff.full_name = "Jane Doe"

        mock_event = MagicMock()
        mock_event.target.id = "p1"
        handler = OnStaffActivated(mock_event)

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects, \
             patch(f"{SL_MODULE}.get_schedulable_codes", return_value={"DO"}), \
             patch(f"{SL_MODULE}.is_schedulable_staff", return_value=True), \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal:
            mock_objects.get.return_value = mock_staff
            mock_cal.for_calendar_name.return_value.first.return_value = MagicMock()

            result = handler.compute()

            assert result == []

    def test_staff_not_found(self):
        from canvas_sdk.v1.data.staff import Staff

        mock_event = MagicMock()
        mock_event.target.id = "unknown"
        handler = OnStaffActivated(mock_event)

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects:
            mock_objects.get.side_effect = Staff.DoesNotExist

            result = handler.compute()

            assert result == []


class TestOnStaffDeactivated:
    def test_deletes_rules_and_events(self):
        mock_staff = MagicMock()
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"

        mock_event = MagicMock()
        mock_event.target.id = "p1"
        handler = OnStaffDeactivated(mock_event)

        mock_rule = MagicMock()

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects, \
             patch(f"{SL_MODULE}.get_rules_for_provider", return_value=[mock_rule]) as mock_get, \
             patch(f"{SL_MODULE}.build_delete_effects", return_value=["effect1"]) as mock_delete, \
             patch(f"{SL_MODULE}.delete_rules_for_provider", return_value=1) as mock_del_rules:
            mock_objects.get.return_value = mock_staff

            result = handler.compute()

            assert mock_get.mock_calls == [call("p1")]
            assert mock_delete.mock_calls == [call("p1")]
            assert mock_del_rules.mock_calls == [call("p1")]
            assert result == ["effect1"]

    def test_no_rules_does_nothing(self):
        mock_staff = MagicMock()
        mock_staff.first_name = "Jane"
        mock_staff.last_name = "Doe"

        mock_event = MagicMock()
        mock_event.target.id = "p1"
        handler = OnStaffDeactivated(mock_event)

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects, \
             patch(f"{SL_MODULE}.get_rules_for_provider", return_value=[]):
            mock_objects.get.return_value = mock_staff

            result = handler.compute()

            assert result == []


class TestOnPluginInstalled:
    def test_empty_cache_preserves_events(self):
        """When cache is empty, plugin should only create calendars, not delete events."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=True), \
             patch(f"{SL_MODULE}.mark_installed") as mock_mark:

            result = handler.compute()

            assert mock_mark.mock_calls == [call()]
            assert result == []

    def test_creates_calendars_for_active_providers(self):
        """Should create Clinic calendars for schedulable staff that don't have one."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        staff1 = MagicMock()
        staff1.id = "s1"
        staff1.full_name = "Jane Doe"
        staff1.first_name = "Jane"
        staff1.last_name = "Doe"

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[staff1]), \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal, \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=True), \
             patch(f"{SL_MODULE}.mark_installed"), \
             patch(f"{SL_MODULE}.uuid4", return_value="new-cal-id"):
            mock_cal.for_calendar_name.return_value.first.return_value = None

            result = handler.compute()

            assert len(result) == 1  # Calendar create effect

    def test_skips_existing_calendars_on_install(self):
        """Should skip staff that already have a Clinic calendar."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        staff1 = MagicMock()
        staff1.id = "s1"
        staff1.full_name = "Jane Doe"

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[staff1]), \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal, \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=True), \
             patch(f"{SL_MODULE}.mark_installed"):
            mock_cal.for_calendar_name.return_value.first.return_value = MagicMock()

            result = handler.compute()

            assert result == []

    def test_calendar_creation_exception_handled(self):
        """Exceptions during calendar creation should be caught per-staff."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        staff1 = MagicMock()
        staff1.id = "s1"
        staff1.full_name = "Jane Doe"

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[staff1]), \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal, \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=True), \
             patch(f"{SL_MODULE}.mark_installed"):
            mock_cal.for_calendar_name.side_effect = Exception("DB error")

            result = handler.compute()

            # Should not crash, returns empty (no successful calendars)
            assert result == []

    def test_first_install_full_sync(self):
        """First install should delete all events and resync rules, blocks, recurring blocks."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        mock_rule = MagicMock()
        mock_rule.provider_id = "p1"
        mock_rule.is_active = True
        mock_rule.booking_interval.min_lead_hours = 24

        mock_block = MagicMock()
        mock_block.provider_id = "p1"

        mock_rb = MagicMock()
        mock_rb.provider_id = "p1"

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[mock_rule]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[mock_block]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[mock_rb]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=True), \
             patch(f"{SL_MODULE}.mark_installed") as mock_mark, \
             patch(f"{SL_MODULE}.delete_all_plugin_events", return_value=[]) as mock_delete_all, \
             patch(f"{SL_MODULE}.sync_provider_availability", return_value=["sync-fx"]) as mock_sync, \
             patch(f"{SL_MODULE}.build_lead_time_block_effects", return_value=["lead-fx"]) as mock_lead, \
             patch(f"{SL_MODULE}.build_block_event_effects", return_value=["block-fx"]) as mock_block_fx, \
             patch(f"{SL_MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"]) as mock_rb_fx:

            result = handler.compute()

            assert mock_delete_all.mock_calls == [call()]
            assert mock_mark.mock_calls == [call()]
            assert mock_sync.mock_calls == [call("p1")]
            assert mock_lead.mock_calls == [call(mock_rule)]
            assert mock_block_fx.mock_calls == [call(mock_block)]
            assert mock_rb_fx.mock_calls == [call(mock_rb)]
            assert "sync-fx" in result
            assert "lead-fx" in result
            assert "block-fx" in result
            assert "rb-fx" in result

    def test_first_install_sync_exception_handling(self):
        """Exceptions during rule/block sync should be caught individually."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        mock_rule = MagicMock()
        mock_rule.provider_id = "p1"
        mock_rule.is_active = True
        mock_rule.booking_interval.min_lead_hours = 0

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[mock_rule]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=True), \
             patch(f"{SL_MODULE}.mark_installed"), \
             patch(f"{SL_MODULE}.delete_all_plugin_events", return_value=[]), \
             patch(f"{SL_MODULE}.sync_provider_availability", side_effect=Exception("sync error")):

            result = handler.compute()

            # Should not crash — exception caught per-rule
            assert result == []

    def test_redeploy_lead_time_exception_handling(self):
        """Exceptions during lead-time refresh on redeploy should be caught."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        mock_rule = MagicMock()
        mock_rule.is_active = True
        mock_rule.booking_interval.min_lead_hours = 24

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[mock_rule]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=False), \
             patch(f"{SL_MODULE}.build_lead_time_block_effects", side_effect=Exception("lead error")):

            result = handler.compute()

            # Should not crash — exception caught per-rule
            assert result == []

    def test_redeploy_performs_full_sync(self):
        """On redeploy (not first install), should do a full sync of all rules/blocks."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        mock_rule = MagicMock()
        mock_rule.is_active = True
        mock_rule.provider_id = "p1"
        mock_rule.booking_interval.min_lead_hours = 24

        mock_block = MagicMock()
        mock_block.id = "b1"
        mock_block.provider_id = "p1"

        mock_rb = MagicMock()
        mock_rb.id = "rb1"
        mock_rb.provider_id = "p1"

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[mock_rule]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[mock_block]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[mock_rb]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=False), \
             patch(f"{SL_MODULE}.delete_all_plugin_events", return_value=[]) as mock_delete, \
             patch(f"{SL_MODULE}.sync_provider_availability", return_value=[]) as mock_sync, \
             patch(f"{SL_MODULE}.build_lead_time_block_effects", return_value=[]) as mock_lead, \
             patch(f"{SL_MODULE}.build_block_event_effects", return_value=[]) as mock_block_fx, \
             patch(f"{SL_MODULE}.build_recurring_block_sync_effects", return_value=[]) as mock_rb_fx:

            handler.compute()

            mock_delete.assert_called_once()
            mock_sync.assert_called_once_with("p1")
            mock_lead.assert_called_once_with(mock_rule)
            mock_block_fx.assert_called_once_with(mock_block)
            mock_rb_fx.assert_called_once_with(mock_rb)
