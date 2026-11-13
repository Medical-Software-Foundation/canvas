"""Tests for the scheduled sweep.

The sweep is the half of the plugin no event drives, and it fails quietly: a
patient it never reaches simply keeps a card that is wrong, with nothing to show
for it. So what is pinned here is the orchestration - who gets picked, in what
order, how many, and what is written - rather than the database plumbing, which
lives in services/sweep_store.py and is mocked.

``review_patients`` is mocked throughout. What it produces is tested against a
real database in tests/services/test_review.py; repeating that here would only
test the mock.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.events import EventType

from preventive_screenings.handlers.sweep import (
    BATCH_CEILING,
    EFFECT_BUDGET_BYTES,
    WORST_CARD_BYTES,
    PreventiveScreeningSweep,
    batch_size,
)
from preventive_screenings.services.config_store import new_screening

MODULE = "preventive_screenings.handlers.sweep"
TODAY = date.today()

# Almost every test below runs a single screening, so this is the batch the
# sweep will size itself to. It is computed rather than hardcoded: the point of
# batch_size is that the number moves with the configuration.
BATCH = batch_size(1)


def screening(**over: Any) -> dict:
    fields: dict[str, Any] = {
        "enabled": True,
        # The sweep only ever touches carded screenings, and a card is opt-in,
        # so a sweep fixture without this is a fixture the sweep ignores.
        "protocol_card": True,
        "name": "Mammogram",
        "sex": "any",
        "min_age": 40,
        "max_age": 74,
        "completions": [
            {"value_set_key": "mammography", "source": "imaging_report", "codes": [],
             "label": "", "interval_quantity": 2, "interval_unit": "years"}
        ],
    }
    return new_screening(**{**fields, **over})


def sweep() -> PreventiveScreeningSweep:
    event = Mock()
    event.type = EventType.CRON
    event.name = "CRON"
    return PreventiveScreeningSweep(event=event)


class Recorder:
    """A stand-in for sweep_store that remembers what it was asked to do."""

    def __init__(
        self,
        due: list[str],
        unseen: list[tuple[str, int]],
        stamp: str = "",
        tracked: list[str] | None = None,
        retired: dict[str, str] | None = None,
    ) -> None:
        self._due = due
        self._unseen = unseen
        self.state = {
            "cursor": 0,
            "stamp": stamp,
            "tracked": tracked or [],
            "retired": retired or {},
        }
        self.recorded: list[tuple[str, date, str]] = []
        self.saved: list[tuple[int, str]] = []
        self.invalidated = 0
        self.known: dict[str, str] = {}
        self.retired_seen: list[str] = []
        # How the batch reached review: one call carrying every patient, or one
        # call each. The difference is the run's whole query cost.
        self.review_calls = 0
        self.reviewed_in_one_call: list[str] = []
        # Likewise for the write: one call carrying the batch, not one each.
        self.record_calls = 0

    def load_state(self) -> dict:
        return dict(self.state)

    def retire(self, state: dict, active_ids: list[str], today: date) -> dict:
        gone = {
            key: today.isoformat()
            for key in state.get("tracked", [])
            if key not in active_ids
        }
        return {**state, "tracked": list(active_ids), "retired": {**state["retired"], **gone}}

    def save_state(
        self,
        cursor: int,
        stamp: str,
        tracked: list[str] | None = None,
        retired: dict[str, str] | None = None,
    ) -> None:
        self.saved.append((cursor, stamp))
        self.state["tracked"] = tracked or []
        self.state["retired"] = retired or {}

    def config_stamp(self, doc: dict) -> str:
        return "current"

    def invalidate_all(self, today: date) -> int:
        self.invalidated += 1
        return 3

    def patients_due(self, today: date, limit: int) -> list[str]:
        return self._due[:limit]

    def patients_unseen(self, cursor: int, limit: int) -> list[tuple[str, int]]:
        return self._unseen[:limit]

    def load_reviews(self, keys: list[str]) -> dict[str, Any]:
        # Rows, not bare fingerprints: the sweep reads `.fingerprint` off each
        # and hands the same objects straight back to record_all, which is what
        # turned the write path from two queries per patient into two per run.
        return {key: SimpleNamespace(fingerprint=mark) for key, mark in self.known.items()}

    def fingerprint(self, effects: list) -> str:
        return "".join(str(getattr(e, "payload", e)) for e in effects) or "empty"

    def clamp(self, next_review: date | None, today: date) -> date:
        return next_review or today + timedelta(days=90)

    def record_all(
        self, entries: list[tuple[str, date, str]], stored: dict[str, Any], today: date
    ) -> int:
        self.record_calls += 1
        self.recorded.extend(entries)
        return len(entries)


def run(store: Recorder, screenings: list[dict], effects_by_patient: dict | None = None) -> list:
    """Run one sweep against a recorder, with review_patients stubbed."""
    produced = effects_by_patient or {}

    def fake_review(
        patient_keys: list[str], rules: list[dict], today: date, retired: list | None = None
    ) -> Any:
        store.retired_seen = list(retired or [])
        store.review_calls += 1
        store.reviewed_in_one_call = list(patient_keys)
        outcomes = {}
        for patient_key in patient_keys:
            outcome = Mock()
            outcome.effects = produced.get(patient_key, [Mock(payload=f"card-for-{patient_key}")])
            outcome.next_review = today + timedelta(days=30)
            outcomes[patient_key] = outcome
        return outcomes

    # Patched name by name, not as one module object: the handler imports
    # them individually because the sandbox refuses attribute access on an
    # imported module. Patching a module object here would test a shape that
    # cannot run in production - which is exactly how that bug shipped.
    with (
        patch(f"{MODULE}.load_state", store.load_state),
        patch(f"{MODULE}.save_state", store.save_state),
        patch(f"{MODULE}.retire", store.retire),
        patch(f"{MODULE}.config_stamp", store.config_stamp),
        patch(f"{MODULE}.invalidate_all", store.invalidate_all),
        patch(f"{MODULE}.patients_due", store.patients_due),
        patch(f"{MODULE}.patients_unseen", store.patients_unseen),
        patch(f"{MODULE}.load_reviews", store.load_reviews),
        patch(f"{MODULE}.fingerprint", store.fingerprint),
        patch(f"{MODULE}.clamp", store.clamp),
        patch(f"{MODULE}.record_all", store.record_all),
        patch(f"{MODULE}.load_config", return_value={"screenings": screenings}),
        patch(f"{MODULE}.review_patients", side_effect=fake_review),
    ):
        return sweep().execute()


# --- the schedule ------------------------------------------------------------


def test_the_sweep_runs_on_the_cron_event() -> None:
    assert PreventiveScreeningSweep.RESPONDS_TO == EventType.Name(EventType.CRON)


def test_the_schedule_is_a_real_cron_expression() -> None:
    """CronTask parses this; a malformed one fails on the instance, not here."""
    from cron_converter import Cron

    assert len(Cron(PreventiveScreeningSweep.SCHEDULE).to_list()) == 5


def test_the_manifest_registers_the_sweep(manifest: dict[str, Any]) -> None:
    classes = [handler["class"] for handler in manifest["components"]["handlers"]]

    assert "preventive_screenings.handlers.sweep:PreventiveScreeningSweep" in classes


# --- doing nothing cheaply ---------------------------------------------------


def test_nothing_enabled_does_nothing_at_all() -> None:
    """A practice that has enabled no screenings must not pay for a sweep every
    fifteen minutes forever."""
    store = Recorder(due=["p1"], unseen=[])

    assert run(store, []) == []
    assert store.recorded == []


def test_an_empty_queue_writes_nothing() -> None:
    store = Recorder(due=[], unseen=[])

    assert run(store, [screening()]) == []


# --- who gets picked, and how many -------------------------------------------


def test_the_whole_batch_is_reviewed_in_one_call() -> None:
    """The entire batch goes to review together, not one patient at a time.

    Reviewing them individually is what made a run cost a full set of chart
    queries per patient - 50 patients ran up to 300 queries where 6 would do -
    and it is invisible from the outside, because the cards come out identical
    either way. **If this fails, batch the call rather than deleting the test.**
    """
    store = Recorder(due=[f"p{i}" for i in range(BATCH)], unseen=[])

    run(store, [screening()])

    assert store.review_calls == 1
    assert len(store.reviewed_in_one_call) == BATCH


def test_a_run_is_bounded_by_the_batch_size() -> None:
    """A run returns its effects in one list, so an unbounded sweep would not
    run at all on a large panel. This is the ceiling."""
    store = Recorder(due=[f"p{i}" for i in range(500)], unseen=[])

    run(store, [screening()])

    assert len(store.recorded) == BATCH


def test_patients_already_due_come_before_the_backfill() -> None:
    """A backfill must never starve patients whose cards are wrong today."""
    store = Recorder(due=[f"p{i}" for i in range(BATCH)], unseen=[("new", 9)])

    run(store, [screening()])

    assert [key for key, _when, _mark in store.recorded] == [f"p{i}" for i in range(BATCH)]


def test_the_backfill_fills_the_rest_of_the_batch() -> None:
    """With a short queue there is spare capacity, and a fresh install needs it:
    nobody has a row yet."""
    store = Recorder(due=["p1"], unseen=[("new1", 9), ("new2", 10)])

    run(store, [screening()])

    assert [key for key, _when, _mark in store.recorded] == ["p1", "new1", "new2"]


def test_the_backfill_cursor_advances_past_the_patients_it_took() -> None:
    """Without this the sweep walks the same patients forever and never reaches
    the end of the panel."""
    store = Recorder(due=[], unseen=[("new1", 9), ("new2", 17)])

    run(store, [screening()])

    assert store.saved[-1][0] == 17


def test_the_cursor_is_not_saved_when_the_backfill_finds_nobody() -> None:
    """Once the panel is fully seeded there is nothing to advance past."""
    store = Recorder(due=["p1"], unseen=[], stamp="current")

    run(store, [screening()])

    assert store.saved == []


# --- writing only what changed -----------------------------------------------


def test_a_patient_whose_cards_are_unchanged_is_not_rewritten() -> None:
    """At panel scale the expensive half is writing, and most sweeps find most
    patients unchanged."""
    store = Recorder(due=["p1"], unseen=[])
    store.known = {"p1": "card-for-p1"}

    assert run(store, [screening()]) == []


def test_a_patient_whose_cards_changed_is_rewritten() -> None:
    store = Recorder(due=["p1"], unseen=[])
    store.known = {"p1": "something-else"}

    assert len(run(store, [screening()])) == 1


def test_a_patient_seen_for_the_first_time_is_written() -> None:
    store = Recorder(due=["p1"], unseen=[])

    assert len(run(store, [screening()])) == 1


def test_an_unchanged_patient_is_still_rescheduled() -> None:
    """Skipping the write must not skip the bookkeeping, or the patient stays at
    the head of the queue and blocks everyone behind them."""
    store = Recorder(due=["p1"], unseen=[])
    store.known = {"p1": "card-for-p1"}

    run(store, [screening()])

    assert [key for key, _when, _mark in store.recorded] == ["p1"]


def test_a_patient_with_no_cards_is_rescheduled_but_writes_nothing() -> None:
    """A deceased patient, or one with no date of birth, produces no cards. They
    must still be recorded or the queue never drains past them."""
    store = Recorder(due=["p1"], unseen=[])

    assert run(store, [screening()], {"p1": []}) == []
    assert [key for key, _when, _mark in store.recorded] == ["p1"]


# --- rules changing ----------------------------------------------------------


def test_changed_rules_requeue_the_whole_panel() -> None:
    """Changing an interval invalidates every stored prediction at once, and no
    event says so."""
    store = Recorder(due=["p1"], unseen=[], stamp="stale")

    run(store, [screening()])

    assert store.invalidated == 1
    assert ("current" in [stamp for _cursor, stamp in store.saved])


def test_unchanged_rules_do_not_requeue_anything() -> None:
    """Otherwise every run would requeue the panel and the queue would never
    drain."""
    store = Recorder(due=["p1"], unseen=[], stamp="current")

    run(store, [screening()])

    assert store.invalidated == 0


# --- retracting a screening the practice stopped tracking --------------------


def test_switching_a_screening_off_retracts_it() -> None:
    """Nothing deletes a protocol card, so a screening that stops producing one
    would leave its last state - possibly OVERDUE - on every chart it reached."""
    store = Recorder(due=["p1"], unseen=[], stamp="stale", tracked=["gone", "kept"])

    run(store, [screening(id="kept")])

    assert store.retired_seen == ["gone"]


def test_a_screening_still_tracked_is_not_retracted() -> None:
    store = Recorder(due=["p1"], unseen=[], stamp="stale", tracked=["kept"])

    run(store, [screening(id="kept")])

    assert store.retired_seen == []


def test_switching_a_cards_toggle_off_retracts_it_too() -> None:
    """**The migration case, and the one that could strand cards on charts.**

    Turning a card off is not "stop writing it". Nothing deletes a protocol
    card, so the last state it was written in - very possibly OVERDUE - sits on
    every chart it reached until something overwrites it. The screening is
    still tracked and still appears in the record app; only the card is gone,
    and it has to be actively taken back.
    """
    store = Recorder(due=["p1"], unseen=[], stamp="stale", tracked=["s1"])

    run(store, [screening(id="s1", protocol_card=False)])

    assert store.retired_seen == ["s1"]


def test_the_last_card_being_switched_off_still_retracts() -> None:
    """The version of the above that an early return would swallow. With
    nothing left carded the sweep used to return before it ever looked at what
    it had been carding, which left that card on every chart permanently."""
    store = Recorder(due=["p1"], unseen=[], stamp="stale", tracked=["s1"])

    run(store, [screening(id="s1", protocol_card=False)])

    assert store.retired_seen == ["s1"]
    # It reached the review at all, which is what the early return swallowed.
    assert store.review_calls == 1


def test_a_practice_that_cards_nothing_does_no_work() -> None:
    """The default configuration, every minute, forever. It costs the config
    read and the state read and stops there."""
    store = Recorder(due=["p1"], unseen=[("p2", 2)], stamp="current")

    assert run(store, [screening(protocol_card=False)]) == []
    assert store.recorded == []
    assert store.review_calls == 0


def test_editing_a_rule_that_is_not_carded_does_not_requeue_the_panel() -> None:
    """A config edit changes the stamp whether or not anything is carded. With
    nothing to write and nothing to take back, requeueing would walk the whole
    panel through a review that produces no cards and pay the bookkeeping write
    for every one of them."""
    store = Recorder(due=["p1"], unseen=[], stamp="stale")

    run(store, [screening(protocol_card=False)])

    assert store.invalidated == 0
    # The new stamp is still stored, or this would repeat every single tick.
    assert store.saved == [(0, "current")]


def test_a_rules_change_with_something_to_retract_still_requeues() -> None:
    """Even with nothing carded any more: the retractions are the work."""
    store = Recorder(due=["p1"], unseen=[], stamp="stale", tracked=["s1"])

    run(store, [screening(id="s1", protocol_card=False)])

    assert store.invalidated == 1


def test_a_retraction_keeps_being_applied_until_the_panel_drains() -> None:
    """One run only reaches a batch of patients, so a screening retired days ago
    must still be retracted for everyone the sweep has not reached yet."""
    store = Recorder(
        due=["p1"], unseen=[], stamp="current", retired={"gone": "2026-09-01"}
    )

    run(store, [screening(id="kept")])

    assert store.retired_seen == ["gone"]


# --- sizing the batch against the message ceiling ----------------------------


def test_more_screenings_means_fewer_patients_per_run() -> None:
    """Every enabled screening emits a card for every patient, so the patients
    that fit in one message fall as screenings rise.

    A fixed batch is only ever right for the screening count it was chosen
    against. This is the whole reason batch_size is a function.
    """
    assert batch_size(40) < batch_size(12) < batch_size(6)


def test_no_configuration_can_overrun_the_message_budget() -> None:
    """Across every screening count the config store permits, a full run's
    worst-case cards still fit.

    **If this fails, lower BATCH_CEILING or the budget - do not raise
    WORST_CARD_BYTES to make it pass.**
    """
    from preventive_screenings.services.config_store import MAX_SCREENINGS

    for count in range(1, MAX_SCREENINGS + 1):
        worst = batch_size(count) * count * WORST_CARD_BYTES

        assert worst <= EFFECT_BUDGET_BYTES, f"{count} screenings overruns the budget"


def test_the_budget_stays_under_both_measured_ceilings() -> None:
    """Two ceilings, measured on the instance 2026-09-20.

    gRPC's default maximum message length is 4 MiB, and the instance accepted
    4.2 MiB - but a plugin shipped to every practice cannot assume every
    instance raised it. The runner's memory watchdog binds sooner: 5 MiB of
    effects logged 10 MB of RSS growth during CronTask.compute, 4 MiB did not.
    """
    grpc_default = 4 * 1024 * 1024
    watchdog_floor = 5 * 1024 * 1024  # the smallest size observed to warn

    assert EFFECT_BUDGET_BYTES <= grpc_default / 2
    assert EFFECT_BUDGET_BYTES < watchdog_floor / 2


def test_a_batch_is_never_zero_however_many_screenings() -> None:
    """A zero batch would stall the sweep permanently and log nothing."""
    assert batch_size(10_000) >= 1
    assert batch_size(0) >= 1


def test_the_shipped_screenings_stay_well_inside_the_card_budget() -> None:
    """The six defaults are the typical case, not the bound - the bound is the
    test below. This one catches cards quietly growing."""
    from datetime import date as _date

    from preventive_screenings.services.cards import build_card
    from preventive_screenings.services.config_store import _default_document
    from preventive_screenings.services.screenings import STATE_OVERDUE, ScreeningStatus

    today = _date(2026, 9, 20)
    worst = max(
        len(
            build_card(
                "00000000-0000-4000-8000-000000000000",
                rule,
                ScreeningStatus(STATE_OVERDUE, today - timedelta(days=400), None, -400),
            )
            .apply()
            .payload.encode()
        )
        for rule in _default_document()["screenings"]
    )

    assert worst <= WORST_CARD_BYTES, f"cards grew to {worst} bytes; re-measure"


def test_the_worst_card_the_config_allows_fits_the_budget() -> None:
    """WORST_CARD_BYTES has to bound every card the configuration can produce.

    The six shipped screenings are not that bound - a practice writes its own
    text. This builds the largest card `config_store`'s caps permit: a
    maximum-length name, the maximum number of completion signals each with a
    maximum-length label (they all land in the narrative), and full-length
    order text.

    **If this fails, a legal configuration overruns EFFECT_BUDGET_BYTES**, and
    it does so silently - the run's effects are discarded whole after `record`
    has already marked those patients reviewed, so their cards stay wrong for a
    full cycle with nothing logged. Raise WORST_CARD_BYTES to the new bound, or
    lower the cap that moved; do not delete this.
    """
    from preventive_screenings.services.cards import build_card
    from preventive_screenings.services.config_store import (
        MAX_CODE_CHARS,
        MAX_SIGNALS_PER_SCREENING,
        MAX_TEXT_CHARS,
        normalize_screening,
    )
    from preventive_screenings.services.screenings import STATE_OVERDUE, ScreeningStatus

    biggest = normalize_screening(
        {
            "id": "s" * 32,
            "enabled": True,
            "name": "N" * MAX_TEXT_CHARS,
            "sex": "female",
            # Three-digit ages and a four-figure interval, so every number in
            # the narrative is as long as it can get.
            "min_age": 100,
            "max_age": 120,
            "grace_days": 999,
            "completions": [
                {
                    "codes": ["C" * MAX_CODE_CHARS],
                    "source": "imaging",
                    "label": "L" * MAX_TEXT_CHARS,
                    "interval_quantity": 9999,
                    "interval_unit": "months",
                }
                for _ in range(MAX_SIGNALS_PER_SCREENING)
            ],
            "order_command": "imaging_order",
            "order_code": "O" * MAX_CODE_CHARS,
            "order_button": "B" * MAX_TEXT_CHARS,
            "order_comment": "M" * MAX_TEXT_CHARS,
            "guidance": "G" * 10_000,
        }
    )
    # Overdue with a recommendation is the largest of the three card states.
    card = build_card(
        "00000000-0000-4000-8000-000000000000",
        biggest,
        ScreeningStatus(STATE_OVERDUE, date(2020, 11, 28), date(2019, 12, 31), -99_999),
    )
    size = len(card.apply().payload.encode())

    assert size <= WORST_CARD_BYTES, (
        f"the caps permit a {size}-byte card but runs are sized against "
        f"{WORST_CARD_BYTES}; a legal config would overrun the effect budget"
    )


def test_the_worst_card_carrying_a_value_set_filter_fits_too() -> None:
    """The other shape of worst case, and the one the test above misses.

    A card's order recommendation carries a *search filter* built from the
    screening's value set - that is what pre-fills the command - and the largest
    one this plugin ships (mammography, 92 LOINC codes) is about a kilobyte on
    its own. The test above uses custom codes, so it never sees that kilobyte.

    **If this fails, a value set has grown past what a card can carry.** Raise
    WORST_CARD_BYTES to the new bound and check the drain rate below still
    passes; do not drop the filter, because without it the staged command is
    empty.
    """
    from preventive_screenings.services.cards import build_card
    from preventive_screenings.services.config_store import (
        MAX_CODE_CHARS,
        MAX_SIGNALS_PER_SCREENING,
        MAX_TEXT_CHARS,
        normalize_screening,
    )
    from preventive_screenings.services.screenings import STATE_OVERDUE, ScreeningStatus

    biggest = normalize_screening(
        {
            "id": "s" * 32,
            "enabled": True,
            "name": "N" * MAX_TEXT_CHARS,
            "sex": "female",
            "min_age": 100,
            "max_age": 120,
            "grace_days": 999,
            "completions": [
                {
                    "value_set_key": "mammography",
                    "label": "L" * MAX_TEXT_CHARS,
                    "interval_quantity": 9999,
                    "interval_unit": "months",
                }
                for _ in range(MAX_SIGNALS_PER_SCREENING)
            ],
            "order_command": "imaging_order",
            "order_code": "O" * MAX_CODE_CHARS,
            "order_button": "B" * MAX_TEXT_CHARS,
            "order_comment": "M" * MAX_TEXT_CHARS,
        }
    )
    card = build_card(
        "00000000-0000-4000-8000-000000000000",
        biggest,
        ScreeningStatus(STATE_OVERDUE, date(2020, 11, 28), date(2019, 12, 31), -99_999),
    )
    size = len(card.apply().payload.encode())

    assert size <= WORST_CARD_BYTES, (
        f"a card carrying the largest value-set filter is {size} bytes but runs "
        f"are sized against {WORST_CARD_BYTES}"
    )


def test_the_drain_rate_keeps_the_ninety_day_promise() -> None:
    """sweep_store.retire drops a retired screening after one cycle, assuming
    every patient has been swept by then. That assumption is only true while the
    drain rate can cover the panel in the cycle.

    Pinned at the panel size this plugin is meant to serve. **If this fails the
    guarantee in sweep_store is false, not merely slow.**
    """
    from cron_converter import Cron

    from preventive_screenings.services.sweep_store import MAX_REVIEW_GAP_DAYS

    runs_per_day = len(Cron(PreventiveScreeningSweep.SCHEDULE).to_list()[0]) * 24
    reachable = batch_size(40) * runs_per_day * MAX_REVIEW_GAP_DAYS

    assert reachable >= 200_000, f"only {reachable:,} patients reachable in a cycle"


def test_an_idle_run_says_so(caplog: Any) -> None:
    """A sweep with nothing to do must leave a trace.

    Once the panel is drained this is the normal state, and while it was silent
    a healthy idle sweep and a dead one produced identical logs - which cost a
    wrong diagnosis and left a schedule change unverifiable on 2026-09-20.
    """
    import logging

    store = Recorder(due=[], unseen=[])

    with caplog.at_level(logging.INFO):
        assert run(store, [screening()]) == []

    assert "nothing due" in caplog.text
