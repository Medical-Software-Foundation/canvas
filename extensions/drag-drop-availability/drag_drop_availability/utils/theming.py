"""Theming helper: Canvas defaults out of the box, optional secrets override.

Customers who want to re-skin without forking can set any of the BRAND_*
secrets in their plugin install. Unset / blank / malformed values fall back
to Canvas's house palette (matches the reference plugins in
``medical-software-foundation/canvas`` — see ``provider_scheduling``).
"""

from __future__ import annotations

import re

# Canvas in-app reference palette (gtm-extensions/drag_drop_availability target).
# Keep these in sync with msf-canvas/provider_scheduling/static/availability/styles.css.
_CANVAS_DEFAULTS: dict[str, str] = {
    # Brand-y values: customer-overridable.
    "brand-primary": "#2563eb",          # Canvas blue-600
    "brand-primary-hover": "#1d4ed8",    # Canvas blue-700
    "brand-primary-tint-bg": "#eff6ff",  # Canvas blue-50
    "brand-primary-tint-text": "#1e40af",  # Canvas blue-800
    # Neutral / status values: NOT overridable. Customer can't make them
    # look correct against any palette they pick, so we keep a coherent set.
    "text-strong": "#111827",
    "text-body": "#374151",
    "text-muted": "#4b5563",
    "text-subtle": "#6b7280",
    "text-soft": "#9ca3af",
    "surface-page": "#f9fafb",
    "surface-card": "#ffffff",
    "surface-hover": "#f3f4f6",
    "border-default": "#e5e7eb",
    "border-strong": "#d1d5db",
    "danger-bg": "#fef2f2",
    "danger-fg": "#dc2626",
    "success-bg": "#d1fae5",
    "success-fg": "#065f46",
    "font-stack": (
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif"
    ),
    "radius": "0.5rem",
}

# Which keys can be overridden by secrets, and the secret name for each.
_OVERRIDABLE_COLORS: dict[str, str] = {
    "brand-primary": "BRAND_PRIMARY",
    "brand-primary-hover": "BRAND_PRIMARY_HOVER",
    "brand-primary-tint-bg": "BRAND_PRIMARY_TINT_BG",
    "brand-primary-tint-text": "BRAND_PRIMARY_TINT_TEXT",
}

# Accept #rgb / #rrggbb / #rrggbbaa to prevent CSS injection via secrets.
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# Font-family list: alphanumerics, spaces, commas, dashes, periods, quotes.
# Forbids ``;{}()<>`` etc. so a malformed secret can't escape the CSS rule.
_FONT_STACK_RE = re.compile(r"^[A-Za-z0-9 ,\-'\"\.]+$")

# Font-import URL: only allow Google Fonts CSS endpoints.
_FONT_URL_RE = re.compile(
    r"^https://fonts\.googleapis\.com/css2?\?[A-Za-z0-9=:&;,@_+\-\.%]+$"
)


def resolve_theme(secrets: dict[str, str] | None) -> dict[str, str]:
    """Return the resolved theme dict, applying any valid secret overrides."""
    theme = dict(_CANVAS_DEFAULTS)
    if not secrets:
        return theme
    for key, secret_name in _OVERRIDABLE_COLORS.items():
        raw = (secrets.get(secret_name) or "").strip()
        if raw and _HEX_COLOR_RE.match(raw):
            theme[key] = raw
    raw_font = (secrets.get("BRAND_FONT_STACK") or "").strip()
    if raw_font and _FONT_STACK_RE.match(raw_font):
        theme["font-stack"] = raw_font
    return theme


def resolve_font_url(secrets: dict[str, str] | None) -> str:
    """Return a Google Fonts CSS URL if the secret is set and valid, else ``""``."""
    if not secrets:
        return ""
    raw = (secrets.get("BRAND_FONT_URL") or "").strip()
    if raw and _FONT_URL_RE.match(raw):
        return raw
    return ""


def theme_style_block(secrets: dict[str, str] | None) -> str:
    """Render a ``<link>``+``<style>`` block to drop into a template ``<head>``.

    Include the result once near the top of the rendered HTML, then
    reference variables as ``var(--brand-primary)`` in CSS.

    When ``BRAND_FONT_URL`` is set to a valid Google Fonts URL, a
    ``<link rel="stylesheet">`` is emitted before the ``<style>`` block.
    """
    theme = resolve_theme(secrets)
    font_url = resolve_font_url(secrets)
    parts: list[str] = []
    if font_url:
        parts.append(f'<link href="{font_url}" rel="stylesheet">')
    parts.append("<style>\n:root {")
    parts.extend(f"  --{key}: {value};" for key, value in theme.items())
    parts.append("}\n</style>")
    return "\n".join(parts)
