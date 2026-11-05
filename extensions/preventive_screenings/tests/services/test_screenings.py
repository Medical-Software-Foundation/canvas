"""Tests for the eligibility and due/overdue math.

Pure functions, so these are exhaustive rather than representative: the two
rules they enforce - unknown is never eligible, and overdue is a distinct state
from due - are the ones a wrong answer does the most damage to.
"""

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from typing import Any

import pytest

from preventive_screenings.services.screenings import (
    STATE_DUE,
    STATE_OVERDUE,
    STATE_SATISFIED,
    AWAITING_RESULT_DAYS,
    STATE_ORDERED,
    AttestedCompletion,
    ScreeningStatus,
    describe_interval,
    describe_overdue,
    eligible_from,
    eligible_until,
    is_eligible,
    next_change_date,
    status_for,
)

TODAY = date(2026, 9, 18)


def screening(**over: Any) -> dict:
    """A screening as the config store would have normalized it."""
    out: dict[str, Any] = {
        "id": "s1",
        "enabled": True,
        "name": "Mammogram",
        "sex": "female",
        "min_age": 40,
        "max_age": 74,
        "grace_days": 90,
        "completions": [
            {
                "value_set_key": "mammography",
                "source": "imaging_report",
                "codes": [],
                "label": "",
                "interval_quantity": 2,
                "interval_unit": "years",
            }
        ],
        "exclusions": [],
        "order_command": "imaging_order",
        "order_button": "Order mammogram",
        "order_code": "24606-6",
        "order_comment": "Screening mammogram",
        "guidance": "",
    }
    out.update(over)
    return out


# --- eligibility -------------------------------------------------------------


def test_eligibility_starts_on_the_birthday_not_before() -> None:
    """A patient becomes eligible the day they reach the minimum age."""
    born = date(1986, 9, 18)  # turns 40 on 2026-09-18

    assert eligible_from(screening(), born) == date(2026, 9, 18)
    assert is_eligible(screening(), "F", born, TODAY) is True
    assert is_eligible(screening(), "F", born, date(2026, 9, 17)) is False


def test_the_upper_age_includes_that_whole_year_of_life() -> None:
    """"40 to 74" covers a patient right up to their 75th birthday."""
    born = date(1951, 9, 18)  # turns 75 on 2026-09-18

    assert eligible_until(screening(), born) == date(2026, 9, 18)
    assert is_eligible(screening(), "F", born, date(2026, 9, 17)) is True
    assert is_eligible(screening(), "F", born, TODAY) is False


def test_a_screening_with_no_upper_age_never_ends() -> None:
    """max_age of 0 means no upper limit."""
    rule = screening(min_age=65, max_age=0, sex="any")

    assert eligible_until(rule, date(1930, 1, 1)) is None
    assert is_eligible(rule, "M", date(1930, 1, 1), TODAY) is True


@pytest.mark.parametrize("recorded", ["F", "f", " F "])
def test_a_sex_specific_screening_matches_its_recorded_sex(recorded: str) -> None:
    """Whitespace and case in the stored value do not defeat the match."""
    assert is_eligible(screening(), recorded, date(1976, 1, 1), TODAY) is True


@pytest.mark.parametrize("recorded", ["M", "O", "UNK", "", "   ", "female"])
def test_an_unknown_or_other_sex_never_matches_a_sex_specific_screening(recorded: str) -> None:
    """Unknown is never positive. Showing a mammogram recommendation to a patient
    it does not apply to teaches providers to ignore every card."""
    assert is_eligible(screening(), recorded, date(1976, 1, 1), TODAY) is False


def test_a_screening_for_any_sex_matches_whatever_is_recorded() -> None:
    """A screening with no sex restriction does not care what is on file."""
    rule = screening(sex="any", min_age=18, max_age=0)

    for recorded in ("F", "M", "O", "UNK", ""):
        assert is_eligible(rule, recorded, date(1976, 1, 1), TODAY) is True


# --- due / overdue -----------------------------------------------------------


