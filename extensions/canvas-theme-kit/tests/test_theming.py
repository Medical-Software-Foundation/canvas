"""Tests for token rendering, CSS validation and content hashing.

These are the security-relevant paths: everything here runs on content an admin
typed, which then renders on every patient-facing page using the theme.
"""

import pytest

from canvas_theme_kit.theming import (
    ValidationError,
    content_hash,
    full_stylesheet,
    render_tokens_css,
    validate_css,
    validate_tokens,
)


class TestValidateCss:
    """CSS is not inert — it can issue network requests from a rendered page."""

    @pytest.mark.parametrize(
        "css",
        [
            "@import url('https://evil.example/x.css');",
            "@IMPORT 'other.css';",
            "  @import  'a.css';",
        ],
    )
    def test_rejects_import(self, css: str) -> None:
        with pytest.raises(ValidationError, match="@import"):
            validate_css(css)

    @pytest.mark.parametrize(
        "target",
        [
            "https://tracker.example/pixel.png",
            "http://tracker.example/pixel.png",
            "//tracker.example/pixel.png",
        ],
    )
    def test_rejects_off_origin_url(self, target: str) -> None:
        with pytest.raises(ValidationError):
            validate_css(f".a {{ background: url({target}); }}")

    def test_rejects_off_origin_url_in_font_face(self) -> None:
        css = "@font-face { font-family: X; src: url('https://cdn.example/f.woff2'); }"
        with pytest.raises(ValidationError):
            validate_css(css)

    @pytest.mark.parametrize(
        "target",
        [
            "/plugin-io/api/canvas_theme_kit/assets/logo.png",
            "'/assets/logo.png'",
            '"/assets/logo.png"',
            "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        ],
    )
    def test_allows_same_origin_and_data_uris(self, target: str) -> None:
        validate_css(f".a {{ background: url({target}); }}")  # must not raise

    def test_allows_stylesheet_with_no_urls(self) -> None:
        validate_css(".a { color: var(--ctk-color-accent); }")  # must not raise

    def test_allows_empty_url(self) -> None:
        # url() with nothing in it fetches nothing; no reason to reject it.
        validate_css(".a { background: url(); }")  # must not raise


class TestValidateTokens:
    """Token values are interpolated into a :root block, so they must not escape it."""

    def test_accepts_plain_tokens(self) -> None:
        assert validate_tokens({"color-accent": "#0b5fff", "space-4": "1rem"}) == {
            "color-accent": "#0b5fff",
            "space-4": "1rem",
        }

    def test_accepts_font_stack_with_commas_and_quotes(self) -> None:
        stack = "system-ui, 'Segoe UI', Arial, sans-serif"
        assert validate_tokens({"font-family": stack}) == {"font-family": stack}

    @pytest.mark.parametrize(
        "value",
        [
            "red} body{display:none",
            "red; color: blue",
            "<script>",
        ],
    )
    def test_rejects_values_that_could_escape_the_rule(self, value: str) -> None:
        with pytest.raises(ValidationError, match="forbidden character"):
            validate_tokens({"color-accent": value})

    @pytest.mark.parametrize(
        "name",
        ["Color-Accent", "color_accent", "color--accent", "-color", "color-", "cøler"],
    )
    def test_rejects_malformed_names(self, name: str) -> None:
        with pytest.raises(ValidationError, match="Invalid token name"):
            validate_tokens({name: "#fff"})

    def test_rejects_empty_value(self) -> None:
        with pytest.raises(ValidationError, match="empty value"):
            validate_tokens({"color-accent": "   "})

    def test_rejects_overlong_value(self) -> None:
        with pytest.raises(ValidationError, match="too long"):
            validate_tokens({"color-accent": "a" * 300})

    def test_rejects_overlong_name(self) -> None:
        with pytest.raises(ValidationError, match="Invalid token name"):
            validate_tokens({"a" * 70: "#fff"})

    def test_rejects_non_mapping(self) -> None:
        with pytest.raises(ValidationError, match="JSON object"):
            validate_tokens(["color-accent", "#fff"])

    def test_accepts_empty_mapping(self) -> None:
        assert validate_tokens({}) == {}


class TestRenderTokensCss:
    def test_renders_root_block(self) -> None:
        css = render_tokens_css({"color-accent": "#0b5fff"})
        assert css == ":root{--ctk-color-accent:#0b5fff;}"

    def test_sorts_by_name_so_bytes_are_stable(self) -> None:
        # Stable bytes matter: the ETag is derived from them, so unsorted output
        # would change the ETag on dict ordering alone and defeat caching.
        one = render_tokens_css({"b-token": "2", "a-token": "1"})
        two = render_tokens_css({"a-token": "1", "b-token": "2"})
        assert one == two == ":root{--ctk-a-token:1;--ctk-b-token:2;}"

    def test_empty_tokens_render_empty_block(self) -> None:
        assert render_tokens_css({}) == ":root{}"


class TestFullStylesheet:
    def test_tokens_precede_authored_css(self) -> None:
        out = full_stylesheet(".a{color:red}", {"color-accent": "#0b5fff"})
        assert out.index(":root") < out.index(".a{color:red}")

    def test_tokens_only_when_css_is_empty(self) -> None:
        assert full_stylesheet("", {"color-accent": "#0b5fff"}) == (
            ":root{--ctk-color-accent:#0b5fff;}"
        )


class TestContentHash:
    def test_is_stable_across_token_ordering(self) -> None:
        a = content_hash(".a{}", {"x": "1", "y": "2"})
        b = content_hash(".a{}", {"y": "2", "x": "1"})
        assert a == b

    def test_changes_when_css_changes(self) -> None:
        assert content_hash(".a{}", {}) != content_hash(".b{}", {})

    def test_changes_when_tokens_change(self) -> None:
        assert content_hash(".a{}", {"x": "1"}) != content_hash(".a{}", {"x": "2"})

    def test_is_32_hex_chars(self) -> None:
        digest = content_hash(".a{}", {})
        assert len(digest) == 32
        assert all(c in "0123456789abcdef" for c in digest)


class TestSizeLimits:
    """Published content loads into memory and ships to every consuming page."""

    def test_rejects_oversized_css(self) -> None:
        from canvas_theme_kit.theming import MAX_CSS_BYTES

        with pytest.raises(ValidationError, match="the limit is"):
            validate_css("a" * (MAX_CSS_BYTES + 1))

    def test_accepts_css_at_the_limit(self) -> None:
        from canvas_theme_kit.theming import MAX_CSS_BYTES

        validate_css("a" * MAX_CSS_BYTES)  # must not raise

    def test_measures_bytes_not_characters(self) -> None:
        # A multi-byte character must not slip past a character-count check —
        # what gets served and cached is bytes.
        from canvas_theme_kit.theming import MAX_CSS_BYTES

        with pytest.raises(ValidationError):
            validate_css("\u00e9" * MAX_CSS_BYTES)

    def test_rejects_too_many_tokens(self) -> None:
        from canvas_theme_kit.theming import MAX_TOKENS

        too_many = {f"t{i}": "1" for i in range(MAX_TOKENS + 1)}
        with pytest.raises(ValidationError, match="the limit is"):
            validate_tokens(too_many)

    def test_accepts_tokens_at_the_limit(self) -> None:
        from canvas_theme_kit.theming import MAX_TOKENS

        assert len(validate_tokens({f"t{i}": "1" for i in range(MAX_TOKENS)})) == MAX_TOKENS


class TestCommentsAreNotCode:
    """CSS comments are inert; prose about the rules must not trip them."""

    def test_allows_a_comment_mentioning_import(self) -> None:
        validate_css("/* No @import here, on purpose. */\n.a { color: red; }")

    def test_allows_a_comment_mentioning_an_off_origin_url(self) -> None:
        validate_css("/* Never url(https://cdn.example/x.css) */\n.a { color: red; }")

    def test_still_rejects_a_real_import_after_a_comment(self) -> None:
        with pytest.raises(ValidationError, match="@import"):
            validate_css("/* harmless */\n@import url('https://evil.example/x.css');")

    def test_still_rejects_a_real_off_origin_url_after_a_comment(self) -> None:
        with pytest.raises(ValidationError):
            validate_css("/* harmless */\n.a { background: url(https://evil.example/p.png); }")

    def test_comment_bytes_still_count_toward_the_size_limit(self) -> None:
        # Comments are stored and served, so they are not free.
        from canvas_theme_kit.theming import MAX_CSS_BYTES

        with pytest.raises(ValidationError, match="the limit is"):
            validate_css("/*" + "x" * MAX_CSS_BYTES + "*/")


class TestValidatorBypasses:
    """Shapes that slipped past the first lexical check.

    Each of these issues an off-origin request from a rendered page while the
    original `url()` regex either failed to match it (so nothing was checked)
    or never saw it at all. A security review found them; they are pinned here
    because every one looks like a harmless edge case until it is exploited.
    """

    @pytest.mark.parametrize(
        "css",
        [
            # A quoted target containing `)` or the other quote defeated the
            # regex, and a non-match meant no check ran.
            '.a { background: url("https://evil.example/x)"); }',
            ".a { background: url('https://evil.example/it\"s'); }",
            # image-set() takes a bare string as an image URL — no url() at all.
            '.a { background: image-set("https://evil.example/x.png" 1x); }',
            '.a { background: -webkit-image-set("https://evil.example/x.png" 1x); }',
            # An unterminated url() cannot be checked, so it cannot be allowed.
            ".a { background: url(https://evil.example/x.png; }",
        ],
    )
    def test_rejects_off_origin_fetches_the_regex_missed(self, css: str) -> None:
        with pytest.raises(ValidationError):
            validate_css(css)

    @pytest.mark.parametrize(
        "css",
        [
            # CSS escapes can spell a scheme, or the function name itself, in a
            # form no lexical check recognizes.
            ".a { background: url(\\68ttps://evil.example/x.png); }",
            ".a { background: \\75rl(https://evil.example/x.png); }",
        ],
    )
    def test_rejects_backslash_escapes(self, css: str) -> None:
        with pytest.raises(ValidationError, match="escape"):
            validate_css(css)

    def test_still_allows_a_same_origin_url_with_a_paren_in_quotes(self) -> None:
        validate_css('.a { background: url("/assets/logo(1).png"); }')  # must not raise


class TestTokenValuesCannotFetch:
    """A token value reaches the page through var(), so it needs the same rules
    as the stylesheet. Otherwise `url(https://…)` moves into a token and the
    stylesheet references it with `var(--ctk-x)`."""

    @pytest.mark.parametrize(
        "value",
        [
            "url(https://evil.example/b.png)",
            "url(//evil.example/b.png)",
            'image-set("https://evil.example/b.png" 1x)',
            "url(\\68ttps://evil.example/b.png)",
        ],
    )
    def test_rejects_off_origin_values(self, value: str) -> None:
        with pytest.raises(ValidationError):
            validate_tokens({"brand-image": value})

    @pytest.mark.parametrize(
        "value",
        # No `;base64` form here: `;` is already forbidden in token values, so a
        # base64 data URI belongs in the stylesheet, not a token.
        ["url(/assets/logo.png)", "url('data:image/svg+xml,%3Csvg%3E%3C/svg%3E')"],
    )
    def test_allows_same_origin_and_data_values(self, value: str) -> None:
        assert validate_tokens({"brand-image": value}) == {"brand-image": value}


class TestUrlScannerEdges:
    def test_allows_whitespace_inside_the_parens(self) -> None:
        validate_css('.a { background: url(  "/assets/logo.png"  ); }')  # must not raise

    @pytest.mark.parametrize(
        "css",
        [
            '.a { background: url("/assets/logo.png; }',
            '.a { background: url("/assets/logo.png" junk); }',
            '.a { background: url("/assets/logo.png"',
        ],
    )
    def test_rejects_a_url_it_cannot_read_to_the_end(self, css: str) -> None:
        # What cannot be read cannot be checked, so it is not allowed.
        with pytest.raises(ValidationError, match="url"):
            validate_css(css)
