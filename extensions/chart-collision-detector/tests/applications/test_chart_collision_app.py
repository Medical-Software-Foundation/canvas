"""Tests for the ChartCollisionApp application handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from chart_collision_detector.applications.chart_collision_app import ChartCollisionApp


@pytest.fixture
def mock_event_with_patient() -> MagicMock:
    """Create a mock event with patient and user context."""
    event = MagicMock()
    event.context = {
        "patient": {"id": "patient-uuid-123"},
        "user": {"id": "staff-uuid-456"},
    }
    return event


@pytest.fixture
def mock_event_no_patient() -> MagicMock:
    """Create a mock event without patient context."""
    event = MagicMock()
    event.context = {
        "user": {"id": "staff-uuid-456"},
    }
    return event


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create a mock cache object."""
    cache = MagicMock()
    cache.get.return_value = None
    return cache


class TestOnOpen:
    """Tests for ChartCollisionApp.on_open()."""

    def test_on_open_no_patient_context_returns_none(
        self, mock_event_no_patient: MagicMock
    ) -> None:
        """When no patient context, on_open returns None."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.log"
        ):
            app = ChartCollisionApp(event=mock_event_no_patient)
            result = app.on_open()

            assert result is None

    def test_on_open_no_collision_returns_none(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When no collision, on_open registers user and returns None."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.log"
            ):
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = None  # No existing viewers

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app.on_open()

                assert result is None
                # Verify cache was set with list containing current user
                mock_cache.set.assert_called_once_with(
                    "chart_viewers:patient-uuid-123",
                    json.dumps(["staff-uuid-456"]),
                    timeout_seconds=300,
                )

    def test_on_open_collision_returns_warning_modal(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When collision detected, on_open returns warning modal."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.log"
            ):
                with patch(
                    "chart_collision_detector.applications.chart_collision_app.LaunchModalEffect"
                ) as mock_modal_effect:
                    with patch(
                        "chart_collision_detector.applications.chart_collision_app.Staff"
                    ) as mock_staff:
                        with patch(
                            "chart_collision_detector.applications.chart_collision_app.render_to_string"
                        ) as mock_render:
                            mock_get_cache.return_value = mock_cache
                            # Another user already viewing
                            mock_cache.get.return_value = json.dumps(
                                ["other-staff-uuid-789"]
                            )

                            # Mock Staff query
                            mock_staff.objects.filter.return_value.values_list.return_value = [
                                ("Jane", "Doe")
                            ]

                            mock_render.return_value = "<html>rendered</html>"

                            mock_effect = MagicMock()
                            mock_modal_effect.return_value.apply.return_value = (
                                mock_effect
                            )

                            app = ChartCollisionApp(event=mock_event_with_patient)
                            result = app.on_open()

                            # Verify warning modal returned
                            assert result is mock_effect

                            # Verify cache was updated with both users
                            mock_cache.set.assert_called_once_with(
                                "chart_viewers:patient-uuid-123",
                                json.dumps(["other-staff-uuid-789", "staff-uuid-456"]),
                                timeout_seconds=300,
                            )

                            # Verify Staff was queried for viewer names
                            mock_staff.objects.filter.assert_called_once_with(
                                id__in=["other-staff-uuid-789"]
                            )

                            # Verify render_to_string was called with viewer names
                            mock_render.assert_called_once_with(
                                "templates/warning_modal.html",
                                {"viewers": ["Jane Doe"]},
                            )

                            # Verify LaunchModalEffect was called correctly
                            mock_modal_effect.assert_called_once()
                            call_kwargs = mock_modal_effect.call_args[1]
                            assert call_kwargs["title"] == "Chart Collision Detected"


class TestOnContextChange:
    """Tests for ChartCollisionApp.on_context_change()."""

    def test_on_context_change_no_patient_context_returns_none(
        self, mock_event_no_patient: MagicMock
    ) -> None:
        """When no patient context, on_context_change returns None."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.log"
        ):
            app = ChartCollisionApp(event=mock_event_no_patient)
            result = app.on_context_change()

            assert result is None

    def test_on_context_change_no_collision_returns_none(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When no collision, on_context_change registers user and returns None."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.log"
            ):
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = None

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app.on_context_change()

                assert result is None
                mock_cache.set.assert_called_once_with(
                    "chart_viewers:patient-uuid-123",
                    json.dumps(["staff-uuid-456"]),
                    timeout_seconds=300,
                )

    def test_on_context_change_collision_returns_warning_modal(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When collision detected, on_context_change returns warning modal."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.log"
            ):
                with patch(
                    "chart_collision_detector.applications.chart_collision_app.LaunchModalEffect"
                ) as mock_modal_effect:
                    with patch(
                        "chart_collision_detector.applications.chart_collision_app.Staff"
                    ) as mock_staff:
                        with patch(
                            "chart_collision_detector.applications.chart_collision_app.render_to_string"
                        ):
                            mock_get_cache.return_value = mock_cache
                            mock_cache.get.return_value = json.dumps(
                                ["other-staff-uuid-789"]
                            )

                            mock_staff.objects.filter.return_value.values_list.return_value = [
                                ("Jane", "Doe")
                            ]

                            mock_effect = MagicMock()
                            mock_modal_effect.return_value.apply.return_value = (
                                mock_effect
                            )

                            app = ChartCollisionApp(event=mock_event_with_patient)
                            result = app.on_context_change()

                            assert result is mock_effect


