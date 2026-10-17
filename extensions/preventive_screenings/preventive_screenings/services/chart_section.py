"""Render a patient's screening status as a chart-summary section.

**Why this exists at all.** The client asked for something the protocol cards
cannot give them: *"We also need to see the last completed date, not only when
it's due."* Every card carries that date in its narrative, but UAT on
2026-09-21 confirmed Canvas does not render a ``SATISFIED`` card at all - so
the last-completed date is visible exactly while a screening is overdue, and
invisible the moment it is up to date, which is when somebody actually asks
"when did she last have one?".

**This is the one surface that can be computed live.** A chart-read event may
not return ``ADD_OR_UPDATE_PROTOCOL_CARD`` - proved on the instance
2026-09-19, and the reason the whole plugin is event-driven plus a sweep. But
``PatientChartSummaryCustomSection`` *is* the return type of
``PATIENT_CHART_SUMMARY__GET_CUSTOM_SECTION``, so this section is computed on
chart open and stored nowhere. No card keys, no fingerprints, no retraction,
no staleness. It is simply correct every time it renders.

The section renders ``ScreeningRow``s straight from ``services.review`` rather
than recomputing anything. A card and this section sit inches apart on the same
screen, and two code paths deciding what a screening says would eventually
disagree there.

**It also renders the two write controls**, but only when a caller asks for
them by passing ``RecordActions``. The chart-side record app does; the
chart-summary section handler does not, and must not - a section Canvas
composes into its own layout is not a place to put buttons that write. The
markup itself carries no script: the record app's page supplies the handler, so
this module stays a pure string builder that can be asserted on.

Security: every interpolation is escaped, and the markup loads nothing from
anywhere - no fonts, no scripts, no images. The security review's finding
against the admin page applies here with more force, because this renders on
every chart open rather than behind an admin gate.
"""

from datetime import date
from html import escape
from typing import NamedTuple

from preventive_screenings.services.attestations import (
    KIND_COMPLETED,
    KIND_NOT_APPLICABLE,
    KIND_ORDERED,
    Attestation,
)
from preventive_screenings.services.cards import describe_rule
from preventive_screenings.services.catalog import VALUE_SETS
from preventive_screenings.services.review import ScreeningRow
from preventive_screenings.services.screenings import (
    STATE_DUE,
    STATE_ORDERED,
    STATE_OVERDUE,
    STATE_SATISFIED,
    ScreeningStatus,
    describe_interval,
    describe_overdue,
)


class RecordActions(NamedTuple):
    """What the record app needs to draw its write controls.

    Passed only by the chart-side app. The chart-summary section renders the
    same rows read-only, because a section Canvas composes into its own layout
    is not a place to put buttons that write.
    """

    # Today, for the date field's default and its upper bound. Taken from the
    # caller rather than read here so the whole page is rendered against one
    # date - a section built across midnight would otherwise disagree with the
    # statuses above it.
    today: date
    # Staff id -> readable name, for saying whose statement an attestation is.
    names: dict[str, str]

