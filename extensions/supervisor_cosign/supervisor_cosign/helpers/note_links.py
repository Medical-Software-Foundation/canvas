"""URLs that open a specific note, or the summary page positioned on one.

The chart deep link uses the ``/patient/<key>?noteId=<dbid>`` format. Both builders return ``""`` rather than a half-assembled URL
when an input is missing, so a caller can test the result instead of emitting a
link that goes nowhere.

Kept free of any Canvas SDK import so it is unit-testable outside the sandbox.
"""

from __future__ import annotations

from typing import Any

#: Where the summary page lives. The page itself hardcodes the same prefix.
SUMMARY_VIEW_URL = "/plugin-io/api/supervisor_cosign/summary/view"


def note_chart_url(patient_key: Any, note_dbid: Any) -> str:
    """``/patient/<patient key>?noteId=<note dbid>`` — the chart, on that note.

    **Takes the note's integer ``dbid``, not its UUID.** The UUID does not
    resolve at this route. Passing ``note.id`` here produces a URL that loads the chart and
    silently ignores the note.
    """
    patient = str(patient_key or "").strip()
    dbid = str(note_dbid or "").strip()
    if not patient or not dbid:
        return ""
    return "/patient/" + _quote(patient) + "?noteId=" + _quote(dbid)


def summary_note_url(note_uuid: Any) -> str:
    """The co-sign summary page, opened on this note's attestation form.

    Takes the note **UUID**, unlike :func:`note_chart_url` — this one is our
    own page and it keys on the same id ``CoSignRecord`` stores.
    """
    note = str(note_uuid or "").strip()
    if not note:
        return ""
    return SUMMARY_VIEW_URL + "?note=" + _quote(note)


def _quote(value: str) -> str:
    """Percent-encode the characters that would break out of a URL component.

    Hand-rolled rather than ``urllib.parse.quote``: the values here are Canvas
    keys, uuids and integers, and keeping this module import-free keeps it
    testable without the sandbox in the way.
    """
    out = []
    for char in value:
        if char.isalnum() or char in "-._~":
            out.append(char)
        else:
            out.append("%%%02X" % ord(char))
    return "".join(out)
