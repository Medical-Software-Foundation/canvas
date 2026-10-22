"""Token rendering, CSS validation and content hashing.

Kept out of the handlers so the asset routes, the admin API and the tests all
agree on exactly what a published stylesheet looks like.
"""

import re
from json import dumps
from hashlib import sha256
from typing import Any

# Token names become `--ctk-<name>`. The prefix is deliberately neutral rather
# than inherited from any one organization's design system.
TOKEN_PREFIX = "ctk"

# A token name is a CSS custom-property fragment, nothing more. Anything outside
# this set could close the declaration and inject rules.
TOKEN_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Characters that would let a token value escape its declaration.
TOKEN_VALUE_FORBIDDEN = set("{};<>")

MAX_TOKEN_NAME = 64
MAX_TOKEN_VALUE = 256

# Published content is loaded into memory on every cache miss and shipped to
# every page of every consuming plugin, so its size is an availability concern
# rather than a style preference. 256 KB is far more than a design system needs
# — the reference system this was modeled on ships about 20 KB — while still
# catching a paste that went wrong.
MAX_CSS_BYTES = 256 * 1024
MAX_TOKENS = 500

_IMPORT_RE = re.compile(r"@import\b", re.IGNORECASE)
_URL_OPEN_RE = re.compile(r"url\(", re.IGNORECASE)
# image-set() accepts a bare string as an image URL, so it can fetch without a
# url() anywhere. Matches the -webkit- form too. Rejected outright rather than
# parsed: a design system has no need for it that url() does not cover.
_IMAGE_SET_RE = re.compile(r"image-set\(", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)

# The URL parser deletes these anywhere in a URL before reading it, so
# `h<TAB>ttps:` is `https:` to the browser.
_URL_IGNORED = "\t\n\r"
# ...and trims these from both ends ("C0 control or space").
_URL_TRIMMED = "".join(chr(c) for c in range(0x21))

# A newline ends a CSS string, which is what lets the scanner below agree with
# the browser about where a string stops.
_CSS_NEWLINES = "\n\r\f"


def _is_name_char(ch: str) -> bool:
    """Whether `ch` can continue a CSS identifier (CSS Syntax 3, 4.2)."""
    return ch.isascii() and (ch.isalnum() or ch in "-_") or not ch.isascii()


class ValidationError(Exception):
    """Raised when submitted CSS or tokens would be unsafe to publish."""