# Kept deliberately plain. Canvas owns the chart's visual language and this
# section sits inside it, so it borrows weight and spacing rather than colour
# and chrome - except for overdue, which the brief requires be unmistakable.
_STYLE = """
.ps-wrap{font:13px/1.45 inherit;color:#2b2f33}
.ps-row{padding:8px 0;border-bottom:1px solid #eceff1}
.ps-row:last-child{border-bottom:0}
.ps-name{font-weight:600}
.ps-state{float:right;font-size:12px}
.ps-overdue .ps-name,.ps-overdue .ps-state{color:#b00020}
.ps-due .ps-state{color:#a06000}
.ps-ok .ps-state{color:#5b6770}
.ps-ordered .ps-state{color:#1a6aae}
.ps-detail{color:#5b6770;font-size:12px;margin-top:2px}
.ps-foot{margin-top:10px;color:#79858e;font-size:11px}
.ps-none{color:#5b6770}
/* An attestation is stated, never blended in. "Up to date because a
   colleague said so" and "up to date because the imaging came back" are
   different claims, and the person re-screening needs to tell them apart. */
.ps-att{margin-top:6px;padding:6px 8px;background:#f3f6f9;border-left:3px solid #9bb4c7;
        color:#41525e;font-size:12px;border-radius:0 4px 4px 0}
.ps-act{margin-top:7px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.ps-act select,.ps-act input{font:12px inherit;color:#2b2f33;background:#fff;
        border:1px solid #d6dde3;border-radius:5px;padding:4px 6px}
.ps-btn{font:600 12px inherit;cursor:pointer;border-radius:5px;padding:4px 10px;
        border:1px solid #c3d4e2;background:#fff;color:#1a6aae}
.ps-btn:hover{background:#eef5fc}
.ps-btn[disabled]{opacity:.5;cursor:default}
.ps-undo{border:none;background:none;color:#1a6aae;font:600 12px inherit;
        cursor:pointer;padding:0;text-decoration:underline}
.ps-group{margin-top:14px;padding-top:10px;border-top:1px solid #eceff1}
.ps-group-head{font-size:11px;font-weight:700;text-transform:uppercase;
        letter-spacing:.06em;color:#79858e;margin-bottom:6px}
.ps-msg{margin-bottom:10px;padding:7px 9px;border-radius:5px;font-size:12px;display:none}
""".strip()


def _human_date(value: date) -> str:
    """A date as a clinician writes it, matching the cards exactly."""
    return f"{value.day} {value:%b %Y}"


def _label_of(signal: dict) -> str:
    """What to call one completion signal, in a sentence."""
    entry = VALUE_SETS.get(signal["value_set_key"])
    if entry:
        return entry.label.lower()
    label: str = signal["label"]
    return label.lower()


def _signal_name(screening: dict, index: int | None) -> str:
    """What to call the thing that satisfied this screening."""
    if index is None:
        return ""
    try:
        signal = screening["completions"][index]
    except (IndexError, KeyError):
        return ""
    return _label_of(signal)


def _state_words(status: ScreeningStatus, snoozed: bool) -> tuple[str, str]:
    """The right-hand status label and the row's CSS class.

    Snoozed is stated rather than hidden. A provider who deferred a screening
    should see that it is deferred, not that it is fine - the card goes quiet,
    the record does not.
    """
    if status.state == STATE_OVERDUE:
        word = f"Overdue by {describe_overdue(-status.due_in)}"
        return (f"{word} — snoozed" if snoozed else word, "ps-overdue")
    if status.state == STATE_DUE:
        return ("Due — snoozed" if snoozed else "Due", "ps-due")
    if status.state == STATE_ORDERED:
        return ("Awaiting result", "ps-ordered")
    return ("Up to date", "ps-ok")


def _history(screening: dict, status: ScreeningStatus) -> str:
    """The line the client actually asked for."""
    if status.last_completed is None:
        return "No qualifying result on record"
    when = _human_date(status.last_completed)
    if status.attested:
        # The attestation's own line says who and when, immediately below. This
        # only has to stop the date reading as a chart result.
        return f"Marked complete {when} — no matching result in the chart"
    what = _signal_name(screening, status.last_signal)
    return f"Last completed {when} ({what})" if what else f"Last completed {when}"


def _who(attestation: Attestation, names: dict[str, str]) -> str:
    """Whose statement this is.

    Falls back to "a staff member" rather than printing a raw staff key, which
    answers nobody. The statement and its date are the load-bearing part; the
    name is what makes it checkable.
    """
    return names.get(attestation.recorded_by, "") or "a staff member"


