"""Tests for the counting core.

Everything here runs without a Canvas instance, because the engine, the
detectors and the attribution chain depend only on plain values and injected
collaborators. The Canvas facing adapter is tested separately.
"""

import json

import arrow
import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.v1.data.appointment import Appointment

from attendance_policy_tracker.canvas.actions import CanvasActions, task_id_for
from attendance_policy_tracker.core.attribution import (
    AttributionChain,
    ClinicTagRule,
    ConfiguredDefaultRule,
    NoShowRule,
    PatientPortalRule,
)
from attendance_policy_tracker.core.clock import FixedClock
from attendance_policy_tracker.core.config import (
    KIND_LATE_CANCELLATION,
    KIND_LATE_MOVE,
    KIND_NO_SHOW,
    Config,
    ConfigError,
)
from attendance_policy_tracker.core.contracts import CLINIC, PATIENT
from attendance_policy_tracker.core.detectors import (
    LateCancellationDetector,
    LateMoveDetector,
    NoShowDetector,
)
from attendance_policy_tracker.core.engine import (
    DISCHARGE_REVIEW,
    WARNING,
    AttendanceEngine,
)
from attendance_policy_tracker.core.history import AppointmentHistory, Transition
from attendance_policy_tracker.sweep import LOOKBACK_MINUTES, RUN_JUDGEMENT_GRACE_MINUTES, Sweep

NOW = arrow.get("2026-08-14T12:00:00+00:00")
PATIENT_ID = "6d5003d139024390b562179b3a7ab839"
PROVIDER_ID = "19bc00bba542430a8e15ad41f4ed8005"

CANCELLED = ("CLD",)
NO_SHOW = ("NSW",)
REVERTED = ("RVT",)


class FakeSource:
    """Hands the engine whatever histories a test wants.

    changed_ids and moved_ids stand in for the two families of discovery
    query the real adapter runs, the state watching kind and the reschedule
    link kind. Both default to empty, so a test that never mentions discovery
    at all, which is most of them, is unaffected by their presence.
    """

    def __init__(self, histories=None, cancellations=None, changed_ids=None, moved_ids=None):
        self._histories = list(histories or [])
        self._cancellations = list(cancellations or [])
        self._changed_ids = list(changed_ids or [])
        self._moved_ids = list(moved_ids or [])
        self.calls = 0
        # The since a caller passed each time, recorded so a test can pin
        # which lookback the run judgement used and which the wide patient
        # discovery used, without the two being confused for one another.
        self.recent_cancellations_since_calls = []
        self.patients_with_changes_since_calls = []

    def histories_for(self, patient_id):
        self.calls = self.calls + 1
        return [h for h in self._histories if h.patient_id == patient_id]

    def recent_cancellations(self, since):
        self.recent_cancellations_since_calls.append(since)
        return list(self._cancellations)

    def patients_with_changes_between(self, start, end, states):
        return list(self._changed_ids)

    def patients_with_changes_since(self, since, states):
        self.patients_with_changes_since_calls.append(since)
        return list(self._changed_ids)

    def patients_with_moves_between(self, start, end):
        return list(self._moved_ids)


class FakeTaskReader:
    """Stands in for CanvasTaskReader with a mapping a test controls directly.

    Every identifier task_for asks about is recorded, so a test can assert not
    only what came back but whether the reader was consulted at all.
    """

    def __init__(self, statuses=None, titles=None):
        self._statuses = dict(statuses or {})
        self._titles = dict(titles or {})
        self.asked = []

    def status_of(self, task_id):
        self.asked.append(task_id)
        return self._statuses.get(f"{task_id}")

    def title_of(self, task_id):
        return self._titles.get(f"{task_id}")


def history(
    appointment_id="a1",
    start_offset_days=-3,
    transitions=None,
    labels=None,
    replacement_id=None,
    moved_offset_hours=None,
    moved_by_patient=False,
    patient_id=PATIENT_ID,
):
    """An appointment history positioned relative to the fixed now."""
    start = NOW.shift(days=start_offset_days)
    moved_at = None
    if moved_offset_hours is not None:
        moved_at = start.shift(hours=-moved_offset_hours).datetime
    return AppointmentHistory(
        appointment_id=appointment_id,
        patient_id=patient_id,
        provider_id=PROVIDER_ID,
        start_time=start.datetime,
        transitions=transitions or [],
        labels=labels or [],
        replacement_id=replacement_id,
        moved_at=moved_at,
        moved_by_patient=moved_by_patient,
    )


