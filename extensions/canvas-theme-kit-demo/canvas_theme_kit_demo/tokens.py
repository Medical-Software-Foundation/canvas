"""Read published design tokens from the shared namespace at render time.

This is the piece that eliminates the flash of unstyled content. A page that
only links `core.css` paints once with browser defaults and again when the
stylesheet lands. Inlining the token block into `<head>` means the very first
paint already has the right colors, spacing and type — with **zero network
requests** — and the linked stylesheet then fills in the rules behind it.

Reading tokens straight out of the shared custom-data namespace is what makes
that affordable. The alternative, fetching `tokens.css` over HTTP from the
server rendering the page, would cost a plugin-runner round trip per render and
put the thing we are trying to avoid back on the critical path.

Two sandbox constraints shape the code below, both learned the hard way:

- Everything is imported by name. Canvas's RestrictedPython forbids attribute
  access on a plugin's own modules, so `from x import y` then `y()`, never
  `import x` then `x.y()`.
- Revisions are queried through `ThemeRevision.objects`, never through a
  reverse accessor like `theme.revisions`, which returns None for CustomModels
  inside the sandbox.
"""

from json import dumps, loads

from canvas_sdk.caching.plugins import get_cache

from canvas_theme_kit_demo.models import Theme, ThemeRevision

# Must match canvas_theme_kit's TOKEN_PREFIX. The published stylesheet declares
# `--ctk-*`, so an inline block using any other prefix would define a parallel
# set of variables that nothing reads.
TOKEN_PREFIX = "ctk"

DEFAULT_SLUG = "default"

# Bounds how long a published change takes to reach a server-rendered page.
# Short enough to feel immediate, long enough that a page render never waits on
# the database.
CACHE_TTL_SECONDS = 60

# v2 caches the token map rather than the rendered block. Bumped so a v1 entry
# (a CSS string) is never parsed as a map.
_CACHE_KEY = "ctk-demo:v2:tokens"

# Rendered when no theme is published, so a page still gets a valid (empty)
# custom-property block rather than a broken `<style>` element.
EMPTY_BLOCK = ":root{}"


def render_tokens_css(tokens: dict[str, str]) -> str:
    """Render tokens as a `:root` block.

    Deliberately identical to `canvas_theme_kit.theming.render_tokens_css`,
    including the sort. Plugins cannot import across the boundary, so this is a
    mirror; if the two ever disagree the inline block and the linked stylesheet
    would declare different values for the same token.
    """
    if not tokens:
        return EMPTY_BLOCK
    body = "".join(f"--{TOKEN_PREFIX}-{name}:{tokens[name]};" for name in sorted(tokens))
    return f":root{{{body}}}"


def active_tokens(slug: str = DEFAULT_SLUG) -> dict[str, str]:
    """The token map of the theme's active published revision.

    Returns an empty map when the theme does not exist or was never published,
    so a consuming page degrades to its own fallbacks instead of failing to
    render.
    """
    try:
        theme = Theme.objects.get(slug=slug)
    except Theme.DoesNotExist:
        return {}

    # values_list, not a hydrated row. This sits on the page-render hot path,
    # and a ThemeRevision carries a `css` column of up to 256 KB that nothing
    # here reads — loading it on every cache miss would undercut the whole point
    # of reading tokens from the database instead of over HTTP.
    tokens = (
        ThemeRevision.objects.filter(theme=theme, is_active=True)
        .order_by("-revision")
        .values_list("tokens", flat=True)
        .first()
    )
    return dict(tokens or {})


def cached_tokens(slug: str = DEFAULT_SLUG) -> dict[str, str]:
    """`active_tokens`, cached.

    Cached because this runs on every page render, and the page needs the map
    itself (for its token count) as well as the rendered block. Caching only the
    block would leave every render paying for the queries anyway. A cache
    failure falls through to a live read rather than breaking the page — a slow
    page is better than a 500, and an unstyled one is the very thing this
    exists to prevent.
    """
    cache = get_cache()
    key = f"{_CACHE_KEY}:{slug}"

    try:
        cached = cache.get(key)
        if cached is not None:
            return dict(loads(cached))
    except Exception:  # noqa: BLE001
        pass

    tokens = active_tokens(slug)

    try:
        cache.set(key, dumps(tokens), timeout_seconds=CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        pass
    return tokens


def inline_tokens_css(slug: str = DEFAULT_SLUG) -> str:
    """The `<style>` payload to inline into `<head>`."""
    return render_tokens_css(cached_tokens(slug))
