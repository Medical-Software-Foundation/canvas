"""Tests for group_therapy.helpers generic note rendering."""

from group_therapy.helpers import _esc, build_note_html, build_note_print


def test_esc_escapes_html_and_newlines():
    assert _esc("a & b <x>\nline") == "a &amp; b &lt;x&gt;<br>line"
    assert _esc(None) == ""


def test_build_note_html_renders_meta_and_sections():
    html = build_note_html(
        [("Provider", "Dr. Wang"), ("Date", "2026-06-27"), ("Duration", "")],
        [("How session was conducted", "Virtual"), ("Therapeutic interventions", "CBT, DBT skills")],
    )
    assert "Dr. Wang" in html
    assert "2026-06-27" in html
    assert "How session was conducted" in html
    assert "Virtual" in html
    assert "CBT, DBT skills" in html


def test_build_note_html_skips_empty_values():
    html = build_note_html([("Provider", "Dr. A")], [("Risk", ""), ("Plan", "Continue group")])
    assert "Risk" not in html
    assert "Plan" in html and "Continue group" in html


def test_build_note_html_escapes_user_input():
    html = build_note_html([], [("Note", "<script>alert(1)</script>")])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_build_note_print_renders_sections():
    html = build_note_print(
        [("Provider", "Dr. A"), ("Date", "2026-06-27")],
        [("HPI", "Patient reports anxiety")],
    )
    assert "Dr. A" in html
    assert "HPI" in html
    assert "Patient reports anxiety" in html


def test_build_note_print_skips_empty_sections():
    html = build_note_print([("Provider", "Dr. A")], [("Risk", ""), ("Plan", "Continue")])
    assert "Risk" not in html
    assert "Plan" in html and "Continue" in html
