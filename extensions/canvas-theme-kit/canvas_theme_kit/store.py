"""Theme persistence: draft edits, publishing, rollback and the cached read path.

Publishing is append-only. Rollback republishes an old revision as a *new* one
instead of mutating or deleting history, so "who published what, when" survives
every operation.
"""

from json import loads
from typing import Any, cast

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.templates import render_to_string

from canvas_theme_kit.models import Theme, ThemeRevision
from canvas_theme_kit.theming import (
    ValidationError,
    content_hash,
    full_stylesheet,
    render_tokens_css,
    validate_css,
    validate_tokens,
)

DEFAULT_SLUG = "default"

# Short enough that a publish shows up quickly, long enough that a page render
# never waits on the database. The published stylesheet is separately cached in
# the browser for five minutes, so this is not the limiting factor in how fast
# an edit reaches a user.
CACHE_TTL_SECONDS = 60

_CACHE_PREFIX = "ctk:v1"


def _cache_key(kind: str, slug: str) -> str:
    return f"{_CACHE_PREFIX}:{kind}:{slug}"


def invalidate(slug: str) -> None:
    """Drop cached renders for a theme. Called on every publish and rollback."""
    cache = get_cache()
    for kind in ("css", "tokens", "hash"):
        try:
            cache.delete(_cache_key(kind, slug))
        except Exception:  # noqa: BLE001 - a cache miss must never break a publish
            pass


def default_tokens() -> dict[str, str]:
    """The brand-neutral starter token set new themes begin from.

    Read through `render_to_string` because the plugin sandbox blocks direct
    filesystem access — a handler cannot `open()` a file in its own package.

    Returns an empty map rather than raising if the file is unreadable: a
    missing starter set should leave an admin with an empty theme to fill in,
    not a plugin that cannot create themes at all.
    """
    try:
        return validate_tokens(loads(render_to_string("static/default_tokens.json")))
    except Exception:  # noqa: BLE001
        return {}


def get_theme(slug: str) -> Theme | None:
    """Look up a theme by slug."""
    try:
        return cast(Theme, Theme.objects.get(slug=slug))
    except Theme.DoesNotExist:
        return None


def default_theme() -> Theme | None:
    """The theme served when a consumer names no slug."""
    theme = Theme.objects.filter(is_default=True).first()
    return theme or get_theme(DEFAULT_SLUG)


def active_revision(slug: str) -> ThemeRevision | None:
    """The revision currently published for a theme, if any."""
    theme = get_theme(slug)
    if theme is None:
        return None
    return cast(
        "ThemeRevision | None",
        ThemeRevision.objects.filter(theme=theme, is_active=True)
        .order_by("-revision")
        .first(),
    )


