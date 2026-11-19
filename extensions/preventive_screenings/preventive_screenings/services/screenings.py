"""Eligibility, due/overdue and last-completed math for one patient.

Everything here is a pure function of a screening rule, a patient's age and sex,
and the dates their chart already yielded. Nothing in this module touches the
database - ``services.completion`` does that, once, in batch - which is what
makes the rules cheap to test exhaustively.

Two principles run through it, both from the requirements:

* **Unknown never means positive.** A patient whose sex is not recorded is not
  eligible for a sex-specific screening, and a screening whose completion cannot
  be measured does not produce a card. Showing a screening to a patient it does
  not apply to teaches providers to ignore all of them.
* **Overdue is a distinct state, not a worse shade of due.** A screening becomes
  ``due`` the day its interval runs out and only becomes ``overdue`` once it has
  been due longer than the rule's grace period.
"""

from datetime import date, timedelta
from typing import NamedTuple

from dateutil.relativedelta import relativedelta

# Sex-specific screenings match only a recorded F or M. "O", "UNK" and blank are
# all unknown for this purpose and never match.
_SEX_CODES = {"female": "F", "male": "M"}

STATE_OVERDUE = "overdue"
STATE_DUE = "due"
STATE_SATISFIED = "satisfied"
# Ordered, and the result has not come back. Not a shade of due: the practice
# has already done the thing the card was asking for, and going on calling it
# overdue is the noise that teaches providers to ignore these.
STATE_ORDERED = "ordered"

# How long a screening stays "awaiting result" before it reads as due again.
#
# **It has to expire, and the number is a safety judgement, not a preference.**
# While it holds, a genuinely overdue screening is not shown as overdue - so an
# order that falls through the cracks hides the patient for exactly this long.
# Too short nags a provider who has already acted; too long loses the patient.
#
# 90 days because a referral is the slow case and routinely takes months to
# schedule, where imaging and labs come back in days. `next_change_date`
# schedules the exact expiry, so the card corrects itself on the day rather
# than waiting for the review cycle to come round.
#
# A practice that wants this tighter cannot set it yet. Per-screening config is
# the obvious next step if one asks - the interval already lives there.
AWAITING_RESULT_DAYS = 90


class AttestedCompletion(NamedTuple):
    """A completion a staff member recorded, rather than one found in the chart.

    Carries its own interval because the provider said which of the rule's
    completion signals they were attesting to, and the answer was stored at
    that moment - see ``models.screening_attestation``. Reading the interval
    back off the rule would let an admin reordering the signals later change
    what a past attestation meant.
    """

    on: date
    interval_quantity: int
    interval_unit: str


class ScreeningStatus(NamedTuple):
    """Where one screening stands for one patient, as of today."""

    state: str
    due_date: date
    last_completed: date | None
    # Days until due; negative once past due, which is the native protocols'
    # own convention for overdue.
    due_in: int
    # Which of the rule's completion signals produced `last_completed`, so a
    # reader can be told *what* was done and not only when. A screening can be
    # satisfied several ways and "last completed 21 Sep 2026" is a poorer
    # answer than "colonoscopy, 21 Sep 2026". None when nothing qualifies.
    last_signal: int | None = None
    # Whether `last_completed` came from a staff member saying so rather than
    # from a record in the chart. Every reader states this: "up to date" on a
    # colleague's say-so and "up to date" on an imaging report are different
    # claims, and a clinician deciding whether to re-screen needs to know
    # which one they are looking at.
    attested: bool = False
    # When this screening was ordered, if it is waiting on a result. Set only
    # alongside STATE_ORDERED, and carried here rather than looked up again so
    # the card and the panel cannot disagree about the date.
    ordered_on: date | None = None


def eligible_from(screening: dict, birth_date: date) -> date:
    """The date this patient became old enough for this screening."""
    return birth_date + relativedelta(years=int(screening["min_age"]))


def eligible_until(screening: dict, birth_date: date) -> date | None:
    """The date this patient ages out, or None when the screening has no upper age.

    ``max_age`` is inclusive of that year of life, so a rule that reads "40 to
    74" covers a patient right up to their 75th birthday.
    """
    max_age = int(screening["max_age"])
    if not max_age:
        return None
    return birth_date + relativedelta(years=max_age + 1)


