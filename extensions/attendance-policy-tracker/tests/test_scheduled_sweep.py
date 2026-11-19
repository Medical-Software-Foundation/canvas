"""Tests for the scheduled sweep, the unattended cron path.

Nobody watches this fire. It runs on a five minute cron and applies real task
and tag effects across every eligible patient with no review step in between,
so what it does today has to be pinned before anything about it changes.

execute() builds a Clock, a CanvasVisitSource, and calls the composition root
inline rather than accepting any of the three as arguments, so isolating it
means patching all three at the names this module imports them under. A fake
cron Event drives compute() the same way the SDK's own cron task tests do,
see canvas_sdk/tests/handlers/test_cron_task.py in the plugin SDK source.

Every fake below is duplicated rather than imported from another test module,
the established pattern in this suite, tests/test_core.py and
tests/test_install_stamp.py both carry their own copies of the fakes they
need rather than sharing one module across files.
"""

import datetime
import json
from typing import Any
from unittest.mock import patch

import arrow
import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import Event, EventRequest, EventType
from canvas_sdk.v1.data.task import Task, TaskStatus, TaskType

from attendance_policy_tracker.canvas.actions import TITLES, CanvasActions, task_id_for
from attendance_policy_tracker.canvas.tasks import CanvasTaskReader
from attendance_policy_tracker.core.clock import FixedClock
from attendance_policy_tracker.core.config import Config
from attendance_policy_tracker.core.engine import WARNING, Total
from attendance_policy_tracker.handlers.scheduled_sweep import (
    SWEEP_CURSOR_KEY,
    ScheduledSweep,
    _read_cursor,
)
from attendance_policy_tracker.sweep import (
    HOLDING_FLOOR_GRACE_MINUTES,
    LOOKBACK_MINUTES,
    RUN_JUDGEMENT_GRACE_MINUTES,
    Sweep,
)

NOW = arrow.get("2026-08-14T12:00:00+00:00")
PATIENT_ID = "6d5003d139024390b562179b3a7ab839"

# Patch target prefix, the module scheduled_sweep.py imports its three inline
# collaborators into, not the modules those collaborators are defined in.
MODULE = "attendance_policy_tracker.handlers.scheduled_sweep"


class FakeVisitSource:
    """Stands in for CanvasVisitSource, recording the since and the span it
    is asked about so a test can pin which window the sweep actually used.
    """

    def __init__(
        self,
        changed_ids: list[str] | None = None,
        moved_ids: list[str] | None = None,
    ) -> None:
        self._changed_ids = list(changed_ids or [])
        self._moved_ids = list(moved_ids or [])
        self.changes_since_calls: list[datetime.datetime] = []
        self.moves_between_calls: list[tuple[datetime.datetime, datetime.datetime]] = []

    def patients_with_changes_since(self, since: Any, states: Any) -> list[str]:
        self.changes_since_calls.append(since)
        return list(self._changed_ids)

    def patients_with_moves_between(self, start: Any, end: Any) -> list[str]:
        self.moves_between_calls.append((start, end))
        return list(self._moved_ids)


class FakeEngine:
    """A minimal engine, carrying only the two methods the sweep calls."""

    def __init__(
        self,
        runs: list[dict[str, Any]] | None = None,
        totals_by_patient: dict[str, Total] | None = None,
    ) -> None:
        self._runs = list(runs or [])
        self._totals = dict(totals_by_patient or {})
        self.runs_since_calls: list[datetime.datetime] = []
        self.total_for_calls: list[str] = []

    def runs_of_clinic_cancellations(self, since: datetime.datetime) -> list[dict[str, Any]]:
        self.runs_since_calls.append(since)
        return list(self._runs)

    def total_for(self, patient_id: str) -> Total:
        self.total_for_calls.append(patient_id)
        return self._totals.get(patient_id, Total(patient_id, 0, [], []))


