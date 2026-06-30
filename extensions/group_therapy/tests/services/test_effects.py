"""Tests for group_therapy.services.effects builders."""

from unittest.mock import patch

from group_therapy.services.effects import (
    billing_applies,
    build_checkin_effects,
    build_documentation_effects,
    build_no_show_effects,
)

_EFFECTS = "group_therapy.services.effects"
_META = [("Provider", "Dr. A"), ("Date", "2026-06-27")]
_SECTIONS = [("How session was conducted", "Virtual"), ("Assessment", "Stable")]


def _doc(**over):
    kwargs = dict(
        target_note_id="note-123", meta_pairs=_META, summary_sections=_SECTIONS,
        condition_id="cond-1", billing_mode="group", cpt_code="90853",
        sign=False, participant_index=0,
    )
    kwargs.update(over)
    return build_documentation_effects(**kwargs)


def test_billing_per_participant_always_true():
    assert billing_applies("per_participant", 0) is True
    assert billing_applies("per_participant", 3) is True


def test_billing_group_only_first():
    assert billing_applies("group", 0) is True
    assert billing_applies("group", 1) is False


@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_documentation_targets_existing_note_no_create(mock_custom, mock_assess, mock_perform):
    effects = _doc()
    assert not any("CREATE_NOTE" in str(getattr(e, "type", "")) for e in effects)
    assert mock_custom.return_value.note_uuid == "note-123"
    mock_assess.assert_called_once_with(note_uuid="note-123", condition_id="cond-1", narrative="")
    mock_perform.assert_called_once_with(note_uuid="note-123", cpt_code="90853")


@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_perform_commit_precedes_assess_commit(mock_custom, mock_assess, mock_perform):
    mock_perform.return_value.commit.return_value = "PERFORM_COMMIT"
    mock_assess.return_value.commit.return_value = "ASSESS_COMMIT"
    effects = _doc()
    assert effects.index("PERFORM_COMMIT") < effects.index("ASSESS_COMMIT")


@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_no_condition_skips_assess(mock_custom, mock_assess, mock_perform):
    _doc(condition_id=None, billing_mode="per_participant", participant_index=2)
    mock_assess.assert_not_called()


@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_group_billing_skips_perform_for_non_first(mock_custom, mock_assess, mock_perform):
    _doc(participant_index=1)
    mock_perform.assert_not_called()


@patch(f"{_EFFECTS}.build_command")
@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_questionnaire_specs_originate_populated_commands(mock_custom, mock_assess, mock_perform, mock_build):
    cmd = mock_build.return_value
    cmd.originate.return_value = "Q_ORIG"
    effects = _doc(condition_id=None, questionnaire_specs=[
        {"code": "QUES_0014", "answers": {"q1": "Good"}},
    ])
    mock_build.assert_called_once_with("QUES_0014", "note-123", {"q1": "Good"})
    assert "Q_ORIG" in effects
    # originated for provider review, not committed
    cmd.commit.assert_not_called()


@patch(f"{_EFFECTS}.build_command")
@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_unresolved_questionnaire_is_skipped(mock_custom, mock_assess, mock_perform, mock_build):
    mock_build.return_value = None
    # condition off + non-first attendee (group billing) -> only the summary remains
    effects = _doc(condition_id=None, participant_index=1,
                   questionnaire_specs=[{"code": "missing", "answers": {}}])
    assert len(effects) == 1  # unresolved questionnaire added nothing


@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_sign_true_emits_lock_and_sign(mock_custom, mock_assess, mock_perform):
    types = [str(getattr(e, "type", "")) for e in _doc(condition_id=None, sign=True)]
    assert "LOCK_NOTE" in types and "SIGN_NOTE" in types


@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_sign_false_omits_lock_and_sign(mock_custom, mock_assess, mock_perform):
    types = [str(getattr(e, "type", "")) for e in _doc(condition_id=None)]
    assert "LOCK_NOTE" not in types and "SIGN_NOTE" not in types


@patch(f"{_EFFECTS}.Note")
@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_check_in_prepended_when_needed(mock_custom, mock_assess, mock_perform, mock_note):
    mock_note.return_value.check_in.return_value = "CHECKIN"
    mock_custom.return_value.originate.return_value = "CUSTOM_ORIG"
    effects = _doc(condition_id=None, check_in=True)
    assert effects[0] == "CHECKIN"
    assert effects.index("CHECKIN") < effects.index("CUSTOM_ORIG")


@patch(f"{_EFFECTS}.Note")
@patch(f"{_EFFECTS}.PerformCommand")
@patch(f"{_EFFECTS}.AssessCommand")
@patch(f"{_EFFECTS}.CustomCommand")
def test_no_check_in_by_default(mock_custom, mock_assess, mock_perform, mock_note):
    _doc(condition_id=None)
    mock_note.assert_not_called()


@patch(f"{_EFFECTS}.Note")
def test_no_show_effects_marks_appointment_note(mock_note):
    mock_note.return_value.no_show.return_value = "NO_SHOW_EFFECT"
    effects = build_no_show_effects("note-9")
    mock_note.assert_called_once_with(instance_id="note-9")
    assert effects == ["NO_SHOW_EFFECT"]


@patch(f"{_EFFECTS}.Note")
def test_checkin_effects_checks_in_note(mock_note):
    mock_note.return_value.check_in.return_value = "CHECKIN_EFFECT"
    effects = build_checkin_effects("note-9")
    mock_note.assert_called_once_with(instance_id="note-9")
    assert effects == ["CHECKIN_EFFECT"]
