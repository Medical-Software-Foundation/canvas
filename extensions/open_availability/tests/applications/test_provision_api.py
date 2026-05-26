import json
from unittest.mock import MagicMock, patch
from uuid import UUID

from open_availability.applications.provision_api import ProvisionAvailabilityAPI


class TestProvisionAvailabilityAPI:
    """Tests for the provisioning API endpoint."""

    def _make_handler(self, secrets: dict[str, str] | None = None) -> ProvisionAvailabilityAPI:
        """Create a ProvisionAvailabilityAPI handler with mocked event."""
        mock_event = MagicMock()
        mock_event.context = {
            "method": "POST",
            "path": "/provision-availability/run",
            "query_string": "",
            "body": "",
            "headers": "",
        }
        handler = ProvisionAvailabilityAPI(event=mock_event)
        handler.secrets = secrets or {
            "SCHEDULABLE_ROLES": "MD,DO,NP,PA",
            "simpleapi-api-key": "test-api-key",
        }
        return handler

    @staticmethod
    def _make_credentials(key: str = "test-api-key") -> MagicMock:
        """Create a mock APIKeyCredentials object."""
        creds = MagicMock()
        creds.key = key
        return creds

    def test_authenticate_succeeds_with_valid_key(self) -> None:
        """Test authentication passes when the correct API key is provided."""
        handler = self._make_handler()
        creds = self._make_credentials("test-api-key")
        assert handler.authenticate(creds) is True

    def test_authenticate_fails_with_wrong_key(self) -> None:
        """Test authentication fails when an incorrect API key is provided."""
        handler = self._make_handler()
        creds = self._make_credentials("wrong-key")
        assert handler.authenticate(creds) is False

    def test_authenticate_fails_with_empty_key(self) -> None:
        """Test authentication fails when an empty API key is provided."""
        handler = self._make_handler()
        creds = self._make_credentials("")
        assert handler.authenticate(creds) is False

    def test_authenticate_fails_with_no_secret(self) -> None:
        """Test authentication fails when the secret is not configured."""
        handler = self._make_handler(secrets={"SCHEDULABLE_ROLES": "MD,DO,NP,PA"})
        creds = self._make_credentials("some-key")
        assert handler.authenticate(creds) is False

    def test_provisions_staff_without_calendar(self) -> None:
        """Test creates calendar + event for staff with no existing calendar."""
        handler = self._make_handler()

        mock_staff = MagicMock()
        mock_staff.id = "staff-1"
        mock_staff.full_name = "Dr. Test"
        mock_staff.top_role_abbreviation = "MD"

        with patch(
            "open_availability.applications.provision_api.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.applications.provision_api.CalendarModel.objects"
            ) as mock_cal_objects:
                with patch(
                    "open_availability.applications.provision_api.Calendar"
                ) as mock_cal_class:
                    with patch(
                        "open_availability.applications.provision_api.create_availability_event"
                    ) as mock_create_event:
                        with patch(
                            "open_availability.applications.provision_api.uuid4"
                        ) as mock_uuid:
                            mock_staff_queryset = MagicMock()
                            mock_staff_queryset.count.return_value = 1
                            mock_staff_queryset.__iter__ = lambda self: iter(
                                [mock_staff]
                            )
                            mock_staff_objects.filter.return_value = (
                                mock_staff_queryset
                            )

                            mock_cal_objects.filter.return_value.first.return_value = (
                                None
                            )
                            mock_uuid.return_value = UUID(
                                "11111111-1111-1111-1111-111111111111"
                            )

                            mock_cal_effect = MagicMock()
                            mock_cal_instance = MagicMock()
                            mock_cal_instance.create.return_value = (
                                mock_cal_effect
                            )
                            mock_cal_class.return_value = mock_cal_instance

                            mock_event_effect = MagicMock()
                            mock_create_event.return_value = mock_event_effect

                            result = handler.run_provisioning()

                            # Should have calendar effect + event effect + JSON response
                            assert len(result) == 3
                            assert mock_cal_class.called
                            assert mock_create_event.called

    def test_skips_staff_with_active_availability(self) -> None:
        """Test skips staff that already have active availability."""
        handler = self._make_handler()

        mock_staff = MagicMock()
        mock_staff.id = "staff-1"
        mock_staff.full_name = "Dr. Test"
        mock_staff.top_role_abbreviation = "MD"

        mock_calendar = MagicMock()
        mock_active_event = MagicMock()

        with patch(
            "open_availability.applications.provision_api.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.applications.provision_api.CalendarModel.objects"
            ) as mock_cal_objects:
                with patch(
                    "open_availability.applications.provision_api.create_availability_event"
                ) as mock_create_event:
                    mock_staff_queryset = MagicMock()
                    mock_staff_queryset.count.return_value = 1
                    mock_staff_queryset.__iter__ = lambda self: iter(
                        [mock_staff]
                    )
                    mock_staff_objects.filter.return_value = mock_staff_queryset

                    mock_cal_objects.filter.return_value.first.return_value = (
                        mock_calendar
                    )
                    mock_calendar.events.filter.return_value.first.return_value = (
                        mock_active_event
                    )

                    result = handler.run_provisioning()

                    # Should only have the JSON response (no calendar/event effects)
                    assert len(result) == 1
                    assert not mock_create_event.called

    def test_skips_non_schedulable_staff(self) -> None:
        """Test skips staff with non-schedulable roles."""
        handler = self._make_handler()

        mock_staff = MagicMock()
        mock_staff.id = "staff-1"
        mock_staff.full_name = "Admin User"
        mock_staff.top_role_abbreviation = "ADMIN"

        with patch(
            "open_availability.applications.provision_api.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.applications.provision_api.create_availability_event"
            ) as mock_create_event:
                mock_staff_queryset = MagicMock()
                mock_staff_queryset.count.return_value = 1
                mock_staff_queryset.__iter__ = lambda self: iter(
                    [mock_staff]
                )
                mock_staff_objects.filter.return_value = mock_staff_queryset

                result = handler.run_provisioning()

                assert len(result) == 1  # JSON response only
                assert not mock_create_event.called

    def test_continues_on_per_staff_error(self) -> None:
        """Test error on one staff doesn't block others."""
        handler = self._make_handler()

        mock_staff_bad = MagicMock()
        mock_staff_bad.id = "bad-staff"
        mock_staff_bad.full_name = "Bad Staff"
        mock_staff_bad.top_role_abbreviation = "MD"

        mock_staff_good = MagicMock()
        mock_staff_good.id = "good-staff"
        mock_staff_good.full_name = "Good Staff"
        mock_staff_good.top_role_abbreviation = "MD"

        with patch(
            "open_availability.applications.provision_api.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.applications.provision_api.CalendarModel.objects"
            ) as mock_cal_objects:
                with patch(
                    "open_availability.applications.provision_api.Calendar"
                ) as mock_cal_class:
                    with patch(
                        "open_availability.applications.provision_api.create_availability_event"
                    ) as mock_create_event:
                        with patch(
                            "open_availability.applications.provision_api.uuid4"
                        ) as mock_uuid:
                            mock_staff_queryset = MagicMock()
                            mock_staff_queryset.count.return_value = 2
                            mock_staff_queryset.__iter__ = lambda self: iter(
                                [mock_staff_bad, mock_staff_good]
                            )
                            mock_staff_objects.filter.return_value = (
                                mock_staff_queryset
                            )

                            # First staff errors, second succeeds
                            mock_cal_objects.filter.return_value.first.side_effect = [
                                RuntimeError("DB error"),
                                None,
                            ]

                            mock_uuid.return_value = UUID(
                                "11111111-1111-1111-1111-111111111111"
                            )

                            mock_cal_effect = MagicMock()
                            mock_cal_instance = MagicMock()
                            mock_cal_instance.create.return_value = (
                                mock_cal_effect
                            )
                            mock_cal_class.return_value = mock_cal_instance

                            mock_event_effect = MagicMock()
                            mock_create_event.return_value = mock_event_effect

                            result = handler.run_provisioning()

                            # Calendar + event for good staff + JSON response = 3
                            assert len(result) == 3

                            json_response = result[-1]
                            payload = json.loads(json_response.content)
                            assert payload["errored"] == 1
                            assert payload["errored_staff"] == [
                                "Bad Staff (bad-staff)"
                            ]

    def test_force_provisioning_ends_existing_events(self) -> None:
        """Test force provisioning ends existing events before creating new ones."""
        handler = self._make_handler()

        mock_staff = MagicMock()
        mock_staff.id = "staff-1"
        mock_staff.full_name = "Dr. Test"
        mock_staff.top_role_abbreviation = "MD"

        mock_calendar = MagicMock()
        mock_existing_event = MagicMock()
        mock_existing_event.id = "old-event-1"
        mock_existing_event.title = "Available"
        mock_existing_event.starts_at = MagicMock()
        mock_existing_event.ends_at = MagicMock()

        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_existing_event])

        with patch(
            "open_availability.applications.provision_api.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.applications.provision_api.CalendarModel.objects"
            ) as mock_cal_objects:
                with patch(
                    "open_availability.applications.provision_api.Event"
                ) as mock_event_class:
                    with patch(
                        "open_availability.applications.provision_api.create_availability_event"
                    ) as mock_create_event:
                        mock_staff_queryset = MagicMock()
                        mock_staff_queryset.count.return_value = 1
                        mock_staff_queryset.__iter__ = lambda self: iter(
                            [mock_staff]
                        )
                        mock_staff_objects.filter.return_value = (
                            mock_staff_queryset
                        )

                        mock_cal_objects.filter.return_value.first.return_value = (
                            mock_calendar
                        )
                        mock_calendar.events.filter.return_value = mock_queryset

                        mock_update_instance = MagicMock()
                        mock_update_effect = MagicMock()
                        mock_update_instance.update.return_value = (
                            mock_update_effect
                        )
                        mock_event_class.return_value = mock_update_instance

                        mock_new_event_effect = MagicMock()
                        mock_create_event.return_value = mock_new_event_effect

                        result = handler.force_provisioning()

                        # Should have: end event effect + new event effect + JSON response
                        assert len(result) == 3
                        assert mock_event_class.called
                        assert mock_create_event.called

    def test_force_provisioning_skips_none_when_no_existing(self) -> None:
        """Test force provisioning works normally for staff without existing events."""
        handler = self._make_handler()

        mock_staff = MagicMock()
        mock_staff.id = "staff-1"
        mock_staff.full_name = "Dr. Test"
        mock_staff.top_role_abbreviation = "MD"

        with patch(
            "open_availability.applications.provision_api.Staff.objects"
        ) as mock_staff_objects:
            with patch(
                "open_availability.applications.provision_api.CalendarModel.objects"
            ) as mock_cal_objects:
                with patch(
                    "open_availability.applications.provision_api.Calendar"
                ) as mock_cal_class:
                    with patch(
                        "open_availability.applications.provision_api.create_availability_event"
                    ) as mock_create_event:
                        with patch(
                            "open_availability.applications.provision_api.uuid4"
                        ) as mock_uuid:
                            mock_staff_queryset = MagicMock()
                            mock_staff_queryset.count.return_value = 1
                            mock_staff_queryset.__iter__ = lambda self: iter(
                                [mock_staff]
                            )
                            mock_staff_objects.filter.return_value = (
                                mock_staff_queryset
                            )

                            mock_cal_objects.filter.return_value.first.return_value = (
                                None
                            )
                            mock_uuid.return_value = UUID(
                                "11111111-1111-1111-1111-111111111111"
                            )

                            mock_cal_effect = MagicMock()
                            mock_cal_instance = MagicMock()
                            mock_cal_instance.create.return_value = (
                                mock_cal_effect
                            )
                            mock_cal_class.return_value = mock_cal_instance

                            mock_event_effect = MagicMock()
                            mock_create_event.return_value = mock_event_effect

                            result = handler.force_provisioning()

                            # Calendar + event + JSON response = 3
                            assert len(result) == 3
                            assert mock_cal_class.called
                            assert mock_create_event.called
