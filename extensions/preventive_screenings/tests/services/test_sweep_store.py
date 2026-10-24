"""Tests for the sweep's bookkeeping.

CustomModel tables are not created by the pytest fixtures, so most of this file
mocks the model and asserts the *shape* of the query - which columns, which
filter, which ordering.

**That is thin cover, and it hid a real bug.** ``record`` used to run per
patient, two queries each, and no test could see it: a mocked queryset does not
count queries, so the plugin's query budgets only ever measured the chart reads,
which were already batched. The one part of the sweep with an N+1 was the one
part nothing could measure.

The ``review_table`` fixture below fixes that. The table does not exist, but it
can be *created* - ``connection.schema_editor()`` under
``django_db(transaction=True)`` - which makes ``django_assert_num_queries``
usable against a CustomModel. The batch write is tested that way. SQLite's
query *plans* are still not representative, so this buys exact counts, not
``EXPLAIN``.
"""

import json
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any
from unittest.mock import Mock, patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from preventive_screenings.models import ScreeningReview
from preventive_screenings.services import sweep_store
from preventive_screenings.services.sweep_store import (
    MAX_REVIEW_GAP_DAYS,
    clamp,
    config_stamp,
    fingerprint,
)

MODULE = "preventive_screenings.services.sweep_store"
TODAY = date(2026, 9, 19)


# --- the clamp, which is the safety net --------------------------------------


def test_a_near_prediction_is_kept() -> None:
    assert clamp(TODAY + timedelta(days=10), TODAY) == TODAY + timedelta(days=10)


def test_a_far_prediction_is_pulled_back_to_the_cycle() -> None:
    """A colonoscopy buys ten years, but nobody goes ten years unverified: the
    rules change, and a wrong prediction would otherwise never be caught."""
    assert clamp(TODAY + timedelta(days=4000), TODAY) == TODAY + timedelta(
        days=MAX_REVIEW_GAP_DAYS
    )


def test_no_prediction_still_gets_re_verified() -> None:
    """None means "nothing time can change", which is itself a prediction. If it
    is wrong, the patient would be stranded forever."""
    assert clamp(None, TODAY) == TODAY + timedelta(days=MAX_REVIEW_GAP_DAYS)


def test_a_prediction_of_today_is_pushed_to_tomorrow() -> None:
    """Storing today would make the sweep pick the same patient up every run,
    starving everyone behind them in the queue."""
    assert clamp(TODAY, TODAY) == TODAY + timedelta(days=1)


def test_a_prediction_in_the_past_is_pushed_to_tomorrow() -> None:
    assert clamp(TODAY - timedelta(days=500), TODAY) == TODAY + timedelta(days=1)


# --- change detection --------------------------------------------------------


def effect(payload: str) -> Any:
    found = Mock()
    found.payload = payload
    return found


def test_identical_cards_fingerprint_identically() -> None:
    assert fingerprint([effect("a"), effect("b")]) == fingerprint([effect("a"), effect("b")])


def test_a_changed_card_changes_the_fingerprint() -> None:
    """This is what stops the sweep rewriting a card that says the same thing;
    at panel scale the writes are the expensive half."""
    assert fingerprint([effect("a")]) != fingerprint([effect("a2")])


def test_card_order_is_part_of_the_fingerprint() -> None:
    """Order carries meaning here - overdue cards are emitted first - so a
    reordering is a real change."""
    assert fingerprint([effect("a"), effect("b")]) != fingerprint([effect("b"), effect("a")])


def test_no_cards_fingerprints_stably() -> None:
    assert fingerprint([]) == fingerprint([])


def test_the_config_stamp_ignores_key_order() -> None:
    """Otherwise a rewritten but identical document would requeue the panel."""
    assert config_stamp({"a": 1, "b": 2}) == config_stamp({"b": 2, "a": 1})


def test_changing_a_rule_changes_the_stamp() -> None:
    """An interval change invalidates every stored prediction, and no event
    says so."""
    assert config_stamp({"interval": 10}) != config_stamp({"interval": 5})


# --- the stored state --------------------------------------------------------


def test_missing_state_reads_as_a_fresh_start() -> None:
    with patch(f"{MODULE}.ScreeningConfig") as model:
        model.objects.filter.return_value.first.return_value = None

        assert sweep_store.load_state() == {
            "cursor": 0, "stamp": "", "tracked": [], "retired": {},
        }


