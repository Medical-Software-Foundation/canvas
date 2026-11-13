"""Tests for the chart-summary section renderer.

The section is the answer to a requirement the cards structurally cannot meet:
*"We also need to see the last completed date, not only when it's due."* UAT on
2026-09-21 confirmed Canvas renders no card at all for a SATISFIED screening, so
that date is visible only while a screening is overdue - and invisible exactly
when somebody asks "when did she last have one?".

So the assertions that matter here are about **the satisfied case carrying its
date**, and about **escaping**, because unlike the admin page this renders on
every chart open rather than behind an admin gate.
"""

from datetime import date
from typing import Any

from preventive_screenings.services.attestations import Attestation
from preventive_screenings.services.chart_section import RecordActions, build_section
from preventive_screenings.services.review import ScreeningRow
from preventive_screenings.services.screenings import (
    STATE_DUE,
    STATE_ORDERED,
    STATE_OVERDUE,
    STATE_SATISFIED,
    ScreeningStatus,
)

AS_OF = "2026-09-18"


def screening(**over: Any) -> dict:
    out: dict[str, Any] = {
        "id": "s1",
        "enabled": True,
        "name": "Colorectal cancer screening",
        "sex": "any",
        "min_age": 45,
        "max_age": 75,
        "grace_days": 90,
        "completions": [
            {"value_set_key": "colonoscopy", "source": "procedure", "codes": [],
             "label": "", "interval_quantity": 10, "interval_unit": "years"},
            {"value_set_key": "fobt", "source": "lab_result", "codes": [],
             "label": "", "interval_quantity": 1, "interval_unit": "years"},
        ],
        "exclusions": [],
        "order_command": "refer",
        "order_button": "Refer",
        "order_code": "",
        "order_comment": "",
        "guidance": "",
    }
    out.update(over)
    return out


def status(state: str, **over: Any) -> ScreeningStatus:
    values: dict[str, Any] = {
        "state": state,
        "due_date": date(2036, 9, 21),
        "last_completed": date(2026, 9, 21),
        "due_in": 3652,
        "last_signal": 0,
    }
    values.update(over)
    return ScreeningStatus(**values)


def test_a_satisfied_screening_still_shows_when_it_was_done() -> None:
    """**The reason this section exists.** Canvas renders no card for a
    satisfied screening, so without this the last-completed date is invisible
    precisely when the screening is up to date."""
    html = build_section([ScreeningRow(screening(), status(STATE_SATISFIED), False)], AS_OF)

    assert "Last completed 21 Sep 2026" in html
    assert "Next due 21 Sep 2036" in html
    assert "Up to date" in html


def test_the_last_completed_line_names_what_was_done() -> None:
    """"Last completed 21 Sep 2026" is a poorer answer than "colonoscopy, 21 Sep
    2026" when a screening can be satisfied five different ways."""
    html = build_section([ScreeningRow(screening(), status(STATE_SATISFIED), False)], AS_OF)

    assert "(colonoscopy)" in html


def test_the_modality_follows_the_signal_that_actually_won() -> None:
    """A stool test and a colonoscopy buy very different coverage, so naming the
    wrong one would misrepresent the record."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, last_signal=1), False)], AS_OF
    )

    assert "(fobt / fit stool test)" in html
    assert "(colonoscopy)" not in html


def test_no_qualifying_result_says_so_rather_than_showing_nothing() -> None:
    html = build_section(
        [ScreeningRow(screening(), status(STATE_OVERDUE, last_completed=None,
                                          last_signal=None, due_in=-400), False)],
        AS_OF,
    )

    assert "No qualifying result on record" in html
    assert "Overdue by" in html


def test_overdue_is_stated_and_comes_first() -> None:
    """The brief requires overdue be unmistakable, and the top of the section is
    the triage list just as the cards are."""
    rows = [
        ScreeningRow(screening(name="Up to date one"), status(STATE_SATISFIED), False),
        ScreeningRow(screening(name="Overdue one"), status(STATE_OVERDUE, due_in=-400), False),
    ]
    html = build_section(rows, AS_OF)

    assert html.index("Overdue one") < html.index("Up to date one")
    assert "ps-overdue" in html


def test_due_sorts_between_overdue_and_satisfied() -> None:
    rows = [
        ScreeningRow(screening(name="Satisfied"), status(STATE_SATISFIED), False),
        ScreeningRow(screening(name="Due now"), status(STATE_DUE, due_in=-10), False),
        ScreeningRow(screening(name="Overdue"), status(STATE_OVERDUE, due_in=-400), False),
    ]
    html = build_section(rows, AS_OF)

    assert html.index("Overdue") < html.index("Due now") < html.index("Satisfied")


def test_a_snoozed_screening_says_so_rather_than_reading_as_fine() -> None:
    """The card goes quiet when a provider defers something; the record must
    not, or the section would claim a deferred screening is handled."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_OVERDUE, due_in=-400), True)], AS_OF
    )

    assert "snoozed" in html


