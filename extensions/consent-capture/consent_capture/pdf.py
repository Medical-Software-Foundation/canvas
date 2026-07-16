"""Minimal, dependency-free PDF generation.

The Canvas plugin sandbox has no PDF library (reportlab, fpdf, ...) and no
``zlib``/``io``. This module hand-writes a valid, uncompressed, single-page PDF
using only the standard library.

Design goal: clean, neutral, professional (Apple/Figma/Google-ish) — grayscale
ink, generous margins, a light rule under the title and before the statement, and
label/value rows. No brand colors.
"""

import base64
import re

# US Letter, in PDF points (72 per inch).
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
LEFT = 64
RIGHT = 548
VALUE_X = LEFT + 120

# Grayscale palette (r, g, b in 0..1).
INK = (0.11, 0.12, 0.15)      # near-black text
MUTED = (0.34, 0.36, 0.40)    # section/detail labels
FAINT = (0.54, 0.57, 0.62)    # footer fine print
RULE = (0.87, 0.89, 0.92)     # hairline row separators
BORDER = (0.79, 0.81, 0.84)   # table / box borders
BAR = (0.17, 0.18, 0.21)      # masthead rule

TITLE_SIZE = 21
LABEL_SIZE = 8.5              # uppercase detail/section labels
VALUE_SIZE = 11              # detail values
BODY_SIZE = 10.5
FOOTER_SIZE = 8
BODY_LEADING = 15
PARAGRAPH_GAP = 9

# Detail table geometry.
LABEL_COL = 158              # width of the label column
CELL_PAD = 12                # left padding inside a cell
ROW_H = 23                   # compact detail row height

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


def _line(ops, x1, y1, x2, y2, color=RULE, width=0.6):
    """An arbitrary straight line (used for the table's vertical divider)."""
    ops.append(("line", x1, y1, x2, y2, color, width))


def _rect(ops, x, y, w, h, stroke=BORDER, fill=None, width=0.7):
    """A rectangle by its bottom-left corner. Fills first (if any), then strokes."""
    ops.append(("rect", x, y, w, h, stroke, fill, width))


def _right(ops, x_right, y, font, size, color, text):
    """Draw text right-aligned so it ends at ``x_right``."""
    _text(ops, x_right - _text_width(text, size), y, font, size, color, text)


