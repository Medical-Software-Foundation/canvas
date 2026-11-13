from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import Effect
from canvas_sdk.v1.data.note import NoteStates

from review_all_prescriptions_button.handlers.review_all_prescriptions import (
    ENABLED_VARIABLE,
    ReviewAllPrescriptionsButton,
)

MODULE = "review_all_prescriptions_button.handlers.review_all_prescriptions"


def _button(
    enabled: str | None = "true", note_id: object = 101
) -> ReviewAllPrescriptionsButton:
    event = MagicMock()
    event.context = {"note_id": note_id}
    secrets = {} if enabled is None else {ENABLED_VARIABLE: enabled}
    return ReviewAllPrescriptionsButton(event=event, secrets=secrets)


def _cmd(
    schema_key: str = "prescribe",
    uuid: str = "11111111-1111-1111-1111-111111111111",
    compound: bool = False,
    value: object = 244899,
) -> SimpleNamespace:
    """A staged command row shaped like Canvas stores it."""
    extra: dict = {"coding": []}
    if compound:
        extra["is_compound_medication"] = True
    return SimpleNamespace(
        id=uuid,
        schema_key=schema_key,
        data={"prescribe": {"text": "med", "extra": extra, "value": value}},
    )


def _note_state(state: str = NoteStates.UNLOCKED) -> MagicMock:
    mock = MagicMock()
    mock.objects.get.return_value = SimpleNamespace(state=state)
    mock.DoesNotExist = type("DoesNotExist", (Exception,), {})
    return mock


def _run(button, cmds, not_controlled_dbids=(), note_state=None):
    with (
        patch(f"{MODULE}.CurrentNoteStateEvent", note_state or _note_state()),
        patch(f"{MODULE}.Command") as mock_command,
        patch(f"{MODULE}.CompoundMedication") as mock_compound,
    ):
        mock_command.objects.filter.return_value.order_by.return_value = cmds
        mock_compound.objects.filter.return_value.values_list.return_value = list(
            not_controlled_dbids
        )
        effects = button.handle()
    return effects, mock_command, mock_compound


class TestVisibility:
    @pytest.mark.parametrize("value", [None, "", "false", "yes", "1", " TRUE-ish "])
    def test_hidden_unless_explicitly_enabled(self, value):
        with patch(f"{MODULE}.CurrentNoteStateEvent", _note_state()):
            assert _button(enabled=value).visible() is False

    @pytest.mark.parametrize("value", ["true", "True", " TRUE "])
    def test_visible_when_enabled_and_note_open(self, value):
        with patch(f"{MODULE}.CurrentNoteStateEvent", _note_state()) as mock_state:
            assert _button(enabled=value).visible() is True
        mock_state.objects.get.assert_called_once_with(note__dbid=101)

    def test_hidden_on_locked_note(self):
        with patch(f"{MODULE}.CurrentNoteStateEvent", _note_state(NoteStates.LOCKED)):
            assert _button().visible() is False

    def test_hidden_when_note_state_missing(self):
        state = _note_state()
        state.objects.get.side_effect = state.DoesNotExist
        with patch(f"{MODULE}.CurrentNoteStateEvent", state):
            assert _button().visible() is False

    def test_hidden_without_note_id(self):
        assert _button(note_id=None).visible() is False


class TestHandle:
    def test_reviews_each_staged_prescribe_command(self):
        cmds = [_cmd("prescribe", "a" * 32), _cmd("prescribe", "b" * 32)]
        effects, mock_command, mock_compound = _run(_button(), cmds)

        assert [e.type for e in effects] == [
            Effect(type="REVIEW_PRESCRIBE_COMMAND").type,
            Effect(type="REVIEW_PRESCRIBE_COMMAND").type,
        ]
        filter_kwargs = mock_command.objects.filter.call_args.kwargs
        assert filter_kwargs["note__dbid"] == 101
        assert filter_kwargs["state"] == "staged"
        assert filter_kwargs["entered_in_error__isnull"] is True
        mock_compound.objects.filter.assert_not_called()

    def test_only_prescribe_commands_are_queried(self):
        """SDK docs: review() works on Prescribe only, so Refill and Adjust are not touched."""
        _, mock_command, _ = _run(_button(), [])
        assert list(mock_command.objects.filter.call_args.kwargs["schema_key__in"]) == [
            "prescribe"
        ]

    def test_review_effect_targets_the_command(self):
        effects, _, _ = _run(_button(), [_cmd(uuid="d" * 32)])
        assert "d" * 32 in effects[0].payload

    def test_no_staged_prescriptions_returns_nothing(self):
        effects, _, _ = _run(_button(), [])
        assert effects == []

    @pytest.mark.parametrize("enabled", [None, "false"])
    def test_does_nothing_when_disabled(self, enabled):
        effects, mock_command, _ = _run(_button(enabled=enabled), [_cmd()])
        assert effects == []
        mock_command.objects.filter.assert_not_called()

    def test_does_nothing_on_locked_note(self):
        effects, mock_command, _ = _run(
            _button(), [_cmd()], note_state=_note_state(NoteStates.LOCKED)
        )
        assert effects == []
        mock_command.objects.filter.assert_not_called()

    def test_does_nothing_without_note_id(self):
        effects, mock_command, _ = _run(_button(note_id=None), [_cmd()])
        assert effects == []
        mock_command.objects.filter.assert_not_called()


class TestControlledCompounds:
    def test_skips_scheduled_compound_and_reviews_the_rest(self):
        cmds = [
            _cmd(
                uuid="a" * 32, compound=True, value=7
            ),  # scheduled (not in not-controlled set)
            _cmd(uuid="b" * 32, compound=True, value=8),  # schedule "N"
            _cmd(uuid="c" * 32),  # FDB-coded
        ]
        effects, _, mock_compound = _run(_button(), cmds, not_controlled_dbids=[8])

        assert len(effects) == 2
        assert "a" * 32 not in "".join(e.payload for e in effects)
        kwargs = mock_compound.objects.filter.call_args.kwargs
        assert kwargs["dbid__in"] == {7, 8}
        assert kwargs["controlled_substance"] == "N"

    def test_compound_not_found_is_skipped(self):
        effects, _, _ = _run(
            _button(), [_cmd(compound=True, value=99)], not_controlled_dbids=[]
        )
        assert effects == []

    def test_compound_without_readable_id_is_skipped(self):
        effects, _, _ = _run(
            _button(),
            [_cmd(compound=True, value="not-an-int")],
            not_controlled_dbids=[],
        )
        assert effects == []

    @pytest.mark.parametrize(
        "data",
        [None, {}, {"prescribe": "text"}, {"prescribe": {"extra": None}}],
    )
    def test_non_compound_shapes_are_reviewed(self, data):
        cmd = SimpleNamespace(id="e" * 32, schema_key="prescribe", data=data)
        effects, _, mock_compound = _run(_button(), [cmd])
        assert len(effects) == 1
        mock_compound.objects.filter.assert_not_called()
