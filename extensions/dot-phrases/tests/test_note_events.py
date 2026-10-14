from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from canvas_sdk.events import EventType

from dot_phrases.handlers.note_events import BlockUnfinished, ExpandPhrases, leftovers_key

MODULE = "dot_phrases.handlers.note_events"


def phrase(dbid: int, code: str, text: str, use_in: list[str] | None = None, sig: bool = False, ntp: bool = False) -> Any:
    return SimpleNamespace(dbid=dbid, code=code, text=text, use_in=use_in, rx_sig=sig, rx_note_to_pharmacist=ntp)


PHRASES = {
    "metf500": phrase(1, "metf500", "Take 1 tablet by mouth twice daily with meals", use_in=[], sig=True),
    "kneehpi": phrase(2, "kneehpi", "{first_name} reports {pick side: right | left} knee pain. ***", use_in=["hpi"]),
    "fallprec": phrase(3, "fallprec", "Discussed fall precautions with {first_name}."),
}


class FakeCache:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, timeout_seconds: int | None = None) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


def event(event_type: int, fields: dict[str, Any], target: str = "cmd-1") -> Any:
    return SimpleNamespace(type=event_type, context={"fields": fields}, target=SimpleNamespace(id=target))


@pytest.fixture
def env() -> Any:
    cache = FakeCache()
    command = SimpleNamespace(state="staged", patient=None, note=None, originator_id=7)
    with (
        patch(f"{MODULE}.get_cache", return_value=cache),
        patch(f"{MODULE}.Command") as command_model,
        patch(f"{MODULE}.Staff") as staff_model,
        patch(f"{MODULE}.usable_phrases", return_value=PHRASES) as usable,
        patch(f"{MODULE}.placeholder_values", return_value={"first_name": "Jane"}),
        patch(f"{MODULE}.record_use") as record_use,
    ):
        command_model.objects.filter.return_value.select_related.return_value.defer.return_value.first.return_value = command
        command_model.objects.filter.return_value.first.return_value = command
        staff_model.objects.filter.return_value.values_list.return_value.first.return_value = 42
        yield SimpleNamespace(cache=cache, command=command, usable=usable, record_use=record_use)


