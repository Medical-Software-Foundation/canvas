"""Tests for the ChartCollisionApp application handler."""

from unittest.mock import MagicMock, call, patch

import pytest

from chart_collision_detector.protocols.chart_collision_app import ChartCollisionApp


@pytest.fixture
def mock_event_with_patient() -> MagicMock:
    """Create a mock event with patient and user context."""
    event = MagicMock()
    event.context = {
        "patient": {"id": "patient-uuid-123"},
        "user": {"staff": "staff-uuid-456"},
    }
    return event


@pytest.fixture
def mock_event_no_patient() -> MagicMock:
    """Create a mock event without patient context."""
    event = MagicMock()
    event.context = {
        "user": {"staff": "staff-uuid-456"},
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
            "chart_collision_detector.protocols.chart_collision_app.log"
        ) as mock_log:
            app = ChartCollisionApp(event=mock_event_no_patient)
            result = app.on_open()

            assert result is None
            assert mock_log.mock_calls == [
                call.info("ChartCollisionApp: No patient context available")
            ]

    def test_on_open_no_collision_returns_none(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When no collision, on_open registers user and returns None."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ) as mock_log:
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = None

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app.on_open()

                assert result is None
                mock_cache.set.assert_called_once_with(
                    "chart_viewer:patient-uuid-123",
                    "staff-uuid-456",
                    timeout_seconds=300,
                )
                assert mock_log.mock_calls == [
                    call.info(
                        "ChartCollisionApp: Staff staff-uuid-456 now viewing patient patient-uuid-123"
                    )
                ]

    def test_on_open_collision_returns_warning_modal(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When collision detected, on_open returns warning modal."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ):
                with patch(
                    "chart_collision_detector.protocols.chart_collision_app.LaunchModalEffect"
                ) as mock_modal_effect:
                    mock_get_cache.return_value = mock_cache
                    mock_cache.get.return_value = "other-staff-uuid-789"

                    mock_effect = MagicMock()
                    mock_modal_effect.return_value.apply.return_value = mock_effect

                    app = ChartCollisionApp(event=mock_event_with_patient)
                    result = app.on_open()

                    # Verify result is the modal effect
                    assert result is mock_effect
                    mock_cache.set.assert_not_called()

                    # Verify LaunchModalEffect was called with warning content
                    mock_modal_effect.assert_called_once()
                    call_kwargs = mock_modal_effect.call_args[1]
                    assert "Chart In Use" in call_kwargs["content"]
                    assert call_kwargs["title"] == "Chart Warning"


class TestOnContextChange:
    """Tests for ChartCollisionApp.on_context_change()."""

    def test_on_context_change_no_patient_context_returns_none(
        self, mock_event_no_patient: MagicMock
    ) -> None:
        """When no patient context, on_context_change returns None."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.log"
        ) as mock_log:
            app = ChartCollisionApp(event=mock_event_no_patient)
            result = app.on_context_change()

            assert result is None
            assert mock_log.mock_calls == [
                call.info("ChartCollisionApp: No patient context available")
            ]

    def test_on_context_change_no_collision_returns_none(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When no collision, on_context_change registers user and returns None."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ) as mock_log:
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = None

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app.on_context_change()

                assert result is None
                mock_cache.set.assert_called_once_with(
                    "chart_viewer:patient-uuid-123",
                    "staff-uuid-456",
                    timeout_seconds=300,
                )

    def test_on_context_change_collision_returns_warning_modal(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When collision detected, on_context_change returns warning modal."""
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

                    app = ChartCollisionApp(event=mock_event_with_patient)
                    result = app.on_context_change()

                    assert result == mock_effect
                    mock_cache.set.assert_not_called()


class TestCheckCollisionAndWarn:
    """Tests for ChartCollisionApp._check_collision_and_warn()."""

    def test_no_event_returns_none(self) -> None:
        """When event is None, returns None."""
        mock_event = MagicMock()
        mock_event.context = {}

        app = ChartCollisionApp(event=mock_event)
        app.event = None

        with patch(
            "chart_collision_detector.protocols.chart_collision_app.log"
        ):
            result = app._check_collision_and_warn()
            assert result is None

    def test_missing_patient_id_returns_none(self) -> None:
        """When patient dict exists but has no ID, returns None."""
        mock_event = MagicMock()
        mock_event.context = {
            "patient": {"name": "Test Patient"},  # Has data but no id key
            "user": {"staff": "staff-uuid-456"},
        }

        with patch(
            "chart_collision_detector.protocols.chart_collision_app.log"
        ) as mock_log:
            app = ChartCollisionApp(event=mock_event)
            result = app._check_collision_and_warn()

            assert result is None
            assert mock_log.mock_calls == [
                call.info("ChartCollisionApp: No patient ID in context")
            ]

    def test_missing_staff_id_returns_none(self, mock_cache: MagicMock) -> None:
        """When user has no staff key, returns None and logs warning."""
        mock_event = MagicMock()
        mock_event.context = {
            "patient": {"id": "patient-uuid-123"},
            "user": {},  # No staff key
        }

        with patch(
            "chart_collision_detector.protocols.chart_collision_app.log"
        ) as mock_log:
            app = ChartCollisionApp(event=mock_event)
            result = app._check_collision_and_warn()

            assert result is None
            assert len(mock_log.mock_calls) == 1
            assert mock_log.mock_calls[0][0] == "warning"

    def test_same_user_refreshes_ttl_returns_none(
        self, mock_event_with_patient: MagicMock, mock_cache: MagicMock
    ) -> None:
        """When same user is already cached, refresh TTL and return None."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.get_cache"
        ) as mock_get_cache:
            with patch(
                "chart_collision_detector.protocols.chart_collision_app.log"
            ) as mock_log:
                mock_get_cache.return_value = mock_cache
                mock_cache.get.return_value = "staff-uuid-456"  # Same user

                app = ChartCollisionApp(event=mock_event_with_patient)
                result = app._check_collision_and_warn()

                assert result is None
                mock_cache.set.assert_called_once_with(
                    "chart_viewer:patient-uuid-123",
                    "staff-uuid-456",
                    timeout_seconds=300,
                )
                # No logging for same user refresh
                assert mock_log.mock_calls == []


class TestCreateWarningModal:
    """Tests for the _create_warning_modal method."""

    def test_modal_contains_expected_content(
        self, mock_event_with_patient: MagicMock
    ) -> None:
        """Verify the warning modal contains expected HTML content."""
        with patch(
            "chart_collision_detector.protocols.chart_collision_app.LaunchModalEffect"
        ) as mock_modal_effect:
            mock_effect = MagicMock()
            mock_modal_effect.return_value.apply.return_value = mock_effect

            app = ChartCollisionApp(event=mock_event_with_patient)
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