def _attested_line(attestation: Attestation, names: dict[str, str], actions: bool) -> str:
    """The provenance line, and the offer to take the statement back."""
    who = escape(_who(attestation, names))
    if attestation.ordered:
        text = f"Ordered {_human_date(attestation.effective_date)} by {who}"
        if attestation.label:
            text += f" — {escape(attestation.label)}"
    elif attestation.completed:
        text = f"Marked complete {_human_date(attestation.effective_date)} by {who}"
        if attestation.effective_date != attestation.recorded_at:
            # Two dates, because they answer different questions: when the
            # screening happened, which drives when the next one is due, and
            # when somebody said so, which is what a reader is judging.
            text += f", recorded {_human_date(attestation.recorded_at)}"
    else:
        text = (
            f"Marked not applicable by {who} "
            f"on {_human_date(attestation.recorded_at)}"
        )
    undo = (
        f'<button class="ps-undo" data-act="clear" '
        f'data-s="{escape(attestation.screening_id)}">Undo</button>'
        if actions
        else ""
    )
    sep = " · " if undo else ""
    return f'<div class="ps-att">{text}{sep}{undo}</div>'


def _signal_picker(screening: dict) -> str:
    """Which completion signal the provider is attesting to.

    A screening can be satisfied several ways for different lengths of time -
    a colonoscopy covers ten years where a stool test covers one - so "it was
    done" is not enough to work out when the next one is due. With only one way
    to satisfy it there is nothing to ask, and the field is left out.
    """
    completions = screening["completions"]
    if len(completions) < 2:
        return ""
    options = "".join(
        f'<option value="{index}">{escape(_label_of(signal))} — '
        f"covers {escape(describe_interval(signal['interval_quantity'], signal['interval_unit']))}"
        "</option>"
        for index, signal in enumerate(completions)
    )
    return (
        f'<select class="ps-sig" data-s="{escape(str(screening["id"]))}" '
        f'aria-label="What was done">{options}</select>'
    )


def _order_button(screening: dict, status: ScreeningStatus) -> str:
    """The one-click order, for a screening that is due and configures one.

    **This used to exist only on the protocol card.** Cards became opt-in and
    off by default in 0.18.0, which took the client's "order it without leaving
    the chart" requirement with them for any practice that cards nothing - so
    it lives here too now.

    Left out for a screening already awaiting a result: offering to order it
    again is how two mammograms get booked.
    """
    if status.state not in (STATE_DUE, STATE_OVERDUE) or not screening["order_command"]:
        return ""
    label = screening["order_button"] or "Order"
    return (
        f'<button class="ps-btn ps-order" data-act="{KIND_ORDERED}" '
        f'data-s="{escape(str(screening["id"]))}">{escape(label)}</button>'
    )


def _actions_html(
    screening: dict, status: ScreeningStatus, actions: RecordActions
) -> str:
    """Everything a provider can do about this screening from here.

    The date defaults to today and is capped there. A screening cannot have
    been done tomorrow, and a future date would make it read as satisfied on
    evidence that does not exist yet - the route refuses one too, because a
    client-side ``max`` is a convenience, not a check.
    """
    screening_id = escape(str(screening["id"]))
    today = actions.today.isoformat()
    return (
        f'<div class="ps-act">{_order_button(screening, status)}'
        f"{_signal_picker(screening)}"
        f'<input class="ps-when" type="date" data-s="{screening_id}" '
        f'value="{today}" max="{today}" aria-label="Date it was done">'
        f'<button class="ps-btn" data-act="{KIND_COMPLETED}" data-s="{screening_id}">'
        "Mark complete</button>"
        f'<button class="ps-btn" data-act="{KIND_NOT_APPLICABLE}" data-s="{screening_id}">'
        "Not applicable</button></div>"
    )


# Which screenings a provider needs to look at first. Ordered sits below due
# and above up-to-date: the practice has already acted on it, so it is not part
# of the triage list, but it is still unfinished business in a way a satisfied
# screening is not.
_RANK = {STATE_OVERDUE: 0, STATE_DUE: 1, STATE_ORDERED: 2, STATE_SATISFIED: 3}


