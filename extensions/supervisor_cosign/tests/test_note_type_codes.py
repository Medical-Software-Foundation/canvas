"""Tests for how COSIGN_NOTE_TYPE_CODES is read and which notes it admits."""

from types import SimpleNamespace

import pytest

from supervisor_cosign.helpers.note_type_codes import (
    note_type_eligible,
    parse_cosign_note_type_codes,
)

TREATMENT_CODES = frozenset({"officevisit", "followup", "newpatienteval"})


def make_note(code: str, name: str = "") -> SimpleNamespace:
    return SimpleNamespace(note_type_version=SimpleNamespace(code=code, name=name))


@pytest.mark.parametrize(
    "raw",
    [
        '["office_visit", "follow_up", "new_patient_eval"]',
        "office_visit, follow_up, new_patient_eval",
        "[office_visit, follow_up, new_patient_eval]",
        "['office_visit', 'follow_up', 'new_patient_eval']",
        ' [ "office_visit","follow_up",,"new_patient_eval" ] ',
    ],
)
def test_array_and_comma_forms_parse_to_the_same_codes(raw: str) -> None:
    assert parse_cosign_note_type_codes({"COSIGN_NOTE_TYPE_CODES": raw}) == TREATMENT_CODES


@pytest.mark.parametrize("raw", ["", "[]", "  ", None])
def test_empty_values_parse_to_no_codes(raw) -> None:
    assert parse_cosign_note_type_codes({"COSIGN_NOTE_TYPE_CODES": raw}) == frozenset()


def test_json_array_ignores_non_string_and_blank_entries() -> None:
    secrets = {"COSIGN_NOTE_TYPE_CODES": '["office_visit", "", null, 42]'}
    assert parse_cosign_note_type_codes(secrets) == frozenset({"officevisit", "42"})


def test_listed_treatment_note_type_is_eligible() -> None:
    secrets = {"COSIGN_NOTE_TYPE_CODES": '["office_visit", "follow_up"]'}
    assert note_type_eligible(make_note("follow_up"), secrets) is True


def test_unlisted_note_type_is_ineligible_when_array_is_set() -> None:
    secrets = {"COSIGN_NOTE_TYPE_CODES": '["office_visit", "follow_up"]'}
    assert note_type_eligible(make_note("107728002", "Chart review"), secrets) is False


def test_match_is_exact_after_normalizing() -> None:
    secrets = {"COSIGN_NOTE_TYPE_CODES": '["visit"]'}
    assert note_type_eligible(make_note("office_visit"), secrets) is False


def test_unset_secret_admits_every_note_type() -> None:
    assert note_type_eligible(make_note("107728002"), {}) is True