class FakeActions:
    """A minimal actions collaborator, carrying only the two methods the
    sweep calls, each handing back a fixed, recognisable sentinel effect so
    a test can tell the two apart in whatever execute() returns.
    """

    def __init__(
        self,
        tag_effects: list[Any] | None = None,
        task_effects: list[Any] | None = None,
    ) -> None:
        self._tag_effects = list(tag_effects or [])
        self._task_effects = list(task_effects or [])
        self.tagged_runs: list[Any] = []
        self.tasked_totals: list[Total] = []

    def tag_runs(self, runs: list[dict[str, Any]]) -> list[Any]:
        self.tagged_runs.append(runs)
        return list(self._tag_effects)

    def tasks_for(self, total: Total) -> list[Any]:
        self.tasked_totals.append(total)
        return list(self._task_effects)


class FakeStore:
    """A settings store backed by a dictionary, the same shape
    tests/test_install_stamp.py already uses for the same reason.
    """

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(values or {})
        self.write_calls: list[dict[str, str]] = []

    def read(self) -> dict[str, str]:
        return dict(self.values)

    def write(self, values: dict[str, str]) -> None:
        self.write_calls.append(dict(values))
        for key, value in values.items():
            text = f"{value}".strip()
            if text:
                self.values[key] = text
            else:
                self.values.pop(key, None)


def make_cron_event(timestamp: str) -> Event:
    """A cron event carrying this timestamp as its target.

    The same shape the SDK's own cron task tests build, EventRequest with a
    CRON type and the timestamp as the target, wrapped in an Event.
    """
    request = EventRequest(type=EventType.CRON, target=timestamp)
    return Event(request)


def _parts(
    config: Config | None = None,
    engine: FakeEngine | None = None,
    actions: FakeActions | None = None,
    store: FakeStore | None = None,
) -> dict[str, Any]:
    """The mapping the real composition root would hand execute(), built
    from fakes instead so a test controls exactly what each collaborator
    does without touching a database.
    """
    return {
        "config": config if config is not None else Config(),
        "engine": engine if engine is not None else FakeEngine(),
        "actions": actions if actions is not None else FakeActions(),
        "store": store if store is not None else FakeStore(),
    }


class TestExecuteBuildsItsOwnCollaborators:
    """Pins execute() exactly as it behaves today, before any cursor or
    comparison guard change is made. Clock, CanvasVisitSource, and build are
    patched at the names this module imports them under, because execute()
    constructs all three inline rather than accepting them as arguments.
    """

    def test_calls_build_with_clock_and_source_but_no_store(self) -> None:
        """The divergence worth pinning. handlers/api.py builds its own
        NamespaceSettingsStore and passes it to build() explicitly, this
        path passes only clock and source and leaves store to build's own
        default. Both still resolve the same NamespaceSettingsStore, since
        that default is exactly what a passed store would have been, so the
        two paths read the same policy despite the different call. This
        test is what would catch it if that ever stopped being true.
        """
        fixed_clock = FixedClock(NOW.datetime)
        source = FakeVisitSource()

        with (
            patch(f"{MODULE}.Clock", return_value=fixed_clock) as clock_cls,
            patch(f"{MODULE}.CanvasVisitSource", return_value=source) as source_cls,
            patch(f"{MODULE}.build", return_value=_parts()) as build_fn,
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            handler.execute()

        clock_cls.assert_called_once_with()
        source_cls.assert_called_once_with()
        build_fn.assert_called_once_with(clock=fixed_clock, source=source)

    def test_returns_the_effects_the_sweep_produced(self) -> None:
        """execute() hands back exactly what the sweep earned, a run's tag
        effects followed by a total's task effects, nothing added and
        nothing dropped along the way.
        """
        actions = FakeActions(tag_effects=["tag-effect"], task_effects=["task-effect"])
        engine = FakeEngine(
            runs=[{"appointments": []}],
            totals_by_patient={PATIENT_ID: Total(PATIENT_ID, 5, [], [WARNING])},
        )
        source = FakeVisitSource(changed_ids=[PATIENT_ID])

        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=source),
            patch(f"{MODULE}.build", return_value=_parts(engine=engine, actions=actions)),
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            effects = handler.execute()

        assert effects == ["tag-effect", "task-effect"]
        assert engine.total_for_calls == [PATIENT_ID]

    def test_a_patient_below_every_line_earns_no_task_effect(self) -> None:
        """A recomputed patient who has not reached a line yet is still
        counted in the sweep, but never handed to tasks_for, matching the
        engine's own guard at sweep.py.
        """
        actions = FakeActions()
        engine = FakeEngine(totals_by_patient={PATIENT_ID: Total(PATIENT_ID, 1, [], [])})
        source = FakeVisitSource(changed_ids=[PATIENT_ID])

        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=source),
            patch(f"{MODULE}.build", return_value=_parts(engine=engine, actions=actions)),
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            effects = handler.execute()

        assert effects == []
        assert actions.tasked_totals == []