def _timing(status: ScreeningStatus) -> str:
    """When it was, or will be, due."""
    if status.state in (STATE_ORDERED, STATE_OVERDUE):
        return f"Was due {_human_date(status.due_date)}"
    if status.state == STATE_DUE:
        return f"Due since {_human_date(status.due_date)}"
    return f"Next due {_human_date(status.due_date)}"


def _row_html(row: ScreeningRow, actions: RecordActions | None) -> str:
    """One screening as a block of escaped markup."""
    status = row.status
    if status is None:  # pragma: no cover - filtered out before we get here
        return ""
    label, css = _state_words(status, row.snoozed)
    names = actions.names if actions else {}

    if row.attestation is not None:
        # Already attested: show whose statement it is and offer to undo it,
        # rather than offering to record a second one over the top. Changing
        # the date means taking the first statement back, which is the honest
        # shape - an attestation is a claim, not a field.
        tail = _attested_line(row.attestation, names, actions is not None)
    elif actions is not None:
        tail = _actions_html(row.screening, status, actions)
    else:
        tail = ""

    return (
        f'<div class="ps-row {css}">'
        f'<span class="ps-state">{escape(label)}</span>'
        f'<div class="ps-name">{escape(str(row.screening["name"]))}</div>'
        f'<div class="ps-detail">{escape(_history(row.screening, status))}</div>'
        f'<div class="ps-detail">{escape(_timing(status))}</div>'
        f'<div class="ps-detail">{escape(describe_rule(row.screening))}</div>'
        f"{tail}</div>"
    )


def _not_applicable_html(rows: list[ScreeningRow], actions: RecordActions) -> str:
    """Screenings a person has marked as not applying to this patient.

    Only the ones somebody *decided* about. A screening that does not apply by
    age, sex or a condition on the chart stays hidden: that is the rule
    working, it is not information a provider is looking for, and every one of
    them is a row to scroll past. A person's judgement is different - it is the
    only not-applicable state another clinician might want to revisit, and the
    only one with anything to undo.
    """
    marked = [
        row
        for row in rows
        if row.status is None
        and row.attestation is not None
        and row.attestation.not_applicable
    ]
    if not marked:
        return ""
    body = "".join(
        f'<div class="ps-row">'
        f'<div class="ps-name">{escape(str(row.screening["name"]))}</div>'
        f"{_attested_line(row.attestation, actions.names, True)}"  # type: ignore[arg-type]
        f"</div>"
        for row in marked
    )
    return (
        '<div class="ps-group"><div class="ps-group-head">Marked not applicable</div>'
        f"{body}</div>"
    )


def build_section(
    rows: list[ScreeningRow],
    defaults_as_of: str,
    actions: RecordActions | None = None,
) -> str:
    """The whole section as self-contained, escaped HTML.

    Screenings that do not apply to this patient are left out. They are not
    information a provider is looking for on a chart, and every one of them is
    a row to scroll past - the reason the cards emit a quiet NOT_APPLICABLE is
    to retract a stale card, which has no equivalent here because nothing is
    stored.

    Ordered the way the cards are: overdue first, then due by how long, then
    the ones that are fine. The top of the section is the triage list.

    ``actions`` turns on the write controls, and is passed only by the
    chart-side record app. Left out - as the chart-summary section handler
    leaves it out - this renders exactly as it always has: read-only, with no
    script and nothing to click.
    """
    applicable = [row for row in rows if row.status is not None]
    if not applicable:
        body = '<div class="ps-none">No preventive screenings apply to this patient.</div>'
    else:
        applicable.sort(
            key=lambda row: (
                _RANK.get(row.status.state, 9),  # type: ignore[union-attr]
                row.status.due_in,  # type: ignore[union-attr]
            )
        )
        body = "".join(_row_html(row, actions) for row in applicable)

    if actions is not None:
        body += _not_applicable_html(rows, actions)

    foot = (
        f'<div class="ps-foot">Practice screening rules — '
        f"defaults current as of {escape(defaults_as_of)}.</div>"
    )
    return f"<style>{_STYLE}</style><div class=\"ps-wrap\">{body}{foot}</div>"
