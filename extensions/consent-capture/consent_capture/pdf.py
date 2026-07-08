"""Minimal, dependency-free PDF generation.

The Canvas plugin sandbox has no PDF library (reportlab, fpdf, ...) and no
``zlib``/``io``. This module hand-writes a valid, uncompressed, single-page PDF
using only the standard library.

Design goal: clean, neutral, professional (Apple/Figma/Google-ish) — grayscale
ink, generous margins, a light rule under the title and before the statement, and
label/value rows. No brand colors.
"""

import base64

# US Letter, in PDF points (72 per inch).
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
LEFT = 64
RIGHT = 548
VALUE_X = LEFT + 120

# Grayscale palette (r, g, b in 0..1).
INK = (0.11, 0.12, 0.15)      # near-black text
MUTED = (0.42, 0.45, 0.50)    # secondary labels / footer
RULE = (0.85, 0.87, 0.90)     # hairline dividers

TITLE_SIZE = 20
HEADING_SIZE = 12
BODY_SIZE = 10.5
LABEL_SIZE = 10
FOOTER_SIZE = 8
BODY_LEADING = 16
PARAGRAPH_GAP = 8

# Usable text width (points): left margin to right margin.
TEXT_WIDTH = RIGHT - LEFT

# Helvetica character widths (units per 1000 em, from the standard AFM). Used to
# measure real text width so paragraphs wrap flush to the right margin instead of
# by an approximate character count.
_HELV_WIDTHS = {
    " ": 278, "!": 278, "\"": 355, "#": 556, "$": 556, "%": 889, "&": 667,
    "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
    ".": 278, "/": 278, "0": 556, "1": 556, "2": 556, "3": 556, "4": 556,
    "5": 556, "6": 556, "7": 556, "8": 556, "9": 556, ":": 278, ";": 278,
    "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015, "A": 667, "B": 667,
    "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "I": 278,
    "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
    "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469,
    "_": 556, "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556,
    "f": 278, "g": 556, "h": 556, "i": 222, "j": 222, "k": 500, "l": 222,
    "m": 833, "n": 556, "o": 556, "p": 556, "q": 556, "r": 333, "s": 500,
    "t": 278, "u": 556, "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
    "{": 334, "|": 260, "}": 334, "~": 584,
}


def _escape(text):
    """Escape characters that are special inside a PDF text string."""
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _num(value):
    """Format a number for the PDF content stream (no trailing zeros noise)."""
    if isinstance(value, int):
        return str(value)
    return ("%.2f" % value).rstrip("0").rstrip(".")


def _text_width(text, size):
    """Width of ``text`` in points at the given font size (Helvetica metrics)."""
    total = 0
    for ch in text:
        total += _HELV_WIDTHS.get(ch, 556)
    return total / 1000.0 * size