def published_css(slug: str) -> str | None:
    """Rendered `core.css` for a theme, cached.

    Returns None when the theme has never been published, which the asset route
    turns into a 404 rather than serving an empty stylesheet — an empty file
    would be indistinguishable from a working theme with no rules.
    """
    cache = get_cache()
    key = _cache_key("css", slug)

    try:
        cached = cache.get(key)
        if cached is not None:
            return str(cached)
    except Exception:  # noqa: BLE001
        pass

    revision = active_revision(slug)
    if revision is None:
        return None

    rendered = full_stylesheet(revision.css, revision.tokens or {})
    try:
        cache.set(key, rendered, timeout_seconds=CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        pass
    return rendered


def _active_tokens(slug: str) -> dict[str, str] | None:
    """The active revision's tokens, or None if the theme was never published.

    Projected to the one column, unlike `active_revision`: a revision row
    carries up to 256 KB of css that the token route never serves.
    """
    theme = get_theme(slug)
    if theme is None:
        return None
    row = (
        ThemeRevision.objects.filter(theme=theme, is_active=True)
        .order_by("-revision")
        .values("tokens")
        .first()
    )
    return None if row is None else dict(row["tokens"] or {})


def published_tokens_css(slug: str) -> str | None:
    """Just the `:root` token block for a theme, cached.

    This is what a consuming plugin inlines into `<head>` to get correct colors
    on first paint with no network request.
    """
    cache = get_cache()
    key = _cache_key("tokens", slug)

    try:
        cached = cache.get(key)
        if cached is not None:
            return str(cached)
    except Exception:  # noqa: BLE001
        pass

    tokens = _active_tokens(slug)
    if tokens is None:
        return None

    rendered = render_tokens_css(tokens)
    try:
        cache.set(key, rendered, timeout_seconds=CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        pass
    return rendered


def save_draft(
    theme: Theme, css: str, tokens: Any, editor: str
) -> Theme:
    """Validate and store a draft. Does not affect what anyone is being served."""
    validate_css(css)
    clean_tokens = validate_tokens(tokens)

    theme.draft_css = css
    theme.draft_tokens = clean_tokens
    theme.updated_by = editor
    theme.save()
    return theme


def reset_draft(theme: Theme, editor: str) -> Theme:
    """Restore the shipped starter tokens and clear authored CSS.

    A draft-only operation: nothing published changes until someone with
    publish rights ships it. That matters because rollback cannot help here —
    it only replays *published* revisions, so a draft mangled before the first
    publish would otherwise be unrecoverable.
    """
    theme.draft_css = ""
    theme.draft_tokens = default_tokens()
    theme.updated_by = editor
    theme.save()
    return theme


def load_revision_into_draft(
    theme: Theme, revision_number: int, editor: str
) -> Theme:
    """Copy a published revision's content back into the draft.

    Distinct from `rollback`, which republishes. This changes only what the
    editor is working on, so it needs edit rights rather than publish rights —
    and it is what someone actually means by "put the old version back in front
    of me so I can look at it".
    """
    try:
        source = ThemeRevision.objects.get(theme=theme, revision=revision_number)
    except ThemeRevision.DoesNotExist:
        raise ValidationError(
            f"Revision {revision_number} does not exist for theme {theme.slug!r}."
        ) from None

    theme.draft_css = source.css
    theme.draft_tokens = source.tokens or {}
    theme.updated_by = editor
    theme.save()
    return theme


def publish(theme: Theme, publisher: str, note: str = "") -> ThemeRevision:
    """Snapshot the current draft as a new active revision.

    Re-validates rather than trusting that the draft was clean when saved: the
    validator may have tightened since, and this is the last gate before the
    content reaches a patient-facing page.
    """
    css = theme.draft_css or ""
    tokens = validate_tokens(theme.draft_tokens or {})
    validate_css(css)

    return _append_revision(theme, css, tokens, publisher, note)


def rollback(theme: Theme, revision_number: int, publisher: str) -> ThemeRevision:
    """Republish an earlier revision as a new one.

    The old revision is left untouched. Rolling back to revision 3 produces
    revision 7 with revision 3's content, so the history still shows that a
    rollback happened and who did it.
    """
    try:
        source = ThemeRevision.objects.get(theme=theme, revision=revision_number)
    except ThemeRevision.DoesNotExist:
        raise ValidationError(
            f"Revision {revision_number} does not exist for theme {theme.slug!r}."
        ) from None

    # Same gate as publish. The content being replayed is older than any draft,
    # so it is the most likely to fail a validator that has since tightened,
    # and skipping the check would make rollback the way around it.
    css = source.css or ""
    tokens = validate_tokens(source.tokens or {})
    validate_css(css)

    note = f"rollback to revision {revision_number}"
    return _append_revision(theme, css, tokens, publisher, note)


def _append_revision(
    theme: Theme, css: str, tokens: dict[str, str], publisher: str, note: str
) -> ThemeRevision:
    """Create the next revision and make it the only active one.

    "Exactly one active revision per theme" is enforced here rather than by a
    database constraint, because the SDK's supported constraint set does not
    include a conditional unique index. Deactivating first means a crash between
    the two writes leaves zero active revisions (the asset route 404s) rather
    than two (a coin flip over which stylesheet the organization gets).
    """
    # values_list, not .first(): only the number is needed, and a hydrated
    # row would drag along the css blob.
    latest = (
        ThemeRevision.objects.filter(theme=theme)
        .order_by("-revision")
        .values_list("revision", flat=True)
        .first()
    )
    next_number = (latest + 1) if latest else 1

    ThemeRevision.objects.filter(theme=theme, is_active=True).update(is_active=False)

    revision = ThemeRevision.objects.create(
        theme=theme,
        revision=next_number,
        css=css,
        tokens=tokens,
        content_hash=content_hash(css, tokens),
        is_active=True,
        published_by=publisher,
        note=note,
    )

    invalidate(theme.slug)
    return cast(ThemeRevision, revision)