def test_state_survives_a_round_trip() -> None:
    row = Mock()
    row.payload = json.dumps(
        {"cursor": 42, "stamp": "abc", "tracked": ["s1"], "retired": {"s2": "2026-09-01"}}
    )
    with patch(f"{MODULE}.ScreeningConfig") as model:
        model.objects.filter.return_value.first.return_value = row

        assert sweep_store.load_state() == {
            "cursor": 42, "stamp": "abc", "tracked": ["s1"], "retired": {"s2": "2026-09-01"},
        }


def test_unreadable_state_does_not_stop_the_sweep() -> None:
    """This runs unattended on a schedule; a bad row must cost one quiet cycle,
    not a crash loop against the whole panel."""
    with patch(f"{MODULE}.ScreeningConfig") as model:
        model.objects.filter.side_effect = RuntimeError("no such table")

        assert sweep_store.load_state() == {
            "cursor": 0, "stamp": "", "tracked": [], "retired": {},
        }


def test_saving_state_updates_an_existing_row() -> None:
    row = Mock()
    with patch(f"{MODULE}.ScreeningConfig") as model:
        model.objects.filter.return_value.first.return_value = row
        sweep_store.save_state(7, "s")

    assert json.loads(row.payload) == {
        "cursor": 7, "stamp": "s", "tracked": [], "retired": {},
    }
    row.save.assert_called_once()


def test_saving_state_creates_a_row_when_there_is_none() -> None:
    with patch(f"{MODULE}.ScreeningConfig") as model:
        model.objects.filter.return_value.first.return_value = None
        sweep_store.save_state(7, "s")

    model.objects.create.assert_called_once()


def test_a_failed_state_save_does_not_raise() -> None:
    with patch(f"{MODULE}.ScreeningConfig") as model:
        model.objects.filter.side_effect = RuntimeError("namespace not ready")

        sweep_store.save_state(1, "s")  # must not raise


# --- the queue ---------------------------------------------------------------


def test_the_due_queue_takes_the_oldest_first_and_is_bounded() -> None:
    """Oldest first so a patient cannot be starved, bounded so one run cannot
    try to rewrite the panel."""
    with patch(f"{MODULE}.ScreeningReview") as model:
        chain = model.objects.filter.return_value.order_by.return_value
        chain.values_list.return_value = ["a", "b"]

        assert sweep_store.patients_due(TODAY, 50) == ["a", "b"]

    assert model.objects.filter.call_args.kwargs == {"next_review__lte": TODAY}
    model.objects.filter.return_value.order_by.assert_called_once_with("next_review")


def test_a_broken_queue_read_yields_nothing_rather_than_raising() -> None:
    with patch(f"{MODULE}.ScreeningReview") as model:
        model.objects.filter.side_effect = RuntimeError("no such table")

        assert sweep_store.patients_due(TODAY, 50) == []


def test_the_backfill_walks_forward_from_the_cursor_and_skips_the_deceased() -> None:
    """A cursor keeps this an indexed range scan rather than an anti-join
    against every patient in the practice."""
    with patch(f"{MODULE}.Patient") as model:
        chain = model.objects.filter.return_value.order_by.return_value
        chain.values.return_value = [{"id": "p1", "dbid": 5}, {"id": "p2", "dbid": 6}]

        assert sweep_store.patients_unseen(4, 50) == [("p1", 5), ("p2", 6)]

    assert model.objects.filter.call_args.kwargs == {"dbid__gt": 4, "deceased": False}
    model.objects.filter.return_value.order_by.assert_called_once_with("dbid")


def test_a_broken_backfill_read_yields_nothing_rather_than_raising() -> None:
    with patch(f"{MODULE}.Patient") as model:
        model.objects.filter.side_effect = RuntimeError("boom")

        assert sweep_store.patients_unseen(0, 50) == []


def test_changed_rules_requeue_every_patient_in_one_update() -> None:
    """One update rather than a recomputation: the sweep then drains the panel
    in bounded batches instead of attempting it in a single run."""
    with patch(f"{MODULE}.ScreeningReview") as model:
        model.objects.update.return_value = 1234

        assert sweep_store.invalidate_all(TODAY) == 1234

    model.objects.update.assert_called_once_with(next_review=TODAY)