def _wrap(text, size=BODY_SIZE, max_width=TEXT_WIDTH):
    """Word-wrap ``text`` to fit ``max_width`` points at the given font size."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if _text_width(candidate, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _text(ops, x, y, font, size, color, text):
    if text:
        ops.append(("text", x, y, font, size, color, text))


def _rule(ops, y, color=RULE, width=0.6, x1=LEFT, x2=RIGHT):
    ops.append(("rule", x1, y, x2, color, width))


def _build_ops(
    title,
    patient_name,
    patient_dob,
    staff_name,
    date,
    statement_paragraphs,
    time="",
    consented_by="Patient",
):
    """Build the drawing operations (text + rules) for the page."""
    ops = []

    # Title + underline.
    y = 738
    _text(ops, LEFT, y, "F2", TITLE_SIZE, INK, title or "Consent")
    _rule(ops, y - 12)

    # Detail rows: muted bold label, dark value.
    y -= 40
    rows = [
        ("Patient", patient_name or "(name unavailable)"),
        ("Date of birth", patient_dob or "-"),
        ("Consent given by", consented_by or "Patient"),
        ("Collected by", staff_name or "Unknown"),
        ("Date", date),
    ]
    for label, value in rows:
        _text(ops, LEFT, y, "F2", LABEL_SIZE, MUTED, label)
        _text(ops, VALUE_X, y, "F1", LABEL_SIZE, INK, value)
        y -= 18

    # Consent statement section — omitted entirely when no statement is on file.
    if statement_paragraphs:
        y -= 4
        _rule(ops, y)
        y -= 26

        _text(ops, LEFT, y, "F2", HEADING_SIZE, INK, "Consent statement")
        y -= 24

        for paragraph in statement_paragraphs:
            for wrapped in _wrap(paragraph, BODY_SIZE, TEXT_WIDTH):
                _text(ops, LEFT, y, "F1", BODY_SIZE, INK, wrapped)
                y -= BODY_LEADING
            y -= PARAGRAPH_GAP

    # Footer: generation date + time.
    _rule(ops, 60)
    if time:
        footer = "Generated %s at %s" % (date, time)
    else:
        footer = "Generated %s" % date
    _text(ops, LEFT, 46, "F1", FOOTER_SIZE, MUTED, footer)

    return ops


def _content_stream(ops):
    """Render drawing operations to a PDF content stream string."""
    parts = []
    for op in ops:
        if op[0] == "text":
            _, x, y, font, size, color, text = op
            r, g, b = color
            parts.append("%s %s %s rg" % (_num(r), _num(g), _num(b)))
            parts.append(
                "BT /%s %s Tf 1 0 0 1 %s %s Tm (%s) Tj ET"
                % (font, _num(size), _num(x), _num(y), _escape(text))
            )
        elif op[0] == "rule":
            _, x1, y, x2, color, width = op
            r, g, b = color
            parts.append("%s %s %s RG" % (_num(r), _num(g), _num(b)))
            parts.append(
                "%s w %s %s m %s %s l S"
                % (_num(width), _num(x1), _num(y), _num(x2), _num(y))
            )
    return "\n".join(parts)


def _assemble_pdf(content_stream):
    """Assemble a complete PDF document from a content stream string."""
    content_bytes = content_stream.encode("latin-1", "replace")

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            "/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> "
            "/Contents 6 0 R >>" % (PAGE_WIDTH, PAGE_HEIGHT)
        ).encode("latin-1")
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    stream_obj = (
        b"<< /Length "
        + str(len(content_bytes)).encode("latin-1")
        + b" >>\nstream\n"
        + content_bytes
        + b"\nendstream"
    )
    objects.append(stream_obj)

    # Header + binary marker comment. The high-byte comment on the second line is
    # what tells PDF viewers and content-type sniffers to treat the file as a
    # binary PDF rather than plain text. Object offsets are computed against this
    # exact prefix.
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += ("%d 0 obj\n" % index).encode("latin-1") + body + b"\nendobj\n"

    xref_offset = len(pdf)
    count = len(objects) + 1
    xref = ("xref\n0 %d\n" % count).encode("latin-1")
    xref += b"0000000000 65535 f \n"
    for offset in offsets:
        xref += ("%010d 00000 n \n" % offset).encode("latin-1")
    pdf += xref
    pdf += (
        "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
        % (count, xref_offset)
    ).encode("latin-1")
    return pdf


def generate_consent_pdf(
    title,
    patient_name,
    patient_dob,
    staff_name,
    date,
    statement_paragraphs,
    time="",
    consented_by="Patient",
):
    """Return the consent documentation as raw PDF bytes."""
    ops = _build_ops(
        title,
        patient_name,
        patient_dob,
        staff_name,
        date,
        statement_paragraphs,
        time,
        consented_by,
    )
    return _assemble_pdf(_content_stream(ops))


def generate_consent_pdf_base64(
    title,
    patient_name,
    patient_dob,
    staff_name,
    date,
    statement_paragraphs,
    time="",
    consented_by="Patient",
):
    """Return the consent documentation PDF as a base64-encoded string."""
    pdf_bytes = generate_consent_pdf(
        title,
        patient_name,
        patient_dob,
        staff_name,
        date,
        statement_paragraphs,
        time,
        consented_by,
    )
    return base64.b64encode(pdf_bytes).decode("ascii")
