"""Guards on the test doubles themselves.

These stubs stand in for SDK behavior the suite relies on. If a stub drifts from
the real SDK, every test above it keeps passing while production breaks, so the
few behaviors we actually depend on are pinned here.
"""

import pytest


class TestLaunchModalEffectStub:
    """The real effect rejects url+content together; the stub must too."""

    def test_url_only_is_accepted(self):
        from canvas_sdk.effects.launch_modal import LaunchModalEffect

        effect = LaunchModalEffect(url="/plugin-io/api/scheduling_waitlist/app/")

        assert effect.url == "/plugin-io/api/scheduling_waitlist/app/"
        assert effect.content is None

    def test_content_only_is_accepted(self):
        from canvas_sdk.effects.launch_modal import LaunchModalEffect

        effect = LaunchModalEffect(content="<p>form</p>")

        assert effect.content == "<p>form</p>"
        assert effect.url is None

    def test_url_and_content_together_raise(self):
        from canvas_sdk.effects.launch_modal import LaunchModalEffect

        with pytest.raises(ValueError, match="mutually exclusive"):
            LaunchModalEffect(url="/somewhere", content="<p>form</p>")

    def test_right_chart_pane_target_is_available(self):
        from canvas_sdk.effects.launch_modal import LaunchModalEffect

        assert LaunchModalEffect.TargetType.RIGHT_CHART_PANE == "right_chart_pane"


class TestAuthMixinImportPaths:
    """Both import paths are real SDK exports and both are used in this repo."""

    def test_mixin_importable_from_package(self):
        from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin

        assert StaffSessionAuthMixin is not None

    def test_mixin_importable_from_security_module(self):
        from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin

        assert StaffSessionAuthMixin is not None

    def test_both_paths_yield_the_same_class(self):
        from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin as from_package
        from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin as from_security

        assert from_package is from_security


class TestActionButtonStub:
    def test_chart_patient_header_location_exists(self):
        from canvas_sdk.handlers.action_button import ActionButton

        assert ActionButton.ButtonLocation.CHART_PATIENT_HEADER == "chart_patient_header"

    def test_note_header_location_exists(self):
        from canvas_sdk.handlers.action_button import ActionButton

        assert ActionButton.ButtonLocation.NOTE_HEADER == "note_header"

    def test_context_returns_empty_dict_when_event_context_is_not_a_dict(self):
        from canvas_sdk.handlers.action_button import ActionButton

        button = ActionButton(event=None)

        assert button.context == {}


class TestNoteStatesStub:
    def test_cancelled_and_noshow_states_exist(self):
        from canvas_sdk.v1.data.note import NoteStates

        assert NoteStates.CANCELLED == "CLD"
        assert NoteStates.NOSHOW == "NSW"


class TestQStub:
    """The match predicate is the feature, so Q has to keep its tree."""

    def test_or_records_both_branches(self):
        from django.db.models import Q

        combined = Q(provider_preference="any") | Q(desired_provider_id=4)

        assert combined.connector == "OR"
        assert combined.leaves() == [{"provider_preference": "any"}, {"desired_provider_id": 4}]

    def test_and_records_both_branches(self):
        from django.db.models import Q

        combined = Q(a=1) & Q(b=2)

        assert combined.connector == "AND"
        assert combined.leaves() == [{"a": 1}, {"b": 2}]

    def test_nested_composition_flattens_in_order(self):
        from django.db.models import Q

        combined = (Q(a=1) | Q(b=2)) & Q(c=3)

        assert combined.leaves() == [{"a": 1}, {"b": 2}, {"c": 3}]

    def test_equal_trees_compare_equal(self):
        from django.db.models import Q

        assert (Q(a=1) | Q(b=2)) == (Q(a=1) | Q(b=2))

    def test_different_connectors_compare_unequal(self):
        from django.db.models import Q

        assert (Q(a=1) | Q(b=2)) != (Q(a=1) & Q(b=2))


class TestEventTypeStub:
    def test_name_round_trips_for_the_events_this_plugin_uses(self):
        from canvas_sdk.events import EventType

        for name in ("APPOINTMENT_CANCELED", "APPOINTMENT_NO_SHOWED", "APPOINTMENT_CREATED"):
            assert EventType.Name(getattr(EventType, name)) == name