def test_screenings_that_do_not_apply_are_left_out() -> None:
    """A not-applicable card exists only to retract a stale one. Nothing is
    stored here, so there is nothing to retract and nothing to show."""
    rows = [
        ScreeningRow(screening(name="Applies"), status(STATE_SATISFIED), False),
        ScreeningRow(screening(name="Does not apply"), None, False),
    ]
    html = build_section(rows, AS_OF)

    assert "Applies" in html
    assert "Does not apply" not in html


def test_a_patient_nothing_applies_to_gets_a_sentence_not_an_empty_box() -> None:
    html = build_section([ScreeningRow(screening(), None, False)], AS_OF)

    assert "No preventive screenings apply to this patient." in html


def test_every_interpolation_is_escaped() -> None:
    """**This renders on every chart open**, not behind the admin gate, and a
    screening name is free text an admin types. The security review's finding
    against the admin page applies here with more force."""
    hostile = screening(name='<script>alert("x")</script>')
    html = build_section([ScreeningRow(hostile, status(STATE_SATISFIED), False)], AS_OF)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_section_loads_nothing_from_anywhere() -> None:
    """No fonts, no scripts, no images. The security review required this of the
    admin page; a section on every chart has no excuse either."""
    html = build_section([ScreeningRow(screening(), status(STATE_SATISFIED), False)], AS_OF)

    for forbidden in ("http://", "https://", "<script", "<img", "@import", "url("):
        assert forbidden not in html, f"section reaches for {forbidden}"


def test_the_defaults_stamp_is_shown_so_rules_are_not_mistaken_for_current() -> None:
    """The brief: make it obvious they are defaults *and when they were current*,
    so the practice reviews rather than assumes."""
    html = build_section([ScreeningRow(screening(), status(STATE_SATISFIED), False)], AS_OF)

    assert "defaults current as of 2026-09-18" in html


def test_a_signal_index_that_no_longer_exists_degrades_quietly() -> None:
    """A rule edited between the read and the render must not raise on a chart."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, last_signal=99), False)], AS_OF
    )

    assert "Last completed 21 Sep 2026" in html
    assert "(" not in html.split("Last completed")[1].split("<")[0]


def test_a_custom_coded_signal_is_named_by_its_label() -> None:
    """A practice's own screening has no catalog entry, so the label they typed
    is the only name it has."""
    custom = screening(completions=[{
        "value_set_key": "", "source": "procedure", "codes": ["77080"],
        "label": "DXA bone density scan", "interval_quantity": 2, "interval_unit": "years",
    }])
    html = build_section([ScreeningRow(custom, status(STATE_SATISFIED), False)], AS_OF)

    assert "(dxa bone density scan)" in html


def test_a_date_without_a_known_modality_still_shows_the_date() -> None:
    """Knowing *when* but not *what* is still most of the answer the client
    asked for, so it is shown rather than suppressed."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, last_signal=None), False)], AS_OF
    )

    assert "Last completed 21 Sep 2026" in html
    assert "Last completed 21 Sep 2026 (" not in html


# --- the write controls -------------------------------------------------------
#
# These are rendered only when a caller passes RecordActions. The chart-summary
# section handler does not, and must not: a section Canvas composes into its
# own layout is not a place to put buttons that write.

TODAY = date(2026, 10, 5)


def actions(**names: str) -> RecordActions:
    return RecordActions(today=TODAY, names=dict(names))


def attestation(**over: Any) -> Attestation:
    values: dict[str, Any] = {
        "screening_id": "s1",
        "kind": "completed",
        "effective_date": date(2026, 3, 4),
        "interval_quantity": 10,
        "interval_unit": "years",
        "label": "",
        "recorded_by": "staff-1",
        "recorded_at": date(2026, 3, 4),
    }
    values.update(over)
    return Attestation(**values)