def transition(state, hours_before_start, start_offset_days=-3, by_patient=False):
    """A transition positioned relative to its appointment's start."""
    start = NOW.shift(days=start_offset_days)
    return Transition(
        state=state,
        occurred_at=start.shift(hours=-hours_before_start).datetime,
        by_patient=by_patient,
    )


def _wire(source, overrides=None):
    """The engine, its config and its clock, wired the same way the plugin wires them.

    Shared behind build_engine and build_sweep, so the two compositions can
    never quietly drift from one another.
    """
    config = Config(overrides)
    clock = FixedClock(NOW.datetime)
    detectors = [
        NoShowDetector(NO_SHOW, REVERTED),
        LateMoveDetector(clock, config.move_boundary_hours),
        LateCancellationDetector(clock, config.late_cutoff_hours, CANCELLED, REVERTED),
    ]
    chain = AttributionChain(
        [
            NoShowRule(),
            PatientPortalRule(),
            ClinicTagRule(config.clinic_tag),
            ConfiguredDefaultRule(config.default_attribution),
        ]
    )
    engine = AttendanceEngine(config, source, detectors, chain, clock, CANCELLED)
    return engine, config, clock


def build_engine(source, overrides=None):
    """The composition the tests exercise, wired the same way the plugin wires it."""
    engine, _config, _clock = _wire(source, overrides)
    return engine


def build_sweep(source, overrides=None, task_reader=None):
    """The sweep composition the tests exercise, wired the same way run() is.

    Defaults to an empty fake reader, so every test that never mentions a
    task's prior state behaves exactly as if nothing had ever been raised
    before, which is what the whole suite assumed before the reader existed.
    """
    engine, config, clock = _wire(source, overrides)
    actions = CanvasActions(config, task_reader or FakeTaskReader())
    return Sweep(config, engine, actions, source, clock)


class TestConfig:
    def test_ships_the_stated_defaults(self):
        config = Config()
        assert config.late_cutoff_hours == 24
        assert config.move_boundary_hours == 24
        assert config.warning_line == 3
        assert config.discharge_review_line == 5
        assert config.counting_window_months == 12
        assert config.holding_window_minutes == 15
        assert config.run_count == 3
        assert config.run_window_minutes == 15
        assert config.default_attribution == PATIENT
        assert config.clinic_tag == "clinic-cancelled"

    def test_refuses_a_review_line_at_or_below_the_warning_line(self):
        with pytest.raises(ConfigError):
            Config({"warning_line": 5, "discharge_review_line": 5})
        with pytest.raises(ConfigError):
            Config({"warning_line": 6, "discharge_review_line": 5})

    def test_refuses_an_unknown_default_attribution(self):
        with pytest.raises(ConfigError):
            Config({"default_attribution": "nobody"})

    def test_refuses_an_unknown_counted_kind(self):
        with pytest.raises(ConfigError):
            Config({"counted_kinds": ["not_a_kind"]})

    def test_blank_override_falls_back_to_the_default(self):
        config = Config({"warning_line": "", "late_cutoff_hours": None})
        assert config.warning_line == 3
        assert config.late_cutoff_hours == 24

    def test_a_negative_bounded_value_is_refused(self):
        with pytest.raises(ConfigError):
            Config({"run_count": -1})

    def test_an_unresolved_attribute_raises_rather_than_returning_nothing(self):
        with pytest.raises(AttributeError):
            Config().this_setting_does_not_exist

    def test_the_review_team_and_labels_are_reachable_by_line_name(self):
        config = Config(
            {
                "warning_team_id": "team-warn",
                "discharge_review_team_id": "team-review",
                "warning_task_labels": ["urgent"],
                "discharge_review_task_labels": ["chart-review"],
            }
        )
        assert config.team_for(DISCHARGE_REVIEW) == "team-review"
        assert config.labels_for(DISCHARGE_REVIEW) == ["chart-review"]

    def test_an_unrecognised_line_name_earns_no_team_and_no_labels(self):
        config = Config({"warning_team_id": "team-warn"})
        assert config.team_for("not_a_real_line") == ""
        assert config.labels_for("not_a_real_line") == []


