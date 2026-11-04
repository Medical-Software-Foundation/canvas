"""Per-viewer allowlists keyed on a plugin secret holding staff identifiers.

Two rules are load-bearing and easy to get wrong:

**Unset means nobody.** An allowlist guards a surface whose whole point is not
being seen yet, so the failure mode has to be "too few people see it", never
"the clinic saw it". Go GA by setting the secret to ``"*"``, not by deleting
it — deleting silently re-closes the feature.

**Read the header off the headers object.** Canvas hands over a
``CaseInsensitiveMultiDict``; ``dict(request.headers).get(...)`` flattens it,
makes the lookup casing-dependent, and silently denies everyone.

One caveat specific to this plugin: ``staff_allowed`` answers the wildcard
before it looks at the identity, so a blank id passes when the secret is
``"*"``. That is fine for a pure feature flag and wrong here, because the
summary queries are *scoped by* that id. ``cosign_access.viewer_role`` rejects
a blank id before consulting this module. Do not paper over it here — the
mirror has to stay byte-comparable to its source.
"""

from __future__ import annotations

from typing import Any

#: The secret value that opens a gated surface to everyone.
STAFF_KEY_WILDCARD = "*"

#: Separators accepted inside a staff-key secret. Commas are the documented
#: form; newlines and spaces are tolerated because the realistic way one of
#: these gets written is by pasting keys out of a spreadsheet or a Slack
#: message.
STAFF_KEY_SEPARATORS = (",", ";", "\n", "\r", "\t", " ")

#: The header Canvas sets from the session. It strips the header if a client
#: tries to send it, which is what makes it trustworthy — see
#: ``SessionCredentials`` in ``canvas_sdk.handlers.simple_api.security``.
STAFF_ID_HEADER = "canvas-logged-in-user-id"


def normalize_staff_key(value: Any) -> str:
    """Lowercased, dash-free form of a staff identifier, for comparison only.

    ``Staff.id`` is a 32-char hex ``key`` with no dashes, but the value someone
    pastes into a secret may well be the dashed UUID rendering of it.
    Normalizing both sides means a dashed paste still matches.

    **Comparison only — never store or send this.** Dashing or un-dashing a
    staff key on a *write* path has already broken one feature (it silently
    emptied ``ordering_provider_key`` on lab orders). Here nothing is written;
    the normalized string is compared and discarded.
    """
    text = str(value or "").strip().lower()
    return text.replace("-", "")


def parse_staff_keys(secrets: Any, secret_name: str) -> frozenset[str]:
    """The normalized allowlist held in ``secret_name`` (empty when unset)."""
    try:
        raw = (secrets or {}).get(secret_name, "")
    except Exception:
        return frozenset()
    text = str(raw or "")
    for separator in STAFF_KEY_SEPARATORS:
        text = text.replace(separator, ",")
    keys = set()
    for chunk in text.split(","):
        normalized = normalize_staff_key(chunk)
        if normalized:
            keys.add(normalized)
    return frozenset(keys)


def staff_allowed(secrets: Any, secret_name: str, staff_id: Any) -> bool:
    """True when ``staff_id`` appears in the ``secret_name`` allowlist.

    Unset (or whitespace-only) means nobody. ``"*"`` means everybody. A blank
    or unreadable identity is denied rather than allowed: an anonymous caller
    must not inherit the allowlist, because this predicate is often the only
    thing standing between a clinic and a surface they should not see.
    """
    keys = parse_staff_keys(secrets, secret_name)
    if not keys:
        return False
    if STAFF_KEY_WILDCARD in keys:
        return True
    normalized = normalize_staff_key(staff_id)
    if not normalized:
        return False
    return normalized in keys


def requesting_staff_id(request: Any) -> str:
    """The logged-in staff id for this request, or ``""`` if unavailable."""
    try:
        return str(request.headers.get(STAFF_ID_HEADER, "") or "")
    except Exception:
        return ""