def _strip_comments(css: str) -> str:
    """`css` with each comment replaced by a space, as a browser tokenizes it.

    CSS comments are inert, so a stylesheet that mentions @import while
    explaining that it avoids one must not be rejected for saying so. But `/*`
    only opens a comment *outside* a string and outside an unquoted url(). A
    regex strip that did not know that let `content:"/*"` … `content:"*/"`
    hide a live url() between them from every check. Each branch below mirrors
    one rule of the CSS Syntax tokenizer; getting any of them wrong in the
    direction of stripping too much reopens that hole.

    Backslash escapes are walked over so they cannot desync the scanner, and
    are then refused outright by `_reject_fetches`.
    """
    out: list[str] = []
    i, n = 0, len(css)
    while i < n:
        ch = css[i]
        if ch == "/" and css.startswith("*", i + 1):
            # An unclosed comment runs to the end of the sheet, as it does in
            # the browser.
            end = css.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        if ch in "'\"":
            # A string ends at its closing quote or, unclosed, at a newline.
            j = i + 1
            while j < n and css[j] != ch and css[j] not in _CSS_NEWLINES:
                j += 2 if css[j] == "\\" else 1
            if j < n and css[j] == ch:
                j += 1
            out.append(css[i:j])
            i = j
            continue
        if ch == "\\":
            out.append(css[i : i + 2])
            i += 2
            continue
        if css[i : i + 4].lower() == "url(" and not (i and _is_name_char(css[i - 1])):
            # `url(` followed by a quote is a function taking a string, which
            # the branches above handle. Anything else is one url token that
            # runs to `)`, and `/*` inside it is just part of the address.
            j = i + 4
            while j < n and css[j] in " \t" + _CSS_NEWLINES:
                j += 1
            if j >= n or css[j] not in "'\"":
                while j < n and css[j] != ")":
                    j += 2 if css[j] == "\\" else 1
                j = min(j + 1, n)
            out.append(css[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _has_open_string(value: str) -> bool:
    """Whether `value` ends inside a quoted string."""
    quote = ""
    for ch in value:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
    return bool(quote)


def validate_css(css: str) -> None:
    """Reject stylesheets that could phone home from a patient-facing page.

    CSS is not inert. `@import` pulls in a remote stylesheet, and a `url()`
    pointing off-origin issues a request the moment the rule matches — which is
    enough to leak that a given page was rendered, and with attribute selectors,
    something about what was on it. Both are blocked; same-origin paths and
    `data:` URIs are allowed.

    This is a lexical check, not a parser. It is deliberately conservative: it
    can reject an exotic-but-harmless stylesheet, and that is the right trade
    for content an admin publishes to every consuming page at once.
    """
    # Size is measured on what was submitted — comments are bytes we store and
    # serve, so they count.
    size = len(css.encode("utf-8"))
    if size > MAX_CSS_BYTES:
        raise ValidationError(
            f"Stylesheet is {size // 1024} KB; the limit is "
            f"{MAX_CSS_BYTES // 1024} KB. Published CSS is served on every page "
            "of every consuming plugin."
        )

    # Checked on the raw source: inside a <style> element even a comment or a
    # string closes the element. Served as text/css this is inert, but a
    # consumer that inlines core.css would be handed markup. `<` alone stays
    # legal because media-query range syntax (`(width < 600px)`) needs it.
    if "</" in css:
        raise ValidationError(
            "'</' is not allowed: it would close the <style> element on any page "
            "that inlines this stylesheet."
        )

    # Checked against comment-stripped source so prose cannot trip the rules.
    code = _strip_comments(css)

    if _IMPORT_RE.search(code):
        raise ValidationError(
            "@import is not allowed: it loads a stylesheet from another origin "
            "on every page that uses this theme."
        )

    _reject_fetches(code)

    return None


def _url_targets(code: str) -> list[str]:
    """Every url() target in `code`, read the way a browser reads it.

    Each target is normalized the way the URL parser does it before the
    caller checks its scheme: a target that only looks same-origin once you
    ignore a tab is not same-origin.

    A regex over `url(...)` fails to *match* a quoted target that contains `)`
    or the other quote character, and a failed match meant nothing was checked
    at all. This walks each `url(` to its real end instead, and refuses
    anything it cannot read to the end: what cannot be checked cannot be
    allowed.
    """
    targets = []
    for match in _URL_OPEN_RE.finditer(code):
        i = match.end()
        while i < len(code) and code[i].isspace():
            i += 1
        if i < len(code) and code[i] in "'\"":
            end = code.find(code[i], i + 1)
            if end == -1:
                raise ValidationError("Unterminated string inside url().")
            target = code[i + 1 : end]
            rest = end + 1
            while rest < len(code) and code[rest].isspace():
                rest += 1
            if rest >= len(code) or code[rest] != ")":
                raise ValidationError(
                    "Malformed url(): expected ')' after the quoted target."
                )
        else:
            end = code.find(")", i)
            if end == -1:
                raise ValidationError("Unterminated url().")
            target = code[i:end]
        target = "".join(c for c in target if c not in _URL_IGNORED)
        targets.append(target.strip(_URL_TRIMMED))
    return targets


def _reject_fetches(code: str) -> None:
    """Raise if `code` could issue an off-origin request when rendered.

    Shared by the stylesheet and token values: a token reaches the page through
    var(), so a check that covered only the stylesheet would move the problem
    into a token.
    """
    # Escapes can spell a scheme (`\68ttps:`) or the function name itself
    # (`\75rl(`) in a form no lexical check recognizes. The shipped themes use
    # none, and refusing them is what makes the checks below sound.
    if "\\" in code:
        raise ValidationError(
            "Backslash escapes are not allowed: they can disguise a url() or its "
            "scheme from this check. Write the characters out instead."
        )
    if _IMAGE_SET_RE.search(code):
        raise ValidationError(
            "image-set() is not allowed: it can load an image from another "
            "origin without url(). Use url() with a same-origin path or a data: URI."
        )
    for target in _url_targets(code):
        if not target or target.lower().startswith("data:"):
            continue
        if target.startswith("//"):
            raise ValidationError(
                f"Protocol-relative url() is not allowed: {target!r}. "
                "Use a same-origin path beginning with '/' or a data: URI."
            )
        if _SCHEME_RE.match(target):
            raise ValidationError(
                f"Off-origin url() is not allowed: {target!r}. "
                "Use a same-origin path beginning with '/' or a data: URI."
            )


def validate_tokens(tokens: Any) -> dict[str, str]:
    """Return a clean `{name: value}` map, or raise.

    Token values are interpolated straight into a `:root` block, so a value
    carrying `}` or `;` could close the rule and append arbitrary CSS. Names and
    values are both constrained rather than escaped, because there is no
    legitimate token that needs those characters.
    """
    if not isinstance(tokens, dict):
        raise ValidationError("Tokens must be a JSON object of name -> value.")

    if len(tokens) > MAX_TOKENS:
        raise ValidationError(
            f"{len(tokens)} tokens submitted; the limit is {MAX_TOKENS}. "
            "Every token is rendered into the :root block inlined on each page."
        )

    clean: dict[str, str] = {}
    for raw_name, raw_value in tokens.items():
        name = str(raw_name).strip()
        if len(name) > MAX_TOKEN_NAME or not TOKEN_NAME_RE.match(name):
            raise ValidationError(
                f"Invalid token name {raw_name!r}: use lowercase letters, digits "
                "and single hyphens, e.g. 'color-primary'."
            )

        value = str(raw_value).strip()
        if not value:
            raise ValidationError(f"Token {name!r} has an empty value.")
        if len(value) > MAX_TOKEN_VALUE:
            raise ValidationError(f"Token {name!r} value is too long.")
        if TOKEN_VALUE_FORBIDDEN & set(value):
            raise ValidationError(
                f"Token {name!r} value contains a forbidden character "
                f"(one of {''.join(sorted(TOKEN_VALUE_FORBIDDEN))})."
            )
        # Every token renders into one `:root{}` block, so a value that leaves
        # a string or comment open swallows every token after it, and the
        # authored CSS too. A newline would end a string mid-value.
        if (
            "/*" in value
            or _has_open_string(value)
            or any(c in _CSS_NEWLINES for c in value)
        ):
            raise ValidationError(
                f"Token {name!r} value leaves a quote or comment open, or spans "
                "lines. It would break every token after it."
            )
        try:
            _reject_fetches(value)
        except ValidationError as exc:
            raise ValidationError(f"Token {name!r}: {exc}") from exc
        clean[name] = value

    return clean


def render_tokens_css(tokens: dict[str, str]) -> str:
    """Render tokens as a `:root` block.

    Emitted on one line and sorted by name: sorting keeps the bytes stable so
    the ETag only changes when the tokens actually change, rather than on dict
    ordering.
    """
    if not tokens:
        return ":root{}"
    body = "".join(f"--{TOKEN_PREFIX}-{name}:{tokens[name]};" for name in sorted(tokens))
    return f":root{{{body}}}"


def content_hash(css: str, tokens: dict[str, str]) -> str:
    """Stable hash of everything a consumer would see.

    Derived from the content itself rather than a version number, so it stays
    correct even when someone publishes without bumping anything.
    """
    payload = dumps(
        {"css": css, "tokens": dict(sorted(tokens.items()))},
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:32]


def full_stylesheet(css: str, tokens: dict[str, str]) -> str:
    """The published `core.css`: token block first, then the authored CSS.

    Tokens lead so the authored CSS can reference them, and so the first bytes a
    browser parses are the ones that decide colors and spacing.
    """
    return f"{render_tokens_css(tokens)}\n{css}" if css else render_tokens_css(tokens)