def test_a_failed_invalidate_reports_nothing_requeued() -> None:
    with patch(f"{MODULE}.ScreeningReview") as model:
        model.objects.update.side_effect = RuntimeError("boom")

        assert sweep_store.invalidate_all(TODAY) == 0


def test_one_patient_can_be_pushed_to_the_front_of_the_queue() -> None:
    """A staff member marking a screening complete changes what their cards
    should say, and no Canvas event fires for it - it is this plugin's own data
    that moved."""
    with patch(f"{MODULE}.ScreeningReview") as model:
        model.objects.filter.return_value.update.return_value = 1

        assert sweep_store.invalidate_patient("p1", TODAY) == 1

    model.objects.filter.assert_called_once_with(patient_key="p1")
    model.objects.filter.return_value.update.assert_called_once_with(next_review=TODAY)


def test_requeueing_a_patient_leaves_the_fingerprint_alone() -> None:
    """**Deliberate, and load-bearing.** The record route also returns the
    recomputed cards directly, and a SimpleAPI route returning an effect is a
    mechanism this plugin has never proved works. Storing the new fingerprint
    here would make the sweep agree the cards were already right and skip them,
    so a silent failure of that mechanism would leave the card stale forever.
    """
    with patch(f"{MODULE}.ScreeningReview") as model:
        sweep_store.invalidate_patient("p1", TODAY)

    _, kwargs = model.objects.filter.return_value.update.call_args
    assert "fingerprint" not in kwargs


def test_a_failed_requeue_reports_nothing_moved() -> None:
    with patch(f"{MODULE}.ScreeningReview") as model:
        model.objects.filter.side_effect = RuntimeError("boom")

        assert sweep_store.invalidate_patient("p1", TODAY) == 0


def test_no_patients_means_no_review_query() -> None:
    with patch(f"{MODULE}.ScreeningReview") as model:
        assert sweep_store.load_reviews([]) == {}

    model.objects.filter.assert_not_called()


def test_a_broken_review_read_rewrites_rather_than_raising() -> None:
    """Falling back to an empty map means the cards are rewritten. Writing a
    card that was already right is wasteful; skipping one that changed is wrong.
    """
    with patch(f"{MODULE}.ScreeningReview") as model:
        model.objects.filter.side_effect = RuntimeError("boom")

        assert sweep_store.load_reviews(["p1"]) == {}


def test_a_failed_write_does_not_raise() -> None:
    with patch(f"{MODULE}.ScreeningReview") as model:
        model.objects.bulk_create.side_effect = RuntimeError("boom")

        assert sweep_store.record_all([("p1", TODAY, "f")], {}, TODAY) == 0


def test_writing_nothing_touches_the_database_not_at_all() -> None:
    with patch(f"{MODULE}.ScreeningReview") as model:
        assert sweep_store.record_all([], {}, TODAY) == 0

    model.objects.bulk_create.assert_not_called()
    model.objects.bulk_update.assert_not_called()


# --- the batch write, against a real table -----------------------------------


@pytest.fixture
def review_table() -> Iterator[None]:
    """Create the CustomModel's table, so its queries can actually be counted.

    The pytest fixtures do not create custom-data tables, which is why the rest
    of this file mocks the model - and why the N+1 in the write path went
    unseen for as long as it did. `schema_editor` can create it, as long as the
    test is not inside an atomic block: SQLite cannot disable foreign-key
    checks mid-transaction, hence `django_db(transaction=True)` on each test
    that asks for this.
    """
    with connection.schema_editor() as editor:
        editor.create_model(ScreeningReview)
    yield
    with connection.schema_editor() as editor:
        editor.delete_model(ScreeningReview)