def test_never_done_is_due_from_the_moment_of_eligibility() -> None:
    """A patient who just aged in is due, not overdue."""
    born = date(1986, 9, 18)  # turned 40 today

    status = status_for(screening(), {}, born, TODAY)

    assert status.state == STATE_DUE
    assert status.last_completed is None
    assert status.due_date == date(2026, 9, 18)
    assert status.due_in == 0


def test_never_done_and_long_eligible_is_overdue() -> None:
    """A 62-year-old with no mammogram on file reads as overdue, which is what
    makes patients whose history predates the install work with no backfill."""
    born = date(1964, 1, 1)  # eligible since 2004

    status = status_for(screening(), {}, born, TODAY)

    assert status.state == STATE_OVERDUE
    assert status.due_date == date(2004, 1, 1)
    assert status.due_in < 0


def test_a_recent_completion_is_satisfied() -> None:
    """Inside the interval, nothing is owed."""
    status = status_for(screening(), {0: date(2025, 6, 1)}, date(1976, 1, 1), TODAY)

    assert status.state == STATE_SATISFIED
    assert status.last_completed == date(2025, 6, 1)
    assert status.due_date == date(2027, 6, 1)
    assert status.due_in > 0


def test_the_interval_running_out_makes_it_due_not_overdue() -> None:
    """The grace period is what separates due from overdue."""
    # Due 2026-09-01, 17 days ago, inside the 90-day grace.
    status = status_for(screening(), {0: date(2024, 9, 1)}, date(1976, 1, 1), TODAY)

    assert status.state == STATE_DUE
    assert status.due_in == -17


def test_past_the_grace_period_it_becomes_overdue() -> None:
    """Once it has been due longer than the grace period, it reads as overdue."""
    # Due 2026-01-01, 260 days ago, well past the 90-day grace.
    status = status_for(screening(), {0: date(2024, 1, 1)}, date(1976, 1, 1), TODAY)

    assert status.state == STATE_OVERDUE
    assert status.due_in == -260


def test_the_grace_boundary_is_inclusive() -> None:
    """Exactly at the grace period is still due; one day past is overdue."""
    rule = screening(grace_days=10)

    assert status_for(rule, {0: date(2024, 9, 8)}, date(1976, 1, 1), TODAY).state == STATE_DUE
    assert status_for(rule, {0: date(2024, 9, 7)}, date(1976, 1, 1), TODAY).state == STATE_OVERDUE


def test_a_zero_grace_period_makes_due_and_overdue_adjacent() -> None:
    """A practice that wants no grace gets none."""
    rule = screening(grace_days=0)

    assert status_for(rule, {0: date(2024, 9, 18)}, date(1976, 1, 1), TODAY).state == STATE_DUE
    assert status_for(rule, {0: date(2024, 9, 17)}, date(1976, 1, 1), TODAY).state == STATE_OVERDUE


def test_the_longest_coverage_wins_across_signals() -> None:
    """A clear colonoscopy is not undone by an older stool test.

    Colorectal screening is satisfied 10 years after a colonoscopy or 1 year
    after a FIT. A patient with both, two years ago, is covered by the
    colonoscopy and must not be chased for another FIT.
    """
    rule = screening(
        name="Colorectal",
        sex="any",
        min_age=45,
        max_age=75,
        completions=[
            {"value_set_key": "colonoscopy", "source": "procedure", "codes": [], "label": "",
             "interval_quantity": 10, "interval_unit": "years"},
            {"value_set_key": "fobt", "source": "lab_result", "codes": [], "label": "",
             "interval_quantity": 1, "interval_unit": "years"},
        ],
    )

    status = status_for(rule, {0: date(2024, 6, 1), 1: date(2024, 6, 1)}, date(1970, 1, 1), TODAY)

    assert status.state == STATE_SATISFIED
    assert status.due_date == date(2034, 6, 1)
    assert status.last_completed == date(2024, 6, 1)


