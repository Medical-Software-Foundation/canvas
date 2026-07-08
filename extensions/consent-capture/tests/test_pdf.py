"""Tests for consent_capture/pdf.py.

These are pure-function tests (no external dependencies). The module hand-writes
a PDF, so tests assert on the structural bytes/markers and exercise the wrapping,
escaping and number-formatting helpers plus every branch of the page builder.
"""

import base64

from consent_capture import pdf
from consent_capture.pdf import (
    _build_ops,
    _content_stream,
    _escape,
    _num,
    _text,
    _text_width,
    _wrap,
    generate_consent_pdf,
    generate_consent_pdf_base64,
)


class TestEscape:
    def test_escapes_backslash_and_parens(self):
        assert _escape(r"a\b(c)d") == r"a\\b\(c\)d"

    def test_plain_text_unchanged(self):
        assert _escape("plain text") == "plain text"


class TestNum:
    def test_int_formats_without_decimal(self):
        assert _num(10) == "10"

    def test_float_strips_trailing_zeros(self):
        assert _num(10.50) == "10.5"

    def test_float_strips_to_integer_form(self):
        assert _num(12.00) == "12"

    def test_float_keeps_two_places(self):
        assert _num(0.6) == "0.6"


class TestTextWidth:
    def test_known_characters(self):
        # space width is 278/1000 em; at size 10 -> 2.78 pt.
        assert round(_text_width(" ", 10), 2) == 2.78

    def test_unknown_character_uses_default_width(self):
        # 'é' isn't in the Helvetica table -> default 556 units.
        assert round(_text_width("é", 10), 2) == 5.56


class TestWrap:
    def test_short_text_single_line(self):
        assert _wrap("hello world", size=10, max_width=1000) == ["hello world"]

    def test_empty_text_returns_single_empty_line(self):
        assert _wrap("", size=10, max_width=1000) == [""]

    def test_long_text_wraps_to_multiple_lines(self):
        text = "word " * 40
        lines = _wrap(text.strip(), size=10, max_width=100)
        assert len(lines) > 1
        # every produced line fits within the max width
        for line in lines:
            assert _text_width(line, 10) <= 100

    def test_single_word_longer_than_width_still_emitted(self):
        lines = _wrap("supercalifragilistic", size=10, max_width=10)
        assert lines == ["supercalifragilistic"]


class TestBuildOps:
    def test_with_statement_and_time(self):
        ops = _build_ops(
            title="Consent to Treat",
            patient_name="Jane Doe",
            patient_dob="1990-01-01",
            staff_name="Dr. Smith",
            date="2026-07-07",
            statement_paragraphs=["Para one.", "Para two."],
            time="2:32 PM",
            consented_by="Patient",
        )
        kinds = [op[0] for op in ops]
        assert "text" in kinds and "rule" in kinds
        # Footer with time is present.
        footer_texts = [op[-1] for op in ops if op[0] == "text"]
        assert "Generated 2026-07-07 at 2:32 PM" in footer_texts
        assert "Consent statement" in footer_texts

    def test_without_statement_omits_statement_section(self):
        ops = _build_ops(
            title="Consent",
            patient_name="Jane Doe",
            patient_dob="1990-01-01",
            staff_name="Dr. Smith",
            date="2026-07-07",
            statement_paragraphs=[],
            time="",
            consented_by="Patient",
        )
        texts = [op[-1] for op in ops if op[0] == "text"]
        assert "Consent statement" not in texts
        # Footer without time.
        assert "Generated 2026-07-07" in texts

    def test_empty_values_use_fallbacks(self):
        ops = _build_ops(
            title="",
            patient_name="",
            patient_dob="",
            staff_name="",
            date="2026-07-07",
            statement_paragraphs=[],
            time="",
            consented_by="",
        )
        texts = [op[-1] for op in ops if op[0] == "text"]
        assert "Consent" in texts  # title fallback
        assert "(name unavailable)" in texts  # patient name fallback
        assert "-" in texts  # dob fallback
        assert "Unknown" in texts  # staff fallback
        assert "Patient" in texts  # consented_by fallback


class TestText:
    def test_empty_text_appends_nothing(self):
        ops = []
        _text(ops, 10, 10, "F1", 10, (0, 0, 0), "")
        assert ops == []

    def test_nonempty_text_appends_op(self):
        ops = []
        _text(ops, 10, 20, "F1", 10, (0, 0, 0), "Hi")
        assert ops == [("text", 10, 20, "F1", 10, (0, 0, 0), "Hi")]


class TestContentStream:
    def test_renders_text_and_rule_operators(self):
        ops = [
            ("text", 64, 700, "F1", 10.5, (0.1, 0.1, 0.1), "Hello"),
            ("rule", 64, 690, 548, (0.85, 0.87, 0.9), 0.6),
        ]
        stream = _content_stream(ops)
        assert "BT" in stream and "Tj ET" in stream
        assert "(Hello)" in stream
        assert " m " in stream and " l S" in stream
        assert " rg" in stream and " RG" in stream

    def test_unknown_operator_is_ignored(self):
        # Neither "text" nor "rule": the loop skips it (defensive branch).
        assert _content_stream([("noop", 1, 2)]) == ""


class TestGeneratePdf:
    def test_generate_pdf_returns_valid_structure(self):
        pdf_bytes = generate_consent_pdf(
            title="Consent to Treat",
            patient_name="Jane Doe",
            patient_dob="1990-01-01",
            staff_name="Dr. Smith",
            date="2026-07-07",
            statement_paragraphs=["I consent (fully) to \\ treatment."],
            time="2:32 PM",
            consented_by="Patient",
        )
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert pdf_bytes.rstrip().endswith(b"%%EOF")
        assert b"/Type /Catalog" in pdf_bytes
        assert b"xref" in pdf_bytes
        assert b"trailer" in pdf_bytes

    def test_generate_pdf_minimal_no_statement_no_time(self):
        pdf_bytes = generate_consent_pdf(
            title="",
            patient_name="",
            patient_dob="",
            staff_name="",
            date="2026-07-07",
            statement_paragraphs=[],
        )
        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert b"%%EOF" in pdf_bytes

    def test_base64_wrapper_round_trips(self):
        encoded = generate_consent_pdf_base64(
            title="Consent",
            patient_name="Jane Doe",
            patient_dob="1990-01-01",
            staff_name="Dr. Smith",
            date="2026-07-07",
            statement_paragraphs=["Statement."],
        )
        assert isinstance(encoded, str)
        decoded = base64.b64decode(encoded)
        assert decoded.startswith(b"%PDF-1.4")
        # Matches the raw generator output for identical inputs.
        assert decoded == generate_consent_pdf(
            title="Consent",
            patient_name="Jane Doe",
            patient_dob="1990-01-01",
            staff_name="Dr. Smith",
            date="2026-07-07",
            statement_paragraphs=["Statement."],
        )

    def test_module_exposes_page_geometry(self):
        assert pdf.PAGE_WIDTH == 612
        assert pdf.PAGE_HEIGHT == 792
