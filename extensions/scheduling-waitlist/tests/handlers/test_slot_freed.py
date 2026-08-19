"""Announcing a freed slot to the scheduling team."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scheduling_waitlist.handlers.slot_freed import SlotFreedHandler

MODULE = "scheduling_waitlist.handlers.slot_freed"

SECRETS = {
    "WAITLIST_SCHEDULING_TEAM": "Front Desk",
    "WAITLIST_APPOINTMENT_TYPES": "estab",
}


def _handler(appointment_id="appt-key", event_type="APPOINTMENT_CANCELED", secrets=None):
    """A handler whose event mirrors the real one's two identity fields.

    ``type`` is the protobuf enum *integer* and ``name`` is the readable string,
    exactly as ``canvas_sdk.events.Event`` sets them. Setting only ``type``, to
    the name, is what let the handler read the wrong field for so long: the
    suite saw "APPOINTMENT_CANCELED" where the instance produced "4".
    """
    from canvas_sdk.events import EventType

    handler = SlotFreedHandler.__new__(SlotFreedHandler)
    event = MagicMock()
    event.target.id = appointment_id
    event.context = {}
    event.type = getattr(EventType, event_type)
    event.name = event_type
    handler.event = event
    handler.secrets = SECRETS if secrets is None else secrets
    return handler


def _appointment(start_offset_days=9, **overrides):
    record = MagicMock()
    record.dbid = 900
    record.id = "appt-key"
    record.start_time = datetime.now(timezone.utc) + timedelta(days=start_offset_days)
    record.duration_minutes = 30
    record.note_type_id = 7
    record.note_type.name = "Established Visit"
    record.note_type.code = "estab"
    record.provider_id = 101
    record.provider.first_name = "Alice"
    record.provider.last_name = "Chen"
    record.location_id = 3
    record.location.full_name = "Riverside Clinic"
    record.patient_id = 55
    # Set explicitly: an auto-created MagicMock attribute is truthy, which would
    # make every appointment here look like the result of a reschedule.
    record.appointment_rescheduled_from_id = None
    record.appointment_rescheduled_to.exists.return_value = False
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def _entry(name="Jordan Lee"):
    entry = MagicMock()
    entry.patient.first_name = name.split()[0]
    entry.patient.last_name = name.split()[-1]
    entry.priority_label = "High"
    entry.preferred_windows = []
    entry.preferred_window_note = ""
    entry.note = ""
    entry.note_type.name = "Established Visit"
    entry.provider_preference = "specific"
    entry.desired_provider.first_name = "Alice"
    entry.desired_provider.last_name = "Chen"
    entry.location_preference = "specific"
    entry.desired_location.full_name = "Riverside Clinic"
    entry.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    return entry


BANNER = "banner-effect"

MISSING = object()


class _Ctx:
    """Patches everything the handler touches, with sensible defaults."""

    def __init__(
        self,
        appointment=None,
        entries=None,
        claimed=True,
        team_id="team-1",
        origin=MISSING,
        existing_task_id="task-earlier",
    ):
        self.appointment = appointment if appointment is not None else _appointment()
        self.entries = entries if entries is not None else [_entry()]
        self.claimed = claimed
        self.team_id = team_id
        # What an already-present ledger row carries. A row that really was
        # announced has a task id; one that matched nobody has an empty string,
        # and must not block a later attempt. A MagicMock's auto-attribute is
        # truthy, so leaving this implicit hid that distinction entirely.
        self.existing_task_id = existing_task_id
        # The appointment a reschedule was moved away from, returned by the
        # handler's second lookup. ``MISSING`` means no second lookup is
        # expected; ``None`` means one happens and finds nothing.
        self.origin = origin
        self.ledger = MagicMock()
        self.ledger.task_id = existing_task_id

    def __enter__(self):
        self._patches = [
            patch(f"{MODULE}.Appointment"),
            patch(f"{MODULE}.SlotNotification"),
            patch(f"{MODULE}.find_matching_entries", return_value=self.entries),
            patch(f"{MODULE}.find_entries_for_appointment", return_value=[]),
            patch(f"{MODULE}.resolve_team_id", return_value=self.team_id),
            patch(f"{MODULE}.apply_transition"),
            patch(f"{MODULE}.banner_effects", return_value=[BANNER]),
        ]
        (
            self.appointment_model,
            self.notification_model,
            self.matcher,
            self.rearm_lookup,
            self.team_resolver,
            self.transition,
            self.banner,
        ) = [p.start() for p in self._patches]

        queryset = self.appointment_model.objects.filter.return_value.select_related.return_value
        if self.origin is MISSING:
            queryset.first.return_value = self.appointment
        else:
            # First lookup resolves the event's appointment, second follows the
            # reschedule back to the slot that actually opened.
            queryset.first.side_effect = [self.appointment, self.origin]
        self.notification_model.objects.get_or_create.return_value = (
            self.ledger,
            self.claimed,
        )
        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()
        return False


def effects_of(handler, **ctx_kwargs):
    with _Ctx(**ctx_kwargs) as ctx:
        return handler.compute(), ctx


class TestPayloadHandling:
    def test_an_event_with_no_identifier_is_ignored(self):
        handler = _handler(appointment_id=None)

        assert handler.compute() == []

    def test_a_missing_appointment_is_ignored(self):
        handler = _handler()
        with _Ctx() as ctx:
            queryset = (
                ctx.appointment_model.objects.filter.return_value.select_related.return_value
            )
            queryset.first.return_value = None

            assert handler.compute() == []

    def test_appointments_marked_entered_in_error_are_excluded(self):
        _, ctx = effects_of(_handler())

        assert (
            ctx.appointment_model.objects.filter.call_args.kwargs["entered_in_error__isnull"]
            is True
        )


class TestGuards:
    def test_a_slot_with_no_service_is_not_announced(self):
        effects, _ = effects_of(_handler(), appointment=_appointment(note_type_id=None))

        assert effects == []

    def test_a_slot_starting_too_soon_is_not_announced(self):
        # Nobody could fill it, so it is not worth interrupting anyone.
        effects, _ = effects_of(
            _handler(), appointment=_appointment(start_offset_days=0)
        )

        assert effects == []

    def test_a_slot_already_in_the_past_is_not_announced(self):
        effects, _ = effects_of(
            _handler(), appointment=_appointment(start_offset_days=-2)
        )

        assert effects == []

    def test_no_matching_patients_means_no_task(self):
        effects, _ = effects_of(_handler(), entries=[])

        assert effects == []

    def test_no_matches_still_records_the_slot_as_handled(self):
        # Otherwise a duplicate event re-runs the whole match for nothing.
        _, ctx = effects_of(_handler(), entries=[])

        ctx.ledger.save.assert_called_once()


class TestDeduplication:
    def test_a_slot_already_announced_raises_no_second_task(self):
        effects, _ = effects_of(_handler(), claimed=False)

        assert effects == []

    def test_the_slot_is_claimed_before_the_match_runs(self):
        # The loser of a race then pays one insert instead of a full query and
        # a duplicate task.
        _, ctx = effects_of(_handler(), claimed=False)

        ctx.matcher.assert_not_called()

    def test_the_claim_is_keyed_on_the_slot_fingerprint(self):
        _, ctx = effects_of(_handler())

        assert "slot_fingerprint" in ctx.notification_model.objects.get_or_create.call_args.kwargs

    def test_a_cancellation_and_a_no_show_claim_the_same_key(self):
        # Same booking, same freed slot; they must not each raise a task. The
        # one appointment object is shared so the two runs differ only in the
        # event that delivered them.
        appointment = _appointment()

        _, cancelled = effects_of(
            _handler(event_type="APPOINTMENT_CANCELED"), appointment=appointment
        )
        _, no_showed = effects_of(
            _handler(event_type="APPOINTMENT_NO_SHOWED"), appointment=appointment
        )

        assert (
            cancelled.notification_model.objects.get_or_create.call_args.kwargs[
                "slot_fingerprint"
            ]
            == no_showed.notification_model.objects.get_or_create.call_args.kwargs[
                "slot_fingerprint"
            ]
        )


class TestTask:
    def test_a_task_and_its_comment_are_returned(self):
        effects, _ = effects_of(_handler())

        assert len(effects) == 2

    def test_the_task_goes_to_the_configured_team(self):
        effects, _ = effects_of(_handler())

        assert effects[0].team_id == "team-1"

    def test_the_task_names_how_many_people_to_ring(self):
        effects, _ = effects_of(_handler(), entries=[_entry("Jordan Lee"), _entry("Sam Poe")])

        assert "2 to call" in effects[0].title

    def test_the_title_carries_no_internal_event_identifier(self):
        # event.type is an integer; reading it put "4" in the task text.
        effects, _ = effects_of(_handler())

        assert "(4)" not in effects[0].title
        assert "(4)" not in effects[1].body

    def test_the_task_is_not_attached_to_any_one_patient(self):
        # It names several people; binding it to one would put a task about
        # everybody on a single person's chart.
        effects, _ = effects_of(_handler())

        assert getattr(effects[0], "patient_id", None) is None

    def test_the_comment_lists_the_matching_patients(self):
        effects, _ = effects_of(_handler())

        assert "Jordan Lee" in effects[1].body

    def test_the_comment_says_nobody_has_been_booked(self):
        effects, _ = effects_of(_handler())

        assert "never books anyone into the slot" in effects[1].body

    def test_the_comment_says_how_the_slot_came_free(self):
        effects, _ = effects_of(_handler(event_type="APPOINTMENT_NO_SHOWED"))

        assert "Marked no-show." in effects[1].body

    def test_the_comment_and_task_share_an_identifier(self):
        effects, _ = effects_of(_handler())

        assert effects[1].task_id == effects[0].id

    def test_an_imminent_slot_is_marked_urgent(self):
        effects, _ = effects_of(_handler(), appointment=_appointment(start_offset_days=1))

        assert effects[0].priority == "urgent"

    def test_a_distant_slot_is_not_marked_urgent(self):
        effects, _ = effects_of(_handler())

        assert effects[0].priority is None


class TestFailClosedOnTeam:
    def test_no_configured_team_means_no_task(self):
        # An unassigned task is a task nobody opens, so guessing a fallback
        # would quietly drop the notification this plugin exists to send.
        effects, _ = effects_of(_handler(), team_id="")

        assert effects == []

    def test_the_failure_is_logged_as_an_error(self):
        import sys

        effects_of(_handler(), team_id="")

        assert sys.modules["logger"].log.error.called


class TestReArm:
    def test_entries_booked_into_this_appointment_go_back_on_the_list(self):
        handler = _handler()
        entry = MagicMock()

        with _Ctx() as ctx:
            ctx.rearm_lookup.return_value = [entry]
            handler.compute()

        assert ctx.transition.call_args.kwargs["to_status"] == "waiting"

    def test_re_arming_happens_even_when_the_slot_is_not_announced(self):
        # The patient belongs back on the list whether or not the freed slot is
        # worth telling anyone about.
        handler = _handler()

        with _Ctx(appointment=_appointment(start_offset_days=0)) as ctx:
            ctx.rearm_lookup.return_value = [MagicMock()]
            handler.compute()

        ctx.transition.assert_called_once()

    def test_re_arming_refreshes_the_patients_chart_banner(self):
        # Their chart said they were booked; the cancellation makes that false.
        handler = _handler()

        with _Ctx() as ctx:
            ctx.rearm_lookup.return_value = [MagicMock()]
            effects = handler.compute()

        assert BANNER in effects

    def test_the_banner_rides_along_even_when_the_slot_is_not_announced(self):
        # The early returns are the easy place to drop it, so they are asserted
        # rather than assumed: a slot too soon to fill still un-books a patient.
        handler = _handler()

        with _Ctx(appointment=_appointment(start_offset_days=0)) as ctx:
            ctx.rearm_lookup.return_value = [MagicMock()]
            effects = handler.compute()

        assert effects == [BANNER]

    def test_the_banner_precedes_the_task_so_the_chart_is_correct_first(self):
        handler = _handler()

        with _Ctx() as ctx:
            ctx.rearm_lookup.return_value = [MagicMock()]
            effects = handler.compute()

        assert effects[0] == BANNER
        assert len(effects) == 3

    def test_nothing_re_armed_means_no_banner_write(self):
        # A cancellation for a patient who was never on the list must not touch
        # their chart.
        handler = _handler()

        with _Ctx() as ctx:
            ctx.rearm_lookup.return_value = []
            effects = handler.compute()

        assert BANNER not in effects
        ctx.banner.assert_not_called()


class TestEventCoverage:
    """Every channel a booked slot can open through.

    A slot frees up whether staff cancel it, the patient cancels it themselves
    in the portal, someone no-shows, or the booking is moved to another time.
    Subscribing only to the staff-side cancellation misses most of them.
    """

    def test_responds_to_a_staff_cancellation(self):
        assert "APPOINTMENT_CANCELED" in SlotFreedHandler.RESPONDS_TO

    def test_responds_to_a_no_show(self):
        assert "APPOINTMENT_NO_SHOWED" in SlotFreedHandler.RESPONDS_TO

    def test_responds_to_a_patient_cancelling_in_the_portal(self):
        # The most common cancellation channel in practice, and the one the
        # plugin was silent on.
        assert "PATIENT_PORTAL__APPOINTMENT_CANCELED" in SlotFreedHandler.RESPONDS_TO

    def test_responds_to_a_patient_rescheduling_in_the_portal(self):
        assert "PATIENT_PORTAL__APPOINTMENT_RESCHEDULED" in SlotFreedHandler.RESPONDS_TO

    def test_responds_to_a_booking_being_moved_to_another_time(self):
        assert "APPOINTMENT_RESCHEDULED" in SlotFreedHandler.RESPONDS_TO

    def test_a_portal_cancellation_raises_a_task_like_any_other(self):
        handler = _handler(event_type="PATIENT_PORTAL__APPOINTMENT_CANCELED")
        effects, _ = effects_of(handler)

        # A task and its comment. No banner here because nothing was re-armed.
        assert [type(effect).__name__ for effect in effects] == [
            "AddTask",
            "AddTaskComment",
        ]

    def test_the_triggering_event_is_recorded_on_the_ledger(self):
        handler = _handler(event_type="PATIENT_PORTAL__APPOINTMENT_CANCELED")
        with _Ctx() as ctx:
            handler.compute()

        defaults = ctx.notification_model.objects.get_or_create.call_args.kwargs["defaults"]
        assert defaults["trigger_event"] == "PATIENT_PORTAL__APPOINTMENT_CANCELED"


class TestRescheduledAwayFreesTheOriginalSlot:
    """A reschedule opens the slot it moved away from, not the one it moved to.

    The event names the new booking, so announcing that appointment would
    advertise a slot that is occupied. The freed slot is the original, reached
    through ``appointment_rescheduled_from_id``.
    """

    def test_the_original_slot_is_announced_rather_than_the_new_booking(self):
        moved_to = _appointment(
            start_offset_days=20,
            dbid=901,
            id="new-appt",
            appointment_rescheduled_from_id=900,
        )
        original = _appointment(start_offset_days=9, dbid=900, id="appt-key")

        handler = _handler(appointment_id="new-appt", event_type="APPOINTMENT_RESCHEDULED")
        with _Ctx(appointment=moved_to, origin=original) as ctx:
            handler.compute()

        # The slot offered to the waitlist is the one that opened up.
        slot = ctx.matcher.call_args.args[0]
        assert slot.appointment_dbid == 900
        assert slot.appointment_id == "appt-key"

    def test_the_original_is_looked_up_by_its_row_id(self):
        moved_to = _appointment(dbid=901, appointment_rescheduled_from_id=900)
        handler = _handler(event_type="APPOINTMENT_RESCHEDULED")

        with _Ctx(appointment=moved_to, origin=_appointment(dbid=900)) as ctx:
            handler.compute()

        second = ctx.appointment_model.objects.filter.call_args_list[1]
        assert second.kwargs["dbid"] == 900
        assert second.kwargs["entered_in_error__isnull"] is True

    def test_an_unloadable_original_falls_back_to_the_event_appointment(self):
        # Better to announce the appointment we have than to go silent.
        moved_to = _appointment(dbid=901, appointment_rescheduled_from_id=900)
        handler = _handler(event_type="APPOINTMENT_RESCHEDULED")

        with _Ctx(appointment=moved_to, origin=None) as ctx:
            effects = handler.compute()

        assert ctx.matcher.call_args.args[0].appointment_dbid == 901
        assert [type(effect).__name__ for effect in effects] == [
            "AddTask",
            "AddTaskComment",
        ]

    def test_a_plain_cancellation_is_not_traced_back(self):
        # Nothing was rescheduled, so there is no second lookup to make.
        handler = _handler()
        with _Ctx() as ctx:
            handler.compute()

        assert ctx.appointment_model.objects.filter.call_count == 1

    def test_a_patient_moved_to_another_time_is_not_put_back_on_the_list(self):
        # They still have an appointment, so re-arming their entry would claim
        # they are waiting when they are booked.
        moved_away = _appointment(dbid=900)
        moved_away.appointment_rescheduled_to.exists.return_value = True
        handler = _handler(event_type="APPOINTMENT_RESCHEDULED")

        with _Ctx(appointment=moved_away) as ctx:
            handler.compute()

        ctx.transition.assert_not_called()

    def test_a_cancelled_patient_is_still_put_back_on_the_list(self):
        handler = _handler()
        with _Ctx() as ctx:
            ctx.rearm_lookup.return_value = [MagicMock()]
            effects = handler.compute()

        ctx.transition.assert_called_once()
        assert BANNER in effects

    def test_the_same_slot_reached_by_reschedule_and_cancel_is_announced_once(self):
        # Both paths fingerprint the original appointment, so the ledger turns
        # the second one away. The one ``original`` object is shared so the two
        # runs describe the same slot rather than two slots a moment apart.
        original = _appointment(dbid=900)
        moved_to = _appointment(dbid=901, appointment_rescheduled_from_id=900)

        with _Ctx(appointment=moved_to, origin=original) as first:
            _handler(event_type="APPOINTMENT_RESCHEDULED").compute()
            first_slot = first.matcher.call_args.args[0]

        with _Ctx(appointment=original) as second:
            _handler(event_type="APPOINTMENT_CANCELED").compute()
            second_slot = second.matcher.call_args.args[0]

        assert first_slot.fingerprint() == second_slot.fingerprint()


class TestAnnouncingNothingDoesNotBurnTheSlot:
    """A slot that matched nobody must still be announceable later.

    The dedup guard exists because one cancellation can reach the plugin several
    times within seconds, and each delivery would otherwise raise its own task.
    It is not meant to mean "this slot may never be announced". Freeing a slot
    while the list is empty, then freeing it again once somebody has joined, is
    exactly the case a scheduler would expect to work -- and it did not.
    """

    def test_a_row_that_raised_no_task_is_claimable_again(self):
        effects, ctx = effects_of(_handler(), claimed=False, existing_task_id="")

        # It got past the guard and matched, so a task is raised.
        assert any(getattr(e, "title", None) for e in effects)
        ctx.matcher.assert_called_once()

    def test_a_row_that_raised_a_task_still_blocks(self):
        # No task, and the match never runs -- a duplicate delivery of one
        # cancellation must not cost a full query, let alone a second task.
        effects, ctx = effects_of(
            _handler(), claimed=False, existing_task_id="task-earlier"
        )

        assert effects == []
        ctx.matcher.assert_not_called()

    def test_a_blank_looking_task_id_counts_as_none(self):
        effects, _ = effects_of(_handler(), claimed=False, existing_task_id="   ")

        assert any(getattr(e, "title", None) for e in effects)

    def test_re_announcing_records_the_freeing_that_counted(self):
        # Otherwise the ledger would keep pointing at the earlier event that
        # announced nothing.
        _, ctx = effects_of(
            _handler(event_type="APPOINTMENT_NO_SHOWED"),
            claimed=False,
            existing_task_id="",
        )

        assert ctx.ledger.trigger_event == "APPOINTMENT_NO_SHOWED"
        assert ctx.ledger.notified_at is not None

    def test_the_task_id_is_stored_so_the_next_delivery_is_blocked(self):
        _, ctx = effects_of(_handler(), claimed=False, existing_task_id="")

        assert ctx.ledger.task_id
        ctx.ledger.save.assert_called()


class TestTheOutcomeIsAlwaysLogged:
    """Both endings used to be inferable only from the absence of other lines."""

    def test_matching_nobody_says_so(self):
        import sys

        sys.modules["logger"].log.info.reset_mock()
        effects_of(_handler(), entries=[])

        logged = " ".join(str(c) for c in sys.modules["logger"].log.info.call_args_list)
        assert "matched nobody" in logged

    def test_raising_a_task_says_how_many_matched(self):
        import sys

        sys.modules["logger"].log.info.reset_mock()
        effects_of(_handler(), entries=[_entry("Jordan Lee"), _entry("Sam Poe")])

        logged = " ".join(str(c) for c in sys.modules["logger"].log.info.call_args_list)
        assert "matched 2 waitlisted patients" in logged

    def test_one_match_reads_in_the_singular(self):
        import sys

        sys.modules["logger"].log.info.reset_mock()
        effects_of(_handler(), entries=[_entry()])

        logged = " ".join(str(c) for c in sys.modules["logger"].log.info.call_args_list)
        assert "matched 1 waitlisted patient;" in logged
