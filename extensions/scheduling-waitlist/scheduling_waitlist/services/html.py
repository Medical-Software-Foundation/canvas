"""Helpers for embedding data in server-rendered HTML."""

from __future__ import annotations

import json
from typing import Any


def safe_json(value: Any) -> str:
    """Serialize to JSON with HTML-unsafe characters escaped to unicode.

    ``json.dumps`` leaves ``<``, ``>``, and ``&`` alone, so dropping its output
    straight into an inline ``<script>`` block lets any stored value containing
    ``</script>`` close the tag early and run whatever follows as markup. A
    practice location or patient note is enough to carry that.

    The ``\\u003c`` / ``\\u003e`` / ``\\u0026`` escapes are ordinary JSON, decode
    back to the original characters when the browser parses them, and never
    produce a literal ``</script>`` for the HTML tokenizer to act on.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
