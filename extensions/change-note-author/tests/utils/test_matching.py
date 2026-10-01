"""Unit tests for the pure helpers that drive Chart Review detection and the staff
picker labels. These run without a live Canvas instance."""

from change_note_author.utils.matching import (
    DEFAULT_CHART_REVIEW_NOTE_TYPE_NAME,
    initials,
    is_chart_review_note_type,
    staff_display_name,
    staff_subtitle,
)


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeStaff:
    def __init__(
        self,
        credentialed_name=None,
        full_name=None,
        first_name="",
        last_name="",
        top_clinical_role=None,
        top_role_abbreviation=None,
    ):
        self.credentialed_name = credentialed_name
        self.full_name = full_name
        self.first_name = first_name
        self.last_name = last_name
        self.top_clinical_role = top_clinical_role
        self.top_role_abbreviation = top_role_abbreviation


# ---- is_chart_review_note_type -------------------------------------------------

def test_exact_match_default_name():
    assert is_chart_review_note_type("Chart Review", None) is True


def test_case_and_whitespace_insensitive():
    assert is_chart_review_note_type("  chart review  ", "Chart Review") is True


def test_non_chart_review_note_type_is_hidden():
    assert is_chart_review_note_type("Office Visit", "Chart Review") is False


def test_configured_custom_name_matches():
    assert is_chart_review_note_type("Records Review", "Records Review") is True


def test_configured_custom_name_rejects_default():
    # When a custom name is configured, the old default should no longer match.
    assert is_chart_review_note_type("Chart Review", "Records Review") is False


def test_blank_configured_name_falls_back_to_default():
    assert is_chart_review_note_type("Chart Review", "   ") is True
    assert DEFAULT_CHART_REVIEW_NOTE_TYPE_NAME == "Chart Review"


def test_missing_note_type_name_is_false():
    assert is_chart_review_note_type(None, "Chart Review") is False
    assert is_chart_review_note_type("", "Chart Review") is False


# ---- staff_display_name --------------------------------------------------------

def test_prefers_credentialed_name():
    staff = _FakeStaff(credentialed_name="Larry Weed MD", full_name="Larry Weed")
    assert staff_display_name(staff) == "Larry Weed MD"


def test_falls_back_to_full_name():
    staff = _FakeStaff(full_name="Larry Weed")
    assert staff_display_name(staff) == "Larry Weed"


def test_falls_back_to_first_last():
    staff = _FakeStaff(first_name="Larry", last_name="Weed")
    assert staff_display_name(staff) == "Larry Weed"


def test_handles_no_name():
    staff = _FakeStaff()
    assert staff_display_name(staff) == "Unknown staff"


# ---- staff_subtitle ------------------------------------------------------------

def test_subtitle_prefers_clinical_role():
    staff = _FakeStaff(top_clinical_role=_FakeRole("Physician"), top_role_abbreviation="MD")
    assert staff_subtitle(staff) == "Physician"


def test_subtitle_falls_back_to_abbreviation():
    staff = _FakeStaff(top_clinical_role=None, top_role_abbreviation="MA")
    assert staff_subtitle(staff) == "MA"


def test_subtitle_empty_when_no_role():
    staff = _FakeStaff()
    assert staff_subtitle(staff) == ""


# ---- initials ------------------------------------------------------------------

def test_initials_two_words():
    assert initials("Canvas Provider MD") == "CP"


def test_initials_single_word():
    assert initials("Cher") == "C"


def test_initials_with_comma_credentials():
    assert initials("Alexis Morgan, MD") == "AM"


def test_initials_empty():
    assert initials("") == "?"
    assert initials(None) == "?"


def test_initials_with_no_letters():
    assert initials("123 456") == "?"
    assert initials("---") == "?"