def test_last_completed_is_the_most_recent_of_any_signal() -> None:
    """The date shown to the provider is the latest thing that actually happened,
    even when an older signal is the one buying the longer coverage."""
    rule = screening(
        sex="any",
        completions=[
            {"value_set_key": "colonoscopy", "source": "procedure", "codes": [], "label": "",
             "interval_quantity": 10, "interval_unit": "years"},
            {"value_set_key": "fobt", "source": "lab_result", "codes": [], "label": "",
             "interval_quantity": 1, "interval_unit": "years"},
        ],
    )

    status = status_for(rule, {0: date(2020, 1, 1), 1: date(2026, 3, 1)}, date(1970, 1, 1), TODAY)

    assert status.last_completed == date(2026, 3, 1)
    assert status.due_date == date(2030, 1, 1)  # the colonoscopy still covers it


def test_a_month_interval_is_honoured() -> None:
    """Intervals configured in months move by months, not by 30-day blocks."""
    rule = screening(
        completions=[
            {"value_set_key": "mammography", "source": "imaging_report", "codes": [], "label": "",
             "interval_quantity": 18, "interval_unit": "months"},
        ],
    )

    status = status_for(rule, {0: date(2025, 3, 31)}, date(1976, 1, 1), TODAY)

    assert status.due_date == date(2026, 9, 30)


# --- wording -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("quantity", "unit", "expected"),
    [(1, "years", "1 year"), (2, "years", "2 years"), (1, "months", "1 month"),
     (18, "months", "18 months")],
)
def test_describe_interval_says_it_the_way_a_provider_would(
    quantity: int, unit: str, expected: str
) -> None:
    assert describe_interval(quantity, unit) == expected


@pytest.mark.parametrize(
    ("days", "expected"),
    [(1, "1 day"), (0, "1 day"), (29, "29 days"), (30, "1 month"), (364, "12 months"),
     (365, "1 year"), (800, "2 years")],
)
def test_describe_overdue_rounds_down_so_it_never_overstates(days: int, expected: str) -> None:
    """"Overdue by 1 year" is never said of something eleven months late."""
    assert describe_overdue(days) == expected


# --- when the card could next change -----------------------------------------
#
# next_change_date is what makes a scheduled sweep affordable: it decides when a
# patient is looked at again. Too late and a card stays wrong; too early and the
# sweep does needless work at a scale where that is the whole cost. So every
# branch is pinned here, including the exact boundary days.


def born_for_age(age: int, on: date = TODAY) -> date:
    """A birth date that makes the patient exactly `age` today."""
    return date(on.year - age, on.month, on.day)


def test_a_patient_too_young_is_revisited_on_the_day_they_age_in() -> None:
    born = born_for_age(38)

    assert next_change_date(screening(), None, born, TODAY) == eligible_from(
        screening(), born
    )


def test_a_patient_aged_out_is_never_revisited() -> None:
    """Nothing time does brings a screening back once they are past the upper
    age, so scheduling another look is pure waste."""
    born = born_for_age(80)

    assert next_change_date(screening(), None, born, TODAY) is None


def test_a_satisfied_screening_is_revisited_the_day_it_falls_due() -> None:
    born = born_for_age(50)
    status = status_for(screening(), {0: date(2026, 3, 1)}, born, TODAY)
    assert status.state == STATE_SATISFIED

    assert next_change_date(screening(), status, born, TODAY) == status.due_date


def test_a_due_screening_is_revisited_the_day_it_tips_overdue() -> None:
    """The day after the grace period, because the grace boundary is inclusive."""
    born = born_for_age(50)
    status = status_for(screening(), {0: date(2024, 9, 1)}, born, TODAY)
    assert status.state == STATE_DUE

    expected = status.due_date + timedelta(days=screening()["grace_days"] + 1)
    assert next_change_date(screening(), status, born, TODAY) == expected


