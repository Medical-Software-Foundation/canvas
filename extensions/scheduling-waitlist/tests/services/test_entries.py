"""Building the roster query."""

from unittest.mock import MagicMock, patch

import pytest

from scheduling_waitlist.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PREFERENCE_ANY
from scheduling_waitlist.services.entries import (
    EDITABLE_FIELDS,
    ENTRY_RELATIONS,
    DuplicateEntryError,
    create_entry,
    find_live_entry,
    get_entry,
    has_live_entry_for_service,
    live_entries_for_patient,
    update_entry,
    SORT_PRIORITY,
    build_queryset,
    list_entries,
    normalize_limit,
    normalize_offset,
    normalize_sort,
)


class _Recorder:
    """Records every queryset call so the built query can be asserted on.

    Recorded values are kept under ``*_args`` names so they cannot shadow the
    queryset methods they record.
    """

    def __init__(self):
        self.filters = []
        self.select_related_args = ()
        self.order_by_args = ()
        self.slice = None
        self.count_value = 0
        self.items = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def select_related(self, *args):
        self.select_related_args = args
        return self

    def order_by(self, *args):
        self.order_by_args = args
        return self

    def count(self):
        return self.count_value

    def all(self):
        return self

    def __getitem__(self, item):
        self.slice = item
        return self.items

    def __iter__(self):
        # Without this, list(queryset) falls back to the legacy iteration
        # protocol and calls __getitem__ with rising indexes forever, since
        # this stub never raises IndexError.
        return iter(self.items)


def _recorder():
    return _Recorder()


def _filter_kwargs(recorder):
    merged = {}
    for _args, kwargs in recorder.filters:
        merged.update(kwargs)
    return merged


def _filter_args(recorder):
    found = []
    for args, _kwargs in recorder.filters:
        found.extend(args)
    return found


def _filter_leaves(recorder):
    """Every leaf condition across the Q objects the query was filtered with."""
    leaves = []
    for arg in _filter_args(recorder):
        leaves.extend(arg.leaves())
    return leaves


class TestNormalizeSort:
    def test_blank_falls_back_to_priority(self):
        assert normalize_sort("") == (SORT_PRIORITY, False)

    def test_unknown_key_falls_back_rather_than_failing(self):
        # A stale bookmark should still render the roster.
        assert normalize_sort("colour") == (SORT_PRIORITY, False)

    def test_known_key_is_accepted(self):
        assert normalize_sort("wait") == ("wait", False)

    def test_leading_minus_reverses_the_direction(self):
        assert normalize_sort("-wait") == ("wait", True)

    def test_none_falls_back_to_priority(self):
        assert normalize_sort(None) == (SORT_PRIORITY, False)


class TestNormalizeLimit:
    def test_absent_uses_the_default_page_size(self):
        assert normalize_limit(None) == DEFAULT_PAGE_SIZE

    def test_valid_value_is_used(self):
        assert normalize_limit("25") == 25

    def test_oversized_value_is_capped(self):
        assert normalize_limit("100000") == MAX_PAGE_SIZE

    def test_zero_and_negative_fall_back_to_the_default(self):
        assert normalize_limit("0") == DEFAULT_PAGE_SIZE
        assert normalize_limit("-5") == DEFAULT_PAGE_SIZE

    def test_non_numeric_is_rejected_so_the_caller_can_explain_why(self):
        assert normalize_limit("lots") is None


class TestNormalizeOffset:
    def test_absent_starts_at_the_beginning(self):
        assert normalize_offset(None) == 0

    def test_valid_value_is_used(self):
        assert normalize_offset("40") == 40

    def test_negative_is_clamped_to_zero(self):
        assert normalize_offset("-10") == 0

    def test_non_numeric_is_rejected(self):
        assert normalize_offset("later") is None


