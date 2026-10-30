"""Stamps this plugin's own install moment into its storage, once.

Clinical history predating a fresh install currently counts toward every
total, so a fresh install would immediately attribute incidents nobody was
ever told to track. The platform offers no way to read the install moment
from inside the sandbox, there is no field on the plugin and no query into
its own history, so the only way to know that moment is to capture it at the
one instant it is knowable, when the platform tells this plugin it exists.

The platform emits PLUGIN_CREATED exactly once when a plugin is first
installed, and again on a reinstall, but never on a version upgrade, so an
upgrade never moves the floor. That single write becomes a floor the engine
reads alongside the counting window, so a total never blames a patient for
history that predates the policy actually being in force against them.
"""

import datetime
from typing import Any

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler

from attendance_policy_tracker.canvas.settings_store import NamespaceSettingsStore

from logger import log

# This plugin's own name, the same string the manifest carries and the same
# string the platform hands back as the install event's target id.
PLUGIN_NAME = "attendance_policy_tracker"

# The stored key the floor lives under, the same name config.py and
# composition.py already know as a setting.
INSTALL_FLOOR_KEY = "install_floor"


def stamp_install_moment(store: Any, now: datetime.datetime | None = None) -> bool:
    """Write the install floor, but only the first time this ever runs.

    Reading before writing is what makes a reinstall harmless. A stamp that
    already exists is left standing rather than moved forward, so an
    uninstall followed by a reinstall never grants anybody a fresh floor and
    quietly forgets what already happened. Returns whether it wrote a stamp.
    """
    stored = store.read()
    existing = stored.get(INSTALL_FLOOR_KEY)
    if existing and f"{existing}".strip():
        log.info("attendance install floor already stamped, leaving it in place")
        return False
    moment = arrow.get(now) if now is not None else arrow.utcnow()
    stamped = moment.to("utc").isoformat()
    store.write({INSTALL_FLOOR_KEY: stamped})
    log.info(f"attendance install floor stamped at {stamped}")
    return True


class InstallFloorStamp(BaseHandler):
    """Captures the install moment, the one time the platform offers it."""

    RESPONDS_TO = EventType.Name(EventType.PLUGIN_CREATED)

    def compute(self) -> list[Effect]:
        """Stamp the floor when this plugin is the one that was installed.

        The event fires for every plugin installed on the instance, so a
        target that names somebody else's plugin is left alone. Nothing is
        ever returned as an effect, the whole point of this handler is the
        write it makes to storage.
        """
        if f"{self.event.target.id}" == PLUGIN_NAME:
            stamp_install_moment(NamespaceSettingsStore())
        return []
