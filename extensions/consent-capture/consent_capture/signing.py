"""Pure helpers for "Sign on this device" (no SDK imports).

Kept separate from the handler so the name check, the accepted-signature rules and
the signature image validation can be unit-tested without a live Canvas
environment. The picker runs the same name check in the browser (``nameKey`` /
``sameName`` in ``templates/picker.html``); the server repeats it so a mismatch can
never be recorded without staff choosing what to do about it.
"""

import base64
import hashlib

# How a signature was made. Drawn strokes are classified by the pointer that made
# them (``touch`` / ``pen`` -> finger, ``mouse`` -> mouse; browsers report a trackpad
# as a mouse), and a typed signature comes from the Type tab.
SIGNED_WITH = ("finger", "mouse", "typed")

# How it reads in the plugin's own screens (On File, the receipt, Review consents).
SIGNED_WITH_LABELS = {
    "finger": "Signed on this device (finger or stylus)",
    "mouse": "Signed on this device (mouse or trackpad)",
    "typed": "Signed on this device (typed)",
}

# Name suffixes that make two people different ("Robert Lopez Jr." is not
# "Robert Lopez"). Compared lower-cased with periods removed.
NAME_SUFFIXES = ("jr", "sr", "ii", "iii", "iv", "v")

# The signature image the browser sends: a JPEG (no zlib in the sandbox, so PNG
# can't be embedded in the PDF). A signature canvas exports well under this.
MAX_SIGNATURE_BYTES = 512 * 1024
JPEG_MAGIC = b"\xff\xd8\xff"

# Start-of-frame markers that carry the image size (baseline, progressive, ...).
# Excludes 0xC4 (DHT), 0xC8 (JPG) and 0xCC (DAC), which share the range.
_SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


def name_key(text):
    """Reduce a name to ``(first, last, suffix)`` for comparison.

    Lower-cases, treats periods and commas as spaces, collapses whitespace, and
    pulls a trailing suffix (Jr, Sr, II, III, IV, V) off when there is more than one
    word. Middle names and initials fall between first and last and are ignored."""
    words = (
        str(text or "").lower().replace(".", " ").replace(",", " ").split()
    )
    suffix = ""
    if len(words) > 1 and words[-1] in NAME_SUFFIXES:
        suffix = words.pop()
    first = words[0] if words else ""
    last = words[-1] if len(words) > 1 else ""
    return first, last, suffix


def same_name(a, b):
    """Whether two names belong to the same person: first name, last name and
    suffix agree. "Maria L. Lopez" matches "Maria Lopez"; "Robert Lopez Jr." does
    not match "Robert Lopez"; "Maria Lopez-Garcia" does not match "Maria Lopez"."""
    return name_key(a) == name_key(b)


def accepted_signed_with(settings):
    """The ``SIGNED_WITH`` values the practice accepts, from its settings dict."""
    accepted = []
    if settings.get("accept_finger"):
        accepted.append("finger")
    if settings.get("accept_mouse"):
        accepted.append("mouse")
    if settings.get("accept_typed"):
        accepted.append("typed")
    return accepted


def jpeg_info(data):
    """Return ``(width, height, components)`` of a JPEG by walking its markers to
    the first start-of-frame segment, or ``None`` when it isn't a readable JPEG.
    ``components`` is 1 for grayscale and 3 for color.

    Pure byte arithmetic (no ``struct``) so it runs in the plugin sandbox."""
    if not data or not data.startswith(JPEG_MAGIC):
        return None
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte before a marker
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length
            i += 2
            continue
        length = (data[i + 2] << 8) | data[i + 3]
        if length < 2:
            return None
        if marker in _SOF_MARKERS:
            if i + 10 > n:
                return None
            height = (data[i + 5] << 8) | data[i + 6]
            width = (data[i + 7] << 8) | data[i + 8]
            components = data[i + 9]
            if not width or not height or components not in (1, 3):
                return None
            return width, height, components
        i += 2 + length
    return None


def clean_signature_jpeg(raw):
    """Validate a browser-supplied signature image (base64 JPEG, optionally a
    ``data:image/jpeg;base64,`` URL).

    Returns ``(jpeg_bytes, width, height, components, error)``: the decoded image,
    its size and color components (1 grayscale, 3 color) on success, or empty values
    and a user-facing message on failure. Grayscale and
    color JPEGs are accepted; CMYK is not (browsers never export it)."""
    if not raw or not isinstance(raw, str):
        return b"", 0, 0, 0, "Add a signature before recording."
    payload = raw.split(",", 1)[1] if raw.startswith("data:") else raw
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception:  # noqa: BLE001 - any decode failure is a bad signature
        return b"", 0, 0, 0, "The signature couldn't be read. Please sign again."
    if len(data) > MAX_SIGNATURE_BYTES:
        return b"", 0, 0, 0, "The signature image is too large. Please sign again."
    info = jpeg_info(data)
    if info is None:
        return b"", 0, 0, 0, "The signature couldn't be read. Please sign again."
    return data, info[0], info[1], info[2], None


def statement_fingerprint(paragraphs):
    """The consent text exactly as shown, and a SHA-256 of it.

    Stored with each recording so the record keeps what the signer saw, and a
    later edit to the consent in Consent Settings is detectable."""
    text = "\n".join(paragraphs or [])
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()
