"""Tests for the visit source's queries and the fixes that bound them.

Everything in the first half runs against a real, if tiny, sqlite table,
because the point being proven is what a query actually returns once a date
bound and a note scope are pushed into it, not what a plain python object says
it would return. pytest-canvas creates those tables with no ceremony needed
here, the same way the existing suite already relies on it.

The second half runs without a database at all, because it is about the
engine's own arithmetic, which of two moments is later, and about what
_history_for_note reads when it is handed an identifier it does not have to
look up, neither of which needs a Canvas instance underneath it to be true.

Fakes here are defined locally rather than imported from tests/test_core.py or
tests/test_live.py, which is the established pattern in this suite when a
fake is needed that those files do not already export for reuse.
"""

import datetime

import arrow
import pytest
from django.db.models import Model

from canvas_sdk.v1.data.appointment import Appointment, AppointmentLabel
from canvas_sdk.v1.data.note import Note, NoteStateChangeEvent, NoteType
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.task import TaskLabel
from canvas_sdk.v1.data.user import CanvasUser

from attendance_policy_tracker.canvas.source import CanvasVisitSource
from attendance_policy_tracker.canvas.states import BOOKED_STATES, CANCELLED_STATES, NO_SHOW_STATES
from attendance_policy_tracker.core.clock import FixedClock
from attendance_policy_tracker.core.config import Config, ConfigError
from attendance_policy_tracker.core.engine import AttendanceEngine
from attendance_policy_tracker.core.history import Transition

NOW = arrow.get("2026-08-14T12:00:00+00:00")


def _backdate(row: Model, moment: datetime.datetime) -> None:
    """Move a TimestampedModel's created stamp into the past.

    auto_now_add only fires inside Model.save(), so a plain create() always
    lands at the real wall clock moment the test ran. QuerySet.update()
    bypasses that entirely, which is the only way to put a row on either
    side of a bound this suite controls.

    Typed as Model rather than as each caller's concrete class, because every
    model handed to it is a different one and all it needs is the manager and
    the primary key that every model carries.
    """
    row.__class__._default_manager.filter(pk=row.pk).update(created=moment)


def _actor(is_staff: bool, patient: Patient | None = None) -> CanvasUser:
    """A CanvasUser standing in for whoever performed a state change.

    A staff actor names nobody further. A patient actor is linked back to a
    real Patient row through the same OneToOne field the platform uses, since
    _acted_by_patient reads that relation rather than a flag on the user.
    """
    user = CanvasUser.objects.create(is_staff=is_staff)
    if patient is not None:
        patient.user = user
        patient.save()
    return user


def _note_type() -> NoteType:
    return NoteType.objects.create()


def _note(note_type: NoteType, patient: Patient) -> Note:
    return Note.objects.create(note_type_version=note_type, patient=patient)


def _appointment(
    note: Note,
    start_time: object,
    appointment_rescheduled_from_id: int | None = None,
    status: str = "unconfirmed",
) -> Appointment:
    return Appointment.objects.create(
        note=note,
        start_time=start_time,
        duration_minutes=30,
        status=status,
        telehealth_instructions_sent=False,
        appointment_rescheduled_from_id=appointment_rescheduled_from_id,
    )


