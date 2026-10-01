"""Tests for consent_capture/constants.py."""

from consent_capture import constants
from consent_capture.constants import (
    banners_enabled,
    method_generates_pdf,
    normalize_method_options,
    normalize_satisfied_by,
    parse_statement,
    render_capacity,
)


class TestBannersEnabled:
    def test_unset_or_empty_defaults_to_enabled(self):
        assert banners_enabled(None) is True
        assert banners_enabled("") is True
        assert banners_enabled("   ") is True

    def test_explicit_off_values_disable(self):
        for value in ("false", "0", "no", "off", "disabled", "n",
                      "False", "OFF", " No "):
            assert banners_enabled(value) is False, value

    def test_other_values_stay_enabled(self):
        for value in ("true", "1", "yes", "on", "enabled", "anything"):
            assert banners_enabled(value) is True, value


class TestModuleConstants:
    def test_button_constants_present(self):
        assert constants.BUTTON_TITLE == "Consents"
        assert constants.BUTTON_KEY == "COLLECT_CONSENT"
        # Due = red background + white text; satisfied = neutral gray + dark slate text.
        assert constants.BUTTON_DUE_BACKGROUND == "#c0392b"
        assert constants.BUTTON_DUE_TEXT == "#ffffff"
        assert constants.BUTTON_SATISFIED_BACKGROUND == "#e5e7eb"
        assert constants.BUTTON_SATISFIED_TEXT == "#1f2933"
        assert constants.NO_STATEMENT_NOTE
        assert constants.ACCEPTED_STATES == (
            "accepted",
            "accepted_via_patient_portal",
        )

    def test_method_options(self):
        assert constants.METHOD_OPTIONS == ("Verbal", "Electronic", "Written", "Other")

    def test_document_bounds(self):
        assert constants.MAX_DOCUMENT_BYTES == 10 * 1024 * 1024
        assert constants.PDF_MAGIC == b"%PDF-"


class TestMethodGeneratesPdf:
    def test_written_skips_pdf(self):
        assert method_generates_pdf("Written") is False
        assert method_generates_pdf(" written ") is False
        assert method_generates_pdf("WRITTEN") is False

    def test_other_methods_generate_pdf(self):
        assert method_generates_pdf("Verbal") is True
        assert method_generates_pdf("Electronic") is True
        assert method_generates_pdf("") is True   # no method -> still a PDF
        assert method_generates_pdf(None) is True


class TestNormalizeMethodOptions:
    def test_non_list_returns_empty(self):
        assert normalize_method_options(None) == []
        assert normalize_method_options("Verbal") == []

    def test_keeps_only_canonical_in_canonical_order(self):
        # Input order is ignored; unknown values are dropped.
        assert normalize_method_options(
            ["Written", "Verbal", "Phone", "verbal"]
        ) == ["Verbal", "Written"]

    def test_maps_legacy_electronic_form_alias(self):
        assert normalize_method_options(["Electronic Form"]) == ["Electronic"]
        assert normalize_method_options(["electronic form", "Verbal"]) == [
            "Verbal",
            "Electronic",
        ]

    def test_drops_unknown_values(self):
        assert normalize_method_options(["Phone", "Fax"]) == []

    def test_default_capacity_templates_have_placeholders(self):
        assert "[Patient name]" in constants.DEFAULT_CAPACITY_PATIENT
        assert "[Name]" in constants.DEFAULT_CAPACITY_REPRESENTATIVE


class TestNormalizeSatisfiedBy:
    def test_non_list_returns_empty(self):
        assert normalize_satisfied_by(None) == []
        assert normalize_satisfied_by("x") == []

    def test_keeps_system_code_display_and_trims(self):
        assert normalize_satisfied_by([
            {"system": " INTERNAL ", "code": " verbal ", "display": " Verbal "},
        ]) == [{"system": "INTERNAL", "code": "verbal", "display": "Verbal"}]

    def test_tolerates_empty_code(self):
        # Codings can carry identity in system alone (no code).
        assert normalize_satisfied_by([
            {"system": "Universal_Written_Consent", "code": "", "display": "Written"},
        ]) == [{"system": "Universal_Written_Consent", "code": "", "display": "Written"}]

    def test_drops_entries_without_identity(self):
        assert normalize_satisfied_by([
            {"system": "", "code": "", "display": "orphan"},
            {"display": "no keys"},
            "not a dict",
        ]) == []

    def test_dedupes_on_pair_first_wins(self):
        out = normalize_satisfied_by([
            {"system": "INTERNAL", "code": "verbal", "display": "First"},
            {"system": "INTERNAL", "code": "verbal", "display": "Second"},
        ])
        assert out == [{"system": "INTERNAL", "code": "verbal", "display": "First"}]

    def test_missing_display_becomes_empty(self):
        assert normalize_satisfied_by([{"system": "s", "code": "c"}]) == [
            {"system": "s", "code": "c", "display": ""}
        ]


class TestRenderCapacity:
    def test_empty_template_returns_empty(self):
        assert render_capacity("") == ""
        assert render_capacity("   ") == ""
        assert render_capacity(None) == ""

    def test_fills_patient_name(self):
        assert render_capacity(
            "[Patient name] has the capacity for decision-making.",
            patient_name="Jane Doe",
        ) == "Jane Doe has the capacity for decision-making."

    def test_fills_representative_name(self):
        assert render_capacity(
            "Consent obtained by [Name], who has the authority.",
            representative_name="John Roe",
        ) == "Consent obtained by John Roe, who has the authority."

    def test_missing_name_leaves_blank_and_collapses_whitespace(self):
        # Unfilled placeholder becomes empty; surrounding whitespace collapses.
        assert render_capacity("[Patient name] has capacity.") == "has capacity."


class TestParseStatement:
    def test_none_returns_empty(self):
        assert parse_statement(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_statement("") == []

    def test_whitespace_only_returns_empty(self):
        assert parse_statement("   \n  \t ") == []

    def test_single_line(self):
        assert parse_statement("I consent to treatment.") == [
            "I consent to treatment."
        ]

    def test_multiple_lines_become_paragraphs(self):
        raw = "First paragraph.\nSecond paragraph."
        assert parse_statement(raw) == ["First paragraph.", "Second paragraph."]

    def test_blank_lines_are_dropped(self):
        raw = "First.\n\n\nSecond.\n"
        assert parse_statement(raw) == ["First.", "Second."]

    def test_double_pipe_separator(self):
        raw = "First.||Second.||Third."
        assert parse_statement(raw) == ["First.", "Second.", "Third."]

    def test_carriage_returns_normalized(self):
        raw = "First.\r\nSecond.\rThird."
        assert parse_statement(raw) == ["First.", "Second.", "Third."]

    def test_lines_are_stripped(self):
        raw = "   Padded line.   "
        assert parse_statement(raw) == ["Padded line."]