def test_the_day_a_due_screening_tips_is_the_day_it_reads_overdue() -> None:
    """Pins the scheduled date against status_for itself, so the two cannot
    drift apart and leave a card a day stale."""
    born = born_for_age(50)
    status = status_for(screening(), {0: date(2024, 9, 1)}, born, TODAY)
    tips_on = next_change_date(screening(), status, born, TODAY)
    assert tips_on is not None

    assert status_for(screening(), {0: date(2024, 9, 1)}, born, tips_on).state == STATE_OVERDUE


def test_the_upper_age_is_scheduled_when_it_comes_first() -> None:
    """A patient satisfied well past their 75th birthday must still be revisited
    on it, or an aged-out screening keeps showing."""
    born = born_for_age(74)
    status = status_for(
        screening(completions=[{**screening()["completions"][0], "interval_quantity": 10}]),
        {0: TODAY},
        born,
        TODAY,
    )

    assert next_change_date(screening(), status, born, TODAY) == eligible_until(
        screening(), born
    )


@pytest.mark.parametrize(
    ("days_overdue", "expected_next"),
    [
        (0, 2),  # describe_overdue floors at "1 day", so day 1 reads the same
        (1, 2),
        (5, 6),
        (29, 30),  # the last day before it starts counting months
        (30, 60),  # now in whole months
        (200, 210),
        (359, 360),  # month 12, still inside the year
        (364, 365),  # capped: the year boundary takes over before month 13
        (365, 730),  # now in whole years
        (900, 1095),
    ],
)
def test_an_overdue_card_is_revisited_exactly_when_its_wording_changes(
    days_overdue: int, expected_next: int
) -> None:
    """The title says how far past due it is, so an overdue card goes stale on
    its own. These are the only days its wording can change."""
    born = born_for_age(50)
    due_date = TODAY - timedelta(days=days_overdue)
    status = ScreeningStatus(
        state=STATE_OVERDUE, due_date=due_date, last_completed=None, due_in=-days_overdue
    )

    assert next_change_date(screening(grace_days=0), status, born, TODAY) == due_date + timedelta(
        days=expected_next
    )


def test_the_scheduled_overdue_date_really_does_reword_the_card() -> None:
    """Pins the schedule against describe_overdue rather than restating its
    arithmetic, so a change to one fails if the other is not updated."""
    born = born_for_age(50)
    for days_overdue in (0, 5, 29, 30, 200, 364, 365, 900):
        due_date = TODAY - timedelta(days=days_overdue)
        status = ScreeningStatus(
            state=STATE_OVERDUE, due_date=due_date, last_completed=None, due_in=-days_overdue
        )
        when = next_change_date(screening(grace_days=0), status, born, TODAY)
        assert when is not None

        today_words = describe_overdue(days_overdue)
        then_words = describe_overdue((when - due_date).days)
        assert today_words != then_words, f"{days_overdue} days: wording did not change"


def test_a_date_already_past_is_never_scheduled() -> None:
    """A date in the past would make the sweep pick the patient up forever."""
    born = born_for_age(50)
    status = status_for(screening(), {0: date(2000, 1, 1)}, born, TODAY)

    when = next_change_date(screening(), status, born, TODAY)
    assert when is None or when > TODAY


def test_a_screening_with_no_upper_age_schedules_only_on_its_own_status() -> None:
    """With no age to age out of, the status is the only thing time can move."""
    born = born_for_age(50)
    open_ended = screening(max_age=0)
    status = status_for(open_ended, {0: date(2026, 3, 1)}, born, TODAY)

    assert next_change_date(open_ended, status, born, TODAY) == status.due_date


def test_an_eligible_patient_with_no_status_is_still_revisited_when_they_age_out() -> None:
    """An excluding condition means no status is computed, but the patient is
    still age-eligible, and the upper age remains a real future change."""
    born = born_for_age(50)

    assert next_change_date(screening(), None, born, TODAY) == eligible_until(
        screening(), born
    )


def test_an_eligible_patient_with_no_status_and_no_upper_age_is_never_revisited() -> None:
    """Nothing left for time to change, so scheduling a look would be waste."""
    born = born_for_age(50)

    assert next_change_date(screening(max_age=0), None, born, TODAY) is None