def _build_pages(
    title,
    patient_name,
    patient_dob,
    staff_name,
    date,
    statement_paragraphs,
    time="",
    consented_by="Patient",
    method="",
    capacity_statement="",
    responses=None,
):
    """Build per-page drawing ops for the consent-record form.

    Content flows across as many US-Letter pages as needed: the masthead repeats
    at the top of every page and a footer with "Page X of Y" is stamped on each.
    Returns a list of pages, each a list of ops. Helvetica throughout (``F1``
    regular, ``F2`` bold); grayscale; thin borders, no shading.
    """
    CONTENT_TOP = 702   # first content position below the masthead rule
    BOTTOM = 78         # content must stay above the footer band
    pages = []
    st = {"ops": None, "y": CONTENT_TOP}

    def masthead(ops):
        _text(ops, LEFT, 760, "F2", LABEL_SIZE, MUTED, "PATIENT CONSENT RECORD")
        _text(ops, LEFT, 734, "F2", TITLE_SIZE, INK, title or "Consent")
        _rule(ops, 718, color=BAR, width=1.5)

    def new_page():
        ops = []
        pages.append(ops)
        masthead(ops)
        st["ops"] = ops
        st["y"] = CONTENT_TOP

    def need(height):
        if st["y"] - height < BOTTOM:
            new_page()

    new_page()

    # --- Detail table (page 1) ---
    rows = [
        ("Patient", patient_name or "(name unavailable)"),
        ("Date of birth", patient_dob or "-"),
        ("Consenting Party", consented_by or "Patient"),
    ]
    if method:
        rows.append(("Method obtained", method))
    rows += [
        ("Effective date", date),
        ("Obtained by", staff_name or "Unknown"),
    ]
    ops = st["ops"]
    table_top = st["y"]
    table_bottom = table_top - ROW_H * len(rows)
    label_x = LEFT + CELL_PAD
    value_x = LEFT + LABEL_COL + CELL_PAD
    value_w = RIGHT - value_x - CELL_PAD
    for i, (label, value) in enumerate(rows):
        baseline = table_top - i * ROW_H - 15
        _text(ops, label_x, baseline, "F2", LABEL_SIZE, MUTED, label.upper())
        _text(ops, value_x, baseline, "F1", VALUE_SIZE, INK, _wrap(value, VALUE_SIZE, value_w)[0])
        if i:
            _rule(ops, table_top - i * ROW_H)
    _line(ops, LEFT + LABEL_COL, table_bottom, LEFT + LABEL_COL, table_top)
    _rect(ops, LEFT, table_bottom, RIGHT - LEFT, table_top - table_bottom)
    st["y"] = table_bottom - 30

    # --- Consent statement (flows line by line across pages) ---
    if statement_paragraphs:
        need(18 + BODY_LEADING)
        _text(st["ops"], LEFT, st["y"], "F2", LABEL_SIZE, MUTED, "CONSENT STATEMENT")
        st["y"] = st["y"] - 18
        for paragraph in statement_paragraphs:
            for wrapped in _wrap(paragraph, BODY_SIZE, TEXT_WIDTH):
                need(BODY_LEADING)
                _text(st["ops"], LEFT, st["y"], "F1", BODY_SIZE, INK, wrapped)
                st["y"] = st["y"] - BODY_LEADING
            st["y"] = st["y"] - PARAGRAPH_GAP
        st["y"] = st["y"] - 8

    # --- Capacity attestation box (kept together on one page) ---
    if capacity_statement:
        pad = 13
        inner_w = RIGHT - LEFT - 2 * pad
        lines = _wrap(capacity_statement, BODY_SIZE, inner_w)
        box_h = pad + 11 + len(lines) * BODY_LEADING + (pad - 3)
        need(14 + box_h)
        _text(st["ops"], LEFT, st["y"], "F2", LABEL_SIZE, MUTED, "CAPACITY")
        st["y"] = st["y"] - 14
        box_top = st["y"]
        box_bottom = box_top - box_h
        _rect(st["ops"], LEFT, box_bottom, RIGHT - LEFT, box_h)
        ty = box_top - pad - 4
        _text(st["ops"], LEFT + pad, ty, "F2", 7.5, MUTED, "ATTESTATION OF DECISION-MAKING CAPACITY")
        ty -= 15
        for wrapped in lines:
            _text(st["ops"], LEFT + pad, ty, "F1", BODY_SIZE, INK, wrapped)
            ty -= BODY_LEADING
        st["y"] = box_bottom - 30

    # --- Questions & responses (rows flow across pages) ---
    if responses:
        need(12 + 1 + ROW_H)
        _text(st["ops"], LEFT, st["y"], "F2", LABEL_SIZE, MUTED, "QUESTIONS & RESPONSES")
        st["y"] = st["y"] - 12
        _rule(st["ops"], st["y"])
        for prompt, answer in responses:
            answer_w = _text_width(answer, BODY_SIZE) + 24
            q_lines = _wrap(prompt, BODY_SIZE, (RIGHT - answer_w) - LEFT)
            row_h = max(ROW_H, len(q_lines) * BODY_LEADING + 8)
            need(row_h)
            baseline = st["y"] - 15
            _right(st["ops"], RIGHT, baseline, "F1", BODY_SIZE, INK, answer)
            for wrapped in q_lines:
                _text(st["ops"], LEFT, baseline, "F1", BODY_SIZE, INK, wrapped)
                baseline -= BODY_LEADING
            st["y"] = min(st["y"] - ROW_H, baseline + BODY_LEADING - 8)
            _rule(st["ops"], st["y"])
        st["y"] = st["y"] - 22

    # --- Footer, stamped on every page with the correct page count ---
    recorded = "Recorded %s at %s" % (date, time) if time else "Recorded %s" % date
    total = len(pages)
    for index, ops in enumerate(pages):
        _rule(ops, 60)
        _text(ops, LEFT, 46, "F1", FOOTER_SIZE, FAINT, recorded)
        _right(ops, RIGHT, 46, "F1", FOOTER_SIZE, FAINT,
               "Confidential · Patient Health Information · Page %d of %d" % (index + 1, total))
    return pages


