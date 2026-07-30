"""Tests for BlockDuplicateCodingGapHandler and its helpers."""

from unittest.mock import Mock, patch

from canvas_sdk.events import EventType

from duplicate_coding_gap_validation.handlers.duplicate_coding_gap_validation import (
    ACTIVE_CONDITION_MESSAGE,
    DUPLICATE_GAP_MESSAGE,
    RESOLVED_CONDITION_MESSAGE,
    BlockDuplicateCodingGapHandler,
    has_duplicate_coding_gap,
    matching_condition_statuses,
)
from tests.conftest import (
    make_command,
    make_coding,
    make_condition,
    make_detected_issue,
    make_diagnose_entry,
    make_patient,
    wire_condition_queryset,
)

HANDLER_MODULE = "duplicate_coding_gap_validation.handlers.duplicate_coding_gap_validation"


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def test_responds_to_create_coding_gap_post_validation() -> None:
    """The handler subscribes to the Create Coding Gap post-validation event."""
    assert (
        EventType.Name(EventType.CREATE_CODING_GAP_COMMAND__POST_VALIDATION)
        in BlockDuplicateCodingGapHandler.RESPONDS_TO
    )


# --------------------------------------------------------------------------- #
# _selected_icd10s — coding-gap-specific extraction from the `diagnose` field
# --------------------------------------------------------------------------- #
def test_selected_icd10s_reads_code_and_display_from_extra_coding() -> None:
    """The ICD-10 code and display come from each pick's extra.coding entry."""
    data = {"diagnose": [make_diagnose_entry("G47.30", display="Sleep apnea")]}
    assert BlockDuplicateCodingGapHandler._selected_icd10s(data) == [("G47.30", "Sleep apnea")]


def test_selected_icd10s_handles_multiple_picks() -> None:
    """All selected diagnoses (max_selections=10) are returned."""
    data = {
        "diagnose": [
            make_diagnose_entry("E11.65", display="T2DM w/ hyperglycemia"),
            make_diagnose_entry("I10", display="Hypertension"),
        ]
    }
    assert BlockDuplicateCodingGapHandler._selected_icd10s(data) == [
        ("E11.65", "T2DM w/ hyperglycemia"),
        ("I10", "Hypertension"),
    ]


def test_selected_icd10s_falls_back_to_top_level_value() -> None:
    """When no ICD-10 coding is present, the top-level value is used as the code."""
    entry = {"text": "Some dx", "value": "E11.65", "extra": {"coding": []}}
    assert BlockDuplicateCodingGapHandler._selected_icd10s({"diagnose": [entry]}) == [
        ("E11.65", "Some dx")
    ]


def test_selected_icd10s_wraps_single_dict_and_ignores_non_icd10_coding() -> None:
    """A single dict is treated as one pick; a non-ICD-10 coding falls back to value."""
    entry = {
        "text": "Dx",
        "value": "E1165",
        "extra": {"coding": [{"code": "44054006", "system": "http://snomed.info/sct"}]},
    }
    assert BlockDuplicateCodingGapHandler._selected_icd10s({"diagnose": entry}) == [
        ("E1165", "Dx")
    ]


def test_selected_icd10s_empty_when_no_diagnose() -> None:
    """No diagnose field yields no selections."""
    assert BlockDuplicateCodingGapHandler._selected_icd10s({}) == []


# --------------------------------------------------------------------------- #
# Condition matching
# --------------------------------------------------------------------------- #
@patch(f"{HANDLER_MODULE}.Condition")
def test_matching_condition_statuses_returns_matching_status(mock_condition) -> None:
    """A committed condition sharing an ICD-10 code contributes its clinical status."""
    wire_condition_queryset(mock_condition, [make_condition("active", [make_coding("E11.65")])])
    assert matching_condition_statuses("patient-1", {"E1165"}) == {"active"}


@patch(f"{HANDLER_MODULE}.Condition")
def test_matching_condition_statuses_ignores_non_matching_codes(mock_condition) -> None:
    """Conditions with different codes do not match."""
    wire_condition_queryset(mock_condition, [make_condition("active", [make_coding("I10")])])
    assert matching_condition_statuses("patient-1", {"E1165"}) == set()


# --------------------------------------------------------------------------- #
# Existing coding gap (DetectedIssue) matching
# --------------------------------------------------------------------------- #
def test_has_duplicate_coding_gap_matches_normalized() -> None:
    """A coding gap's evidence code matches on the normalized ICD-10 (dotted DB value)."""
    patient = make_patient(detected_issues=[make_detected_issue(["E11.65"])])
    assert has_duplicate_coding_gap(patient, {"E1165"}) is True


