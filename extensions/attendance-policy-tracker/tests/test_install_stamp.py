"""The one time write that gives the counting engine its install floor.

Exercised through the pure stamping function rather than through the handler
and the event plumbing behind it, because the decision worth pinning is read
before write, not how the platform delivers PLUGIN_CREATED. The handler
itself stays a thin shell around this.
"""

from unittest.mock import patch

import arrow
from canvas_sdk.events import Event, EventRequest, EventType

from attendance_policy_tracker.handlers.install_stamp import (
    INSTALL_FLOOR_KEY,
    PLUGIN_NAME,
    InstallFloorStamp,
    stamp_install_moment,
)

NOW = arrow.get("2026-08-14T12:00:00+00:00")

MODULE = "attendance_policy_tracker.handlers.install_stamp"


class FakeStore:
    """A settings store backed by a dictionary, the same shape the plugin uses."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def read(self):
        return dict(self.values)

    def write(self, values):
        for key, value in values.items():
            if f"{value}".strip():
                self.values[key] = f"{value}".strip()
            else:
                self.values.pop(key, None)


class TestStampInstallMoment:
    def test_an_absent_stamp_is_written_as_an_iso_utc_moment(self):
        store = FakeStore()
        wrote = stamp_install_moment(store, now=NOW.datetime)
        assert wrote is True
        assert store.values[INSTALL_FLOOR_KEY] == NOW.to("utc").isoformat()

    def test_an_empty_stamp_is_treated_the_same_as_absent(self):
        store = FakeStore({INSTALL_FLOOR_KEY: ""})
        wrote = stamp_install_moment(store, now=NOW.datetime)
        assert wrote is True
        assert store.values[INSTALL_FLOOR_KEY] == NOW.to("utc").isoformat()

    def test_a_second_call_does_not_move_an_existing_stamp(self):
        store = FakeStore()
        stamp_install_moment(store, now=NOW.datetime)
        first_stamp = store.values[INSTALL_FLOOR_KEY]

        later = NOW.shift(days=5).datetime
        wrote_again = stamp_install_moment(store, now=later)

        assert wrote_again is False
        assert store.values[INSTALL_FLOOR_KEY] == first_stamp


def _plugin_created_event(target_name: str) -> Event:
    """A PLUGIN_CREATED event naming whichever plugin was just installed."""
    request = EventRequest(
        type=EventType.PLUGIN_CREATED, target=target_name, target_type=None, context="{}"
    )
    return Event(request)


class TestInstallFloorStampHandler:
    """The thin shell around stamp_install_moment, and the one thing that
    belongs to it rather than the pure function, telling this plugin's own
    install apart from everybody else's on the same instance.
    """

    def test_this_plugins_own_install_event_stamps_the_floor(self) -> None:
        with patch(f"{MODULE}.NamespaceSettingsStore") as store_cls, patch(
            f"{MODULE}.stamp_install_moment"
        ) as stamp_fn:
            handler = InstallFloorStamp(_plugin_created_event(PLUGIN_NAME))
            effects = handler.compute()

        assert effects == []
        stamp_fn.assert_called_once_with(store_cls.return_value)

    def test_a_different_plugins_install_event_is_left_alone(self) -> None:
        with patch(f"{MODULE}.NamespaceSettingsStore"), patch(
            f"{MODULE}.stamp_install_moment"
        ) as stamp_fn:
            handler = InstallFloorStamp(_plugin_created_event("some-other-plugin"))
            effects = handler.compute()

        assert effects == []
        stamp_fn.assert_not_called()
