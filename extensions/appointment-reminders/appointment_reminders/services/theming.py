"""Theming helper: the Canvas house palette as CSS custom properties.

The palette is fixed. The two pages that use it (the Appointment Reminders
admin modal and the per-patient chart pane) render inside Canvas's own
chrome, so they follow Canvas styling rather than a per-install override.
Matches the reference plugins in ``medical-software-foundation/canvas`` —
see ``provider_scheduling``.
"""

from __future__ import annotations

# Canvas in-app reference palette. Keep in sync with the same module in
# scheduling_with_rooms; both plugins ship to the same instances.
_CANVAS_DEFAULTS: dict[str, str] = {
    "brand-primary": "#2563eb",          # Canvas blue-600
    "brand-primary-hover": "#1d4ed8",    # Canvas blue-700
    "brand-primary-tint-bg": "#eff6ff",  # Canvas blue-50
    "brand-primary-tint-text": "#1e40af",  # Canvas blue-800
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
    "warning-bg": "#fff8e1",
    "warning-fg": "#d4850f",
    "font-stack": (
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif"
    ),
    "radius": "0.5rem",
}


def theme_style_block() -> str:
    """Render ``<style>:root { --*: ...; }</style>``.

    Drop into a template ``<head>``; reference variables as
    ``var(--brand-primary)`` etc. inside CSS.
    """
    parts = ["<style>\n:root {"]
    parts.extend(f"  --{key}: {value};" for key, value in _CANVAS_DEFAULTS.items())
    parts.append("}\n</style>")
    return "\n".join(parts)