def is_eligible(screening: dict, sex_at_birth: str, birth_date: date, today: date) -> bool:
    """Whether this screening applies to this patient at all, today.

    Age and sex only. Excluding conditions are a database question and are
    applied separately, by the handler, for the screenings that survive this.
    """
    wanted_sex = _SEX_CODES.get(screening["sex"])
    if wanted_sex and str(sex_at_birth or "").strip().upper() != wanted_sex:
        return False
    if today < eligible_from(screening, birth_date):
        return False
    ends = eligible_until(screening, birth_date)
    return ends is None or today < ends


def _shift(start: date, quantity: int, unit: str) -> date:
    """Move a date forward by a configured interval."""
    if unit == "months":
        return start + relativedelta(months=quantity)
    return start + relativedelta(years=quantity)


def status_for(
    screening: dict,
    completions: dict[int, date],
    birth_date: date,
    today: date,
    attested: AttestedCompletion | None = None,
    ordered: date | None = None,
) -> ScreeningStatus:
    """Resolve one screening to due / overdue / satisfied for this patient.

    ``completions`` maps a completion signal's index within the rule to the most
    recent date that signal was satisfied. A signal with no qualifying record is
    simply absent.

    Each signal carries its own interval, because a screening can be satisfied
    several ways for different lengths of time - a colonoscopy covers ten years
    where a stool test covers one. The screening is due when the *longest*
    coverage any single completion bought has run out, so a clear colonoscopy is
    not undone by an old FIT.

    With no qualifying record at all, the screening has been due since the
    patient became eligible. That is what makes a 62-year-old with no mammogram
    on file read as overdue rather than as newly due, and it is why patients
    with history predating the install need no backfill.

    ``attested`` is a completion a staff member recorded from the chart-side
    record app, for a screening that was done but left no record this plugin
    can read. **It is merged, never substituted**: it joins the same two
    comparisons as every chart-derived completion, so a real imaging report
    that is more recent still wins on both coverage and last-completed. An
    attestation can supply evidence the chart lacked; it cannot overrule
    evidence the chart has.
    """
    covered_until: date | None = None
    last_completed: date | None = None
    last_signal: int | None = None
    attested_last = False

    for index, completed in completions.items():
        signal = screening["completions"][index]
        until = _shift(completed, int(signal["interval_quantity"]), signal["interval_unit"])
        if covered_until is None or until > covered_until:
            covered_until = until
        if last_completed is None or completed > last_completed:
            last_completed = completed
            last_signal = index

    if attested is not None:
        until = _shift(attested.on, int(attested.interval_quantity), attested.interval_unit)
        if covered_until is None or until > covered_until:
            covered_until = until
        if last_completed is None or attested.on > last_completed:
            last_completed = attested.on
            last_signal = None
            attested_last = True

    due_date = covered_until if covered_until else eligible_from(screening, birth_date)
    due_in = (due_date - today).days

    if today < due_date:
        state = STATE_SATISFIED
    elif (today - due_date).days <= int(screening["grace_days"]):
        state = STATE_DUE
    else:
        state = STATE_OVERDUE

    # Checked after the state is settled, and never against SATISFIED: a real
    # result that has already landed is the better answer, and an order placed
    # before it is simply spent.
    ordered_on = None
    if (
        state in (STATE_DUE, STATE_OVERDUE)
        and ordered is not None
        and today <= ordered + timedelta(days=AWAITING_RESULT_DAYS)
    ):
        state = STATE_ORDERED
        ordered_on = ordered

    return ScreeningStatus(
        state=state,
        due_date=due_date,
        last_completed=last_completed,
        due_in=due_in,
        last_signal=last_signal,
        attested=attested_last,
        ordered_on=ordered_on,
    )


