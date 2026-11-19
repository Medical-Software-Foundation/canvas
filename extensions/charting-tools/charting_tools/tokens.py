"""Short-lived signed tokens binding an in-command button click to a note.

The panel rendered inside a Diagnose/Assess command lives in a
sandboxed frame that cannot send a staff-session cookie, so a button's call to
this plugin authenticates itself with one of these tokens instead. A token is
minted server-side when the buttons are rendered and embedded in the HTML; it
encodes the note uuid, the originating command uuid, and an expiry, signed with
the ``PANEL_TOKEN_SIGNING_KEY`` setting. The command endpoints never trust a note id
from the client — they read it back out of the verified token.
"""

from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from time import time

DEFAULT_TTL_SECONDS = 14400  # 4 hours; the panel is re-signed on an edit before then


def sign_token(
    note_uuid: str,
    origin_command_uuid: str,
    signing_key: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> str:
    """Return a signed token binding a caller to a note + origin command.

    Format: "note_uuid|origin_command_uuid|expiry_epoch.hex_signature". UUIDs
    contain no "|" or ".", and the signature is hex, so the separators are
    unambiguous. No base64 is needed (its urlsafe variants aren't on the sandbox
    allowlist).
    """
    current = int(now if now is not None else time())
    expiry = current + int(ttl_seconds)
    payload = "%s|%s|%d" % (note_uuid, origin_command_uuid or "", expiry)
    signature = hmac_new(
        signing_key.encode("utf-8"), payload.encode("utf-8"), sha256
    ).hexdigest()
    return "%s.%s" % (payload, signature)


def verify_token(token: str, signing_key: str, now: float | None = None) -> tuple[str, str] | None:
    """Return (note_uuid, origin_command_uuid) if valid and unexpired, else None."""
    current = int(now if now is not None else time())
    try:
        payload, signature = token.rsplit(".", 1)
    except (ValueError, AttributeError):
        return None
    expected = hmac_new(
        signing_key.encode("utf-8"), payload.encode("utf-8"), sha256
    ).hexdigest()
    if not compare_digest(expected, signature):
        return None
    try:
        note_uuid, origin_command_uuid, expiry_text = payload.rsplit("|", 2)
        expiry = int(expiry_text)
    except ValueError:
        return None
    if not note_uuid or current > expiry:
        return None
    return note_uuid, origin_command_uuid
