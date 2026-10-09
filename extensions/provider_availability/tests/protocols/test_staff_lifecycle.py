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
             patch(f"{SL_MODULE}.get_schedulable_provider_ids", return_value={"p1"}) as mock_sched, \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal:
            mock_objects.get.return_value = mock_staff
            mock_cal.filter.return_value.first.return_value = None
            mock_cal.for_calendar_name.return_value.first.return_value = None

            result = handler.compute()

            assert mock_objects.mock_calls == [call.get(id="p1")]
            assert mock_sched.mock_calls == [call()]
            assert len(result) == 1  # Calendar create effect

    def test_skips_non_provider_role(self):
        mock_staff = MagicMock()
        mock_staff.id = "s1"

        mock_event = MagicMock()
        mock_event.target.id = "s1"
        handler = OnStaffActivated(mock_event)

        with patch(f"{SL_MODULE}.Staff.objects") as mock_objects, \
             patch(f"{SL_MODULE}.get_schedulable_provider_ids", return_value={"someone-else"}):
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
             patch(f"{SL_MODULE}.get_schedulable_provider_ids", return_value={"cc1"}), \
             patch(f"{SL_MODULE}.CalendarModel.objects") as mock_cal:
            mock_objects.get.return_value = mock_staff
            mock_cal.filter.return_value.first.return_value = None
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
             patch(f"{SL_MODULE}.get_schedulable_provider_ids", return_value={"p1"}), \
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
    # Version patches: full sync is gated on first_install OR a version change.
    # First-install tests force sync via is_first_install=True; redeploy tests
    # force it via a version mismatch (synced "0.0.1" vs current "0.0.2").
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
             patch(f"{SL_MODULE}._current_plugin_version", return_value="1.0"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value=""), \
             patch(f"{SL_MODULE}.set_synced_version") as mock_set_ver, \
             patch(f"{SL_MODULE}.mark_installed") as mock_mark:

            result = handler.compute()

            assert mock_mark.mock_calls == [call()]
            assert mock_set_ver.mock_calls == [call("1.0")]
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
             patch(f"{SL_MODULE}._current_plugin_version", return_value="1.0"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value=""), \
             patch(f"{SL_MODULE}.set_synced_version"), \
             patch(f"{SL_MODULE}.mark_installed"), \
             patch(f"{SL_MODULE}.deterministic_calendar_id", return_value="new-cal-id"):
            mock_cal.filter.return_value.first.return_value = None
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
             patch(f"{SL_MODULE}._current_plugin_version", return_value="1.0"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value=""), \
             patch(f"{SL_MODULE}.set_synced_version"), \
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
             patch(f"{SL_MODULE}._current_plugin_version", return_value="1.0"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value=""), \
             patch(f"{SL_MODULE}.set_synced_version"), \
             patch(f"{SL_MODULE}.mark_installed"):
            mock_cal.for_calendar_name.side_effect = Exception("DB error")

            result = handler.compute()

            # Should not crash, returns empty (no successful calendars)
            assert result == []

    def test_first_install_reconciles_per_entity(self):
        """First install reconciles per-entity (no blanket event sweep)."""
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

        sched_staff = MagicMock()
        sched_staff.id = "p1"

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[sched_staff]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[mock_rule]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[mock_block]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[mock_rb]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=True), \
             patch(f"{SL_MODULE}._current_plugin_version", return_value="1.0"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value=""), \
             patch(f"{SL_MODULE}.set_synced_version") as mock_set_ver, \
             patch(f"{SL_MODULE}.mark_installed") as mock_mark, \
             patch(f"{SL_MODULE}.sync_provider_availability", return_value=["sync-fx"]) as mock_sync, \
             patch(f"{SL_MODULE}.build_provider_lead_time_effects", return_value=["lead-fx"]) as mock_lead, \
             patch(f"{SL_MODULE}.build_delete_block_effects", return_value=["del-block-fx"]) as mock_del_block, \
             patch(f"{SL_MODULE}.build_block_event_effects", return_value=["block-fx"]) as mock_block_fx, \
             patch(f"{SL_MODULE}.build_recurring_block_sync_effects", return_value=["rb-fx"]) as mock_rb_fx:

            result = handler.compute()

            assert mock_mark.mock_calls == [call()]
            assert mock_set_ver.mock_calls == [call("1.0")]
            assert mock_sync.mock_calls == [call("p1", schedulable_ids={"p1"})]
            assert mock_lead.mock_calls == [call("p1", [mock_rule])]
            # Block reconciliation deletes the block's own prior events first,
            # then recreates — never a blanket calendar sweep.
            assert mock_del_block.mock_calls == [call("p1", mock_block)]
            assert mock_block_fx.mock_calls == [call(mock_block)]
            assert mock_rb_fx.mock_calls == [call(mock_rb)]
            assert "sync-fx" in result
            assert "lead-fx" in result
            assert "del-block-fx" in result
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
             patch(f"{SL_MODULE}._current_plugin_version", return_value="1.0"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value=""), \
             patch(f"{SL_MODULE}.set_synced_version"), \
             patch(f"{SL_MODULE}.mark_installed"), \
             patch(f"{SL_MODULE}.sync_provider_availability", side_effect=Exception("sync error")):

            result = handler.compute()

            # Should not crash — exception caught per-rule
            assert result == []

    def test_redeploy_reconciles_without_destructive_sweep(self):
        """On redeploy, reconcile per-entity — NO blanket event deletion.

        This is the regression guard for Kristen's concern: a redeploy must not
        wipe every event on the Clinic/Admin calendars. The handler must no
        longer call any all-events delete; instead each block deletes only its
        own prior events before recreating.
        """
        import provider_availability.protocols.staff_lifecycle as sl

        # The destructive helper must no longer exist / be referenced.
        assert not hasattr(sl, "delete_all_plugin_events")

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

        sched_staff = MagicMock()
        sched_staff.id = "p1"

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[sched_staff]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.get_all_rules", return_value=[mock_rule]), \
             patch(f"{SL_MODULE}.get_all_blocks", return_value=[mock_block]), \
             patch(f"{SL_MODULE}.get_all_recurring_blocks", return_value=[mock_rb]), \
             patch(f"{SL_MODULE}.is_first_install", return_value=False), \
             patch(f"{SL_MODULE}._current_plugin_version", return_value="0.0.2"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value="0.0.1"), \
             patch(f"{SL_MODULE}.set_synced_version") as mock_set_ver, \
             patch(f"{SL_MODULE}.sync_provider_availability", return_value=[]) as mock_sync, \
             patch(f"{SL_MODULE}.build_provider_lead_time_effects", return_value=[]) as mock_lead, \
             patch(f"{SL_MODULE}.build_delete_block_effects", return_value=[]) as mock_del_block, \
             patch(f"{SL_MODULE}.build_block_event_effects", return_value=[]) as mock_block_fx, \
             patch(f"{SL_MODULE}.build_recurring_block_sync_effects", return_value=[]) as mock_rb_fx:

            handler.compute()

            mock_set_ver.assert_called_once_with("0.0.2")
            mock_sync.assert_called_once_with("p1", schedulable_ids={"p1"})
            mock_lead.assert_called_once_with("p1", [mock_rule])
            mock_del_block.assert_called_once_with("p1", mock_block)
            mock_block_fx.assert_called_once_with(mock_block)
            mock_rb_fx.assert_called_once_with(mock_rb)

    def test_redeploy_same_version_skips_full_sync(self):
        """A config-only redeploy at the same version must NOT rebuild events."""
        mock_event = MagicMock()
        handler = OnPluginInstalled(mock_event)

        with patch(f"{SL_MODULE}.get_schedulable_staff", return_value=[]), \
             patch(f"{SL_MODULE}.CalendarModel.objects"), \
             patch(f"{SL_MODULE}.is_first_install", return_value=False), \
             patch(f"{SL_MODULE}._current_plugin_version", return_value="1.2.3"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value="1.2.3"), \
             patch(f"{SL_MODULE}.get_all_rules") as mock_rules, \
             patch(f"{SL_MODULE}.sync_provider_availability") as mock_sync, \
             patch(f"{SL_MODULE}.set_synced_version") as mock_set_ver:

            result = handler.compute()

            # No resync: rules aren't even read, nothing synced.
            assert mock_rules.mock_calls == []
            assert mock_sync.mock_calls == []
            assert mock_set_ver.mock_calls == []
            assert result == []

    def test_redeploy_lead_time_exception_handling(self):
        """Exceptions during lead-time refresh on a version-change redeploy should be caught."""
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
             patch(f"{SL_MODULE}._current_plugin_version", return_value="0.0.2"), \
             patch(f"{SL_MODULE}.get_synced_version", return_value="0.0.1"), \
             patch(f"{SL_MODULE}.set_synced_version"), \
             patch(f"{SL_MODULE}.sync_provider_availability", return_value=[]), \
             patch(f"{SL_MODULE}.build_provider_lead_time_effects", side_effect=Exception("lead error")):

            result = handler.compute()

            # Should not crash — exception caught per-rule
            assert result == []
