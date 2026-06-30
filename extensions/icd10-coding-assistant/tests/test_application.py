"""Tests for ICD10CodingApplication."""

from unittest.mock import MagicMock, patch

import pytest

from icd10_coding_assistant.applications.icd10_application import ICD10CodingApplication


@pytest.fixture
def app_instance(mock_event: MagicMock) -> ICD10CodingApplication:
    mock_event.context = {"patient": {"id": "patient-abc"}}
    app = ICD10CodingApplication(mock_event)
    return app


# ------------------------------------------------------------------
# on_open
# ------------------------------------------------------------------


def test_on_open_launches_default_modal(
    app_instance: ICD10CodingApplication,
) -> None:
    """on_open must return a LaunchModalEffect targeting DEFAULT_MODAL."""
    from canvas_sdk.effects.launch_modal import LaunchModalEffect

    # Capture the real TargetType value before patching replaces the class
    expected_target = LaunchModalEffect.TargetType.DEFAULT_MODAL

    with patch(
        "icd10_coding_assistant.applications.icd10_application.LaunchModalEffect"
    ) as mock_modal:
        mock_effect = MagicMock()
        mock_modal.return_value.apply.return_value = mock_effect
        # Make TargetType on the mock return the real enum so the handler gets the right value
        mock_modal.TargetType = LaunchModalEffect.TargetType

        result = app_instance.on_open()

    mock_modal.assert_called_once()
    call_kwargs = mock_modal.call_args[1]
    assert "patient-abc" in call_kwargs["url"]
    assert call_kwargs["target"] == expected_target
    assert result == mock_effect


def test_on_open_url_contains_correct_plugin_prefix(
    app_instance: ICD10CodingApplication,
) -> None:
    """URL must use the correct plugin path prefix."""
    with patch(
        "icd10_coding_assistant.applications.icd10_application.LaunchModalEffect"
    ) as mock_modal:
        mock_modal.return_value.apply.return_value = MagicMock()
        app_instance.on_open()

    url: str = mock_modal.call_args[1]["url"]
    assert "/plugin-io/api/icd10_coding_assistant/ui/icd10-coding" in url


# ------------------------------------------------------------------
# compute_notification_badge
# ------------------------------------------------------------------


def test_compute_notification_badge_returns_count_when_conditions_missing(
    app_instance: ICD10CodingApplication,
) -> None:
    """Badge should return the number of uncoded conditions."""
    mock_cache = MagicMock()
    mock_cache.get_or_set.side_effect = lambda key, fn, **kw: fn()

    with patch(
        "icd10_coding_assistant.applications.icd10_application.get_cache",
        return_value=mock_cache,
    ):
        with patch(
            "icd10_coding_assistant.applications.icd10_application.get_conditions_missing_icd10",
            return_value=[MagicMock(), MagicMock()],
        ):
            result = app_instance.compute_notification_badge()

    assert result == 2


def test_compute_notification_badge_returns_none_when_all_coded(
    app_instance: ICD10CodingApplication,
) -> None:
    """Badge should return None (no badge) when all conditions are coded."""
    mock_cache = MagicMock()
    mock_cache.get_or_set.side_effect = lambda key, fn, **kw: fn()

    with patch(
        "icd10_coding_assistant.applications.icd10_application.get_cache",
        return_value=mock_cache,
    ):
        with patch(
            "icd10_coding_assistant.applications.icd10_application.get_conditions_missing_icd10",
            return_value=[],
        ):
            result = app_instance.compute_notification_badge()

    assert result is None


def test_compute_notification_badge_returns_none_when_no_patient(
    mock_event: MagicMock,
) -> None:
    """Badge should return None if patient context is missing."""
    mock_event.context = {}
    app = ICD10CodingApplication(mock_event)

    result = app.compute_notification_badge()

    assert result is None


def test_compute_notification_badge_uses_cache(
    app_instance: ICD10CodingApplication,
) -> None:
    """Badge should call get_or_set with a patient-scoped key."""
    mock_cache = MagicMock()
    mock_cache.get_or_set.return_value = 3

    with patch(
        "icd10_coding_assistant.applications.icd10_application.get_cache",
        return_value=mock_cache,
    ):
        result = app_instance.compute_notification_badge()

    assert mock_cache.get_or_set.call_count == 1
    call_key: str = mock_cache.get_or_set.call_args[0][0]
    assert "patient-abc" in call_key
    assert result == 3