def _overdue_text_changes_on(due_date: date, today: date) -> date:
    """The next date ``describe_overdue`` would word an overdue card differently.

    An overdue card's title states how far past due it is, so it goes stale on
    its own even when nothing in the chart changes. ``describe_overdue`` steps
    in days below a month, then whole months, then whole years, so the wording
    only changes on those boundaries - and they are all computable rather than
    approximated by refreshing everything on some arbitrary cadence.
    """
    days = (today - due_date).days
    if days < 30:
        # Still counted in days, so tomorrow reads differently - except that
        # describe_overdue floors at "1 day", so days 0 and 1 read the same and
        # the first genuine change is day 2. Scheduling day 1 would re-emit an
        # identical card.
        next_days = max(days + 1, 2)
    elif days < 365:
        # Counted in whole months, until the year boundary takes over at 365.
        next_days = min((days // 30 + 1) * 30, 365)
    else:
        next_days = (days // 365 + 1) * 365
    return due_date + timedelta(days=next_days)


def next_change_date(
    screening: dict,
    status: ScreeningStatus | None,
    birth_date: date,
    today: date,
    snoozed_until: date | None = None,
) -> date | None:
    """The next date this screening's card could differ, with an unchanged chart.

    This is what makes a scheduled sweep affordable: every time-driven change
    has a date that is *knowable now*, so a patient only has to be looked at
    again on that date rather than swept up nightly on the chance something
    moved. ``None`` means nothing will change with the passage of time alone -
    only a chart change can - so there is no need to revisit at all.

    ``status`` is None for a patient this screening does not currently apply to
    by age, in which case the only thing time can do is make them eligible.

    ``snoozed_until`` is the date a provider has deferred this screening to. A
    snooze running out changes the card - the title goes back from ``Snoozed``
    to the due or overdue text - and **nothing fires an event when a date
    passes**, so it has to be scheduled here or the card would read ``Snoozed``
    long after the snooze ended, until some unrelated chart change happened to
    rewrite it.

    It deliberately does NOT account for chart changes; those arrive as events.
    """
    candidates: list[date] = []

    if snoozed_until is not None:
        # The first day it is no longer snoozed. `completion.snoozed_until`
        # treats the snooze as covering its own date, so the two agree.
        candidates.append(snoozed_until + timedelta(days=1))

    starts = eligible_from(screening, birth_date)
    ends = eligible_until(screening, birth_date)

    if today < starts:
        # Too young. Ageing in is the only thing time can do, and once they are
        # in, that day's computation schedules whatever comes next.
        return starts
    if ends is not None and today >= ends:
        # Aged out for good. Nothing time does brings this screening back.
        return None
    if ends is not None:
        candidates.append(ends)

    if status is not None:
        if status.state == STATE_ORDERED and status.ordered_on is not None:
            # The day the order stops counting and the screening reads as due
            # again. Nothing fires an event when a date passes, so without this
            # the card would say "awaiting result" indefinitely - which is the
            # one failure this state must not have.
            candidates.append(
                status.ordered_on + timedelta(days=AWAITING_RESULT_DAYS + 1)
            )
        elif status.state == STATE_SATISFIED:
            candidates.append(status.due_date)
        elif status.state == STATE_DUE:
            # Due tips to overdue the first day past the grace period.
            candidates.append(
                status.due_date + timedelta(days=int(screening["grace_days"]) + 1)
            )
        else:
            candidates.append(_overdue_text_changes_on(status.due_date, today))

    future = [when for when in candidates if when > today]
    return min(future) if future else None


def describe_interval(quantity: int, unit: str) -> str:
    """An interval as a provider would say it: "2 years", "18 months", "1 year"."""
    word = unit.rstrip("s")
    return f"{quantity} {word}" if quantity == 1 else f"{quantity} {word}s"


def describe_overdue(days: int) -> str:
    """How far past due, in the largest unit that stays honest.

    Rounds down, so "overdue by 1 year" is never said of something 11 months
    late. Under a month it stays in days rather than claiming "0 months".
    """
    if days >= 365:
        years = days // 365
        return describe_interval(years, "years")
    if days >= 30:
        months = days // 30
        return describe_interval(months, "months")
    return describe_interval(max(days, 1), "days")