def test_the_section_has_no_buttons_unless_a_caller_asks_for_them() -> None:
    """The chart-summary handler renders the same rows read-only. A write
    control appearing there by default would put buttons in a surface that has
    no script to make them work."""
    html = build_section([ScreeningRow(screening(), status(STATE_DUE), False)], AS_OF)

    assert "data-act" not in html
    # The class exists in the stylesheet either way; what must not exist is
    # anything wearing it.
    assert 'class="ps-act"' not in html


def test_a_due_screening_offers_both_write_actions() -> None:
    html = build_section(
        [ScreeningRow(screening(), status(STATE_DUE), False)], AS_OF, actions()
    )

    assert 'data-act="completed"' in html
    assert 'data-act="not_applicable"' in html


def test_the_date_field_defaults_to_today_and_cannot_be_set_later() -> None:
    """A client-side cap is a convenience rather than a check - the route
    refuses a future date too - but it is the one that stops the honest
    mistake."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_DUE), False)], AS_OF, actions()
    )

    assert 'value="2026-10-05"' in html
    assert 'max="2026-10-05"' in html


def test_a_screening_with_several_completions_asks_which_one_was_done() -> None:
    """A colonoscopy covers ten years where a stool test covers one, so "it was
    done" does not say when the next one is due."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_DUE), False)], AS_OF, actions()
    )

    assert "ps-sig" in html
    assert "covers 10 years" in html
    assert "covers 1 year" in html


def test_a_screening_with_one_completion_asks_nothing() -> None:
    """There is nothing to choose, and a select with one option is a question
    that wastes a click."""
    one = screening(completions=[screening()["completions"][0]])

    html = build_section([ScreeningRow(one, status(STATE_DUE), False)], AS_OF, actions())

    assert "ps-sig" not in html


def test_an_attested_completion_says_so_and_names_who() -> None:
    """The line the whole out-of-chart storage decision rests on."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, attested=True), False,
                      attestation())],
        AS_OF,
        actions(**{"staff-1": "Ada Okafor"}),
    )

    assert "Marked complete 4 Mar 2026 by Ada Okafor" in html
    assert "Marked complete 21 Sep 2026 — no matching result in the chart" in html


def test_a_statement_recorded_later_than_it_happened_shows_both_dates() -> None:
    """They answer different questions: when the screening happened, which
    drives the next due date, and when somebody said so, which is what a reader
    is judging."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, attested=True), False,
                      attestation(recorded_at=date(2026, 10, 1)))],
        AS_OF,
        actions(),
    )

    assert "Marked complete 4 Mar 2026 by a staff member, recorded 1 Oct 2026" in html


def test_an_unknown_author_is_described_rather_than_printed() -> None:
    """A raw staff key answers nobody, and putting one in front of a clinician
    looks like a bug."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, attested=True), False,
                      attestation(recorded_by="deadbeef"))],
        AS_OF,
        actions(),
    )

    assert "by a staff member" in html
    assert "deadbeef" not in html


def test_an_attested_screening_offers_undo_instead_of_a_second_statement() -> None:
    """An attestation is a claim, not a field. Changing it means taking the
    first one back, which is the honest shape and leaves one statement."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, attested=True), False,
                      attestation())],
        AS_OF,
        actions(),
    )

    assert 'data-act="clear"' in html
    assert 'data-act="completed"' not in html


def test_undo_is_not_offered_without_the_write_controls() -> None:
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED, attested=True), False,
                      attestation())],
        AS_OF,
    )

    assert "Marked complete 4 Mar 2026" in html
    assert "data-act" not in html


def test_a_screening_marked_not_applicable_is_listed_so_it_can_be_undone() -> None:
    """It is the one not-applicable state another clinician might want to
    revisit. Hiding it with the rest would make it impossible to take back."""
    html = build_section(
        [ScreeningRow(screening(), None, False,
                      attestation(kind="not_applicable", recorded_at=date(2026, 10, 1)))],
        AS_OF,
        actions(**{"staff-1": "Ada Okafor"}),
    )

    assert "Marked not applicable" in html
    assert "by Ada Okafor on 1 Oct 2026" in html
    assert 'data-act="clear"' in html


def test_a_screening_that_simply_does_not_apply_stays_hidden() -> None:
    """Age, sex and chart exclusions are the rule working. Every one of them
    listed is a row to scroll past, and there is nothing to undo."""
    html = build_section([ScreeningRow(screening(), None, False)], AS_OF, actions())

    assert "Colorectal" not in html
    assert "Marked not applicable" not in html


