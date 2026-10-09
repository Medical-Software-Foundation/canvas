"""Renders the admin UI HTML for provider availability management.

The page itself lives in templates/admin_page.html and is read on every
request, like the page's script and styles. Keeping it as a Python string
meant an update could leave the previous version's page in memory while the
new script was served, so changes to the page did not show until a restart.
"""

import json
from datetime import datetime, timezone

from canvas_sdk.templates import render_to_string


def render_admin_page(preloaded: dict | None = None) -> str:
    """Return the admin UI HTML with optional pre-rendered data."""
    if preloaded:
        # No "<" at all inside the script: "</script>" would end it early and
        # "<!--<script" would make the browser swallow the next script tag.
        # "\u003c" is the same character to JSON and JavaScript.
        raw = json.dumps(preloaded, default=str)
        safe_json = raw.replace("<", "\\u003c")
        script_tag = f"<script>window.__PRELOADED__={safe_json};</script>"
    else:
        script_tag = ""
    # Stamped per request: the assets are served no-cache, so this only has to
    # change whenever the page is built, and it can never outlive an update.
    cache_bust = str(int(datetime.now(timezone.utc).timestamp()))
    return render_to_string(
        "templates/admin_page.html",
        {"preloaded_script": script_tag, "cache_bust": cache_bust},
    ) or ""
