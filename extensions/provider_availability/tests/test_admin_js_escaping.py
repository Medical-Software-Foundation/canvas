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
