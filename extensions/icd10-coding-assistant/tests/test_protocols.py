"""Tests for AssessConditionValidation and UpdateAssessAfterChangeDiagnosis protocols."""

from unittest.mock import MagicMock, patch

import pytest

from icd10_coding_assistant.protocols.assess_condition_validation import (
    AssessConditionValidation,
    UpdateAssessAfterChangeDiagnosis,
)


# ---------------------------------------------------------------------------
# AssessConditionValidation
# ---------------------------------------------------------------------------


@pytest.fixture
def assess_event_no_condition() -> MagicMock:
    event = MagicMock()
    event.context = {"fields": {"condition": None}}
    return event


@pytest.fixture
def assess_event_with_condition() -> MagicMock:
    event = MagicMock()
    event.context = {
        "fields": {
            "condition": {"value": 42},
        },
        "note": {"uuid": "note-uuid-1"},
    }
    return event


def test_assess_validation_no_condition_returns_empty(
    assess_event_no_condition: MagicMock,
) -> None:
    """If condition field is absent or falsy, return [] (no-op)."""
    handler = AssessConditionValidation(assess_event_no_condition)
    result = handler.compute()
    assert result == []


def test_assess_validation_passes_when_icd10_present(
    assess_event_with_condition: MagicMock,
) -> None:
    """No validation error when the condition already has an ICD-10 coding."""
    handler = AssessConditionValidation(assess_event_with_condition)

    with patch(
        "icd10_coding_assistant.protocols.assess_condition_validation.ConditionCoding"
    ) as mock_cc:
        mock_cc.objects.filter.return_value.exists.return_value = True
        result = handler.compute()

    assert result == []


def test_assess_validation_blocks_when_no_icd10(
    assess_event_with_condition: MagicMock,
) -> None:
    """Validation error emitted when condition has no ICD-10 coding."""
    handler = AssessConditionValidation(assess_event_with_condition)

    with patch(
        "icd10_coding_assistant.protocols.assess_condition_validation.ConditionCoding"
    ) as mock_cc:
        mock_cc.objects.filter.return_value.exists.return_value = False

        with patch(
            "icd10_coding_assistant.protocols.assess_condition_validation.CommandValidationErrorEffect"
        ) as mock_effect_cls:
            mock_effect = MagicMock()
            mock_effect_cls.return_value = mock_effect

            result = handler.compute()

    assert len(result) == 1
    mock_effect.add_error.assert_called_once()
    mock_effect.apply.assert_called_once()


def test_assess_validation_filters_by_dbid(
    assess_event_with_condition: MagicMock,
) -> None:
    """ConditionCoding lookup must use condition_id (dbid), not condition__id."""
    handler = AssessConditionValidation(assess_event_with_condition)

    with patch(
        "icd10_coding_assistant.protocols.assess_condition_validation.ConditionCoding"
    ) as mock_cc:
        mock_cc.objects.filter.return_value.exists.return_value = True
        handler.compute()

    filter_kwargs = mock_cc.objects.filter.call_args[1]
    # Must filter on condition_id (dbid) not condition__id (external key)
    assert "condition_id" in filter_kwargs
    assert filter_kwargs["condition_id"] == 42


def test_assess_validation_excludes_entered_in_error(
    assess_event_with_condition: MagicMock,
) -> None:
    """Entered-in-error codings must be excluded from the check."""
    handler = AssessConditionValidation(assess_event_with_condition)

    with patch(
        "icd10_coding_assistant.protocols.assess_condition_validation.ConditionCoding"
    ) as mock_cc:
        mock_cc.objects.filter.return_value.exists.return_value = True
        handler.compute()

    filter_kwargs = mock_cc.objects.filter.call_args[1]
    assert "condition__entered_in_error__isnull" in filter_kwargs
    assert filter_kwargs["condition__entered_in_error__isnull"] is True


# ---------------------------------------------------------------------------
# UpdateAssessAfterChangeDiagnosis
# ---------------------------------------------------------------------------


@pytest.fixture
def update_diag_event() -> MagicMock:
    event = MagicMock()
    event.context = {
        "fields": {
            "condition": {"value": 42},
            "new_condition": {"value": "E11.9"},
        },
        "patient": {"id": "patient-abc"},
    }
    return event


def test_update_assess_returns_empty_when_no_new_coding(
    update_diag_event: MagicMock,
) -> None:
    """If no ConditionCoding found, return [] rather than crashing on None.first()."""
    handler = UpdateAssessAfterChangeDiagnosis(update_diag_event)

    with patch(
        "icd10_coding_assistant.protocols.assess_condition_validation.ConditionCoding"
    ) as mock_cc:
        mock_cc.objects.filter.return_value.order_by.return_value.first.return_value = (
            None
        )

        result = handler.compute()

    assert result == []


def test_update_assess_re_points_open_commands(
    update_diag_event: MagicMock,
) -> None:
    """Open staged assess commands get re-pointed to the new condition."""
    handler = UpdateAssessAfterChangeDiagnosis(update_diag_event)

    mock_new_coding = MagicMock()
    mock_new_coding.condition.id = "new-condition-uuid"

    mock_assess_cmd = MagicMock()
    mock_assess_cmd.id = "cmd-uuid-1"

    with patch(
        "icd10_coding_assistant.protocols.assess_condition_validation.ConditionCoding"
    ) as mock_cc:
        mock_cc.objects.filter.return_value.order_by.return_value.first.return_value = (
            mock_new_coding
        )

        with patch(
            "icd10_coding_assistant.protocols.assess_condition_validation.Command"
        ) as mock_cmd_cls:
            mock_cmd_cls.objects.filter.return_value = [mock_assess_cmd]

            with patch(
                "icd10_coding_assistant.protocols.assess_condition_validation.AssessCommand"
            ) as mock_assess_cls:
                mock_edit_effect = MagicMock()
                mock_assess_cls.return_value.edit.return_value = mock_edit_effect

                result = handler.compute()

    assert len(result) == 1
    mock_assess_cls.assert_called_once_with(
        command_uuid="cmd-uuid-1",
        condition_id="new-condition-uuid",
    )
    mock_assess_cls.return_value.edit.assert_called_once()


def test_update_assess_excludes_entered_in_error_codings(
    update_diag_event: MagicMock,
) -> None:
    """ConditionCoding lookup for new condition must exclude entered_in_error."""
    handler = UpdateAssessAfterChangeDiagnosis(update_diag_event)

    with patch(
        "icd10_coding_assistant.protocols.assess_condition_validation.ConditionCoding"
    ) as mock_cc:
        mock_cc.objects.filter.return_value.order_by.return_value.first.return_value = (
            None
        )
        handler.compute()

    filter_kwargs = mock_cc.objects.filter.call_args[1]
    assert "condition__entered_in_error__isnull" in filter_kwargs
    assert filter_kwargs["condition__entered_in_error__isnull"] is True