class TestAttributionChain:
    def _chain(self, default=PATIENT):
        return AttributionChain(
            [
                NoShowRule(),
                PatientPortalRule(),
                ClinicTagRule("clinic-cancelled"),
                ConfiguredDefaultRule(default),
            ]
        )

    def test_a_no_show_counts_against_the_patient_even_when_tagged(self):
        from attendance_policy_tracker.core.contracts import Incident

        incident = Incident(
            "a1", PATIENT_ID, KIND_NO_SHOW, NOW.datetime, NOW.datetime, PROVIDER_ID,
            labels=["clinic-cancelled"],
        )
        self._chain().apply(incident)
        assert incident.attribution == PATIENT

    def test_a_portal_cancellation_beats_a_clinic_default(self):
        from attendance_policy_tracker.core.contracts import Incident

        incident = Incident(
            "a1", PATIENT_ID, KIND_LATE_CANCELLATION, NOW.datetime, NOW.datetime,
            PROVIDER_ID, by_patient_portal=True,
        )
        self._chain(default=CLINIC).apply(incident)
        assert incident.attribution == PATIENT

    def test_a_tagged_staff_cancellation_counts_against_the_clinic(self):
        from attendance_policy_tracker.core.contracts import Incident

        incident = Incident(
            "a1", PATIENT_ID, KIND_LATE_CANCELLATION, NOW.datetime, NOW.datetime,
            PROVIDER_ID, labels=["clinic-cancelled"],
        )
        self._chain().apply(incident)
        assert incident.attribution == CLINIC

    def test_an_untagged_staff_cancellation_falls_to_the_default(self):
        from attendance_policy_tracker.core.contracts import Incident

        incident = Incident(
            "a1", PATIENT_ID, KIND_LATE_CANCELLATION, NOW.datetime, NOW.datetime, PROVIDER_ID
        )
        self._chain().apply(incident)
        assert incident.attribution == PATIENT

    def test_a_chain_with_no_claiming_rule_is_loud(self):
        from attendance_policy_tracker.core.contracts import Incident

        chain = AttributionChain([PatientPortalRule()])
        incident = Incident(
            "a1", PATIENT_ID, KIND_LATE_CANCELLATION, NOW.datetime, NOW.datetime, PROVIDER_ID
        )
        with pytest.raises(RuntimeError):
            chain.apply(incident)

    def test_an_empty_chain_is_refused(self):
        with pytest.raises(ValueError):
            AttributionChain([])


