"""Bundled-template loader for the Exam tab.

Checkpoint 2 ships a static `default_templates.json` alongside the plugin.
A later checkpoint will add a URL-fetched override (per spec §11).
"""
from __future__ import annotations

import json
from typing import Any

from canvas_sdk.templates import render_to_string
from logger import log

DEFAULT_TEMPLATES_PATH = "templates/default_templates.json"

# Cached on first call. The bundled JSON ships with the plugin and only
# changes on reinstall (which reloads the module), so re-parsing it on
# every /exam/templates request is pure waste. `None` = not yet loaded;
# `{}` = loaded but empty / malformed (callers degrade gracefully).
_DEFAULT_TEMPLATES_CACHE: dict[str, Any] | None = None


def load_default_templates() -> dict[str, Any]:
    """Read the bundled templates JSON. Returns an empty dict if the file
    is missing or malformed — callers handle the empty case by falling
    back to an empty string. Result is cached for the lifetime of the
    process."""
    global _DEFAULT_TEMPLATES_CACHE
    if _DEFAULT_TEMPLATES_CACHE is not None:
        return _DEFAULT_TEMPLATES_CACHE
    try:
        raw = render_to_string(DEFAULT_TEMPLATES_PATH)
        parsed = json.loads(raw)
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        log.warning(f"[templates] failed to load defaults: {exc.__class__.__name__}: {exc}")
        _DEFAULT_TEMPLATES_CACHE = {}
        return _DEFAULT_TEMPLATES_CACHE
    _DEFAULT_TEMPLATES_CACHE = parsed if isinstance(parsed, dict) else {}
    return _DEFAULT_TEMPLATES_CACHE


def get_hpi_template(code: str | None) -> str:
    """Return the HPI prefill text for a given RFV code, falling back to
    the `default` entry, then to an empty string."""
    data = load_default_templates()
    templates = data.get("templates", {}) if isinstance(data, dict) else {}
    if code and code in templates:
        entry = templates[code]
    else:
        entry = templates.get("default", {})
    if not isinstance(entry, dict):
        return ""
    hpi = entry.get("hpi", "")
    return hpi if isinstance(hpi, str) else ""
