"""Pure helpers for the Twilio inbound-SMS webhook.

Signature verification, form-body parsing, and structured intent classification.
No PHI, no free-form/NLP — only exact-match Y/N tokens are actioned; anything
else is a safe no-op. Kept dependency-free so it is fully unit-testable.
"""
import base64
import hashlib
import hmac


def _url_decode(token: bytes) -> str:
    """Percent-decode one urlencoded token (``+`` → space, ``%XX`` → byte).

    Decodes at the byte level then UTF-8, so multi-byte characters (emoji,
    accents) in an SMS body survive. Hand-rolled because the Canvas sandbox
    disallows ``urllib.parse.parse_qsl`` / ``unquote``.

    Accumulates into a ``list[int]`` rather than a ``bytearray`` because the
    sandbox validator blocks ``bytearray``.
    """
    out: list[int] = []
    i = 0
    n = len(token)
    while i < n:
        c = token[i]
        if c == 0x2B:  # '+'
            out.append(0x20)
            i += 1
        elif c == 0x25 and i + 2 < n:  # '%'
            try:
                out.append(int(token[i + 1 : i + 3], 16))
                i += 3
            except ValueError:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return bytes(out).decode("utf-8", errors="replace")


def parse_form_body(raw: bytes | str | None) -> dict[str, str]:
    """Parse an ``application/x-www-form-urlencoded`` body into a flat dict.

    Twilio posts single-valued params (``From``, ``To``, ``Body``, ...). Blank
    values are kept so signature computation matches Twilio's exactly. Later
    duplicate keys win (last-value), matching typical form semantics.
    """
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    result: dict[str, str] = {}
    for pair in raw.split(b"&"):
        if not pair:
            continue
        key, sep, value = pair.partition(b"=")
        result[_url_decode(key)] = _url_decode(value)
    return result


def valid_twilio_signature(
    url: str | None,
    params: dict[str, str],
    auth_token: str | None,
    signature: str | None,
) -> bool:
    """Verify Twilio's ``X-Twilio-Signature`` header.

    Twilio signs ``url + "".join(key + value for key in sorted(params))`` with
    HMAC-SHA1 keyed by the account auth token, base64-encoded. **Fails closed:**
    a missing auth token, webhook url, or signature returns ``False``.
    """
    if not (auth_token and url and signature):
        return False
    data = url
    for key in sorted(params):
        data += key + params[key]
    digest = hmac.new(
        auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# Structured tokens only. Exact-match (whole message) so a message like
# "no problem, see you then" is NOT misread as a decline.
#
# "cancel" is deliberately absent from _DECLINE. Twilio publishes it as an
# unsubscribe synonym, so a patient texting it means "stop texting me", not
# "cancel my appointment". It is handled as an opt-out below; treating it as an
# appointment action too would attribute an intent the patient never expressed.
_CONFIRM = {"y", "yes", "confirm", "confirmed", "1", "c"}
_DECLINE = {"n", "no", "decline", "declined", "2"}

# Twilio's standard consent keywords. Twilio acts on these itself — it adds or
# removes the number from its block list and auto-replies — and then forwards
# the message here, so the plugin's job is to mirror the same decision onto the
# chart. See https://help.twilio.com/articles/223134027.
#
# YES deliberately overlaps _CONFIRM above: it is both Twilio's opt-in keyword
# and this plugin's confirm token, and a patient texting it means both — put me
# back on the list, and yes to the appointment. That overlap is why consent is
# classified on its own axis rather than folded into `classify_reply`, which can
# only return one verdict.
_OPT_OUT = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke", "optout"}
_OPT_IN = {"start", "yes", "unstop"}


def _normalize(body: str | None) -> str:
    """Trim surrounding whitespace and punctuation and casefold."""
    if not body:
        return ""
    return body.strip().lower().strip(".!?, ")


def classify_reply(body: str | None) -> str:
    """Classify an inbound SMS as ``"confirm"`` / ``"decline"`` / ``"unrecognized"``.

    Only a message that is *exactly* a known token (after trimming surrounding
    whitespace/punctuation) is actioned. Multi-word or unknown messages return
    ``"unrecognized"`` — a deliberate no-op, since a false decline would wrongly
    flag a patient who actually meant to confirm.
    """
    normalized = _normalize(body)
    if normalized in _CONFIRM:
        return "confirm"
    if normalized in _DECLINE:
        return "decline"
    return "unrecognized"


def classify_consent(body: str | None) -> str:
    """Classify an inbound SMS as ``"opt_out"`` / ``"opt_in"`` / ``""`` (neither).

    Orthogonal to :func:`classify_reply`: a message can carry both a consent
    change and an appointment intent, and the caller acts on each. ``YES`` is
    the live case — opt back in *and* confirm.

    Twilio only matches a bare keyword, so "PLEASE CANCEL" does not opt anyone
    out on their side. Stripping trailing punctuation makes this slightly more
    generous than that ("stop." counts here), which errs toward *not* texting a
    patient who plainly asked us to stop.
    """
    normalized = _normalize(body)
    if normalized in _OPT_OUT:
        return "opt_out"
    if normalized in _OPT_IN:
        return "opt_in"
    return ""
