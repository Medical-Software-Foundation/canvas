"""Tests for theme helpers."""

from provider_availability_manager.utils.theming import (
    resolve_font_url,
    resolve_theme,
    theme_style_block,
)


def test_no_secrets_returns_defaults():
    theme = resolve_theme(None)
    assert theme["brand-primary"] == "#2563eb"


def test_valid_hex_overrides_default():
    theme = resolve_theme({"BRAND_PRIMARY": "#abcdef"})
    assert theme["brand-primary"] == "#abcdef"


def test_invalid_hex_falls_back_to_default():
    theme = resolve_theme({"BRAND_PRIMARY": "not-a-color"})
    assert theme["brand-primary"] == "#2563eb"


def test_font_url_only_accepts_google_fonts():
    assert resolve_font_url({"BRAND_FONT_URL": "https://evil.example.com/x"}) == ""
    assert resolve_font_url({
        "BRAND_FONT_URL": "https://fonts.googleapis.com/css2?family=Inter"
    }) == "https://fonts.googleapis.com/css2?family=Inter"


def test_theme_style_block_includes_brand_primary_var():
    block = theme_style_block(None)
    assert "--brand-primary:" in block
    assert ":root" in block