class TestCheckCollisionAndWarn:
    """Tests for ChartCollisionApp._check_collision_and_warn()."""

    def test_no_event_returns_none(self) -> None:
        """When event is None, returns None."""
        mock_event = MagicMock()
        mock_event.context = {}

        app = ChartCollisionApp(event=mock_event)
        app.event = None

        with patch(
            "chart_collision_detector.applications.chart_collision_app.log"
        ):
            result = app._check_collision_and_warn()
            assert result is None

    def test_missing_staff_id_returns_none(self) -> None:
        """When user has no id, returns None."""
        mock_event = MagicMock()
        mock_event.context = {
            "patient": {"id": "patient-uuid-123"},
            "user": {},  # No id key
        }

        with patch(
            "chart_collision_detector.applications.chart_collision_app.log"
        ):
            app = ChartCollisionApp(event=mock_event)
            result = app._check_collision_and_warn()

            assert result is None

    def test_same_user_does_not_duplicate_in_list(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When same user is already in list, don't add duplicate."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.log"
            ):
                mock_get_cache.return_value = mock_cache
                # Same user already in list
                mock_cache.get.return_value = json.dumps(["staff-uuid-456"])

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app._check_collision_and_warn()

                # No warning since only current user
                assert result is None

                # List should still only have one entry
                mock_cache.set.assert_called_once_with(
                    "chart_viewers:patient-uuid-123",
                    json.dumps(["staff-uuid-456"]),
                    timeout_seconds=300,
                )

    def test_multiple_other_viewers_shows_all_names(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When multiple other viewers, modal shows all their names."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.log"
            ):
                with patch(
                    "chart_collision_detector.applications.chart_collision_app.LaunchModalEffect"
                ) as mock_modal_effect:
                    with patch(
                        "chart_collision_detector.applications.chart_collision_app.Staff"
                    ) as mock_staff:
                        with patch(
                            "chart_collision_detector.applications.chart_collision_app.render_to_string"
                        ) as mock_render:
                            mock_get_cache.return_value = mock_cache
                            # Two other users already viewing
                            mock_cache.get.return_value = json.dumps(
                                ["staff-A", "staff-B"]
                            )

                            mock_staff.objects.filter.return_value.values_list.return_value = [
                                ("Alice", "Smith"),
                                ("Bob", "Jones"),
                            ]

                            mock_render.return_value = "<html>rendered</html>"

                            mock_effect = MagicMock()
                            mock_modal_effect.return_value.apply.return_value = (
                                mock_effect
                            )

                            app = ChartCollisionApp(event=mock_event_with_patient)
                            result = app._check_collision_and_warn()

                            assert result is mock_effect

                            # Verify render_to_string was called with both viewer names
                            mock_render.assert_called_once_with(
                                "templates/warning_modal.html",
                                {"viewers": ["Alice Smith", "Bob Jones"]},
                            )

    def test_invalid_cache_value_resets_list(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When cache has invalid JSON, reset to empty list."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.log"
            ) as mock_log:
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = "invalid json{"

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app._check_collision_and_warn()

                # Should succeed with just current user
                assert result is None

                # Warning should be logged
                assert any(
                    "Invalid cache value" in str(c) for c in mock_log.mock_calls
                )


class TestCreateWarningModal:
    """Tests for the _create_warning_modal method."""

    def test_modal_single_viewer(self, mock_event_with_patient: MagicMock) -> None:
        """Verify modal is created with single viewer name."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.LaunchModalEffect"
        ) as mock_modal_effect:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.render_to_string"
            ) as mock_render:
                mock_render.return_value = "<html>rendered</html>"
                mock_effect = MagicMock()
                mock_modal_effect.return_value.apply.return_value = mock_effect

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app._create_warning_modal(["Jane Doe"])

                mock_render.assert_called_once_with(
                    "templates/warning_modal.html",
                    {"viewers": ["Jane Doe"]},
                )
                assert result == mock_effect

    def test_modal_multiple_viewers(self, mock_event_with_patient: MagicMock) -> None:
        """Verify modal is created with multiple viewer names."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.LaunchModalEffect"
        ) as mock_modal_effect:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.render_to_string"
            ) as mock_render:
                mock_render.return_value = "<html>rendered</html>"
                mock_effect = MagicMock()
                mock_modal_effect.return_value.apply.return_value = mock_effect

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app._create_warning_modal(
                    ["Alice Smith", "Bob Jones", "Carol White"]
                )

                mock_render.assert_called_once_with(
                    "templates/warning_modal.html",
                    {"viewers": ["Alice Smith", "Bob Jones", "Carol White"]},
                )
                assert result == mock_effect

    def test_modal_uses_correct_title(self, mock_event_with_patient: MagicMock) -> None:
        """Verify modal uses 'Chart Collision Detected' as title."""
        with patch(
            "chart_collision_detector.applications.chart_collision_app.LaunchModalEffect"
        ) as mock_modal_effect:
            with patch(
                "chart_collision_detector.applications.chart_collision_app.render_to_string"
            ):
                mock_effect = MagicMock()
                mock_modal_effect.return_value.apply.return_value = mock_effect

                app = ChartCollisionApp(event=mock_event_with_patient)
                app._create_warning_modal(["Jane Doe"])

                call_kwargs = mock_modal_effect.call_args[1]
                assert call_kwargs["title"] == "Chart Collision Detected"