def payload(effect: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(effect.payload)["data"]
    return data


class TestExpandPhrases:
    def test_metf500_in_a_sig_becomes_the_phrase(self, env: Any) -> None:
        effects = ExpandPhrases(event(EventType.PRESCRIBE_COMMAND__POST_UPDATE, {"sig": ".metf500"})).compute()
        assert len(effects) == 1
        assert payload(effects[0])["sig"] == "Take 1 tablet by mouth twice daily with meals"
        env.record_use.assert_called_once_with([1])

    def test_creators_personal_phrases_are_used(self, env: Any) -> None:
        ExpandPhrases(event(EventType.PLAN_COMMAND__POST_UPDATE, {"narrative": ".fallprec"})).compute()
        env.usable.assert_called_once_with(42)

    def test_plan_expands_and_fills_the_patient(self, env: Any) -> None:
        effects = ExpandPhrases(event(EventType.PLAN_COMMAND__POST_UPDATE, {"narrative": ".fallprec"})).compute()
        assert payload(effects[0])["narrative"] == "Discussed fall precautions with Jane."

    def test_instruct_comment_uses_the_sdk_field_name(self, env: Any) -> None:
        effects = ExpandPhrases(event(EventType.INSTRUCT_COMMAND__POST_UPDATE, {"narrative": ".fallprec"})).compute()
        assert payload(effects[0])["comment"] == "Discussed fall precautions with Jane."

    def test_leftover_fill_ins_are_remembered_for_validation(self, env: Any) -> None:
        ExpandPhrases(event(EventType.HISTORY_OF_PRESENT_ILLNESS_COMMAND__POST_UPDATE, {"narrative": ".kneehpi"})).compute()
        assert env.cache.data[leftovers_key("cmd-1")] == ["[right / left]"]

    def test_no_codes_means_no_database_work(self, env: Any) -> None:
        assert ExpandPhrases(event(EventType.PLAN_COMMAND__POST_UPDATE, {"narrative": "Take .5 mL"})).compute() == []
        env.usable.assert_not_called()

    def test_command_that_is_no_longer_staged_is_left_alone(self, env: Any) -> None:
        env.command.state = "committed"
        assert ExpandPhrases(event(EventType.PLAN_COMMAND__POST_UPDATE, {"narrative": ".fallprec"})).compute() == []

    def test_same_edit_is_never_retried(self, env: Any) -> None:
        handler_event = event(EventType.PLAN_COMMAND__POST_UPDATE, {"narrative": ".fallprec"})
        assert len(ExpandPhrases(handler_event).compute()) == 1
        assert ExpandPhrases(handler_event).compute() == []


    def test_retyping_the_same_code_after_it_expanded_expands_again(self, env: Any) -> None:
        plan = EventType.PLAN_COMMAND__POST_UPDATE
        assert ExpandPhrases(event(plan, {"narrative": ".fallprec"})).compute()
        # The edit lands, so the next save has no code in it; then the provider types the code again.
        assert ExpandPhrases(event(plan, {"narrative": "Discussed fall precautions with Jane."})).compute() == []
        assert ExpandPhrases(event(plan, {"narrative": ".fallprec"})).compute()

    def test_phrases_that_fit_alone_but_not_together_stay_as_typed(self, env: Any) -> None:
        long_one = phrase(8, "long", "x" * 300)
        with patch(f"{MODULE}.usable_phrases", return_value={**PHRASES, "long": long_one}):
            effects = ExpandPhrases(event(EventType.ALLERGY_COMMAND__POST_UPDATE, {"narrative": ".long .long"})).compute()
        assert effects == []


    def test_sig_phrase_fills_patient_details_and_leaves_fill_ins(self, env: Any) -> None:
        taper = phrase(12, "taper", "Take {blank count} tablets for {first_name}", use_in=[], sig=True)
        with patch(f"{MODULE}.usable_phrases", return_value={**PHRASES, "taper": taper}):
            effects = ExpandPhrases(event(EventType.PRESCRIBE_COMMAND__POST_UPDATE, {"sig": ".taper"})).compute()
        assert payload(effects[0])["sig"] == "Take [count] tablets for Jane"
        assert env.cache.get(leftovers_key("cmd-1")) == ["[count]"]

    def test_sig_phrase_that_no_longer_fits_once_filled_stays_as_typed(self, env: Any) -> None:
        accent = phrase(13, "accent", "For {first_name}", use_in=[], sig=True)
        with (
            patch(f"{MODULE}.usable_phrases", return_value={**PHRASES, "accent": accent}),
            patch(f"{MODULE}.placeholder_values", return_value={"first_name": "José"}),
        ):
            assert ExpandPhrases(event(EventType.PRESCRIBE_COMMAND__POST_UPDATE, {"sig": ".accent"})).compute() == []


class TestBlockUnfinished:
    def errors(self, effects: list[Any]) -> list[str]:
        assert len(effects) == 1
        return [e["message"] for e in payload(effects[0])["errors"]]

    def test_typo_blocks_review(self, env: Any) -> None:
        effects = BlockUnfinished(event(EventType.PRESCRIBE_COMMAND__POST_VALIDATION, {"sig": "Take daily .typo"})).compute()
        assert self.errors(effects) == ["Sig: .typo is not a saved phrase. Fix or remove it."]

    def test_half_ml_passes(self, env: Any) -> None:
        assert BlockUnfinished(event(EventType.PRESCRIBE_COMMAND__POST_VALIDATION, {"sig": "Take .5 mL daily"})).compute() == []

    def test_phrase_not_set_up_for_the_sig_blocks_review(self, env: Any) -> None:
        effects = BlockUnfinished(event(EventType.PRESCRIBE_COMMAND__POST_VALIDATION, {"sig": ".fallprec"})).compute()
        assert self.errors(effects) == ["Sig: .fallprec isn't set up for the Sig. Type the text instead."]

    def test_phrase_not_set_up_for_this_command(self, env: Any) -> None:
        effects = BlockUnfinished(event(EventType.PLAN_COMMAND__POST_VALIDATION, {"narrative": ".kneehpi"})).compute()
        assert self.errors(effects) == [".kneehpi isn't set up for Plan."]

    def test_leftover_brackets_and_stars_block_recording(self, env: Any) -> None:
        env.cache.data[leftovers_key("cmd-1")] = ["[right / left]"]
        text = "Jane reports [right / left] knee pain. ***"
        effects = BlockUnfinished(event(EventType.HISTORY_OF_PRESENT_ILLNESS_COMMAND__POST_VALIDATION, {"narrative": text})).compute()
        assert self.errors(effects) == ["Fill in [right / left].", "Fill in the blank marked ***."]

    def test_filled_in_command_passes(self, env: Any) -> None:
        env.cache.data[leftovers_key("cmd-1")] = ["[right / left]"]
        text = "Jane reports left knee pain. Stiff in the morning."
        assert BlockUnfinished(event(EventType.HISTORY_OF_PRESENT_ILLNESS_COMMAND__POST_VALIDATION, {"narrative": text})).compute() == []

    def test_too_long_after_filling_says_so(self, env: Any) -> None:
        near = phrase(9, "near", "x" * 508 + " {first_name}")
        with patch(f"{MODULE}.usable_phrases", return_value={**PHRASES, "near": near}), patch(f"{MODULE}.placeholder_values", return_value={"first_name": "Jane"}):
            result = BlockUnfinished(event(EventType.ALLERGY_COMMAND__POST_VALIDATION, {"narrative": ".near"})).compute()
        assert ".near is too long for Allergy: 513 characters, and the limit is 512." in payload(result[0])["errors"][0]["message"]

    def test_too_long_together_says_so(self, env: Any) -> None:
        half = phrase(10, "half", "x" * 300)
        with patch(f"{MODULE}.usable_phrases", return_value={**PHRASES, "half": half}):
            result = BlockUnfinished(event(EventType.ALLERGY_COMMAND__POST_VALIDATION, {"narrative": ".half .half"})).compute()
        assert "Together, the phrases here are over the 512-character limit for Allergy." in payload(result[0])["errors"][0]["message"]

    def test_sig_phrases_too_long_together_give_a_reason(self, env: Any) -> None:
        big = phrase(11, "big", "x" * 600, use_in=[], sig=True)
        with patch(f"{MODULE}.usable_phrases", return_value={**PHRASES, "big": big}):
            result = BlockUnfinished(event(EventType.PRESCRIBE_COMMAND__POST_VALIDATION, {"sig": ".big .big"})).compute()
        message = payload(result[0])["errors"][0]["message"]
        assert "Together, the phrases in the Sig are over 1,000 characters." in message
        assert ": ." not in message

    def test_unfilled_fill_ins_in_a_sig_block_review_and_send(self, env: Any) -> None:
        env.cache.set(leftovers_key("cmd-1"), ["[count]"])
        result = BlockUnfinished(event(EventType.PRESCRIBE_COMMAND__POST_VALIDATION, {"sig": "Take [count] tablets ***"})).compute()
        messages = [e["message"] for e in payload(result[0])["errors"]]
        assert "Sig: Fill in [count]." in messages
        assert "Sig: Fill in the blank marked ***." in messages

    def test_filled_in_sig_passes(self, env: Any) -> None:
        env.cache.set(leftovers_key("cmd-1"), ["[count]"])
        assert BlockUnfinished(event(EventType.PRESCRIBE_COMMAND__POST_VALIDATION, {"sig": "Take 2 tablets daily"})).compute() == []

    def test_review_commands_are_not_registered(self) -> None:
        assert EventType.Name(EventType.PLAN_COMMAND__POST_VALIDATION) in BlockUnfinished.RESPONDS_TO
        assert "LAB_REVIEW_COMMAND__POST_VALIDATION" not in BlockUnfinished.RESPONDS_TO


def test_expand_listens_to_every_supported_command() -> None:
    assert len(ExpandPhrases.RESPONDS_TO) == 32
    assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_UPDATE) in ExpandPhrases.RESPONDS_TO
