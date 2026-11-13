"""What both handlers share once they know which rules fired: who can actually
be faxed, at which number, with which coversheet, and what was already sent.
"""

from datetime import UTC, date, datetime
from typing import Any

from logger import log

from auto_fax.services.config import Rule
from auto_fax.services.fax_number import e164
from auto_fax.services.recipients import Recipient

# Every fax a plugin sends is recorded with Canvas Bot as its originator. The id
# is the same on every instance (see the SDK's "Faxes sent by a plugin" docs).
CANVAS_BOT_STAFF_ID = "5eede137ecfe4124b8b773040e33be14"


def today_for(provider: Any) -> date:
    """Today in the provider's last known time zone, or UTC without one.

    Facility addresses end on a calendar date, so "today" must be the
    practice's date, not the server's UTC date (which runs a day ahead
    every US evening).
    """
    tz = provider.last_known_timezone if provider else None
    return datetime.now(tz or UTC).date()


def sendable(recipients: list[Recipient], subject: str) -> list[Recipient]:
    """Recipients with a fax number, one per number. Logs the rest.

    ``subject`` names what is being faxed in the log line, e.g. ``note 123``.
    """
    seen: set[str] = set()
    result: list[Recipient] = []
    for recipient in recipients:
        if recipient.problem or not recipient.fax_digits:
            log.warning(
                f"[auto_fax] {subject} rule {recipient.rule.name!r}: skipped "
                f"{recipient.kind}: {recipient.problem}"
            )
            continue
        if recipient.fax_digits in seen:
            continue
        seen.add(recipient.fax_digits)
        result.append(recipient)
    return result


def destination(recipient: Recipient, test_digits: str | None) -> str:
    """The number to dial: the test number when one is set, else the recipient's."""
    return test_digits or recipient.fax_digits or ""


def plugin_faxes(action_events: Any) -> Any:
    """The plugin (Canvas Bot) faxes in these action events, excluding failed ones.

    The one definition of "already sent" for both the note-lock auto-fax and
    the Fax orders button. ``action_events`` is a document's action events
    (``NoteActionEvent``, ``ReferralActionEvent``, ``ImagingOrderActionEvent``,
    ``LabOrderActionEvent``), already filtered to the document(s).
    """
    return action_events.filter(
        event_type="FAXED", originator__staff__id=CANVAS_BOT_STAFF_ID
    ).exclude(delivered_by_fax=False)


def already_faxed(action_events: Any) -> set[str]:
    """E.164 numbers in these action events that a plugin faxed to, excluding failed faxes."""
    numbers = plugin_faxes(action_events).values_list("fax__to_fax_number", flat=True)
    return {number for number in numbers if number}


def skip_already_faxed(
    recipients: list[Recipient], test_digits: str | None, already: set[str]
) -> list[Recipient]:
    """Drop recipients whose destination number is in ``already``."""
    return [r for r in recipients if e164(destination(r, test_digits)) not in already]


def cover_kwargs(rule: Rule, location_id: str | None, subject: str) -> dict[str, Any]:
    """The coversheet arguments every fax effect takes, or none.

    A coversheet needs a practice location. Without one the fax still goes, with
    no coversheet, and a warning is logged.
    """
    cover = rule.cover_sheet
    if cover is None:
        return {}
    if location_id is None:
        log.warning(
            f"[auto_fax] {subject} has no practice location; sending rule "
            f"{rule.name!r} without its coversheet"
        )
        return {}
    return {
        "include_coversheet": True,
        "subject": cover.subject,
        "comment": cover.comment,
        "location_id": location_id,
    }
