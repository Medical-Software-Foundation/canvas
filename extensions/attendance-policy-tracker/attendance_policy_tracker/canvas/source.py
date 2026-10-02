"""The Canvas facing adapter.

The only unit that knows what a Canvas row looks like. It turns appointments and
their note state history into the plain values the counting core works on, so the
core stays testable without an instance and Canvas stays swappable behind one
seam.

One visit thread is one note. A reschedule reuses the original's note rather than
creating a new one, so the note is what carries the state history and a note holds
the original appointment together with every replacement. Grouping by note is
therefore what makes one intended visit produce one incident.

Every dictionary write here names its key as a plain local first. The sandbox
rewrites `target[key] = value` into a guarded write and names the key from the
source text, and it can only do that when the key is a plain name or a literal.
An attribute such as `appointment.note_id` is named `__unknown__` instead, which
trips the guard's rule against keys beginning with an underscore and refuses the
assignment at runtime. The refusal never appears in a test, because tests do not
run inside the sandbox.
"""

import datetime
from typing import Any

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.note import NoteStateChangeEvent

from attendance_policy_tracker.canvas.states import BOOKED_STATES, CANCELLED_STATES
from attendance_policy_tracker.core.history import AppointmentHistory, Transition


class CanvasVisitSource:
    """Reads visit threads out of Canvas."""

    def histories_for(self, patient_id: str) -> list[AppointmentHistory]:
        """Every visit thread belonging to one patient, reaching back without limit.

        Kept unbounded on purpose. The day feed behind the activity route reads a
        caller supplied span that can land anywhere, including before the
        counting window or before this plugin was even installed, and truncating
        this read would make that feed quietly go blank for an old day rather
        than showing what actually happened. histories_since below is the
        narrowed twin, and it is the one the hot per patient total read reaches
        for instead of this one.
        """
        appointments = self._appointments_for(patient_id)
        return self._histories_from(patient_id, appointments)

    def histories_since(
        self, patient_id: str, since: datetime.datetime
    ) -> list[AppointmentHistory]:
        """Every visit thread still worth reading, narrowed to what could matter.

        This is what closes the read side of an unbounded per patient query. A
        patient's total used to be recomputed by fetching every appointment and
        every note state change the patient has ever had, on every read, no
        matter how old. The counting window and the install floor already decide
        which of those rows matter, in core.engine, so the same moment is pushed
        down here to bound the query itself rather than discovering the answer
        only after fetching everything.

        Not exposed as an extra argument on histories_for above, because the
        engine calls that method through a small collaborator contract, and a
        test double standing in for this class only has to answer to the plain
        one argument shape. A source that offers this narrower method gets the
        cheaper query, one that does not is read in full, and either way the
        engine's own filter on the counting window and the install floor is what
        actually decides what counts, so a source with no opinion about dates at
        all still produces a correct total, only a slower one.
        """
        appointments = self._appointments_for(patient_id, since)
        return self._histories_from(patient_id, appointments)

    def _histories_from(
        self, patient_id: str, appointments: list[Any]
    ) -> list[AppointmentHistory]:
        """Shared tail of both entry points above, once the appointments are in hand."""
        if not appointments:
            return []
        note_ids: list[Any] = []
        seen: set[Any] = set()
        for appointment in appointments:
            if appointment.note_id not in seen:
                seen.add(appointment.note_id)
                note_ids.append(appointment.note_id)
        transitions = self._transitions_for(note_ids)
        return self._assemble(patient_id, appointments, transitions)

    def recent_cancellations(self, since: datetime.datetime) -> list[AppointmentHistory]:
        """Visit threads cancelled since a moment, across all patients.

        The run rule reads across patients rather than within one, because a batch
        of cancellations against one provider is evidence about the clinic rather
        than about any single patient.
        """
        rows = (
            NoteStateChangeEvent.objects.filter(
                state__in=CANCELLED_STATES, created__gte=since
            )
            .values_list(
                "note_id",
                "state",
                "created",
                "originator__is_staff",
                "originator__patient__id",
            )
            .order_by("created", "dbid")
        )
        by_note: dict[Any, list[Any]] = {}
        for note_id, state, created, is_staff, patient_key in rows:
            existing = by_note.get(note_id) or []
            # Rebuilt rather than appended in place, because augmented subscript
            # assignment is not available in the plugin sandbox.
            by_note[note_id] = existing + [
                Transition(
                    state=state,
                    occurred_at=created,
                    by_patient=self._acted_by_patient(is_staff, patient_key),
                )
            ]
        if not by_note:
            return []

        # Note is left out on purpose, it is never read as an object below, only
        # note_id straight off the row, so leaving it out costs no extra query
        # and avoids hydrating the note body and its JSON columns on every row.
        # Provider stays joined, because it is still read as an object further
        # down. The raw column cannot stand in for it, that column carries
        # Canvas's own internal integer key while this plugin identifies staff by
        # the separate identifier field, so dropping the join would buy narrower
        # rows and pay a round trip per note thread instead. Patient stays
        # joined, because unlike the single patient read below, nothing here
        # already knows which patient a row belongs to.
        appointments = (
            Appointment.objects.filter(note_id__in=list(by_note.keys()))
            .select_related("patient", "provider")
            .prefetch_related("labels")
            .order_by("start_time", "dbid")
        )
        grouped: dict[Any, list[Any]] = {}
        for appointment in appointments:
            # Named as a plain local before the write, see the note in this
            # module's docstring about how the sandbox guards a subscript
            # assignment.
            note_id = appointment.note_id
            existing = grouped.get(note_id) or []
            grouped[note_id] = existing + [appointment]

        histories = []
        for note_id, note_transitions in by_note.items():
            in_note = grouped.get(note_id) or []
            if not in_note:
                continue
            # The labels carried by the thread are what let the tagging guard
            # skip an appointment that already carries the clinic tag.
            labels = self._labels_across(in_note)
            history = self._history_for_note(in_note, note_transitions, labels)
            if history is not None:
                histories.append(history)
        return histories

    def patients_with_changes_between(
        self,
        start: datetime.datetime,
        end: datetime.datetime,
        states: list[str] | tuple[str, ...],
    ) -> list[str]:
        """Distinct patients whose visits moved into one of these states in a span.

        The bounded twin of patients_with_changes_since. The feed of one day's
        activity needs both ends, because a day in the past is a window rather
        than everything from a moment until now.

        The span is half open, start inclusive and end exclusive, so consecutive
        days neither overlap nor leave a gap at midnight. The caller supplies both
        instants, which keeps every question about which timezone a day belongs to
        on the side that actually knows the answer.
        """
        rows = (
            NoteStateChangeEvent.objects.filter(
                state__in=states, created__gte=start, created__lt=end
            )
            .values_list("note__patient__id", flat=True)
            .order_by()
            .distinct()
        )
        # Deduplicated in Python for the same reason as the unbounded twin, see
        # its docstring for why the distinct alone cannot be relied on.
        seen: list[str] = []
        for key in rows:
            if not key:
                continue
            text = f"{key}"
            if text not in seen:
                seen.append(text)
        return seen

    def patients_with_moves_between(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> list[str]:
        """Distinct patients whose visits actually moved inside a half open span.

        A reschedule writes a booked event rather than a cancellation, so
        neither of the two discovery methods above, watching the cancelled and
        no show states, ever sees a move at all. This is the query built to
        find one directly, and it runs beside those two rather than folding
        into them.

        The span is half open, start inclusive and end exclusive, matching
        both twins above for the same reason, so consecutive days neither
        overlap nor lose anything at midnight.

        Watching the booked states in the discovery filter above was
        rejected, because an initial booking always writes a booked event
        too, so that filter would pull in every patient who booked anything
        rather than only the ones whose visit moved. Counting booked events
        per note inside the window was also rejected, because a visit booked
        long ago and moved today has only one booked event inside the
        window, and a query built to require more than one there would
        filter out the very visit it was meant to find. The reschedule link
        on the appointment row is what actually distinguishes a move, and it
        marks the move regardless of when the visit was first booked, so
        this reads that link instead of counting bookings.
        """
        note_ids = list(
            NoteStateChangeEvent.objects.filter(
                state__in=BOOKED_STATES, created__gte=start, created__lt=end
            ).values_list("note_id", flat=True)
        )
        if not note_ids:
            return []

        rows = (
            Appointment.objects.filter(
                note_id__in=note_ids, appointment_rescheduled_from__isnull=False
            )
            .values_list("note__patient__id", flat=True)
            .order_by()
            .distinct()
        )
        # Deduplicated in Python for the same reason as the two twins above,
        # see patients_with_changes_since for why the distinct alone cannot
        # be relied on.
        seen: list[str] = []
        for key in rows:
            if not key:
                continue
            text = f"{key}"
            if text not in seen:
                seen.append(text)
        return seen

    def patients_with_changes_since(
        self, since: datetime.datetime, states: list[str] | tuple[str, ...]
    ) -> list[str]:
        """Distinct patients whose visits moved into one of these states recently.

        This is how the sweep decides who to recompute without storing a queue of
        pending work. Anybody whose history moved recently is worth a fresh look,
        and anybody whose history did not cannot have crossed a line since the
        last sweep.

        The ordering is cleared before the distinct. A model default ordering is
        added to the selected columns to satisfy the database, so the distinct
        then applies to the pair rather than to the patient alone and the same
        patient comes back once per matching state change. Deduplicated in Python
        as well, because whether a patient appears once on the screen should not
        rest on a subtlety of how the query was composed.
        """
        rows = (
            NoteStateChangeEvent.objects.filter(state__in=states, created__gte=since)
            .values_list("note__patient__id", flat=True)
            .order_by()
            .distinct()
        )
        seen: list[str] = []
        for key in rows:
            if not key:
                continue
            text = f"{key}"
            if text not in seen:
                seen.append(text)
        return seen

    def _appointments_for(
        self, patient_id: str, since: datetime.datetime | None = None
    ) -> list[Any]:
        """Appointments for a patient, oldest first, with labels prefetched.

        The forward query from Appointment is used rather than the reverse
        accessor from Note, because Note declares no related name for it and the
        Django default is inferred rather than confirmed anywhere in the SDK.

        Ordered by start time rather than by a creation timestamp, because
        Appointment carries no created field at all. Start time is also the
        better ordering for this purpose, since it is the order the visits were
        meant to happen in rather than the order somebody booked them. dbid
        breaks ties because it is monotonic while the plugin facing identifier is
        a random UUID.

        Note is left off the join. It is never read as an object further down,
        only note_id straight off the row, so leaving it out costs no extra
        query and avoids hydrating the note body and its JSON columns on every
        row fetched. Provider stays joined, because it is still read as an
        object. The raw column is not a substitute, it carries Canvas's own
        internal integer key while this plugin identifies staff by the separate
        identifier field, so dropping the join would trade one join for a round
        trip per note thread, which is the same shape of fault as the patient
        refetch removed further down.

        since, when given, narrows which note threads are read at all, rather
        than filtering the rows returned. A row level filter on start time alone
        would strand a reschedule chain's other half, the original half of a
        visit that moved from outside this bound to inside it, or the current
        half of a visit that moved from inside it back out, and either way the
        thread would come back with only one of its two ends, which corrupts the
        original versus current call the orientation logic further down makes.
        So the bound only ever decides which threads are worth reading at all,
        found first as a cheap column only query, and once a thread clears that
        bar every row it owns comes back whole.
        """
        query = Appointment.objects.filter(note__patient__id=patient_id)
        if since is not None:
            note_ids = list(
                query.filter(start_time__gte=since)
                .values_list("note_id", flat=True)
                .distinct()
            )
            if not note_ids:
                return []
            query = Appointment.objects.filter(note_id__in=note_ids)
        return list(
            query.select_related("provider")
            .prefetch_related("labels")
            .order_by("start_time", "dbid")
        )

    def _transitions_for(self, note_ids: list[Any]) -> dict[Any, list[Transition]]:
        """Every state these notes moved into, grouped by note.

        Scoped to the note identifiers the appointment read already collected,
        the same way recent_cancellations above scopes its own appointment read
        to the note identifiers its transitions read collected first, just with
        the two queries running in the opposite order since here it is the
        appointment side that knows the relevant notes. Filtering on the note
        this way rather than on the patient alone also means a chart review, a
        message or a letter, none of which are ever looked up here, never enters
        this read in the first place, because none of those note types could
        ever appear among the note identifiers an appointment read produced.

        Read through values_list across the reverse relation on purpose. Reading
        the originator's person through the model accessor raises when the related
        row is absent, while a left joined values_list yields None instead, and an
        absent originator is normal on platform written rows.

        Ordered by created then dbid rather than by the model default, because in
        the plugin facing view the identifier is a random UUID so it is no
        tie break at all, while dbid is monotonic.
        """
        if not note_ids:
            return {}
        rows = (
            NoteStateChangeEvent.objects.filter(note_id__in=note_ids)
            .values_list(
                "note_id",
                "state",
                "created",
                "originator__is_staff",
                "originator__patient__id",
            )
            .order_by("created", "dbid")
        )
        grouped: dict[Any, list[Transition]] = {}
        for note_id, state, created, is_staff, patient_key in rows:
            existing = grouped.get(note_id) or []
            grouped[note_id] = existing + [
                Transition(
                    state=state,
                    occurred_at=created,
                    by_patient=self._acted_by_patient(is_staff, patient_key),
                )
            ]
        return grouped

    def _acted_by_patient(self, is_staff: Any, patient_key: Any) -> bool:
        """True when the person who acted was the patient rather than staff.

        Driven on a running instance, a portal cancellation arrives with a
        populated actor whose staff flag is false and whose person resolves to the
        patient, while a staff action arrives with the flag true. An absent actor
        is neither, and is treated as not the patient so it falls to the tag and
        the default rather than being quietly excused.
        """
        if is_staff is None:
            return False
        if is_staff:
            return False
        return patient_key is not None

    def _assemble(
        self,
        patient_id: str,
        appointments: list[Any],
        transitions: dict[Any, list[Transition]],
    ) -> list[AppointmentHistory]:
        """Group appointments into one visit thread per note."""
        grouped: dict[Any, list[Any]] = {}
        for appointment in appointments:
            # Named as a plain local before the write, see the note in this
            # module's docstring about how the sandbox guards a subscript
            # assignment.
            note_id = appointment.note_id
            existing = grouped.get(note_id) or []
            grouped[note_id] = existing + [appointment]

        histories = []
        for note_id, in_note in grouped.items():
            labels = self._labels_across(in_note)
            history = self._history_for_note(
                in_note, transitions.get(note_id) or [], labels, patient_id
            )
            if history is not None:
                histories.append(history)
        return histories

    def _labels_across(self, in_note: list[Any]) -> list[str]:
        """Every label name on any appointment in the thread.

        Taken across the whole thread because a reschedule carries the original's
        labels forward onto the replacement, so both sides normally agree, and a
        person may have corrected only one of them.
        """
        names = []
        for appointment in in_note:
            for label in appointment.labels.all():
                if label.name not in names:
                    names.append(label.name)
        return names

    def _history_for_note(
        self,
        in_note: list[Any],
        note_transitions: list[Transition],
        labels: list[str],
        patient_id: str | None = None,
    ) -> AppointmentHistory | None:
        """One visit thread, built from the appointments hanging off one note.

        patient_id is optional and, when given, is used as is rather than read
        off the current appointment's own patient relation. The single patient
        read this class serves already knows whose history it asked for, and
        that known identifier is what is passed in, so this method never has to
        fetch a patient row just to be told the answer it was handed to begin
        with. The across patient read below has no single patient in scope, so
        it leaves this empty and this method falls back to reading the row.
        """
        if not in_note:
            return None
        original, current = self._orient(in_note)

        replacement_id = None
        moved_at = None
        moved_by_patient = False
        # A reschedule writes a second booking into the note's state history, so
        # the move is a recorded state change rather than something to infer.
        # Appointment carries no creation timestamp at all, and even if it did,
        # matching a row creation time against the history by proximity would be
        # guessing where the history already states the answer.
        bookings = [t for t in note_transitions if t.state in BOOKED_STATES]
        if len(in_note) > 1 and len(bookings) > 1:
            replacement_id = f"{current.id}"
            move = bookings[-1]
            moved_at = move.occurred_at
            moved_by_patient = move.by_patient

        provider = getattr(current, "provider", None)
        provider_id = f"{provider.id}" if provider is not None else ""
        if patient_id is not None:
            patient_key = patient_id
        else:
            patient = getattr(current, "patient", None)
            patient_key = f"{patient.id}" if patient is not None else ""

        return AppointmentHistory(
            appointment_id=f"{current.id}",
            patient_id=patient_key,
            provider_id=provider_id,
            start_time=current.start_time,
            original_start=original.start_time,
            transitions=note_transitions,
            labels=labels,
            replacement_id=replacement_id,
            moved_at=moved_at,
            moved_by_patient=moved_by_patient,
        )

    def _orient(self, in_note: list[Any]) -> tuple[Any, Any]:
        """Find the head and the tail of one note's reschedule chain.

        A visit moved to an earlier slot inverts start time order, so start time
        cannot be trusted to say which row is the original and which is current
        once a reschedule link is present. The link is the platform's own record
        of which row came from which, and it is followed instead.

        Matching runs on dbid rather than on the plugin facing id, because a self
        referencing foreign key targets the primary key, and dbid is the primary
        key here while id is a separate unique field.
        """
        dbids_in_note = {appointment.dbid for appointment in in_note}
        links = [
            getattr(appointment, "appointment_rescheduled_from_id", None)
            for appointment in in_note
        ]

        if not any(link is not None for link in links):
            # Old data carrying no reschedule link at all. Degrade to the
            # ordering this used to run on unconditionally, rather than refusing
            # to produce a history for a thread the link cannot help with.
            ordered = sorted(in_note, key=lambda item: item.start_time)
            return ordered[0], ordered[-1]

        # A row this note links back to is not the end of the chain, whatever
        # its start time says.
        linked_to_dbids = {link for link in links if link is not None and link in dbids_in_note}

        originals = [
            appointment
            for appointment in in_note
            if appointment.appointment_rescheduled_from_id is None
            or appointment.appointment_rescheduled_from_id not in dbids_in_note
        ]
        currents = [
            appointment for appointment in in_note if appointment.dbid not in linked_to_dbids
        ]

        if not originals or not currents:
            # A chain that manages to name no head or no tail at all, which a
            # correctly written chain cannot do. Fall back rather than raise.
            ordered = sorted(in_note, key=lambda item: item.start_time)
            return ordered[0], ordered[-1]

        # A chain the platform actually writes is linear and leaves exactly one
        # candidate on each end. This tie break only exists for a history the
        # platform should never write, several heads or several tails, and it
        # picks earliest start for the original and latest for the current
        # purely to be deterministic about a case that should not occur.
        original = min(originals, key=lambda item: item.start_time)
        current = max(currents, key=lambda item: item.start_time)
        return original, current