class TestBuildQueryset:
    def _build(self, **kwargs):
        recorder = _recorder()
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.all.return_value = recorder
            build_queryset(**kwargs)
        return recorder

    def test_defaults_to_the_live_statuses_only(self):
        # The roster is a list of people still waiting; closed entries stay out
        # until someone asks for them.
        recorder = self._build()

        assert _filter_kwargs(recorder)["status__in"] == ["waiting", "offered"]

    def test_an_explicit_status_replaces_the_default(self):
        recorder = self._build(status="expired")

        merged = _filter_kwargs(recorder)
        assert merged["status"] == "expired"
        assert "status__in" not in merged

    def test_search_matches_either_part_of_the_patient_name(self):
        recorder = self._build(search="lee")

        conditions = _filter_args(recorder)
        assert conditions, "expected a search condition"
        assert conditions[0].leaves() == [
            {"patient__first_name__icontains": "lee"},
            {"patient__last_name__icontains": "lee"},
        ]

    def test_a_whitespace_only_search_is_ignored(self):
        recorder = self._build(search="   ")

        assert _filter_args(recorder) == []

    def test_a_named_type_also_keeps_entries_that_accept_any_type(self):
        # Filtering the roster by a service asks "who could take a slot like
        # this?", and somebody waiting for anything qualifies. Filtering on
        # note_type_id alone hid exactly those people.
        leaves = _filter_leaves(self._build(note_type_dbid=7))

        assert {"note_type_id": 7} in leaves
        assert {"note_type__isnull": True} in leaves

    def test_provider_any_matches_entries_that_accept_anyone(self):
        # The REST behaviour: PREFERENCE_ANY narrows to the any-provider entries
        # rather than widening. The roster's filter bar does not offer this.
        recorder = self._build(provider_dbid=PREFERENCE_ANY)

        assert _filter_kwargs(recorder)["provider_preference"] == PREFERENCE_ANY

    def test_a_named_provider_also_keeps_entries_that_accept_anyone(self):
        # The bug this class exists for. A patient who will see any provider is
        # the most likely candidate for a named provider's freed slot, and the
        # roster used to deny they existed while the matcher named them.
        leaves = _filter_leaves(self._build(provider_dbid=101))

        assert {"desired_provider_id": 101} in leaves
        assert {"provider_preference": PREFERENCE_ANY} in leaves

    def test_location_any_matches_entries_that_accept_anywhere(self):
        recorder = self._build(location_dbid=PREFERENCE_ANY)

        assert _filter_kwargs(recorder)["location_preference"] == PREFERENCE_ANY

    def test_a_named_location_also_keeps_entries_that_accept_anywhere(self):
        leaves = _filter_leaves(self._build(location_dbid=3))

        assert {"desired_location_id": 3} in leaves
        assert {"location_preference": PREFERENCE_ANY} in leaves

    def test_the_roster_filter_agrees_with_the_freed_slot_matcher(self):
        """The two used to disagree, which is why they now share the predicates.

        A roster that hides a patient the next cancellation will name is worse
        than either behaviour on its own -- it makes the task look wrong.
        """
        from scheduling_waitlist.services.matching import compatibility_q

        roster = _filter_leaves(self._build(provider_dbid=101))
        matcher = compatibility_q(None, 101, None).leaves()

        for leaf in ({"desired_provider_id": 101}, {"provider_preference": PREFERENCE_ANY}):
            assert leaf in roster
            assert leaf in matcher

    def test_blank_filters_are_not_applied(self):
        recorder = self._build(
            note_type_dbid=None, provider_dbid=None, location_dbid=None, priority_label=""
        )

        assert _filter_args(recorder) == []
        assert "priority_label" not in _filter_kwargs(recorder)

    def test_related_rows_are_selected_up_front(self):
        # Without this, a page of 100 rows becomes hundreds of queries because
        # every serialized row reads its patient, type, provider, and location.
        recorder = self._build()

        assert set(recorder.select_related_args) == set(ENTRY_RELATIONS)

    def test_default_order_is_priority_then_longest_waiting(self):
        recorder = self._build()

        assert recorder.order_by_args == ("priority_rank", "created_at", "dbid")

    def test_order_has_a_deterministic_tiebreak(self):
        recorder = self._build()

        assert recorder.order_by_args[-1] == "dbid"

    def test_descending_flips_only_the_leading_column(self):
        # The tiebreakers must stay ascending or equal rows shuffle between
        # requests.
        recorder = self._build(sort="wait", descending=True)

        assert recorder.order_by_args == ("-created_at", "dbid")


class TestListEntries:
    def test_returns_the_page_and_the_unpaged_total(self):
        recorder = _recorder()
        recorder.count_value = 137
        recorder.items = [MagicMock(), MagicMock()]

        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.all.return_value = recorder
            entries, total = list_entries(limit=2, offset=0)

        assert len(entries) == 2
        assert total == 137

    def test_slices_by_the_requested_page(self):
        recorder = _recorder()

        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.all.return_value = recorder
            list_entries(limit=25, offset=50)

        assert recorder.slice == slice(50, 75)


class TestCreateEntry:
    def test_a_new_entry_records_who_added_it(self):
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value.first.return_value = (
                None
            )
            create_entry(created_by_dbid=101, patient_id=55, note_type_id=7)

        assert model.objects.create.call_args.kwargs["created_by_id"] == 101

    def test_a_second_live_entry_for_the_same_service_is_refused(self):
        # Both surfaces post here, so the same patient can be submitted twice.
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value.first.return_value = (
                MagicMock()
            )

            with pytest.raises(DuplicateEntryError):
                create_entry(created_by_dbid=101, patient_id=55, note_type_id=7)

            model.objects.create.assert_not_called()

    def test_losing_a_concurrent_race_is_reported_as_a_duplicate(self):
        from django.db import IntegrityError

        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value.first.return_value = (
                None
            )
            model.objects.create.side_effect = IntegrityError("unique violation")

            with pytest.raises(DuplicateEntryError):
                create_entry(created_by_dbid=101, patient_id=55, note_type_id=7)