class TestAppointmentsForCarriesADateBound:
    """FIX A1. The appointment read now takes a lower bound rather than reading
    a patient's whole history on every call.
    """

    def test_a_patient_with_nothing_at_all_inside_the_bound_reads_no_rows(self) -> None:
        # Every note this patient owns predates the bound, so the cheap
        # column only query that finds note_ids comes back empty, and the
        # second, wider query never runs at all.
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        old_note = _note(note_type, patient)
        _appointment(old_note, NOW.shift(days=-400).datetime)

        since = NOW.shift(days=-30).datetime
        rows = CanvasVisitSource()._appointments_for(patient.id, since)

        assert rows == []

    def test_a_note_entirely_before_the_bound_is_left_out(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        old_note = _note(note_type, patient)
        new_note = _note(note_type, patient)
        _appointment(old_note, NOW.shift(days=-400).datetime)
        kept = _appointment(new_note, NOW.shift(days=-5).datetime)

        since = NOW.shift(days=-30).datetime
        rows = CanvasVisitSource()._appointments_for(patient.id, since)

        assert [row.dbid for row in rows] == [kept.dbid]

    def test_with_no_bound_at_all_every_note_is_read_exactly_as_before(self) -> None:
        # histories_for, the unbounded twin the day feed still relies on, calls
        # this with since left out entirely, so the old behaviour has to stand.
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        old_note = _note(note_type, patient)
        old = _appointment(old_note, NOW.shift(days=-400).datetime)

        rows = CanvasVisitSource()._appointments_for(patient.id)

        assert [row.dbid for row in rows] == [old.dbid]

    def test_a_reschedule_chain_spanning_the_bound_is_read_whole(self) -> None:
        # The row level trap A1 has to avoid. If the bound filtered rows
        # directly rather than threads, the abandoned half of this chain would
        # be dropped while the moved to half survived, and orientation further
        # down would see only one row and wrongly treat it as an unmoved visit.
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        original = _appointment(note, NOW.shift(days=-400).datetime, status="cancelled")
        current = _appointment(
            note,
            NOW.shift(days=-5).datetime,
            appointment_rescheduled_from_id=original.dbid,
        )

        since = NOW.shift(days=-30).datetime
        rows = CanvasVisitSource()._appointments_for(patient.id, since)

        assert {row.dbid for row in rows} == {original.dbid, current.dbid}

    def test_histories_since_keeps_the_true_original_start_for_that_chain(self) -> None:
        # The end to end proof that the whole thread survives assembly, not
        # just the row level query above. A corrupted read here would silently
        # report the abandoned slot's own time as both the original and the
        # current start, which is exactly the wrong answer a late move
        # detector would need to be right about.
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        original = _appointment(note, NOW.shift(days=-400).datetime, status="cancelled")
        current = _appointment(
            note,
            NOW.shift(days=-5).datetime,
            appointment_rescheduled_from_id=original.dbid,
        )

        since = NOW.shift(days=-30).datetime
        histories = CanvasVisitSource().histories_since(patient.id, since)

        assert len(histories) == 1
        assert histories[0].original_start == original.start_time
        assert histories[0].start_time == current.start_time


class TestTransitionsAreScopedToTheNotesGiven:
    """FIX A6. The state change read no longer takes the patient alone, it
    takes the exact note identifiers the appointment read already found.
    """

    def test_a_note_outside_the_given_set_never_appears_in_the_result(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        appointment_note = _note(note_type, patient)
        unrelated_note = _note(note_type, patient)
        NoteStateChangeEvent.objects.create(note=appointment_note, state="CLD")
        NoteStateChangeEvent.objects.create(note=unrelated_note, state="CLD")

        grouped = CanvasVisitSource()._transitions_for([appointment_note.dbid])

        assert set(grouped.keys()) == {appointment_note.dbid}

    def test_an_empty_note_id_list_reads_nothing_at_all(self) -> None:
        assert CanvasVisitSource()._transitions_for([]) == {}


class _PoisonedPatient:
    """A stand in whose id would raise if anything ever asked for it.

    Standing in for the real Patient row, so a test can prove _history_for_note
    never touched it rather than merely asserting the right value came back,
    which a coincidence could also produce.
    """

    @property
    def id(self) -> str:
        raise AssertionError(
            "patient.id was read even though the caller already knew patient_id"
        )


class _FakeRow:
    """A stand in for a Canvas Appointment row, carrying only what the
    orientation and assembly logic reads.
    """

    def __init__(
        self,
        id: str,
        dbid: int,
        start_time: object,
        patient: object = None,
        provider: object = None,
        appointment_rescheduled_from_id: int | None = None,
    ) -> None:
        self.id = id
        self.dbid = dbid
        self.start_time = start_time
        self.patient = patient
        self.provider = provider
        self.appointment_rescheduled_from_id = appointment_rescheduled_from_id


class TestHistoryForNoteDoesNotRefetchThePatient:
    """FIX A3. Given an identifier it already knows, this stops reading the
    patient relation off the row at all.
    """

    def test_a_known_patient_id_is_used_as_is_and_the_row_is_never_touched(self) -> None:
        row = _FakeRow("a1", 1, NOW.datetime, patient=_PoisonedPatient())

        history = CanvasVisitSource()._history_for_note([row], [], [], "known-patient-id")

        assert history is not None
        assert history.patient_id == "known-patient-id"

    def test_with_no_identifier_given_the_row_is_still_read_exactly_as_before(self) -> None:
        # The fallback recent_cancellations relies on, since it spans many
        # patients at once and has no single identifier to hand in.
        class _NamedPatient:
            id = "row-derived-id"

        row = _FakeRow("a1", 1, NOW.datetime, patient=_NamedPatient())
        history = CanvasVisitSource()._history_for_note([row], [], [])

        assert history is not None
        assert history.patient_id == "row-derived-id"


class RecordingSource:
    """Records the since argument the engine hands to the narrowed read.

    Standing in for a source that implements histories_since, so a test can
    pin exactly which moment the effective floor resolves to without a real
    Canvas instance underneath it. histories_for is left raising on purpose,
    since a test built around this fake is specifically checking that the
    engine reaches for the narrower method instead, and a silent fall back
    would hide that it had stopped doing so.
    """

    def __init__(self) -> None:
        self.since_calls: list[object] = []

    def histories_since(self, patient_id: str, since: object) -> list[object]:
        self.since_calls.append(since)
        return []

    def histories_for(self, patient_id: str) -> list[object]:
        raise AssertionError(
            "the engine fell back to the unbounded read even though the narrower one was offered"
        )


class TestEffectiveFloorIsTheLaterMoment:
    """FIX A1's other half. Getting this backwards silently changes counts, a
    fresh install would let history from before the plugin existed straight
    back in, so both directions are pinned here.
    """

    def test_the_counting_window_binds_when_the_install_floor_is_older(self) -> None:
        clock = FixedClock(NOW.datetime)
        config = Config(
            {"counting_window_months": 12, "install_floor": NOW.shift(months=-20).datetime}
        )
        source = RecordingSource()
        engine = AttendanceEngine(config=config, source=source, detectors=[], chain=None, clock=clock)

        engine.total_for("patient-1")

        expected = clock.months_before(NOW.datetime, 12)
        assert source.since_calls == [expected]

    def test_the_install_floor_binds_when_it_is_more_recent_than_the_window(self) -> None:
        clock = FixedClock(NOW.datetime)
        floor = NOW.shift(months=-2).datetime
        config = Config({"counting_window_months": 12, "install_floor": floor})
        source = RecordingSource()
        engine = AttendanceEngine(config=config, source=source, detectors=[], chain=None, clock=clock)

        engine.total_for("patient-1")

        assert source.since_calls == [floor]


class TestEngineToleratesASourceWithNoNarrowerMethod:
    """A source offering only the plain, unbounded method, exactly the shape
    of the duck typed fake the rest of the suite already builds engines
    against, still produces a correct, if slower, read.
    """

    def test_the_plain_method_is_used_and_nothing_raises(self) -> None:
        class PlainSource:
            def __init__(self) -> None:
                self.asked: list[str] = []

            def histories_for(self, patient_id: str) -> list[object]:
                self.asked.append(patient_id)
                return []

        clock = FixedClock(NOW.datetime)
        source = PlainSource()
        engine = AttendanceEngine(
            config=Config(), source=source, detectors=[], chain=None, clock=clock
        )

        total = engine.total_for("patient-2")

        assert source.asked == ["patient-2"]
        assert total.count == 0


class TestConfigUpperBounds:
    """FIX A2. The coupling A1 introduces, once the counting window controls a
    real query bound, a stored value needs a ceiling and not just a floor.
    """

    def test_counting_window_months_accepts_a_value_at_the_ceiling(self) -> None:
        config = Config({"counting_window_months": 60})
        assert config.counting_window_months == 60

    def test_counting_window_months_rejects_a_value_past_the_ceiling(self) -> None:
        with pytest.raises(ConfigError):
            Config({"counting_window_months": 61})

    def test_run_count_rejects_a_value_past_its_ceiling(self) -> None:
        with pytest.raises(ConfigError):
            Config({"run_count": 51})

    def test_an_unrecognised_stored_key_passes_through_harmlessly(self) -> None:
        # Guards the cross lane contract directly. A setting this plugin does
        # not name of its own, such as another handler's cursor riding on the
        # same store, must never trip a bound that was written for a name it
        # was never about.
        config = Config({"counting_window_months": 12, "sweep_cursor": "2026-01-01T00:00:00Z"})
        assert config.counting_window_months == 12


# ---------------------------------------------------------------------------
# The cross patient discovery and read queries. Every one of these decides
# who the sweep, the day feed, or the review surface even looks at, so a
# fault here is invisible rather than loud, a patient simply never surfaces.
# Run against a real, if tiny, sqlite table for the same reason as the first
# half of this file, the point is what the query actually returns.
# ---------------------------------------------------------------------------


class TestHistoriesForReadsThePatientsWholeThread:
    """The unbounded entry point, exercised end to end rather than through
    its two private halves, so a break in how they are glued together would
    still show up here even if each half kept passing on its own.
    """

    def test_a_patients_appointment_comes_back_as_one_history(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        appointment = _appointment(note, NOW.datetime)
        NoteStateChangeEvent.objects.create(note=note, state=CANCELLED_STATES[0])

        histories = CanvasVisitSource().histories_for(patient.id)

        assert len(histories) == 1
        assert histories[0].appointment_id == str(appointment.id)
        assert histories[0].patient_id == patient.id
        assert histories[0].transitions[0].state == CANCELLED_STATES[0]

    def test_a_patient_with_no_appointments_at_all_gets_back_nothing(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        assert CanvasVisitSource().histories_for(patient.id) == []


class TestRecentCancellationsSpansEveryPatient:
    """FIX C2's read. The run rule needs cancellations across patients, so
    this is the one discovery query that does not scope to a single person.
    """

    def test_a_cancellation_inside_the_bound_comes_back_with_its_labels(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        appointment = _appointment(note, NOW.shift(days=2).datetime)
        label = TaskLabel.objects.create(name="clinic-cancelled", position=0)
        AppointmentLabel.objects.create(appointment=appointment, task_label=label)
        change = NoteStateChangeEvent.objects.create(
            note=note, state=CANCELLED_STATES[0], originator=_actor(is_staff=True)
        )
        _backdate(change, NOW.shift(minutes=-10).datetime)

        histories = CanvasVisitSource().recent_cancellations(NOW.shift(hours=-1).datetime)

        assert len(histories) == 1
        assert histories[0].appointment_id == str(appointment.id)
        assert histories[0].labels == ["clinic-cancelled"]
        assert histories[0].transitions[0].by_patient is False

    def test_a_cancellation_before_the_bound_is_left_out(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        _appointment(note, NOW.shift(days=2).datetime)
        change = NoteStateChangeEvent.objects.create(note=note, state=CANCELLED_STATES[0])
        _backdate(change, NOW.shift(hours=-3).datetime)

        histories = CanvasVisitSource().recent_cancellations(NOW.shift(hours=-1).datetime)

        assert histories == []

    def test_a_patient_portal_actor_is_recorded_as_by_patient(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        _appointment(note, NOW.shift(days=2).datetime)
        change = NoteStateChangeEvent.objects.create(
            note=note, state=CANCELLED_STATES[0], originator=_actor(is_staff=False, patient=patient)
        )
        _backdate(change, NOW.shift(minutes=-5).datetime)

        histories = CanvasVisitSource().recent_cancellations(NOW.shift(hours=-1).datetime)

        assert len(histories) == 1
        assert histories[0].transitions[0].by_patient is True

    def test_no_matching_state_changes_at_all_reads_nothing_further(self) -> None:
        # Nothing cancelled inside the bound, so the appointment read this
        # method would otherwise run never has to happen.
        assert CanvasVisitSource().recent_cancellations(NOW.shift(hours=-1).datetime) == []

    def test_a_note_with_a_recorded_cancellation_but_no_surviving_appointment_is_skipped(
        self,
    ) -> None:
        # A defensive gap between the two halves of this read, the state
        # history names a note that the appointment side never finds a row
        # for. Skipped rather than crashing on a thread with nothing to
        # assemble.
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        change = NoteStateChangeEvent.objects.create(note=note, state=CANCELLED_STATES[0])
        _backdate(change, NOW.shift(minutes=-5).datetime)

        assert CanvasVisitSource().recent_cancellations(NOW.shift(hours=-1).datetime) == []


class TestPatientsWithChangesBetweenIsHalfOpen:
    """The bounded twin the day feed reads, scoped to an exact span."""

    def test_a_change_inside_the_span_names_its_patient(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        change = NoteStateChangeEvent.objects.create(note=note, state=CANCELLED_STATES[0])
        _backdate(change, NOW.datetime)

        found = CanvasVisitSource().patients_with_changes_between(
            NOW.shift(hours=-1).datetime, NOW.shift(hours=1).datetime, CANCELLED_STATES
        )

        assert found == [patient.id]

    def test_the_end_instant_itself_is_excluded(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        change = NoteStateChangeEvent.objects.create(note=note, state=CANCELLED_STATES[0])
        _backdate(change, NOW.datetime)

        found = CanvasVisitSource().patients_with_changes_between(
            NOW.shift(hours=-1).datetime, NOW.datetime, CANCELLED_STATES
        )

        assert found == []

    def test_the_start_instant_itself_is_included(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        change = NoteStateChangeEvent.objects.create(note=note, state=CANCELLED_STATES[0])
        _backdate(change, NOW.datetime)

        found = CanvasVisitSource().patients_with_changes_between(
            NOW.datetime, NOW.shift(hours=1).datetime, CANCELLED_STATES
        )

        assert found == [patient.id]

    def test_an_unwatched_state_never_surfaces_the_patient(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        change = NoteStateChangeEvent.objects.create(note=note, state=BOOKED_STATES[0])
        _backdate(change, NOW.datetime)

        found = CanvasVisitSource().patients_with_changes_between(
            NOW.shift(hours=-1).datetime, NOW.shift(hours=1).datetime, CANCELLED_STATES
        )

        assert found == []

    def test_the_same_patient_named_twice_appears_once(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        first_note = _note(note_type, patient)
        second_note = _note(note_type, patient)
        for note in (first_note, second_note):
            change = NoteStateChangeEvent.objects.create(note=note, state=CANCELLED_STATES[0])
            _backdate(change, NOW.datetime)

        found = CanvasVisitSource().patients_with_changes_between(
            NOW.shift(hours=-1).datetime, NOW.shift(hours=1).datetime, CANCELLED_STATES
        )

        assert found == [patient.id]


class TestPatientsWithChangesSinceIsOpenEnded:
    """The sweep's own discovery, everybody who moved since a moment."""

    def test_a_recent_no_show_names_its_patient(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        change = NoteStateChangeEvent.objects.create(note=note, state=NO_SHOW_STATES[0])
        _backdate(change, NOW.shift(minutes=-5).datetime)

        found = CanvasVisitSource().patients_with_changes_since(
            NOW.shift(hours=-1).datetime, NO_SHOW_STATES
        )

        assert found == [patient.id]

    def test_a_change_before_since_is_excluded(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        change = NoteStateChangeEvent.objects.create(note=note, state=NO_SHOW_STATES[0])
        _backdate(change, NOW.shift(hours=-5).datetime)

        found = CanvasVisitSource().patients_with_changes_since(
            NOW.shift(hours=-1).datetime, NO_SHOW_STATES
        )

        assert found == []

    def test_no_qualifying_rows_at_all_gives_an_empty_list(self) -> None:
        assert (
            CanvasVisitSource().patients_with_changes_since(
                NOW.shift(hours=-1).datetime, CANCELLED_STATES
            )
            == []
        )

    def test_a_note_with_no_patient_at_all_is_skipped_rather_than_named_as_none(self) -> None:
        # Platform written rows can carry no patient relation. Naming "None"
        # as a patient would corrupt every caller that treats this list as
        # identifiers worth a lookup.
        note_type = _note_type()
        note = Note.objects.create(note_type_version=note_type, patient=None)
        change = NoteStateChangeEvent.objects.create(note=note, state=NO_SHOW_STATES[0])
        _backdate(change, NOW.shift(minutes=-5).datetime)

        found = CanvasVisitSource().patients_with_changes_since(
            NOW.shift(hours=-1).datetime, NO_SHOW_STATES
        )

        assert found == []


class TestPatientsWithMovesBetweenFindsARescheduleLink:
    """FIX C1's other discovery path. A reschedule writes a booking rather
    than a cancellation, so watching cancelled and no show states alone would
    never see it, and merely watching every booking would pull in every fresh
    appointment too. Only the reschedule link on the row distinguishes a move.
    """

    def test_a_rescheduled_appointment_names_its_patient(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        original = _appointment(note, NOW.shift(days=-3).datetime, status="cancelled")
        _appointment(
            note, NOW.shift(days=3).datetime, appointment_rescheduled_from_id=original.dbid
        )
        change = NoteStateChangeEvent.objects.create(note=note, state=BOOKED_STATES[0])
        _backdate(change, NOW.datetime)

        found = CanvasVisitSource().patients_with_moves_between(
            NOW.shift(hours=-1).datetime, NOW.shift(hours=1).datetime
        )

        assert found == [patient.id]

    def test_an_ordinary_first_booking_with_no_reschedule_link_names_nobody(self) -> None:
        # The rejected design the docstring warns about. Watching booked
        # states alone would catch this too, and it must not.
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        _appointment(note, NOW.shift(days=3).datetime)
        change = NoteStateChangeEvent.objects.create(note=note, state=BOOKED_STATES[0])
        _backdate(change, NOW.datetime)

        found = CanvasVisitSource().patients_with_moves_between(
            NOW.shift(hours=-1).datetime, NOW.shift(hours=1).datetime
        )

        assert found == []

    def test_a_booking_outside_the_span_names_nobody(self) -> None:
        patient = Patient.objects.create(birth_date="1990-01-01")
        note_type = _note_type()
        note = _note(note_type, patient)
        original = _appointment(note, NOW.shift(days=-3).datetime, status="cancelled")
        _appointment(
            note, NOW.shift(days=3).datetime, appointment_rescheduled_from_id=original.dbid
        )
        change = NoteStateChangeEvent.objects.create(note=note, state=BOOKED_STATES[0])
        _backdate(change, NOW.shift(hours=-5).datetime)

        found = CanvasVisitSource().patients_with_moves_between(
            NOW.shift(hours=-1).datetime, NOW.shift(hours=1).datetime
        )

        assert found == []

    def test_no_booked_events_at_all_short_circuits_before_the_appointment_read(self) -> None:
        assert (
            CanvasVisitSource().patients_with_moves_between(
                NOW.shift(hours=-1).datetime, NOW.shift(hours=1).datetime
            )
            == []
        )


class TestActedByPatientIsAPureQuestion:
    """No database needed, this reads only the two values already fetched."""

    def test_no_actor_at_all_is_not_the_patient(self) -> None:
        assert CanvasVisitSource()._acted_by_patient(None, None) is False

    def test_a_staff_actor_is_never_the_patient(self) -> None:
        assert CanvasVisitSource()._acted_by_patient(True, "some-patient-key") is False

    def test_a_non_staff_actor_with_no_resolved_patient_is_not_the_patient(self) -> None:
        # Observed on a running instance as the platform's own actions, which
        # populate no staff flag and resolve to no patient either.
        assert CanvasVisitSource()._acted_by_patient(False, None) is False

    def test_a_non_staff_actor_who_resolves_to_a_patient_is_the_patient(self) -> None:
        assert CanvasVisitSource()._acted_by_patient(False, "some-patient-key") is True


class _FakeLabel:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeLabelManager:
    def __init__(self, names: list[str]) -> None:
        self._labels = [_FakeLabel(name) for name in names]

    def all(self) -> list[_FakeLabel]:
        return self._labels


class _FakeLabeledRow:
    def __init__(self, names: list[str]) -> None:
        self.labels = _FakeLabelManager(names)


class TestLabelsAcrossANoteAreDeduplicated:
    def test_a_label_repeated_on_both_sides_of_a_reschedule_counts_once(self) -> None:
        names = CanvasVisitSource()._labels_across(
            [_FakeLabeledRow(["clinic-cancelled"]), _FakeLabeledRow(["clinic-cancelled"])]
        )
        assert names == ["clinic-cancelled"]

    def test_labels_found_only_on_one_side_are_still_carried(self) -> None:
        names = CanvasVisitSource()._labels_across(
            [_FakeLabeledRow(["a"]), _FakeLabeledRow(["a", "b"])]
        )
        assert names == ["a", "b"]


class TestHistoryForNoteEdgeCases:
    """The two branches TestHistoryForNoteDoesNotRefetchThePatient does not
    already cover, an empty thread and a genuine multi booking move.
    """

    def test_an_empty_thread_produces_no_history_at_all(self) -> None:
        assert CanvasVisitSource()._history_for_note([], [], []) is None

    def test_two_bookings_on_one_note_are_read_as_a_recorded_move(self) -> None:
        original = _FakeRow("a1", 1, NOW.shift(days=-3).datetime)
        current = _FakeRow(
            "a2", 2, NOW.shift(days=1).datetime, appointment_rescheduled_from_id=1
        )
        first_booking = Transition(BOOKED_STATES[0], NOW.shift(days=-10).datetime)
        the_move = Transition(
            BOOKED_STATES[0], NOW.shift(days=-3, hours=-1).datetime, by_patient=True
        )

        history = CanvasVisitSource()._history_for_note(
            [original, current], [first_booking, the_move], []
        )

        assert history is not None
        assert history.replacement_id == "a2"
        assert history.moved_at == the_move.occurred_at
        assert history.moved_by_patient is True

    def test_a_single_booking_on_a_multi_row_note_is_not_read_as_a_move(self) -> None:
        # Two rows but only one booking transition between them, so nothing
        # here counts as a recorded reschedule.
        original = _FakeRow("a1", 1, NOW.shift(days=-3).datetime)
        current = _FakeRow(
            "a2", 2, NOW.shift(days=1).datetime, appointment_rescheduled_from_id=1
        )
        only_booking = Transition(BOOKED_STATES[0], NOW.shift(days=-10).datetime)

        history = CanvasVisitSource()._history_for_note(
            [original, current], [only_booking], []
        )

        assert history is not None
        assert history.replacement_id is None
        assert history.moved_at is None


class TestOrientFallsBackOnAnUnwritableChain:
    """A chain the platform should never produce, every row naming and being
    named by another, so neither an original nor a current candidate is
    left. _orient degrades to the plain start time ordering rather than
    raising, the same fallback old data with no link at all already uses.
    """

    def test_a_two_row_cycle_still_returns_a_head_and_a_tail(self) -> None:
        earlier = _FakeRow("a", 1, NOW.shift(days=-1).datetime, appointment_rescheduled_from_id=2)
        later = _FakeRow("b", 2, NOW.datetime, appointment_rescheduled_from_id=1)

        original, current = CanvasVisitSource()._orient([earlier, later])

        assert original is earlier
        assert current is later
