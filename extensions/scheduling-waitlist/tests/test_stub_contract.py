"""Guards on the test doubles themselves.

These stubs stand in for SDK behavior the suite relies on. If a stub drifts from
the real SDK, every test above it keeps passing while production breaks, so the
few behaviors we actually depend on are pinned here.
"""

import pytest


class TestLaunchModalEffectStub:
    """The roster is launched by url, and the real effect refuses url+content."""

    def test_url_only_is_accepted(self):
        from canvas_sdk.effects.launch_modal import LaunchModalEffect

        effect = LaunchModalEffect(url="/plugin-io/api/scheduling_waitlist/app/")

        assert effect.url == "/plugin-io/api/scheduling_waitlist/app/"
        assert effect.content is None

    def test_url_and_content_together_raise(self):
        from canvas_sdk.effects.launch_modal import LaunchModalEffect

        with pytest.raises(ValueError, match="mutually exclusive"):
            LaunchModalEffect(url="/somewhere", content="<p>form</p>")

    def test_default_modal_target_is_available(self):
        from canvas_sdk.effects.launch_modal import LaunchModalEffect

        assert LaunchModalEffect.TargetType.DEFAULT_MODAL == "default_modal"


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


class TestBannerAlertStub:
    """The chart banner depends on a placement, a stable key, and a length cap."""

    def test_chart_placement_exists(self):
        from canvas_sdk.effects.banner_alert.add_banner_alert import AddBannerAlert

        assert AddBannerAlert.Placement.CHART.value == "chart"

    def test_info_intent_exists(self):
        from canvas_sdk.effects.banner_alert.add_banner_alert import AddBannerAlert

        assert AddBannerAlert.Intent.INFO.value == "info"

    def test_narrative_longer_than_ninety_characters_raises(self):
        from canvas_sdk.effects.banner_alert.add_banner_alert import AddBannerAlert

        with pytest.raises(ValueError, match="90"):
            AddBannerAlert(
                patient_id="p1",
                key="scheduling_waitlist",
                narrative="x" * 91,
                placement=[AddBannerAlert.Placement.CHART],
                intent=AddBannerAlert.Intent.INFO,
            )

    def test_remove_requires_only_patient_and_key(self):
        from canvas_sdk.effects.banner_alert.remove_banner_alert import RemoveBannerAlert

        effect = RemoveBannerAlert(patient_id="p1", key="scheduling_waitlist")

        assert effect.patient_id == "p1"
        assert effect.key == "scheduling_waitlist"


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

        for name in (
            "APPOINTMENT_CANCELED",
            "APPOINTMENT_NO_SHOWED",
            "APPOINTMENT_CREATED",
            "APPOINTMENT_RESCHEDULED",
            "PATIENT_PORTAL__APPOINTMENT_CANCELED",
            "PATIENT_PORTAL__APPOINTMENT_RESCHEDULED",
        ):
            assert EventType.Name(getattr(EventType, name)) == name

    def test_every_event_the_handlers_subscribe_to_exists_in_the_stub(self):
        """Guards against a handler naming an event the stub does not carry.

        The stub is a hand-written list, so an event added to a handler but not
        here fails at import rather than at the assertion -- this makes the
        omission explicit instead.
        """
        from scheduling_waitlist.handlers.appointment_booked import (
            AppointmentBookedHandler,
        )
        from scheduling_waitlist.handlers.slot_freed import SlotFreedHandler

        from tests.conftest import _EventType

        subscribed = set(SlotFreedHandler.RESPONDS_TO) | set(
            AppointmentBookedHandler.RESPONDS_TO
        )
        assert subscribed <= set(_EventType._NAMES)


class TestResponseStubs:
    """The response stubs must accept what the real effects accept.

    A stub with a narrower signature fails only under test, which is backwards:
    the suite is meant to catch what the instance would reject, not invent its
    own rejections.
    """

    def test_html_response_accepts_headers(self):
        from canvas_sdk.effects.simple_api import HTMLResponse

        response = HTMLResponse("<p>hi</p>", headers={"Cache-Control": "no-cache"})

        assert response.headers["Cache-Control"] == "no-cache"

    def test_json_response_accepts_headers(self):
        from canvas_sdk.effects.simple_api import JSONResponse

        response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-cache"})

        assert response.headers["Cache-Control"] == "no-cache"

    def test_html_response_defaults_to_no_headers(self):
        from canvas_sdk.effects.simple_api import HTMLResponse

        assert HTMLResponse("<p>hi</p>").headers == {}


class TestAppointmentStatusStub:
    """The freed-slot statuses the appointment button keys off.

    ``str()`` of a real ``TextChoices`` member is its stored value, which is what
    the handler compares against -- so the stub has to be those strings, not the
    member names.
    """

    def test_cancelled_and_noshowed_are_their_stored_values(self):
        from canvas_sdk.v1.data.appointment import AppointmentProgressStatus

        assert str(AppointmentProgressStatus.CANCELLED) == "cancelled"
        assert str(AppointmentProgressStatus.NOSHOWED) == "noshowed"

    def test_a_booked_status_is_not_one_of_them(self):
        from scheduling_waitlist.handlers.appointment_button import FREED_STATUSES

        assert "confirmed" not in FREED_STATUSES
        assert "cancelled" in FREED_STATUSES
        assert "noshowed" in FREED_STATUSES


class TestNoteStatesStub:
    """The note states the appointment button keys off.

    Stored codes, not member names: the handler compares strings, so a stub with
    readable names would pass the suite and fail on the instance.
    """

    def test_cancelled_and_noshow_are_their_stored_codes(self):
        from canvas_sdk.v1.data.note import NoteStates

        assert str(NoteStates.CANCELLED) == "CLD"
        assert str(NoteStates.NOSHOW) == "NSW"

    def test_the_freed_set_holds_the_codes_not_the_names(self):
        from scheduling_waitlist.handlers.appointment_button import FREED_NOTE_STATES

        assert FREED_NOTE_STATES == {"CLD", "NSW"}