class TestCronScheduleGating:
    """compute() only ever calls execute() on a matching five minute mark,
    the same contract every CronTask carries, pinned here against this
    handler's own SCHEDULE rather than assumed from the SDK's own tests.
    """

    def test_a_matching_five_minute_mark_executes(self) -> None:
        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=FakeVisitSource()),
            patch(f"{MODULE}.build", return_value=_parts()) as build_fn,
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            result = handler.compute()

        assert result == []
        build_fn.assert_called_once()

    def test_a_non_matching_minute_never_builds_anything(self) -> None:
        with (
            patch(f"{MODULE}.Clock") as clock_cls,
            patch(f"{MODULE}.CanvasVisitSource") as source_cls,
            patch(f"{MODULE}.build") as build_fn,
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:06:00+00:00"))
            result = handler.compute()

        assert result == []
        clock_cls.assert_not_called()
        source_cls.assert_not_called()
        build_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Fix C1, the cursor. sweep.py:20 sets a fixed lookback and this handler ran
# it every five minutes with nothing narrowing it, so a patient whose state
# changed once was fully recomputed on every tick until the window aged it
# out. The tests below cover the pure parsing function first, then the
# comparison Sweep.run() itself makes, then the whole handler end to end.
# ---------------------------------------------------------------------------


class TestReadCursor:
    """_read_cursor hands the caller nothing at all in every case a stored
    value cannot be trusted, an absent key, unreadable text, or a moment
    that sits after this run's own now. Nothing is what lets the sweep fall
    back to its full lookback window rather than narrowing it on a cursor
    that might be wrong, the safer error next to a missed threshold crossing.
    """

    def test_an_absent_key_is_nothing(self) -> None:
        assert _read_cursor({}, NOW.datetime) is None

    def test_an_empty_value_is_nothing(self) -> None:
        assert _read_cursor({SWEEP_CURSOR_KEY: "   "}, NOW.datetime) is None

    def test_unreadable_text_is_nothing(self) -> None:
        assert _read_cursor({SWEEP_CURSOR_KEY: "not a moment"}, NOW.datetime) is None

    def test_a_future_dated_cursor_is_nothing(self) -> None:
        future = NOW.shift(minutes=5).isoformat()
        assert _read_cursor({SWEEP_CURSOR_KEY: future}, NOW.datetime) is None

    def test_a_past_moment_parses_and_normalises_to_utc(self) -> None:
        stored = NOW.shift(minutes=-5)
        parsed = _read_cursor({SWEEP_CURSOR_KEY: stored.isoformat()}, NOW.datetime)
        assert parsed == stored.to("utc").datetime

    def test_the_current_moment_itself_is_not_rejected_as_future(self) -> None:
        parsed = _read_cursor({SWEEP_CURSOR_KEY: NOW.isoformat()}, NOW.datetime)
        assert parsed == NOW.to("utc").datetime


def _sweep(
    config: Config | None = None,
    engine: FakeEngine | None = None,
    actions: FakeActions | None = None,
    source: FakeVisitSource | None = None,
    clock: FixedClock | None = None,
) -> Sweep:
    """A Sweep wired from fakes, the same shape execute() wires in production."""
    return Sweep(
        config=config if config is not None else Config(),
        engine=engine if engine is not None else FakeEngine(),
        actions=actions if actions is not None else FakeActions(),
        source=source if source is not None else FakeVisitSource(),
        clock=clock if clock is not None else FixedClock(NOW.datetime),
    )


class TestSinceFloorNarrowsOrWidensTheWindow:
    """Sweep.run() decides the query bound from three moments, the lookback
    floor, the since_floor a caller hands it, and the holding floor below
    which a cursor is never allowed to narrow. These tests call run()
    directly with an already validated moment, since_floor's validation is
    _read_cursor's job above, not this one's.
    """

    def test_a_cursor_never_narrows_past_the_holding_period(self) -> None:
        """The defect this floor exists for. A cursor from a healthy cadence
        names the last few minutes, and an incident recorded before it is
        still uncounted until its holding period ends. Maturing is not a
        change anybody records, so nothing puts that patient back in range and
        the threshold crossing is lost with the totals still reading right.
        """
        source = FakeVisitSource()
        config = Config()
        recent = NOW.shift(minutes=-5).datetime
        expected = NOW.shift(
            minutes=-(config.holding_window_minutes + HOLDING_FLOOR_GRACE_MINUTES)
        ).datetime

        _sweep(config=config, source=source).run(since_floor=recent)

        assert source.changes_since_calls == [expected]
        assert source.moves_between_calls == [(expected, NOW.datetime)]

    def test_an_incident_recorded_before_the_cursor_is_in_range_when_it_matures(self) -> None:
        """The same rule stated as the thing that goes wrong rather than as
        an arithmetic result. An incident recorded one holding period ago
        starts counting now, and the sweep running now has to be able to see
        it however recently the cursor was written.
        """
        source = FakeVisitSource()
        config = Config()
        recorded = NOW.shift(minutes=-config.holding_window_minutes).datetime
        cursor = NOW.shift(minutes=-1).datetime

        _sweep(config=config, source=source).run(since_floor=cursor)

        assert source.changes_since_calls[0] <= recorded

    def test_a_cursor_already_wider_than_the_holding_floor_is_honoured(self) -> None:
        """The floor is a bound on how far a cursor may narrow, not a
        replacement for it. A cursor that already reaches further back than
        the holding period still narrows the window to itself.
        """
        source = FakeVisitSource()
        older = NOW.shift(minutes=-60).datetime

        _sweep(source=source).run(since_floor=older)

        assert source.changes_since_calls == [older]

    def test_a_since_floor_older_than_the_lookback_floor_never_narrows_it(self) -> None:
        source = FakeVisitSource()
        stale = NOW.shift(minutes=-(LOOKBACK_MINUTES + 200)).datetime
        expected_floor = NOW.shift(minutes=-LOOKBACK_MINUTES).datetime

        _sweep(source=source).run(since_floor=stale)

        assert source.changes_since_calls == [expected_floor]

    def test_no_since_floor_falls_back_to_the_plain_lookback_exactly_as_before(self) -> None:
        source = FakeVisitSource()
        expected_floor = NOW.shift(minutes=-LOOKBACK_MINUTES).datetime

        _sweep(source=source).run()

        assert source.changes_since_calls == [expected_floor]

    def test_the_run_judgement_window_never_reads_since_floor(self) -> None:
        """The run judgement span is its own narrow window, unrelated to the
        wide lookback the cursor narrows, see RUN_JUDGEMENT_GRACE_MINUTES in
        sweep.py. A cursor must never touch it.
        """
        engine = FakeEngine()
        recent = NOW.shift(minutes=-5).datetime
        config = Config()
        expected_run_since = NOW.shift(
            minutes=-(config.run_window_minutes + RUN_JUDGEMENT_GRACE_MINUTES)
        ).datetime

        _sweep(config=config, engine=engine).run(since_floor=recent)

        assert engine.runs_since_calls == [expected_run_since]


class TestExecutePersistsCursorOnlyOnSuccess:
    """The end to end handler path, cursor read before the sweep runs and
    written back only once it has actually finished without raising.
    """

    def test_a_fresh_store_runs_the_full_lookback_then_writes_a_cursor(self) -> None:
        store = FakeStore()
        source = FakeVisitSource()

        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=source),
            patch(f"{MODULE}.build", return_value=_parts(store=store)),
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            handler.execute()

        assert source.changes_since_calls == [NOW.shift(minutes=-LOOKBACK_MINUTES).datetime]
        assert store.values[SWEEP_CURSOR_KEY] == arrow.get(NOW.datetime).to("utc").isoformat()

    def test_a_recent_stored_cursor_narrows_only_as_far_as_the_holding_floor(self) -> None:
        """A cursor written five minutes ago does narrow the window, but not
        to itself. It stops at the holding floor, so an incident recorded
        before the cursor is still found on the tick where it starts counting.
        """
        earlier = NOW.shift(minutes=-5)
        store = FakeStore({SWEEP_CURSOR_KEY: earlier.isoformat()})
        source = FakeVisitSource()
        config = Config()
        expected = NOW.shift(
            minutes=-(config.holding_window_minutes + HOLDING_FLOOR_GRACE_MINUTES)
        ).datetime

        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=source),
            patch(f"{MODULE}.build", return_value=_parts(store=store, config=config)),
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            handler.execute()

        assert source.changes_since_calls == [expected]
        assert expected < earlier.to("utc").datetime
        assert store.values[SWEEP_CURSOR_KEY] == arrow.get(NOW.datetime).to("utc").isoformat()

    def test_a_corrupt_stored_cursor_falls_back_to_the_full_lookback(self) -> None:
        store = FakeStore({SWEEP_CURSOR_KEY: "not a moment at all"})
        source = FakeVisitSource()

        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=source),
            patch(f"{MODULE}.build", return_value=_parts(store=store)),
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            handler.execute()

        assert source.changes_since_calls == [NOW.shift(minutes=-LOOKBACK_MINUTES).datetime]
        # The corrupt value is overwritten by this run's own successful cursor.
        assert store.values[SWEEP_CURSOR_KEY] == arrow.get(NOW.datetime).to("utc").isoformat()

    def test_a_future_dated_stored_cursor_falls_back_to_the_full_lookback(self) -> None:
        future = NOW.shift(minutes=10)
        store = FakeStore({SWEEP_CURSOR_KEY: future.isoformat()})
        source = FakeVisitSource()

        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=source),
            patch(f"{MODULE}.build", return_value=_parts(store=store)),
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            handler.execute()

        assert source.changes_since_calls == [NOW.shift(minutes=-LOOKBACK_MINUTES).datetime]

    def test_a_run_that_raises_never_advances_the_cursor(self) -> None:
        class ExplodingEngine(FakeEngine):
            def runs_of_clinic_cancellations(self, since: datetime.datetime) -> list[Any]:
                raise RuntimeError("boom")

        standing_cursor = NOW.shift(minutes=-5).isoformat()
        store = FakeStore({SWEEP_CURSOR_KEY: standing_cursor})

        with (
            patch(f"{MODULE}.Clock", return_value=FixedClock(NOW.datetime)),
            patch(f"{MODULE}.CanvasVisitSource", return_value=FakeVisitSource()),
            patch(
                f"{MODULE}.build",
                return_value=_parts(engine=ExplodingEngine(), store=store),
            ),
        ):
            handler = ScheduledSweep(make_cron_event("2026-08-14T12:05:00+00:00"))
            with pytest.raises(RuntimeError):
                handler.execute()

        # No write was ever attempted, so the window this run never covered
        # is picked up again by the next tick rather than skipped.
        assert store.write_calls == []
        assert store.values[SWEEP_CURSOR_KEY] == standing_cursor


