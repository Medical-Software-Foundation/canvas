"""Schema decisions that are easy to undo by accident.

These assert on field declarations rather than behavior. That is unusual, but
each one guards a choice with a real failure mode behind it, and the plugin
schema pipeline offers no migrations to catch a regression later.
"""

from scheduling_waitlist.constants import PREFERENCE_SPECIFIC, STATUS_WAITING
from scheduling_waitlist.models import SlotNotification, WaitlistEntry


def _field(model, name):
    return model.__dict__[name]


def _meta_index_names(model):
    return {index.kwargs["name"] for index in model.Meta.indexes}


def _meta_constraint_names(model):
    return {constraint.kwargs["name"] for constraint in model.Meta.constraints}


class TestProviderAndLocationPreference:
    def test_provider_preference_is_stored_not_inferred_from_a_null_key(self):
        # The schema pipeline emits no NOT NULL, so a null foreign key cannot be
        # told apart from one never filled in. Reading null as "any" would make
        # a malformed row match every open slot -- failing open. Storing the
        # intent means a malformed row matches nothing.
        assert _field(WaitlistEntry, "provider_preference").default == PREFERENCE_SPECIFIC

    def test_location_preference_is_stored_the_same_way(self):
        assert _field(WaitlistEntry, "location_preference").default == PREFERENCE_SPECIFIC

    def test_desired_provider_is_optional(self):
        assert _field(WaitlistEntry, "desired_provider").null is True

    def test_desired_location_is_optional(self):
        assert _field(WaitlistEntry, "desired_location").null is True


class TestPriority:
    def test_rank_and_label_are_both_stored(self):
        # Label alone would mean re-reading configuration on every query and
        # reordering the backlog whenever it changed; rank alone would leave the
        # roster unreadable after such a change.
        assert _field(WaitlistEntry, "priority_rank") is not None
        assert _field(WaitlistEntry, "priority_label") is not None

    def test_rank_defaults_to_the_most_urgent_position(self):
        assert _field(WaitlistEntry, "priority_rank").default == 0


class TestPreferredWindows:
    def test_windows_are_json_not_an_array_field(self):
        # ArrayField is silently rewritten to JSONField on SQLite, so tests and
        # production would disagree. Declaring JSON keeps them identical.
        assert type(_field(WaitlistEntry, "preferred_windows")).__name__ == "JSONField"

    def test_windows_default_to_empty(self):
        assert _field(WaitlistEntry, "preferred_windows").default == list

    def test_a_timezone_is_captured_alongside_the_window(self):
        # Appointment times are UTC and locations carry no timezone, so without
        # this "Tuesday morning" cannot be evaluated against a slot later.
        assert _field(WaitlistEntry, "preferred_windows_timezone") is not None

    def test_free_text_window_note_is_kept_as_an_escape_hatch(self):
        assert _field(WaitlistEntry, "preferred_window_note") is not None


class TestLifecycleFields:
    def test_new_entries_start_waiting(self):
        assert _field(WaitlistEntry, "status").default == STATUS_WAITING

    def test_expiry_is_stamped_per_entry_rather_than_recomputed(self):
        # Snapshotting at creation keeps a configuration change from
        # retroactively expiring a backlog added under the old value.
        assert _field(WaitlistEntry, "expires_on").null is True

    def test_the_satisfying_appointment_is_recorded(self):
        # Makes the automatic status change auditable and reversible, and lets
        # the matcher skip the entry belonging to the slot that just freed up.
        assert _field(WaitlistEntry, "scheduled_appointment").null is True


class TestIndexesAndConstraints:
    def test_roster_and_match_query_have_a_covering_index(self):
        assert "wl_entry_status_priority" in _meta_index_names(WaitlistEntry)

    def test_the_ageing_sweep_has_an_index(self):
        assert "wl_entry_status_expiry" in _meta_index_names(WaitlistEntry)

    def test_no_index_is_declared_on_a_foreign_key_column(self):
        # Foreign keys are indexed automatically and re-declaring them raises at
        # import time.
        key_fields = {
            "patient",
            "note_type",
            "desired_provider",
            "desired_location",
            "scheduled_appointment",
            "created_by",
            "status_changed_by",
        }
        for index in WaitlistEntry.Meta.indexes:
            assert not key_fields.intersection(index.kwargs["fields"])

    def test_one_live_entry_per_patient_and_type(self):
        assert "wl_entry_one_live_per_patient_type" in _meta_constraint_names(WaitlistEntry)

    def test_that_uniqueness_only_applies_to_live_entries(self):
        # A closed entry must not block the same patient asking again.
        constraint = next(
            c
            for c in WaitlistEntry.Meta.constraints
            if c.kwargs["name"] == "wl_entry_one_live_per_patient_type"
        )

        assert constraint.kwargs["condition"].leaves() == [
            {"status__in": ["waiting", "offered"]}
        ]


class TestSlotNotification:
    def test_the_fingerprint_is_unique(self):
        # This uniqueness is the whole deduplication guarantee: two events for
        # the same freed slot cannot both raise a task.
        assert "wl_slotnotif_unique_fingerprint" in _meta_constraint_names(SlotNotification)

    def test_the_prune_sweep_has_an_index(self):
        assert "wl_slotnotif_notified" in _meta_index_names(SlotNotification)