class TestFindLiveEntry:
    def test_only_live_entries_block_a_new_one(self):
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value.first.return_value = (
                None
            )
            find_live_entry(55, 7)

        kwargs = model.objects.filter.call_args.kwargs
        assert kwargs["status__in"] == ["waiting", "offered"]
        assert kwargs["patient_id"] == 55


class TestUpdateEntry:
    def test_editable_fields_are_applied_and_saved(self):
        entry = MagicMock()

        update_entry(entry, note="revised", priority_label="High")

        assert entry.note == "revised"
        assert entry.priority_label == "High"
        entry.save.assert_called_once()

    def test_the_patient_cannot_be_reassigned_by_an_edit(self):
        # An entry belongs to the person it was created for; moving it would
        # quietly change someone's place in the queue.
        entry = MagicMock()
        entry.patient_id = 55

        update_entry(entry, patient_id=999, note="revised")

        assert entry.patient_id == 55

    def test_an_edit_that_changes_nothing_does_not_write(self):
        entry = MagicMock()

        update_entry(entry, unknown_field="x")

        entry.save.assert_not_called()


class TestGetEntry:
    def test_related_rows_are_selected(self):
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value.first.return_value = (
                None
            )
            get_entry(42)

        selected = model.objects.filter.return_value.select_related.call_args[0]
        assert "patient" in selected


class TestLiveEntriesForPatient:
    """What the chart banner reads to decide whether to appear."""

    def test_only_matchable_statuses_count_as_waiting(self):
        # A patient whose only entry was booked or removed is not waiting, and
        # their chart must not claim otherwise.
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value = []
            live_entries_for_patient(55)

        kwargs = model.objects.filter.call_args.kwargs
        assert kwargs["status__in"] == ["waiting", "offered"]
        assert kwargs["patient_id"] == 55

    def test_related_rows_are_selected_for_the_narrative(self):
        # The banner names the service, so fetching it lazily would be a query
        # per entry on a path that runs on every write.
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value = []
            live_entries_for_patient(55)

        assert model.objects.filter.return_value.select_related.call_args.args == (
            ENTRY_RELATIONS
        )

    def test_a_missing_patient_identifier_queries_nothing(self):
        # Filtering on a null patient would match every entry with a null
        # patient, which is the opposite of "this patient is waiting".
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            assert live_entries_for_patient(None) == []

        model.objects.filter.assert_not_called()

    def test_matches_are_returned_as_a_list(self):
        entries = [MagicMock(), MagicMock()]

        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.select_related.return_value = entries
            assert live_entries_for_patient(55) == entries


class TestEditableFieldsStayInStep:
    """``update_entry`` assigns field by field, so the list can drift from it.

    The sandbox blocks ``setattr``, which is why the assignments are written out.
    That trades a loop for duplication, and this is the test that makes the
    duplication safe.
    """

    def test_every_editable_field_is_assignable(self):
        for name in EDITABLE_FIELDS:
            entry = MagicMock()

            update_entry(entry, **{name: "value"})

            assert getattr(entry, name) == "value", f"{name} was not assigned"
            entry.save.assert_called_once()

    def test_a_field_outside_the_list_is_ignored(self):
        # The patient in particular: reassigning it through a request body would
        # quietly move someone else's place in the queue.
        entry = MagicMock()

        update_entry(entry, patient_id=999)

        entry.save.assert_not_called()

    def test_nothing_to_change_does_not_write(self):
        entry = MagicMock()

        update_entry(entry)

        entry.save.assert_not_called()


class TestHasLiveEntryForService:
    """The narrower question the freed-appointment button asks."""

    def test_it_is_scoped_to_one_patient_and_one_service(self):
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.exists.return_value = True

            assert has_live_entry_for_service(55, 7) is True

        kwargs = model.objects.filter.call_args.kwargs
        assert kwargs["patient_id"] == 55
        assert kwargs["note_type_id"] == 7
        assert kwargs["status__in"] == ["waiting", "offered"]

    def test_only_live_statuses_count(self):
        # A booked or removed entry is not something they are still waiting for.
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.exists.return_value = False

            assert has_live_entry_for_service(55, 7) is False

    def test_a_missing_patient_asks_nothing(self):
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            assert has_live_entry_for_service(None, 7) is False

        model.objects.filter.assert_not_called()

    def test_a_slot_without_a_service_asks_nothing(self):
        # Filtering on a null note type would match "any appointment type" entries
        # and claim they are waiting for a service the slot never named.
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            assert has_live_entry_for_service(55, None) is False

        model.objects.filter.assert_not_called()

    def test_it_answers_with_exists_rather_than_building_a_model(self):
        # It runs on every note header render.
        with patch("scheduling_waitlist.services.entries.WaitlistEntry") as model:
            model.objects.filter.return_value.exists.return_value = True

            has_live_entry_for_service(55, 7)

        model.objects.filter.return_value.exists.assert_called_once()
        model.objects.filter.return_value.select_related.assert_not_called()
