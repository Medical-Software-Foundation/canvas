"""Escaping helpers for the template-to-JavaScript handshake."""

import json
from typing import Any


def safe_json(value: Any) -> str:
    """Serialize a value for embedding in a ``<script type="application/json">``.

    Two escaping problems meet in that element and pull in opposite directions.
    Django autoescaping would turn the JSON quotes into ``&quot;`` and break
    ``JSON.parse``, so the template has to mark the value ``|safe``. But
    ``json.dumps`` does not escape ``<``, ``>`` or ``&``, so a stored value
    containing ``</script>`` would close the tag early and everything after it
    would be parsed as markup.

    Escaping those three characters to their ``\\u`` forms resolves both: the
    output is still valid JSON that ``JSON.parse`` accepts, and it can no longer
    terminate the element it sits in.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