def _statements(captured: CaptureQueriesContext) -> list[str]:
    """The captured SQL, without transaction control.

    `transaction=True` is required for the schema editor, and it makes each
    BEGIN and COMMIT visible to the capture. Those are not the cost being
    measured and there are none of them on the plugin's real path, so they are
    dropped rather than baked into the expected number.
    """
    noise = ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")
    return [
        q["sql"] for q in captured.captured_queries if not q["sql"].upper().startswith(noise)
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("size", [2, 50, 400])
def test_a_whole_batch_is_written_in_two_statements_whatever_its_size(
    review_table: None, size: int
) -> None:
    """**The guard on the N+1.** This used to be two queries per patient - 226
    for a default batch, 800 at BATCH_CEILING - beside the <=6 the very same
    run spent reading the charts.

    Two statements now: one UPDATE carrying a CASE over the existing rows, one
    multi-row INSERT for the new ones.

    Not *exactly* two at every size - Django splits a bulk write at the
    backend's bound parameter limit, so SQLite needs a second INSERT somewhere
    above 200 new rows. Postgres takes ~16k rows of this shape in one
    statement, so the instance will not split at any batch this plugin
    produces. What is pinned is the shape: a handful of statements, not one per
    patient, at every size up to BATCH_CEILING.

    **If this fails, batch the write again; do not raise the number.**
    """
    half = size // 2
    existing = [f"old{i}" for i in range(half)]
    ScreeningReview.objects.bulk_create(
        [
            ScreeningReview(
                patient_key=key, next_review=TODAY, last_reviewed=TODAY, fingerprint="before"
            )
            for key in existing
        ]
    )
    keys = existing + [f"new{i}" for i in range(size - half)]
    later = TODAY + timedelta(days=30)

    with CaptureQueriesContext(connection) as reading:
        stored = sweep_store.load_reviews(keys)
    with CaptureQueriesContext(connection) as writing:
        written = sweep_store.record_all([(key, later, "after") for key in keys], stored, TODAY)

    wrote = len(_statements(writing))

    assert len(_statements(reading)) == 1, "the batch's rows must be read in one query"
    # A per-patient write would be 2x size here - 800 statements at the
    # largest parametrized batch - so this bound cannot be met by accident.
    assert wrote <= 4, f"{size} patients cost {wrote} statements; the write is not batched"
    assert written == size
    assert ScreeningReview.objects.count() == size


@pytest.mark.django_db(transaction=True)
def test_a_settled_panel_writes_only_the_update(review_table: None) -> None:
    """Steady state: once the panel has been swept through, every patient in a
    batch already has a row, so there is nothing to create. The insert must be
    skipped rather than run empty."""
    keys = ["p1", "p2"]
    ScreeningReview.objects.bulk_create(
        [
            ScreeningReview(
                patient_key=key, next_review=TODAY, last_reviewed=TODAY, fingerprint="before"
            )
            for key in keys
        ]
    )
    later = TODAY + timedelta(days=30)

    stored = sweep_store.load_reviews(keys)
    with CaptureQueriesContext(connection) as writing:
        written = sweep_store.record_all([(key, later, "after") for key in keys], stored, TODAY)

    assert len(_statements(writing)) == 1, "nothing to create, so no INSERT"
    assert written == 2
    assert ScreeningReview.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_the_batch_write_updates_the_old_rows_and_creates_the_new_ones(
    review_table: None,
) -> None:
    """Batching must not turn an update into a duplicate row - `patient_key` is
    unique, and a second row for a patient would make their next review
    ambiguous."""
    ScreeningReview.objects.create(
        patient_key="p1", next_review=TODAY, last_reviewed=TODAY, fingerprint="before"
    )
    later = TODAY + timedelta(days=5)

    stored = sweep_store.load_reviews(["p1", "p2"])
    sweep_store.record_all([("p1", later, "after"), ("p2", later, "fresh")], stored, TODAY)

    updated = ScreeningReview.objects.get(patient_key="p1")
    created = ScreeningReview.objects.get(patient_key="p2")

    assert (updated.next_review, updated.fingerprint, updated.last_reviewed) == (
        later,
        "after",
        TODAY,
    )
    assert (created.next_review, created.fingerprint, created.last_reviewed) == (
        later,
        "fresh",
        TODAY,
    )
    assert ScreeningReview.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_a_review_row_comes_back_whole_not_just_its_fingerprint(
    review_table: None,
) -> None:
    """load_reviews returns the rows so record_all can write them back without
    reading them again - the second read is what made this an N+1."""
    ScreeningReview.objects.create(
        patient_key="p1", next_review=TODAY, last_reviewed=TODAY, fingerprint="f1"
    )

    row = sweep_store.load_reviews(["p1"])["p1"]

    assert isinstance(row, ScreeningReview)
    assert row.fingerprint == "f1"
    assert row.pk is not None  # writable without a further read


@pytest.mark.django_db(transaction=True)
def test_the_due_queue_is_ordered_and_limited_against_a_real_table(
    review_table: None,
) -> None:
    """The oldest prediction is the one most likely to be wrong, so it goes
    first; the limit is what keeps a run inside the effect budget."""
    for offset in (5, 1, 3):
        ScreeningReview.objects.create(
            patient_key=f"p{offset}",
            next_review=TODAY - timedelta(days=offset),
            last_reviewed=TODAY,
            fingerprint="f",
        )
    ScreeningReview.objects.create(
        patient_key="future", next_review=TODAY + timedelta(days=1), last_reviewed=TODAY,
        fingerprint="f",
    )

    assert sweep_store.patients_due(TODAY, 2) == ["p5", "p3"]


# --- remembering what stopped being tracked ----------------------------------


def test_a_screening_that_disappeared_is_remembered() -> None:
    state = {"cursor": 0, "stamp": "", "tracked": ["a", "b"], "retired": {}}

    after = sweep_store.retire(state, ["a"], TODAY)

    assert after["retired"] == {"b": TODAY.isoformat()}
    assert after["tracked"] == ["a"]


def test_a_screening_still_tracked_is_not_retired() -> None:
    state = {"cursor": 0, "stamp": "", "tracked": ["a"], "retired": {}}

    assert sweep_store.retire(state, ["a"], TODAY)["retired"] == {}


def test_a_retirement_keeps_its_original_date() -> None:
    """Re-stamping it on every config change would keep it alive forever."""
    state = {"cursor": 0, "stamp": "", "tracked": [], "retired": {"b": "2026-09-01"}}

    assert sweep_store.retire(state, [], TODAY)["retired"]["b"] == "2026-09-01"


def test_a_retirement_is_forgotten_after_a_full_review_cycle() -> None:
    """By then every patient has been swept at least once, so the card is gone
    everywhere and the list must not grow without bound."""
    old = (TODAY - timedelta(days=MAX_REVIEW_GAP_DAYS + 1)).isoformat()
    state = {"cursor": 0, "stamp": "", "tracked": [], "retired": {"b": old}}

    assert sweep_store.retire(state, [], TODAY)["retired"] == {}


def test_a_recent_retirement_is_kept() -> None:
    recent = (TODAY - timedelta(days=MAX_REVIEW_GAP_DAYS - 1)).isoformat()
    state = {"cursor": 0, "stamp": "", "tracked": [], "retired": {"b": recent}}

    assert "b" in sweep_store.retire(state, [], TODAY)["retired"]


def test_a_first_run_retires_nothing() -> None:
    """Nothing has been tracked yet, so nothing can have stopped being tracked."""
    state = {"cursor": 0, "stamp": "", "tracked": [], "retired": {}}

    assert sweep_store.retire(state, ["a", "b"], TODAY)["retired"] == {}


# --- a screening that comes back ---------------------------------------------
#
# Shipped broken in 0.18.0 and hit on the instance within the hour. `retire`
# only ever added, and expired by age, so a card switched off and back on
# inside 90 days stayed in `retired` - and `services.review` writes retractions
# after the cards under the same key, so the screening retracted its own card.


def test_a_screening_that_is_carded_again_stops_being_retired() -> None:
    """**The 0.18.0 bug.** Being carded now beats having been retracted before;
    the card is what the practice is asking for today."""
    state = {"cursor": 0, "stamp": "", "tracked": ["gone"],
             "retired": {"gone": TODAY.isoformat()}}

    assert sweep_store.retire(state, ["gone"], TODAY)["retired"] == {}


def test_the_two_lists_can_never_overlap() -> None:
    """The invariant, stated directly. An id in both means a screening whose
    own retraction overwrites its own card."""
    state = {"cursor": 0, "stamp": "", "tracked": ["a", "b", "c"],
             "retired": {"a": TODAY.isoformat(), "b": TODAY.isoformat()}}

    found = sweep_store.retire(state, ["a", "c"], TODAY)

    assert not set(found["retired"]) & set(found["tracked"])
    assert set(found["retired"]) == {"b"}


def test_a_screening_still_off_stays_retired_when_another_comes_back() -> None:
    """Un-retiring must be per screening, not a reset of the whole list."""
    state = {"cursor": 0, "stamp": "", "tracked": ["back", "still-off"],
             "retired": {"back": TODAY.isoformat(), "still-off": TODAY.isoformat()}}

    assert set(sweep_store.retire(state, ["back"], TODAY)["retired"]) == {"still-off"}