# --- a snooze running out ----------------------------------------------------

BORN = date(1975, 6, 1)


def test_a_snooze_schedules_the_day_it_runs_out() -> None:
    """**Nothing fires an event when a date passes.** A snooze ending changes the
    card - the title goes back from "Snoozed" to the overdue text - so if it is
    not scheduled here, the card reads "Snoozed" long after the snooze ended,
    until some unrelated chart change happens to rewrite it.
    """
    rule = screening(min_age=40, max_age=0, grace_days=90)
    status = ScreeningStatus(STATE_OVERDUE, date(2025, 1, 1), None, -400)

    when = next_change_date(rule, status, BORN, date(2026, 2, 5), date(2026, 3, 1))

    assert when == date(2026, 3, 2), "the first day it is no longer snoozed"


def test_the_snooze_and_the_read_agree_about_the_last_day() -> None:
    """`completion.snoozed_until` treats a snooze as covering its own date, so
    the revisit is the day after. Disagreeing by one day either un-snoozes the
    card a day early or leaves it stuck a day late."""
    rule = screening(min_age=40, max_age=0, grace_days=90)
    status = ScreeningStatus(STATE_OVERDUE, date(2025, 1, 1), None, -400)
    snooze_ends = date(2026, 3, 1)

    when = next_change_date(rule, status, BORN, date(2026, 2, 5), snooze_ends)

    assert when == snooze_ends + timedelta(days=1)


def test_a_sooner_change_still_wins_over_the_snooze() -> None:
    """The snooze is one candidate among several, not an override. A patient who
    ages out next week is still revisited next week."""
    rule = screening(min_age=40, max_age=51, grace_days=90)
    status = ScreeningStatus(STATE_OVERDUE, date(2025, 1, 1), None, -400)
    ages_out = BORN + relativedelta(years=52)

    when = next_change_date(rule, status, BORN, ages_out - timedelta(days=7), date(2099, 1, 1))

    assert when == ages_out


def test_no_snooze_changes_nothing() -> None:
    """The argument defaults to None, so every existing caller is unaffected."""
    rule = screening(min_age=40, max_age=0, grace_days=90)
    status = ScreeningStatus(STATE_OVERDUE, date(2025, 1, 1), None, -400)
    today = date(2026, 2, 5)

    assert next_change_date(rule, status, BORN, today) == next_change_date(
        rule, status, BORN, today, None
    )


# --- a completion a staff member recorded ------------------------------------
#
# The whole safety case for storing attestations outside the chart is that they
# **add** rather than replace. These are the tests that hold that: an
# attestation can supply evidence the chart lacked, and can never overrule
# evidence the chart has.

BORN = date(1976, 6, 15)


def test_an_attestation_can_satisfy_a_screening_with_nothing_in_the_chart() -> None:
    """The case it exists for: the mammogram happened, somewhere this plugin
    cannot read, and the card was shouting OVERDUE at the provider who knew
    that perfectly well."""
    found = status_for(
        screening(), {}, BORN, TODAY,
        AttestedCompletion(on=TODAY - timedelta(days=30), interval_quantity=2,
                           interval_unit="years"),
    )

    assert found.state == STATE_SATISFIED
    assert found.attested is True
    assert found.last_completed == TODAY - timedelta(days=30)


def test_an_attestation_carries_its_own_interval() -> None:
    """Stored when it was recorded, not read back off the rule - so an admin
    reordering the completion signals later cannot change what a past
    attestation meant."""
    found = status_for(
        screening(), {}, BORN, TODAY,
        AttestedCompletion(on=TODAY, interval_quantity=6, interval_unit="months"),
    )

    assert found.due_date == TODAY + relativedelta(months=6)