def test_has_duplicate_coding_gap_false_when_no_overlap() -> None:
    """No overlapping evidence code returns False."""
    patient = make_patient(detected_issues=[make_detected_issue(["I10"])])
    assert has_duplicate_coding_gap(patient, {"E1165"}) is False


# --------------------------------------------------------------------------- #
# compute() — blocking behavior
# --------------------------------------------------------------------------- #
def _handler_for() -> BlockDuplicateCodingGapHandler:
    event = Mock()
    event.target.id = "coding-gap-command-1"
    return BlockDuplicateCodingGapHandler(event=event)


@patch(f"{HANDLER_MODULE}.CommandValidationErrorEffect")
@patch(f"{HANDLER_MODULE}.Condition")
@patch(f"{HANDLER_MODULE}.Command")
def test_blocks_when_active_condition_documented(
    mock_command, mock_condition, mock_effect_cls
) -> None:
    """An active documented condition blocks with the active-condition message."""
    mock_command.objects.get.return_value = make_command([make_diagnose_entry("E11.65")])
    wire_condition_queryset(mock_condition, [make_condition("active", [make_coding("E1165")])])

    effects = _handler_for().compute()

    assert len(effects) == 1
    mock_effect_cls.return_value.add_error.assert_called_once_with(ACTIVE_CONDITION_MESSAGE)


@patch(f"{HANDLER_MODULE}.CommandValidationErrorEffect")
@patch(f"{HANDLER_MODULE}.Condition")
@patch(f"{HANDLER_MODULE}.Command")
def test_blocks_when_resolved_condition_documented(
    mock_command, mock_condition, mock_effect_cls
) -> None:
    """A resolved documented condition blocks with the reactivate message."""
    mock_command.objects.get.return_value = make_command([make_diagnose_entry("E11.65")])
    wire_condition_queryset(mock_condition, [make_condition("resolved", [make_coding("E1165")])])

    effects = _handler_for().compute()

    assert len(effects) == 1
    mock_effect_cls.return_value.add_error.assert_called_once_with(RESOLVED_CONDITION_MESSAGE)


@patch(f"{HANDLER_MODULE}.CommandValidationErrorEffect")
@patch(f"{HANDLER_MODULE}.Condition")
@patch(f"{HANDLER_MODULE}.Command")
def test_blocks_when_duplicate_coding_gap_exists(
    mock_command, mock_condition, mock_effect_cls
) -> None:
    """No matching condition but an existing coding gap blocks with the duplicate-gap message."""
    patient = make_patient(detected_issues=[make_detected_issue(["E11.65"])])
    mock_command.objects.get.return_value = make_command(
        [make_diagnose_entry("E11.65")], patient=patient
    )
    wire_condition_queryset(mock_condition, [])  # no matching condition

    effects = _handler_for().compute()

    assert len(effects) == 1
    mock_effect_cls.return_value.add_error.assert_called_once_with(DUPLICATE_GAP_MESSAGE)


# --------------------------------------------------------------------------- #
# compute() — allow behavior
# --------------------------------------------------------------------------- #
@patch(f"{HANDLER_MODULE}.Condition")
@patch(f"{HANDLER_MODULE}.Command")
def test_allows_when_no_condition_and_no_gap(mock_command, mock_condition) -> None:
    """No matching condition and no existing gap allows the commit."""
    patient = make_patient(detected_issues=[make_detected_issue(["I10"])])
    mock_command.objects.get.return_value = make_command(
        [make_diagnose_entry("E11.65")], patient=patient
    )
    wire_condition_queryset(mock_condition, [make_condition("active", [make_coding("I10")])])

    assert _handler_for().compute() == []


@patch(f"{HANDLER_MODULE}.Command")
def test_allows_when_no_icd10_selected(mock_command) -> None:
    """A command whose diagnose picks carry no ICD-10 fails open (no block)."""
    entry = {"text": "Dx", "value": "", "extra": {"coding": []}}
    mock_command.objects.get.return_value = make_command([entry])
    assert _handler_for().compute() == []


@patch(f"{HANDLER_MODULE}.Command")
def test_allows_when_command_has_no_patient(mock_command) -> None:
    """A command with no patient fails open (no block)."""
    mock_command.objects.get.return_value = make_command(
        [make_diagnose_entry("E11.65")], patient=None
    )
    assert _handler_for().compute() == []
