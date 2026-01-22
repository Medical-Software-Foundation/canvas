"""Tests for the ChartCollisionApp application handler."""

from unittest.mock import MagicMock, call, patch

import pytest

from chart_collision_detector.protocols.chart_collision_app import ChartCollisionApp


@pytest.fixture
def mock_init_event() -> MagicMock:
    """Create a mock event for initializing the handler."""
    return MagicMock()


class TestOnOpen:
    """Tests for ChartCollisionApp.on_open()."""

    def test_on_open_returns_launch_modal_effect(
        self, mock_init_event: MagicMock
    ) -> None:
        """on_open should return a LaunchModalEffect for the app panel."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.LaunchModalEffect"
        ) as mock_modal_effect:
            mock_effect = MagicMock()
            mock_modal_effect.return_value.apply.return_value = mock_effect

            app = ChartCollisionApp(event=mock_init_event)
            result = app.on_open()

            # Verify LaunchModalEffect was called correctly
            assert len(mock_modal_effect.mock_calls) == 2  # __init__ and apply

            init_call = mock_modal_effect.mock_calls[0]
            assert "content" in init_call[2]
            assert "Chart Collision Monitor" in init_call[2]["content"]
            assert init_call[2]["title"] == "Chart Monitor"
            assert (
                init_call[2]["target"]
                == mock_modal_effect.TargetType.RIGHT_CHART_PANE
            )

            # Verify result
            assert result == mock_effect


class TestOnContextChange:
    """Tests for ChartCollisionApp.on_context_change()."""

    def test_non_patient_url_returns_none(
        self, mock_init_event: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When URL doesn't contain /patient/, return None."""
        mock_init_event.context = {
            "url": "/appointments/list",
            "user": {"staff": "staff-uuid-456"},
        }

        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            app = ChartCollisionApp(event=mock_init_event)

            result = app.on_context_change()

            # Verify cache was never accessed
            assert mock_get_cache.mock_calls == []

            # Verify result
            assert result is None

    def test_missing_patient_context_returns_none(
        self, mock_init_event: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When patient context is missing, return None."""
        mock_init_event.context = {
            "url": "/patient/123/chart",
            "user": {"staff": "staff-uuid-456"},
            # No patient key
        }

        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            app = ChartCollisionApp(event=mock_init_event)

            result = app.on_context_change()

            # Verify cache was never accessed
            assert mock_get_cache.mock_calls == []

            # Verify result
            assert result is None

    def test_missing_patient_id_returns_none(
        self, mock_init_event: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When patient ID is missing, return None."""
        mock_init_event.context = {
            "url": "/patient/123/chart",
            "patient": {},  # Empty patient dict
            "user": {"staff": "staff-uuid-456"},
        }

        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            app = ChartCollisionApp(event=mock_init_event)

            result = app.on_context_change()

            # Verify cache was never accessed
            assert mock_get_cache.mock_calls == []

            # Verify result
            assert result is None

    def test_missing_staff_id_returns_none(
        self, mock_init_event: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When staff ID is missing, return None and log warning."""
        mock_init_event.context = {
            "url": "/patient/patient-uuid-123/chart",
            "patient": {"id": "patient-uuid-123"},
            "user": {},  # No staff key
        }

        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ) as mock_log:
                app = ChartCollisionApp(event=mock_init_event)

                result = app.on_context_change()

                # Verify cache was never accessed
                assert mock_get_cache.mock_calls == []

                # Verify warning was logged
                assert len(mock_log.mock_calls) == 1
                assert mock_log.mock_calls[0][0] == "warning"

                # Verify result
                assert result is None

    def test_no_existing_viewer_caches_current_user(
        self, mock_event: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When no one is viewing, cache the current user and return None."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ) as mock_log:
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = None  # No existing viewer

                app = ChartCollisionApp(event=mock_event)

                result = app.on_context_change()

                # Verify get_cache was called
                mock_get_cache.assert_called_once()

                # Verify cache.get was called with the correct key
                mock_cache.get.assert_called_once_with("chart_viewer:patient-uuid-123")

                # Verify cache.set was called to register the viewer
                mock_cache.set.assert_called_once_with(
                    "chart_viewer:patient-uuid-123",
                    "staff-uuid-456",
                    timeout_seconds=300,
                )

                # Verify mock_log
                assert mock_log.mock_calls == [
                    call.info(
                        "ChartCollisionApp: Staff staff-uuid-456 now viewing patient patient-uuid-123"
                    )
                ]

                # Verify result
                assert result is None

    def test_same_viewer_refreshes_ttl(
        self, mock_event: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When the same user reloads, refresh the TTL and return None."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ) as mock_log:
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = "staff-uuid-456"  # Same user

                app = ChartCollisionApp(event=mock_event)

                result = app.on_context_change()

                # Verify get_cache was called
                mock_get_cache.assert_called_once()

                # Verify cache.get was called
                mock_cache.get.assert_called_once_with("chart_viewer:patient-uuid-123")

                # Verify cache.set was called to refresh TTL
                mock_cache.set.assert_called_once_with(
                    "chart_viewer:patient-uuid-123",
                    "staff-uuid-456",
                    timeout_seconds=300,
                )

                # Verify no logging for same user
                assert mock_log.mock_calls == []

                # Verify result
                assert result is None

    def test_different_viewer_shows_warning_modal(
        self, mock_event: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When a different user views, show a warning modal."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ) as mock_log:
                with patch(
                    "chart_collision_detector.protocols.chart_collision_app.LaunchModalEffect"
                ) as mock_modal_effect:
                    mock_get_cache.return_value = mock_cache
                    mock_cache.get.return_value = "other-staff-uuid-789"

                    mock_effect = MagicMock()
                    mock_modal_effect.return_value.apply.return_value = mock_effect

                    app = ChartCollisionApp(event=mock_event)

                    result = app.on_context_change()

                    # Verify get_cache was called
                    mock_get_cache.assert_called_once()

                    # Verify cache.get was called
                    mock_cache.get.assert_called_once_with("chart_viewer:patient-uuid-123")

                    # Verify cache.set was NOT called (don't overwrite existing viewer)
                    mock_cache.set.assert_not_called()

                    # Verify collision was logged
                    assert mock_log.mock_calls == [
                        call.info(
                            "ChartCollisionApp: Collision detected - "
                            "staff staff-uuid-456 viewing patient patient-uuid-123 "
                            "already being viewed by other-staff-uuid-789"
                        )
                    ]

                    # Verify LaunchModalEffect was called
                    assert len(mock_modal_effect.mock_calls) == 2
                    init_call = mock_modal_effect.mock_calls[0]
                    assert "Chart In Use" in init_call[2]["content"]
                    assert init_call[2]["title"] == "Chart Warning"
                    assert (
                        init_call[2]["target"]
                        == mock_modal_effect.TargetType.DEFAULT_MODAL
                    )

                    # Verify result
                    assert result == mock_effect

    def test_no_event_returns_none(self, mock_init_event: MagicMock) -> None:
        """When event context is empty, return None gracefully."""
        mock_init_event.context = {}

        app = ChartCollisionApp(event=mock_init_event)
        # Simulate event being set to one with no context
        app.event = MagicMock()
        app.event.context = {}

        result = app.on_context_change()

        assert result is None


class TestCreateWarningModal:
    """Tests for the _create_warning_modal method."""

    def test_modal_contains_expected_content(
        self, mock_init_event: MagicMock
    ) -> None:
        """Verify the warning modal contains expected HTML content."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.LaunchModalEffect"
        ) as mock_modal_effect:
            mock_effect = MagicMock()
            mock_modal_effect.return_value.apply.return_value = mock_effect

            app = ChartCollisionApp(event=mock_init_event)
            result = app._create_warning_modal()

            # Verify LaunchModalEffect was instantiated correctly
            assert len(mock_modal_effect.mock_calls) == 2
            init_call = mock_modal_effect.mock_calls[0]

            # Check content contains key elements
            content = init_call[2]["content"]
            assert "Chart In Use" in content
            assert "Another user is currently viewing" in content
            assert "concurrent editing may cause conflicts" in content

            # Check title and target
            assert init_call[2]["title"] == "Chart Warning"
            assert (
                init_call[2]["target"]
                == mock_modal_effect.TargetType.DEFAULT_MODAL
            )

            # Verify result
            assert result == mock_effect


class TestGetAppHtml:
    """Tests for the _get_app_html method."""

    def test_app_html_contains_expected_content(
        self, mock_init_event: MagicMock
    ) -> None:
        """Verify the app HTML contains expected content."""
        app = ChartCollisionApp(event=mock_init_event)
        html = app._get_app_html()

        assert "Chart Collision Monitor" in html
        assert "monitors patient chart access" in html
        assert "Monitoring active" in html
