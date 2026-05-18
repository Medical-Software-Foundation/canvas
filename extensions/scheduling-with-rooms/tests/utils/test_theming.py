"""Tests for utils/theming.py."""

from scheduling_with_rooms.utils.theming import (
    _CANVAS_DEFAULTS,
    resolve_theme,
    theme_style_block,
)


def test_resolve_theme_no_secrets_returns_canvas_defaults():
    theme = resolve_theme(None)
    assert theme["brand-primary"] == _CANVAS_DEFAULTS["brand-primary"]
    assert theme["brand-primary-hover"] == _CANVAS_DEFAULTS["brand-primary-hover"]


def test_resolve_theme_empty_secrets_returns_canvas_defaults():
    theme = resolve_theme({})
    assert theme["brand-primary"] == "#2563eb"


def test_resolve_theme_applies_valid_overrides():
    theme = resolve_theme({"BRAND_PRIMARY": "#4A6FA5"})
    assert theme["brand-primary"] == "#4A6FA5"
    # Non-overridden values stay at default.
    assert theme["brand-primary-hover"] == _CANVAS_DEFAULTS["brand-primary-hover"]


def test_resolve_theme_rejects_invalid_color():
    # Anything that isn't a #hex pattern is dropped to prevent CSS injection.
    theme = resolve_theme({"BRAND_PRIMARY": "red; background: url(http://evil)"})
    assert theme["brand-primary"] == _CANVAS_DEFAULTS["brand-primary"]


def test_resolve_theme_rejects_partial_hex():
    theme = resolve_theme({"BRAND_PRIMARY": "#12"})
    assert theme["brand-primary"] == _CANVAS_DEFAULTS["brand-primary"]


def test_resolve_theme_accepts_short_hex():
    theme = resolve_theme({"BRAND_PRIMARY": "#abc"})
    assert theme["brand-primary"] == "#abc"


def test_resolve_theme_accepts_8char_hex_with_alpha():
    theme = resolve_theme({"BRAND_PRIMARY": "#01a4ff80"})
    assert theme["brand-primary"] == "#01a4ff80"


def test_resolve_theme_strips_whitespace():
    theme = resolve_theme({"BRAND_PRIMARY": "  #4a6fa5  "})
    assert theme["brand-primary"] == "#4a6fa5"


def test_resolve_theme_neutrals_not_overridable():
    """Customer can't override the neutral palette — keeps coherent contrast."""
    theme = resolve_theme({"text-strong": "#ff0000"})  # not a real secret name
    assert theme["text-strong"] == _CANVAS_DEFAULTS["text-strong"]


def test_theme_style_block_emits_root_block():
    block = theme_style_block(None)
    assert block.startswith("<style>")
    assert ":root {" in block
    assert "--brand-primary:" in block
    assert "--font-stack:" in block
    assert block.rstrip().endswith("</style>")


def test_theme_style_block_uses_overrides():
    block = theme_style_block({"BRAND_PRIMARY": "#4A6FA5"})
    assert "--brand-primary: #4A6FA5;" in block


# ---- font overrides ----

def test_resolve_theme_accepts_valid_font_stack():
    theme = resolve_theme({"BRAND_FONT_STACK": "Lato, system-ui, sans-serif"})
    assert theme["font-stack"] == "Lato, system-ui, sans-serif"


def test_resolve_theme_accepts_quoted_font_name():
    theme = resolve_theme({"BRAND_FONT_STACK": "'Source Sans 3', sans-serif"})
    assert theme["font-stack"] == "'Source Sans 3', sans-serif"


def test_resolve_theme_rejects_font_stack_with_braces():
    # Anything that could break out of the CSS rule must be rejected.
    theme = resolve_theme({"BRAND_FONT_STACK": "Lato; } body { display: none"})
    assert theme["font-stack"] == _CANVAS_DEFAULTS["font-stack"]


def test_resolve_theme_rejects_font_stack_with_url():
    theme = resolve_theme({"BRAND_FONT_STACK": "url(http://evil)"})
    assert theme["font-stack"] == _CANVAS_DEFAULTS["font-stack"]


def test_theme_style_block_omits_font_link_when_unset():
    block = theme_style_block(None)
    assert "<link" not in block


def test_theme_style_block_includes_font_link_when_valid():
    from scheduling_with_rooms.utils.theming import resolve_font_url

    block = theme_style_block({
        "BRAND_FONT_URL": (
            "https://fonts.googleapis.com/css2?family=Lato:wght@400;700&display=swap"
        )
    })
    assert '<link href="https://fonts.googleapis.com/css2?' in block
    assert "rel=\"stylesheet\"" in block
    # And resolve_font_url returns the same URL.
    assert resolve_font_url({"BRAND_FONT_URL": "https://fonts.googleapis.com/css2?family=Lato"})


def test_resolve_font_url_rejects_other_hosts():
    from scheduling_with_rooms.utils.theming import resolve_font_url

    assert resolve_font_url({"BRAND_FONT_URL": "https://evil.example.com/font.css"}) == ""


def test_resolve_font_url_rejects_http():
    from scheduling_with_rooms.utils.theming import resolve_font_url

    assert resolve_font_url(
        {"BRAND_FONT_URL": "http://fonts.googleapis.com/css2?family=Lato"}
    ) == ""


def test_resolve_font_url_handles_none_secrets():
    from scheduling_with_rooms.utils.theming import resolve_font_url

    assert resolve_font_url(None) == ""


def test_resolve_font_url_empty_secret_returns_empty():
    from scheduling_with_rooms.utils.theming import resolve_font_url

    assert resolve_font_url({"BRAND_FONT_URL": ""}) == ""