# ---------------------------------------------------------------------------
# Fix C2, the comparison guard. canvas/actions.py built a fresh title and
# wrote an update on every tick that recomputed an already open task, whether
# or not the count had actually moved. The tests below cover the guard in
# canvas/actions.py directly, plus the reader it depends on in
# canvas/tasks.py against a real Task row.
# ---------------------------------------------------------------------------


class RichFakeTaskReader:
    """The newer two question contract, status_of and title_of together,
    the shape canvas/tasks.py's CanvasTaskReader carries in production.
    """

    def __init__(
        self,
        statuses: dict[str, str] | None = None,
        titles: dict[str, str] | None = None,
    ) -> None:
        self._statuses = dict(statuses or {})
        self._titles = dict(titles or {})
        self.title_asked: list[Any] = []

    def status_of(self, task_id: Any) -> str | None:
        return self._statuses.get(f"{task_id}")

    def title_of(self, task_id: Any) -> str | None:
        self.title_asked.append(task_id)
        return self._titles.get(f"{task_id}")


class TestTaskForSkipsRedundantUpdates:
    def _config(self) -> Config:
        return Config({"warning_team_id": "team-1"})

    def test_a_matching_stored_title_earns_no_update_effect(self) -> None:
        task_id = task_id_for(PATIENT_ID, WARNING)
        fresh_title = f"{TITLES[WARNING]}, 5 counted visits in the counting window"
        reader = RichFakeTaskReader(
            statuses={f"{task_id}": "OPEN"},
            titles={f"{task_id}": fresh_title},
        )
        actions = CanvasActions(self._config(), reader)

        effect = actions.task_for(PATIENT_ID, WARNING, 5)

        assert effect is None
        assert reader.title_asked == [task_id]

    def test_a_changed_stored_title_still_updates(self) -> None:
        task_id = task_id_for(PATIENT_ID, WARNING)
        reader = RichFakeTaskReader(
            statuses={f"{task_id}": "OPEN"},
            titles={f"{task_id}": "a stale title from an earlier count"},
        )
        actions = CanvasActions(self._config(), reader)

        effect = actions.task_for(PATIENT_ID, WARNING, 9)

        assert effect is not None
        assert effect.type == EffectType.UPDATE_TASK
        payload = json.loads(effect.payload)["data"]
        assert "9 counted visits" in payload["title"]

    def test_title_of_is_never_consulted_on_a_first_evaluation(self) -> None:
        reader = RichFakeTaskReader()
        actions = CanvasActions(self._config(), reader)

        effect = actions.task_for(PATIENT_ID, WARNING, 3)

        assert effect is not None
        assert effect.type == EffectType.CREATE_TASK
        assert reader.title_asked == []

    def test_title_of_is_never_consulted_on_a_settled_task(self) -> None:
        task_id = task_id_for(PATIENT_ID, WARNING)
        reader = RichFakeTaskReader(statuses={f"{task_id}": "COMPLETED"})
        actions = CanvasActions(self._config(), reader)

        effect = actions.task_for(PATIENT_ID, WARNING, 3)

        assert effect is None
        assert reader.title_asked == []


class TestCanvasTaskReaderAgainstARealTask:
    """canvas/tasks.py's own reader, exercised against a real Task row
    rather than a fake, so the query and field shape underneath status_of
    and title_of are covered too, not only the contract they carry.
    """

    def test_no_task_at_an_identifier_answers_nothing_for_both_questions(
        self, db: None
    ) -> None:
        reader = CanvasTaskReader()
        missing_id = task_id_for(PATIENT_ID, WARNING)

        assert reader.status_of(missing_id) is None
        assert reader.title_of(missing_id) is None

    def test_an_existing_task_answers_its_stored_status_and_title(self, db: None) -> None:
        task_id = task_id_for(PATIENT_ID, WARNING)
        Task.objects.create(
            id=task_id,
            task_type=TaskType.TASK,
            tag="attendance-policy-tracker",
            title="Attendance policy, patient has reached the warning threshold",
            status=TaskStatus.OPEN,
        )

        reader = CanvasTaskReader()

        assert reader.status_of(task_id) == "OPEN"
        assert (
            reader.title_of(task_id)
            == "Attendance policy, patient has reached the warning threshold"
        )
