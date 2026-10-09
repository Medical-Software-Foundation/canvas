"""Staff-typed text must be escaped before it is placed into the admin page as HTML.

Reasons are typed by any staff member who can edit, and the page runs on the
Canvas instance's own domain, so an unescaped reason containing markup runs as
script for everyone who opens Provider Availability. This scans admin.js for a
reason or a name joined into an HTML string without going through _escHtml.
"""

import re
from pathlib import Path

ADMIN_JS = Path(__file__).parent.parent / "provider_availability" / "static" / "js" / "admin.js"

# `' + x.reason + '`, `' + (b.reason || ...`, `' + name + '`, `' + initials + '`
_RAW_JOIN = re.compile(r"'\s*\+\s*\(?\s*(?:[A-Za-z_]+\.)?(reason|name|initials|label|rbReasonText)\b\s*(?:\|\||\+|\))")


def test_reasons_and_names_are_escaped_in_html():
    offenders = []
    for lineno, line in enumerate(ADMIN_JS.read_text().splitlines(), start=1):
        if "<" not in line:  # only lines that build HTML
            continue
        for match in _RAW_JOIN.finditer(line):
            offenders.append(f"admin.js:{lineno}: {line.strip()[:120]}")
    assert offenders == [], "Wrap these in _escHtml(...):\n" + "\n".join(offenders)


def test_the_scan_catches_an_unescaped_reason():
    """The pattern has to be able to fail, or the test above proves nothing."""
    assert _RAW_JOIN.search("html += '<span>' + b.reason + '</span>';")
    assert _RAW_JOIN.search("x = '<div>' + (r.reason || '-') + '</div>';")
    assert not _RAW_JOIN.search("html += '<span>' + _escHtml(b.reason) + '</span>';")


# `+ o.reason`, `+ (r.reason || ...)` anywhere, not only on lines that contain markup:
# a reason can be joined into a variable first and placed into HTML lines later.
# A `(x.reason ? ... : ...)` test is not a join. rbReasonText is built here and
# escaped where it is shown, which _RAW_JOIN above checks.
_RAW_REASON = re.compile(r"\+\s*\(?\s*[A-Za-z_]+\.reason\b(?!\s*\?)")
# Record JSON placed into an inline handler must be entity-escaped: JSON keeps
# apostrophes and quotes, which end the attribute early.
_HANDLER_JSON = re.compile(r"(?<!_escHtml\()JSON\.stringify\(JSON\.stringify\(")


def test_reasons_are_never_joined_raw():
    offenders = [
        f"admin.js:{lineno}: {line.strip()[:120]}"
        for lineno, line in enumerate(ADMIN_JS.read_text().splitlines(), start=1)
        if _RAW_REASON.search(line) and "rbReasonText =" not in line
    ]
    assert offenders == [], "Wrap these in _escHtml(...):\n" + "\n".join(offenders)


def test_record_json_in_handlers_is_escaped():
    offenders = [
        f"admin.js:{lineno}: {line.strip()[:120]}"
        for lineno, line in enumerate(ADMIN_JS.read_text().splitlines(), start=1)
        if _HANDLER_JSON.search(line)
    ]
    assert offenders == [], "Wrap these in _escHtml(...):\n" + "\n".join(offenders)


def test_escaping_covers_quotes_for_attributes():
    """_escHtml output goes into title="..." and onclick='...', so it must escape both quote marks."""
    src = ADMIN_JS.read_text()
    body = src[src.index("function _escHtml("):]
    body = body[: body.index("\n}\n")]
    assert "&quot;" in body and "&#39;" in body


def test_the_new_scans_can_fail():
    assert _RAW_REASON.search("const label = ' - ' + o.reason;")
    assert _RAW_REASON.search("x = 'a' + (r.reason || '')")
    assert not _RAW_REASON.search("x = 'a' + _escHtml(o.reason)")
    assert not _RAW_REASON.search("x = '<b>' + (r.reason ? _escHtml(r.reason) : '-')")
    assert _HANDLER_JSON.search("const j = JSON.stringify(JSON.stringify(r));")
    assert not _HANDLER_JSON.search("const j = _escHtml(JSON.stringify(JSON.stringify(r)));")