class TestCounting:
    def test_a_late_cancellation_counts_once(self):
        source = FakeSource([history(transitions=[transition("CLD", 2)])])
        total = build_engine(source).total_for(PATIENT_ID)
        assert total.count == 1
        assert total.incidents[0].kind == KIND_LATE_CANCELLATION

    def test_an_early_cancellation_does_not_count(self):
        source = FakeSource([history(transitions=[transition("CLD", 72)])])
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_the_cutoff_boundary_excludes_a_cancellation_exactly_on_it(self):
        source = FakeSource([history(transitions=[transition("CLD", 24)])])
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_a_no_show_counts(self):
        source = FakeSource([history(transitions=[transition("NSW", 0)])])
        total = build_engine(source).total_for(PATIENT_ID)
        assert total.count == 1
        assert total.incidents[0].kind == KIND_NO_SHOW

    def test_one_appointment_contributes_at_most_one_incident(self):
        # An append only history carrying both a no show and a cancellation.
        source = FakeSource(
            [history(transitions=[transition("NSW", 0), transition("CLD", 1)])]
        )
        total = build_engine(source).total_for(PATIENT_ID)
        assert total.count == 1

    def test_a_late_move_counts_and_is_not_also_a_cancellation(self):
        # A moved appointment carries a booking rather than a cancellation, and
        # the move detector runs first, so the visit yields exactly one incident.
        source = FakeSource(
            [
                history(
                    transitions=[transition("BKD", 2)],
                    replacement_id="a2",
                    moved_offset_hours=2,
                )
            ]
        )
        total = build_engine(source).total_for(PATIENT_ID)
        assert total.count == 1
        assert total.incidents[0].kind == KIND_LATE_MOVE

    def test_an_early_move_counts_nothing(self):
        source = FakeSource(
            [
                history(
                    transitions=[transition("BKD", 72)],
                    replacement_id="a2",
                    moved_offset_hours=72,
                )
            ]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_a_late_move_is_measured_against_the_slot_it_gave_up(self):
        # Moved two hours before the original slot, into a slot three weeks out.
        # Measuring against the new slot would make this look early and miss it.
        original = NOW.shift(days=-3)
        source = FakeSource(
            [
                AppointmentHistory(
                    appointment_id="a1",
                    patient_id=PATIENT_ID,
                    provider_id=PROVIDER_ID,
                    start_time=NOW.shift(days=18).datetime,
                    original_start=original.datetime,
                    transitions=[Transition("BKD", original.shift(hours=-2).datetime)],
                    replacement_id="a2",
                    moved_at=original.shift(hours=-2).datetime,
                )
            ]
        )
        total = build_engine(source).total_for(PATIENT_ID)
        assert total.count == 1
        assert total.incidents[0].kind == KIND_LATE_MOVE
        # Anchored to the slot given up, so the counting window sees the right date.
        assert total.incidents[0].anchor == original.datetime

    def test_a_tag_carried_onto_a_replacement_does_not_count_twice(self):
        # Both the original and its replacement carry the tag, which is what the
        # platform actually does, and the replacement has no incident of its own.
        original = history(
            appointment_id="a1",
            transitions=[transition("BKD", 2)],
            labels=["clinic-cancelled"],
            replacement_id="a2",
            moved_offset_hours=2,
        )
        replacement = history(
            appointment_id="a2",
            start_offset_days=-1,
            transitions=[transition("SCH", 48, start_offset_days=-1)],
            labels=["clinic-cancelled"],
        )
        source = FakeSource([original, replacement])
        total = build_engine(source).total_for(PATIENT_ID)
        # The move is the clinic's because the tag says so, so nothing counts.
        assert total.count == 0

    def test_a_clinic_tagged_cancellation_is_excluded(self):
        source = FakeSource(
            [history(transitions=[transition("CLD", 2)], labels=["clinic-cancelled"])]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_a_portal_cancellation_counts_even_when_the_default_is_the_clinic(self):
        source = FakeSource(
            [history(transitions=[transition("CLD", 2, by_patient=True)])]
        )
        engine = build_engine(source, {"default_attribution": CLINIC})
        assert engine.total_for(PATIENT_ID).count == 1

    def test_an_incident_outside_the_counting_window_does_not_count(self):
        source = FakeSource(
            [
                history(
                    start_offset_days=-400,
                    transitions=[transition("CLD", 2, start_offset_days=-400)],
                )
            ]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_the_anchor_is_the_appointment_start_not_the_state_change(self):
        # A visit that sat outside the window is not dragged back in by being
        # cancelled recently.
        old_start = NOW.shift(days=-400)
        source = FakeSource(
            [
                AppointmentHistory(
                    appointment_id="a1",
                    patient_id=PATIENT_ID,
                    provider_id=PROVIDER_ID,
                    start_time=old_start.datetime,
                    transitions=[
                        Transition("CLD", NOW.shift(days=-1).datetime),
                    ],
                )
            ]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_an_incident_inside_the_holding_window_is_not_visible_yet(self):
        recent = NOW.shift(minutes=-5)
        source = FakeSource(
            [
                AppointmentHistory(
                    appointment_id="a1",
                    patient_id=PATIENT_ID,
                    provider_id=PROVIDER_ID,
                    start_time=NOW.shift(hours=2).datetime,
                    transitions=[Transition("CLD", recent.datetime)],
                )
            ]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_the_same_incident_becomes_visible_once_the_holding_window_passes(self):
        settled = NOW.shift(minutes=-30)
        source = FakeSource(
            [
                AppointmentHistory(
                    appointment_id="a1",
                    patient_id=PATIENT_ID,
                    provider_id=PROVIDER_ID,
                    start_time=NOW.shift(hours=-2).datetime,
                    transitions=[Transition("CLD", settled.datetime)],
                )
            ]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 1

    def test_a_switched_off_kind_stops_counting(self):
        source = FakeSource([history(transitions=[transition("NSW", 0)])])
        engine = build_engine(
            source, {"counted_kinds": [KIND_LATE_CANCELLATION, KIND_LATE_MOVE]}
        )
        assert engine.total_for(PATIENT_ID).count == 0

    def test_a_patient_with_no_history_totals_zero(self):
        assert build_engine(FakeSource([])).total_for(PATIENT_ID).count == 0

    def test_nothing_is_stored_between_reads(self):
        source = FakeSource([history(transitions=[transition("CLD", 2)])])
        engine = build_engine(source)
        first = engine.total_for(PATIENT_ID)
        second = engine.total_for(PATIENT_ID)
        assert first.count == second.count == 1
        # Two reads means two trips to history, which is what recompute means.
        assert source.calls == 2


class TestInstallFloor:
    """Clinical history predating the plugin is not counted against anybody."""

    def test_an_incident_before_the_floor_is_excluded_and_one_after_it_counts(self):
        floor = NOW.shift(days=-30).datetime
        before = history(
            appointment_id="a1",
            start_offset_days=-60,
            transitions=[transition("CLD", 2, start_offset_days=-60)],
        )
        after = history(
            appointment_id="a2",
            start_offset_days=-10,
            transitions=[transition("CLD", 2, start_offset_days=-10)],
        )
        engine = build_engine(FakeSource([before, after]), {"install_floor": floor})
        total = engine.total_for(PATIENT_ID)
        assert total.count == 1
        assert total.incidents[0].appointment_id == "a2"

    def test_a_missing_floor_counts_everything_exactly_as_before(self):
        # Old enough that any plausible floor would exclude it, but with no
        # override standing the engine behaves exactly as it always has.
        source = FakeSource(
            [
                history(
                    start_offset_days=-300,
                    transitions=[transition("CLD", 2, start_offset_days=-300)],
                )
            ]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 1


class TestReversal:
    """Restore on a note writes a reversal, which undoes what it followed."""

    def test_a_reverted_no_show_produces_no_incident(self):
        source = FakeSource(
            [history(transitions=[transition("NSW", 2), transition("RVT", 1)])]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_a_reverted_cancellation_produces_no_incident(self):
        source = FakeSource(
            [history(transitions=[transition("CLD", 2), transition("RVT", 1)])]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0

    def test_cancel_restore_cancel_again_counts_the_second_cancellation(self):
        # The reversal sits between the two cancellations. Positional scanning
        # is what lets the second cancellation still be found, a plain search
        # for any reversal anywhere would wrongly clear it too.
        second_cancellation = transition("CLD", 1)
        source = FakeSource(
            [
                history(
                    transitions=[
                        transition("CLD", 5),
                        transition("RVT", 3),
                        second_cancellation,
                    ]
                )
            ]
        )
        total = build_engine(source).total_for(PATIENT_ID)
        assert total.count == 1
        assert total.incidents[0].occurred_at == second_cancellation.occurred_at

    def test_a_reversal_before_the_matched_transition_does_not_remove_it(self):
        # The reversal happened first, well before the cancellation it could
        # never have undone, so the cancellation stands.
        source = FakeSource(
            [history(transitions=[transition("RVT", 5), transition("CLD", 2)])]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 1

    def test_a_reverted_transition_neither_detector_watches_changes_nothing(self):
        # Check in is not a state either detector watches, so reverting it has
        # nothing to undo and the visit still counts for nothing.
        source = FakeSource(
            [history(transitions=[transition("CIN", 2), transition("RVT", 1)])]
        )
        assert build_engine(source).total_for(PATIENT_ID).count == 0


class TestLines:
    def _engine_with(self, count):
        histories = [
            history(appointment_id=f"a{index}", transitions=[transition("CLD", 2)])
            for index in range(count)
        ]
        return build_engine(FakeSource(histories))

    def test_below_the_warning_line_reaches_nothing(self):
        assert self._engine_with(2).total_for(PATIENT_ID).lines_reached == []

    def test_at_the_warning_line_reaches_the_warning(self):
        total = self._engine_with(3).total_for(PATIENT_ID)
        assert total.lines_reached == [WARNING]
        assert total.reaches(WARNING)
        assert not total.reaches(DISCHARGE_REVIEW)

    def test_past_the_warning_line_still_reaches_only_the_warning(self):
        assert self._engine_with(4).total_for(PATIENT_ID).lines_reached == [WARNING]

    def test_at_the_review_line_reaches_both(self):
        total = self._engine_with(5).total_for(PATIENT_ID)
        assert total.lines_reached == [WARNING, DISCHARGE_REVIEW]

    def test_a_total_that_clears_both_lines_at_once_reports_both(self):
        total = self._engine_with(9).total_for(PATIENT_ID)
        assert total.reaches(WARNING)
        assert total.reaches(DISCHARGE_REVIEW)


class TestTaskFor:
    """CanvasActions.task_for reads the task reader before deciding what to
    emit, so a line stays raised once without ever being raised twice.
    """

    def _config(self):
        return Config({"warning_team_id": "team-1"})

    def test_a_first_evaluation_creates_the_task(self):
        reader = FakeTaskReader()
        actions = CanvasActions(self._config(), reader)

        effect = actions.task_for(PATIENT_ID, WARNING, 3)

        assert effect is not None
        assert effect.type == EffectType.CREATE_TASK
        payload = json.loads(effect.payload)["data"]
        assert payload["id"] == str(task_id_for(PATIENT_ID, WARNING))

    def test_a_second_evaluation_updates_rather_than_creates(self):
        task_id = task_id_for(PATIENT_ID, WARNING)
        reader = FakeTaskReader({f"{task_id}": "OPEN"})
        actions = CanvasActions(self._config(), reader)

        effect = actions.task_for(PATIENT_ID, WARNING, 5)

        assert effect is not None
        assert effect.type == EffectType.UPDATE_TASK
        payload = json.loads(effect.payload)["data"]
        assert payload["id"] == str(task_id)
        assert "5 counted visits" in payload["title"]

    def test_a_settled_task_is_never_recreated(self):
        task_id = task_id_for(PATIENT_ID, WARNING)

        completed = FakeTaskReader({f"{task_id}": "COMPLETED"})
        assert CanvasActions(self._config(), completed).task_for(
            PATIENT_ID, WARNING, 4
        ) is None

        closed = FakeTaskReader({f"{task_id}": "CLOSED"})
        assert CanvasActions(self._config(), closed).task_for(
            PATIENT_ID, WARNING, 4
        ) is None

    def test_a_line_with_no_team_configured_raises_nothing_and_is_never_read(self):
        reader = FakeTaskReader()
        actions = CanvasActions(Config(), reader)

        effect = actions.task_for(PATIENT_ID, WARNING, 3)

        assert effect is None
        assert reader.asked == []


class TestRunRule:
    def test_a_run_of_cancellations_against_one_provider_is_found(self):
        base = NOW.shift(hours=-2)
        histories = []
        for index in range(3):
            histories.append(
                AppointmentHistory(
                    appointment_id=f"a{index}",
                    patient_id=f"p{index}",
                    provider_id=PROVIDER_ID,
                    start_time=NOW.shift(days=2).datetime,
                    transitions=[Transition("CLD", base.shift(minutes=index * 2).datetime)],
                )
            )
        engine = build_engine(FakeSource(cancellations=histories))
        runs = engine.runs_of_clinic_cancellations(base.shift(hours=-1).datetime)
        assert len(runs) == 1
        assert runs[0]["provider_id"] == PROVIDER_ID
        assert len(runs[0]["appointments"]) == 3

    def test_cancellations_spread_wider_than_the_window_are_not_a_run(self):
        base = NOW.shift(hours=-5)
        histories = []
        for index in range(3):
            histories.append(
                AppointmentHistory(
                    appointment_id=f"a{index}",
                    patient_id=f"p{index}",
                    provider_id=PROVIDER_ID,
                    start_time=NOW.shift(days=2).datetime,
                    transitions=[Transition("CLD", base.shift(minutes=index * 30).datetime)],
                )
            )
        engine = build_engine(FakeSource(cancellations=histories))
        assert engine.runs_of_clinic_cancellations(base.shift(hours=-1).datetime) == []

    def test_two_cancellations_are_below_the_run_count(self):
        base = NOW.shift(hours=-2)
        histories = []
        for index in range(2):
            histories.append(
                AppointmentHistory(
                    appointment_id=f"a{index}",
                    patient_id=f"p{index}",
                    provider_id=PROVIDER_ID,
                    start_time=NOW.shift(days=2).datetime,
                    transitions=[Transition("CLD", base.shift(minutes=index).datetime)],
                )
            )
        engine = build_engine(FakeSource(cancellations=histories))
        assert engine.runs_of_clinic_cancellations(base.shift(hours=-1).datetime) == []


class TestSweepFindsPatientsThroughMovesAlone:
    """A reschedule writes a booked event rather than a cancellation, so the
    state watching discovery the sweep already ran never sees a move. The fix
    adds a second discovery path through the reschedule link, unioned beside
    the first rather than replacing it.
    """

    def _moved_history(self, appointment_id):
        # Moved two hours before the slot it gave up, well inside the default
        # twenty four hour boundary, so every one of these earns an incident.
        return history(
            appointment_id=appointment_id,
            transitions=[transition("BKD", 2)],
            replacement_id=f"{appointment_id}-b",
            moved_offset_hours=2,
        )

    def test_a_patient_crossing_the_warning_line_through_moves_alone_earns_the_task(self):
        # The default warning line is three, and discovery here runs only
        # through patients_with_moves_between, patients_with_changes_since
        # returns nobody.
        histories = [self._moved_history(f"a{index}") for index in range(3)]
        source = FakeSource(histories, moved_ids=[PATIENT_ID])
        sweep = build_sweep(source, {"warning_team_id": "team-1"})

        result = sweep.run()

        assert result["swept"] == 1
        assert len(result["effects"]) == 1

    def test_a_move_outside_the_boundary_earns_no_task_from_the_sweep(self):
        # Discovery still finds the patient through the reschedule link, but a
        # move well outside the boundary earns no incident, so nothing is
        # raised. Discovery and counting stay separate concerns.
        far_moved = history(
            transitions=[transition("BKD", 72)],
            replacement_id="a1-b",
            moved_offset_hours=72,
        )
        source = FakeSource([far_moved], moved_ids=[PATIENT_ID])
        sweep = build_sweep(source, {"warning_team_id": "team-1"})

        result = sweep.run()

        assert result["swept"] == 1
        assert result["effects"] == []

    def test_a_day_of_ordinary_new_bookings_adds_nobody_to_the_sweep(self):
        # Both discovery methods return nobody, since an ordinary booking is
        # neither a cancellation, a no show, nor a reschedule.
        source = FakeSource([])
        sweep = build_sweep(source)

        result = sweep.run()

        assert result["swept"] == 0
        assert result["effects"] == []


def _clinic_cancellation(appointment_id, patient_id, minutes_offset, labels=None):
    """A run rule history, cancelled a few minutes ago against the shared provider."""
    base = NOW.shift(minutes=-10)
    return AppointmentHistory(
        appointment_id=appointment_id,
        patient_id=patient_id,
        provider_id=PROVIDER_ID,
        start_time=NOW.shift(days=2).datetime,
        transitions=[Transition("CLD", base.shift(minutes=minutes_offset).datetime)],
        labels=labels or [],
    )


def _real_appointment():
    """A bare Appointment row, so a tagging effect can validate against it.

    AddAppointmentLabel checks that the appointment it names actually exists
    before it can be applied, so a test that expects an effect to be emitted
    needs a real row behind the id it carries. A fake history is otherwise
    enough everywhere else, this is the one seam where the adapter's own
    effect insists on the real thing.
    """
    return Appointment.objects.create(
        start_time=NOW.datetime,
        duration_minutes=30,
        status="unconfirmed",
        telehealth_instructions_sent=False,
    )


class TestRunJudgementIsNarrowed:
    """The tagging guard only works once the adapter hands the run rule real
    labels, and even then a run stays inside the sweep's wide lookback long
    enough for a removed tag to be reapplied. The fix gives the run judgement
    its own narrowed span, so a run is judged once and then ages out. These
    tests pin the guard and the narrowing from the sweep's own side, with the
    adapter's part covered separately.
    """

    def test_a_second_sweep_over_the_same_run_emits_no_tagging_effects(self):
        clinic_tag = Config().clinic_tag
        histories = [
            _clinic_cancellation(f"a{index}", f"p{index}", index * 2, labels=[clinic_tag])
            for index in range(3)
        ]
        sweep = build_sweep(FakeSource(cancellations=histories))

        result = sweep.run()

        # The run is still found, a fresh label just has nothing left to add.
        assert result["runs_tagged"] == 1
        assert result["effects"] == []

    def test_a_run_with_one_already_tagged_appointment_tags_only_the_others(self):
        clinic_tag = Config().clinic_tag
        untagged_one = _real_appointment()
        untagged_two = _real_appointment()
        histories = [
            _clinic_cancellation(str(untagged_one.id), "p0", 0),
            _clinic_cancellation("already_tagged", "p1", 2, labels=[clinic_tag]),
            _clinic_cancellation(str(untagged_two.id), "p2", 4),
        ]
        sweep = build_sweep(FakeSource(cancellations=histories))

        result = sweep.run()

        assert len(result["effects"]) == 2
        tagged_ids = {
            json.loads(effect.payload)["data"]["appointment_id"] for effect in result["effects"]
        }
        assert tagged_ids == {str(untagged_one.id), str(untagged_two.id)}

    def test_the_run_judgement_lookback_is_narrower_than_patient_discovery(self):
        source = FakeSource()
        sweep = build_sweep(source)

        sweep.run()

        expected_run_since = NOW.shift(
            minutes=-(Config().run_window_minutes + RUN_JUDGEMENT_GRACE_MINUTES)
        ).datetime
        expected_wide_since = NOW.shift(minutes=-LOOKBACK_MINUTES).datetime
        assert source.recent_cancellations_since_calls == [expected_run_since]
        assert source.patients_with_changes_since_calls == [expected_wide_since]


class TestDerivedIdentifierIsPinned:
    """The task identifier derives from the internal line name, not the display.

    The displayed wording and the internal name used to be the same string, and
    the wording pass split them apart on purpose. Renaming the internal name
    would silently change every derived identifier and raise a second task for
    every patient already at a line, so these literals pin the derivation. A
    failure here means somebody renamed a line constant, which is an instance
    breaking change rather than a wording change.
    """

    def test_the_warning_identifier_never_moves(self):
        assert str(task_id_for("patient-1", "warning")) == (
            "aa665ab0-c472-8eb3-1ba4-ddd3a31544ac"
        )

    def test_the_review_identifier_never_moves(self):
        assert str(task_id_for("patient-1", "discharge_review")) == (
            "db9160fa-1424-a92c-f7f5-04ee91843781"
        )

    def test_the_line_constants_carry_the_pinned_names(self):
        assert WARNING == "warning"
        assert DISCHARGE_REVIEW == "discharge_review"


class TestRealClockReadsWallTime:
    def test_now_returns_a_real_current_moment(self):
        from datetime import datetime

        from attendance_policy_tracker.core.clock import Clock

        before = arrow.utcnow().datetime
        moment = Clock().now()
        after = arrow.utcnow().datetime

        assert isinstance(moment, datetime)
        assert before <= moment <= after


class TestLateMoveDetectorToleratesAHistoryWithNoRecordedMoveMoment:
    """was_moved and moved_at are independent fields on AppointmentHistory,
    so a duck typed history satisfying the structural contract could carry a
    replacement without a recorded moment. This is the detector's own
    defence against that, distinct from CanvasVisitSource, which always sets
    both together.
    """

    def test_a_replacement_with_no_moved_at_yields_no_incident(self):
        from attendance_policy_tracker.core.detectors import LateMoveDetector

        odd_history = AppointmentHistory(
            appointment_id="a1",
            patient_id=PATIENT_ID,
            provider_id=PROVIDER_ID,
            start_time=NOW.datetime,
            replacement_id="a2",
            moved_at=None,
        )
        detector = LateMoveDetector(FixedClock(NOW.datetime), boundary_hours=24)

        assert detector.detect(odd_history) is None


class TestHistoryHelpersWithNothingToFind:
    def test_cancelled_at_with_no_cancellation_in_the_thread_is_none(self):
        bare = AppointmentHistory(
            appointment_id="a1",
            patient_id=PATIENT_ID,
            provider_id=PROVIDER_ID,
            start_time=NOW.datetime,
            transitions=[transition("BKD", 2)],
        )
        assert bare.cancelled_at(CANCELLED) is None
        assert bare.first_transition_into(CANCELLED) is None

    def test_transition_repr_names_its_own_fields(self):
        moment = transition("CLD", 2)
        assert "CLD" in repr(moment)
        assert "by_patient=False" in repr(moment)

    def test_appointment_history_repr_names_its_appointment(self):
        bare = AppointmentHistory(
            appointment_id="a7",
            patient_id=PATIENT_ID,
            provider_id=PROVIDER_ID,
            start_time=NOW.datetime,
        )
        assert "a7" in repr(bare)