def _build_ops(*args, **kwargs):
    """Flattened ops across all pages (kept for tests / simple inspection)."""
    return [op for page in _build_pages(*args, **kwargs) for op in page]


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
        elif op[0] == "line":
            _, x1, y1, x2, y2, color, width = op
            r, g, b = color
            parts.append("%s %s %s RG" % (_num(r), _num(g), _num(b)))
            parts.append(
                "%s w %s %s m %s %s l S"
                % (_num(width), _num(x1), _num(y1), _num(x2), _num(y2))
            )
        elif op[0] == "rect":
            _, x, y, w, h, stroke, fill, width = op
            if fill is not None:
                r, g, b = fill
                parts.append("%s %s %s rg" % (_num(r), _num(g), _num(b)))
                parts.append("%s %s %s %s re f" % (_num(x), _num(y), _num(w), _num(h)))
            if stroke is not None:
                r, g, b = stroke
                parts.append("%s %s %s RG" % (_num(r), _num(g), _num(b)))
                parts.append(
                    "%s w %s %s %s %s re S" % (_num(width), _num(x), _num(y), _num(w), _num(h))
                )
    return "\n".join(parts)


def _assemble_pdf(content_streams):
    """Assemble a multi-page PDF from one content stream per page.

    Each stream is encoded as CP1252 (WinAnsi) so smart punctuation renders; the
    fonts declare /WinAnsiEncoding to match. Object layout: 1 Catalog, 2 Pages,
    3/4 fonts, then a Page + Contents object per page.
    """
    page_bytes = [s.encode("cp1252", "replace") for s in content_streams]
    n = len(page_bytes)

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join("%d 0 R" % (5 + 2 * i) for i in range(n))
    objects.append(("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode("latin-1"))
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    for i, cb in enumerate(page_bytes):
        content_num = 6 + 2 * i
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                "/Contents %d 0 R >>" % (PAGE_WIDTH, PAGE_HEIGHT, content_num)
            ).encode("latin-1")
        )
        objects.append(
            b"<< /Length " + str(len(cb)).encode("latin-1") + b" >>\nstream\n" + cb + b"\nendstream"
        )

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
    method="",
    capacity_statement="",
    responses=None,
):
    """Return the consent documentation as raw PDF bytes (one or more pages)."""
    pages = _build_pages(
        title,
        patient_name,
        patient_dob,
        staff_name,
        date,
        statement_paragraphs,
        time,
        consented_by,
        method,
        capacity_statement,
        responses,
    )
    return _assemble_pdf([_content_stream(page) for page in pages])


def pdf_page_count(data):
    """Count pages in a PDF by its ``/Type /Page`` objects (excluding ``/Type /Pages``).

    Exact for this module's uncompressed output and for uploaded documents saved
    without object streams. Returns 0 when it can't be determined (e.g. a
    compressed/object-stream PDF hides the page objects) so callers can fall back to
    showing just "PDF" without a count."""
    if not data:
        return 0
    try:
        return len(re.findall(rb"/Type\s*/Page(?![s])", data))
    except Exception:  # noqa: BLE001 - a count is best-effort; never raise
        return 0


def generate_consent_pdf_base64(
    title,
    patient_name,
    patient_dob,
    staff_name,
    date,
    statement_paragraphs,
    time="",
    consented_by="Patient",
    method="",
    capacity_statement="",
    responses=None,
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
        method,
        capacity_statement,
        responses,
    )
    return base64.b64encode(pdf_bytes).decode("ascii")
