"""Tests for services/theming.py."""

from appointment_reminders.services.theming import _CANVAS_DEFAULTS, theme_style_block


def test_style_block_declares_every_palette_variable() -> None:
    """Every token the pages may reference is emitted, so no var() resolves empty."""
    block = theme_style_block()
    for key, value in _CANVAS_DEFAULTS.items():
        assert f"  --{key}: {value};" in block


def test_style_block_is_a_root_style_element() -> None:
    block = theme_style_block()
    assert block.startswith("<style>")
    assert ":root {" in block
    assert block.endswith("</style>")


def test_style_block_emits_no_font_import_link() -> None:
    """The palette is self-contained — no external stylesheet is pulled in."""
    assert "<link" not in theme_style_block()


def test_palette_is_fixed_across_calls() -> None:
    assert theme_style_block() == theme_style_block()
