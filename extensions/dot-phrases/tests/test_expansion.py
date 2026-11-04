from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dot_phrases.catalog import DEFAULT_USE_IN, NOTE_COMMAND_KEYS, works_in
from dot_phrases.expansion import expand_note_field, expand_rx_field


def phrase(dbid: int, code: str, text: str, use_in: list[str] | None = None, sig: bool = False, ntp: bool = False) -> Any:
    return SimpleNamespace(dbid=dbid, code=code, text=text, use_in=use_in, rx_sig=sig, rx_note_to_pharmacist=ntp)


PHRASES = {
    "metf500": phrase(1, "metf500", "Take 1 tablet by mouth twice daily with meals", use_in=[], sig=True),
    "kneehpi": phrase(2, "kneehpi", "{first_name} reports {pick side: right | left} knee pain.", use_in=["hpi"]),
    "fallprec": phrase(3, "fallprec", "Discussed fall precautions with {first_name}."),
    "gennote": phrase(4, "gennote", "Generic substitution is OK.", use_in=[], ntp=True),
    "longntp": phrase(5, "longntp", "x" * 211, use_in=[], ntp=True),
    "allergylong": phrase(6, "allergylong", "y" * 600),
}
VALUES = {"first_name": "Jane"}


class TestNoteFields:
    def test_expands_a_phrase_and_fills_the_patient_name(self) -> None:
        result = expand_note_field("Plan: .fallprec", PHRASES, VALUES, "plan")
        assert result.text == "Plan: Discussed fall precautions with Jane."
        assert result.used == (3,)

    def test_choice_comes_in_as_a_bracket_to_fill(self) -> None:
        result = expand_note_field(".kneehpi", PHRASES, VALUES, "hpi")
        assert result.text == "Jane reports [right / left] knee pain."
        assert result.leftovers == ("[right / left]",)

    def test_code_stays_when_the_phrase_is_not_set_up_for_this_command(self) -> None:
        result = expand_note_field(".kneehpi", PHRASES, VALUES, "plan")
        assert result.text == ".kneehpi"
        assert result.used == ()

    def test_code_stays_when_the_text_is_too_long_for_the_field(self) -> None:
        result = expand_note_field(".allergylong", PHRASES, VALUES, "allergy")
        assert result.text == ".allergylong"

    def test_review_commands_expand_phrases_with_fill_ins_too(self) -> None:
        phrases = {
            "kneehpi": phrase(2, "kneehpi", "Side {pick s: a | b}", use_in=["labreview"]),
            "fallprec": phrase(3, "fallprec", "Discussed fall precautions with {first_name}.", use_in=["plan", "labreview"]),
        }
        result = expand_note_field(".kneehpi .fallprec", phrases, VALUES, "labreview")
        assert result.text == "Side [a / b] Discussed fall precautions with Jane."

    @pytest.mark.parametrize("review", ["labreview", "imgreview", "refreview", "docreview"])
    def test_default_phrases_stay_as_typed_in_review_commands(self, review: str) -> None:
        assert expand_note_field(".fallprec", PHRASES, VALUES, review).text == ".fallprec"

    def test_default_phrases_expand_in_other_note_commands(self) -> None:
        assert expand_note_field(".fallprec", PHRASES, VALUES, "goal").text == "Discussed fall precautions with Jane."

    def test_unknown_codes_stay(self) -> None:
        assert expand_note_field("See .typo", PHRASES, VALUES, "plan").text == "See .typo"


class TestPrescriptionFields:
    def test_metf500_in_a_sig_becomes_the_phrase(self) -> None:
        result = expand_rx_field(".metf500", PHRASES, "sig")
        assert result.text == "Take 1 tablet by mouth twice daily with meals"
        assert result.used == (1,)

    def test_phrase_not_checked_for_the_sig_stays(self) -> None:
        assert expand_rx_field(".fallprec", PHRASES, "sig").text == ".fallprec"

    def test_211_character_phrase_is_refused_for_note_to_pharmacist(self) -> None:
        assert expand_rx_field(".longntp", PHRASES, "note_to_pharmacist").text == ".longntp"

    def test_note_to_pharmacist_phrase(self) -> None:
        assert expand_rx_field(".gennote", PHRASES, "note_to_pharmacist").text == "Generic substitution is OK."

    def test_half_ml_sig_is_left_alone(self) -> None:
        assert expand_rx_field("Take .5 mL daily", PHRASES, "sig").text == "Take .5 mL daily"


class TestDefaultUseIn:
    def test_default_leaves_out_orders_referrals_and_reviews(self) -> None:
        off = {"laborder", "imaging", "refer", "labreview", "imgreview", "refreview", "docreview"}
        assert set(NOTE_COMMAND_KEYS) - DEFAULT_USE_IN == off

    def test_checklist_default_matches_the_server_default(self) -> None:
        # The Use in checklist starts with USE_GROUPS_IN checked; it has to match DEFAULT_USE_IN.
        script = (Path(__file__).parent.parent / "dot_phrases/static/shared/use_in.js").read_text()
        block = script[script.index("var USE_GROUPS_IN") : script.index("var USE_GROUPS_OUT")]
        assert set(re.findall(r'"([a-z]+)"', block)) - {"Visit", "Conditions", "Medications", "Allergies", "History", "Goals"} == DEFAULT_USE_IN

    def test_default_phrases_stay_as_typed_in_orders(self) -> None:
        for key in ("laborder", "imaging", "refer"):
            assert expand_note_field(".fallprec", PHRASES, VALUES, key).text == ".fallprec"

    def test_works_in_follows_the_default_or_the_list(self) -> None:
        assert works_in(None, "plan") and not works_in(None, "labreview")
        assert works_in(["labreview"], "labreview") and not works_in(["labreview"], "plan")