def test_the_not_applicable_group_is_left_out_when_there_is_nothing_in_it() -> None:
    html = build_section(
        [ScreeningRow(screening(), status(STATE_DUE), False)], AS_OF, actions()
    )

    assert "Marked not applicable" not in html


def test_a_screening_name_is_still_escaped_inside_the_write_controls() -> None:
    """The controls carry the screening id into an attribute, and the id is
    admin-supplied. The editor caps it; this is the renderer not relying on
    that."""
    html = build_section(
        [ScreeningRow(screening(id='"><script>x</script>'), status(STATE_DUE), False)],
        AS_OF,
        actions(),
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# --- the one-click order, and awaiting a result -------------------------------


def test_a_due_screening_offers_its_order_button() -> None:
    """**This used to exist only on the protocol card.** Cards went opt-in and
    took "order without leaving the chart" with them for any practice that
    cards nothing."""
    html = build_section(
        [ScreeningRow(screening(), status(STATE_DUE), False)], AS_OF, actions()
    )

    assert 'data-act="ordered"' in html
    assert "Refer" in html


def test_a_screening_with_no_order_command_offers_no_button() -> None:
    """A practice can track a screening without offering to order it."""
    html = build_section(
        [ScreeningRow(screening(order_command=""), status(STATE_DUE), False)],
        AS_OF,
        actions(),
    )

    assert 'data-act="ordered"' not in html


def test_an_up_to_date_screening_offers_no_order_button() -> None:
    html = build_section(
        [ScreeningRow(screening(), status(STATE_SATISFIED), False)], AS_OF, actions()
    )

    assert 'data-act="ordered"' not in html


def test_the_order_button_is_absent_without_the_write_controls() -> None:
    """The chart-summary section renders read-only and has no script to make a
    button work."""
    html = build_section([ScreeningRow(screening(), status(STATE_DUE), False)], AS_OF)

    assert "data-act" not in html


def test_an_ordered_screening_reads_as_awaiting_rather_than_overdue() -> None:
    """Jess's ask, in one assertion."""
    html = build_section(
        [
            ScreeningRow(
                screening(),
                status(STATE_ORDERED, due_in=-400, ordered_on=date(2026, 10, 1)),
                False,
                attestation(kind="ordered", effective_date=date(2026, 10, 1),
                            label="Screening colonoscopy"),
            )
        ],
        AS_OF,
        actions(**{"staff-1": "Ada Okafor"}),
    )

    assert "Awaiting result" in html
    assert "Overdue by" not in html
    assert "Ordered 1 Oct 2026 by Ada Okafor — Screening colonoscopy" in html
    # Still says when it was due: "ordered" is not "was never needed".
    assert "Was due" in html


def test_an_ordered_screening_offers_undo_not_another_order() -> None:
    html = build_section(
        [
            ScreeningRow(
                screening(),
                status(STATE_ORDERED, due_in=-400, ordered_on=date(2026, 10, 1)),
                False,
                attestation(kind="ordered", effective_date=date(2026, 10, 1)),
            )
        ],
        AS_OF,
        actions(),
    )

    assert 'data-act="clear"' in html
    assert 'data-act="ordered"' not in html


def test_the_triage_order_puts_ordered_below_due_and_above_fine() -> None:
    """The practice has already acted on an ordered screening, so it is not
    part of the triage list - but it is unfinished in a way a satisfied
    screening is not."""
    rows = [
        ScreeningRow(screening(id="ok", name="Fine"), status(STATE_SATISFIED), False),
        ScreeningRow(
            screening(id="ord", name="Awaited"),
            status(STATE_ORDERED, due_in=-400, ordered_on=date(2026, 10, 1)), False,
        ),
        ScreeningRow(screening(id="due", name="Duenow"), status(STATE_DUE, due_in=-5), False),
        ScreeningRow(screening(id="od", name="Latest"), status(STATE_OVERDUE, due_in=-900), False),
    ]

    html = build_section(rows, AS_OF)
    seen = [name for name in ("Latest", "Duenow", "Awaited", "Fine") if name in html]
    positions = [html.index(name) for name in seen]

    assert seen == ["Latest", "Duenow", "Awaited", "Fine"]
    assert positions == sorted(positions)