def test_a_more_recent_chart_result_beats_the_attestation() -> None:
    """Merged, never substituted. A real imaging report is better evidence and
    has to win both the coverage and the last-completed date."""
    real = TODAY - timedelta(days=10)

    found = status_for(
        screening(), {0: real}, BORN, TODAY,
        AttestedCompletion(on=TODAY - timedelta(days=400), interval_quantity=2,
                           interval_unit="years"),
    )

    assert found.last_completed == real
    assert found.attested is False
    assert found.last_signal == 0


def test_an_attestation_still_extends_coverage_an_older_result_left_short() -> None:
    """The two are compared on coverage as well as recency. An old colonoscopy
    plus a recent attested stool test leaves the patient covered by whichever
    runs out last - the same rule that stops a FIT undoing a colonoscopy."""
    found = status_for(
        screening(), {0: TODAY - relativedelta(years=3)}, BORN, TODAY,
        AttestedCompletion(on=TODAY - relativedelta(years=1), interval_quantity=2,
                           interval_unit="years"),
    )

    assert found.state == STATE_SATISFIED


def test_an_older_attestation_does_not_pull_the_last_completed_date_back() -> None:
    found = status_for(
        screening(), {0: TODAY}, BORN, TODAY,
        AttestedCompletion(on=TODAY - relativedelta(years=5), interval_quantity=20,
                           interval_unit="years"),
    )

    assert found.last_completed == TODAY
    assert found.attested is False


def test_an_expired_attestation_leaves_the_screening_due_again() -> None:
    """"Marked complete" is not "never ask again". It buys exactly the interval
    the provider said it did, and then the screening comes back."""
    found = status_for(
        screening(), {}, BORN, TODAY,
        AttestedCompletion(on=TODAY - relativedelta(years=3), interval_quantity=2,
                           interval_unit="years"),
    )

    assert found.state == STATE_OVERDUE


def test_no_attestation_leaves_the_status_unattested() -> None:
    assert status_for(screening(), {0: TODAY}, BORN, TODAY).attested is False


# --- ordered, awaiting result ------------------------------------------------
#
# Jess's ask: "a screening that has been ordered but the result hasn't come
# back yet ... so it doesn't read as overdue while the practice is waiting".
#
# The danger in this state is specific and worth naming: while it holds, a
# genuinely overdue screening is NOT shown as overdue. Every test below is
# really about bounding that.


def test_ordering_a_due_screening_stops_it_reading_as_overdue() -> None:
    found = status_for(screening(), {}, BORN, TODAY, ordered=TODAY)

    assert found.state == STATE_ORDERED
    assert found.ordered_on == TODAY


def test_an_order_does_not_disturb_a_satisfied_screening() -> None:
    """A result that has already landed is the better answer, and an order
    placed before it is simply spent."""
    found = status_for(
        screening(), {0: TODAY}, BORN, TODAY, ordered=TODAY - timedelta(days=1)
    )

    assert found.state == STATE_SATISFIED
    assert found.ordered_on is None


def test_an_order_stops_counting_once_the_window_closes() -> None:
    """**The safety bound.** An order that fell through the cracks must bring
    the screening back rather than hiding the patient forever."""
    stale = TODAY - timedelta(days=AWAITING_RESULT_DAYS + 1)

    assert status_for(screening(), {}, BORN, TODAY, ordered=stale).state == STATE_OVERDUE


def test_the_last_day_of_the_window_still_counts() -> None:
    edge = TODAY - timedelta(days=AWAITING_RESULT_DAYS)

    assert status_for(screening(), {}, BORN, TODAY, ordered=edge).state == STATE_ORDERED


def test_no_order_leaves_the_state_alone() -> None:
    assert status_for(screening(), {}, BORN, TODAY).ordered_on is None


def test_an_ordered_screening_is_revisited_the_day_its_window_closes() -> None:
    """Nothing fires an event when a date passes. Without this the card would
    read "awaiting result" indefinitely - the one failure this state must not
    have."""
    status = status_for(screening(), {}, BORN, TODAY, ordered=TODAY)

    assert next_change_date(screening(), status, BORN, TODAY) == TODAY + timedelta(
        days=AWAITING_RESULT_DAYS + 1
    )
