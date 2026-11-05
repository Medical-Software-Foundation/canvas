"""The periodic sweep.

The holding period is a read time filter rather than deferred work, so there is
no queue of pending items and nothing to lose on a reinstall. What that design
does need is something to come back and look again once a holding period has
passed, which is this.

Every five minutes is frequent enough that a fifteen minute holding period turns
into a task promptly, and cheap enough that it only ever recomputes patients whose
history actually moved.

A cursor keeps a healthy cadence cheap without ever making it narrower than
correctness requires. Every tick used to re derive the same fixed lookback
window from scratch, so one state change sitting inside that window was fully
recomputed on every tick until it aged out, up to thirty six times at a five
minute schedule against a three hour lookback. The cursor is the last moment
this handler finished a run, stored the same way handlers/install_stamp.py
stores its own single stamped moment, through the settings store the
composition root already builds. A missing, unreadable, or future dated
cursor is worth nothing here and changes nothing, the sweep falls back to the
full lookback exactly as it always ran, because a redundant recompute is
always the safer error next to a threshold crossing this handler never
revisits. The cursor only ever moves forward once a run has actually
finished without raising, so a run that fails leaves the window it never
covered for the next tick to pick up rather than skipping it silently.

How far a healthy cursor is allowed to narrow the window is not decided here.
A cursor this handler considers trustworthy is still not a safe floor on its
own, because an incident recorded before it goes on maturing out of its
holding period afterwards, and the sweep bounds it for that reason. That rule
belongs to the window arithmetic rather than to the reading of a stored value,
so it lives in sweep.py beside the window it constrains.
"""

import datetime
from typing import Any

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.cron_task import CronTask

from attendance_policy_tracker.canvas.source import CanvasVisitSource
from attendance_policy_tracker.composition import build
from attendance_policy_tracker.core.clock import Clock
from attendance_policy_tracker.sweep import Sweep

from logger import log

# The stored key the sweep's last covered moment lives under, read and
# written through the same settings store the policy already uses. Not part
# of EDITABLE_SETTINGS in composition.py, nothing on the configuration screen
# ever writes it, and config_from() never looks for it by name, so it rides
# alongside stored policy without composition or Config ever seeing it.
SWEEP_CURSOR_KEY = "sweep_cursor"


def _read_cursor(stored: dict[str, str], now: datetime.datetime) -> datetime.datetime | None:
    """The last swept moment, or nothing when it cannot be trusted.

    Nothing covers every degenerate case the same way, an absent key, text
    that will not parse, and a moment that sits after this run's own now. Any
    of those hands the caller nothing at all, which is what lets the sweep
    fall back to its full lookback window rather than narrowing it on a value
    that cannot be trusted. A wider recompute costs a little time, a narrowed
    one that trusted a bad cursor could cost a missed threshold crossing.
    """
    raw = stored.get(SWEEP_CURSOR_KEY)
    if raw is None or f"{raw}".strip() == "":
        return None
    try:
        parsed = arrow.get(f"{raw}".strip()).to("utc").datetime
    except (ValueError, TypeError):
        return None
    if parsed > now:
        return None
    return parsed


class ScheduledSweep(CronTask):
    """Recomputes recently active patients on a schedule."""

    # Standard five field cron, evaluated against wall clock time, so this fires
    # on the minute rather than five minutes after the plugin was installed.
    SCHEDULE = "*/5 * * * *"

    def execute(self) -> list[Effect]:
        """Run the sweep and return whatever effects it earned."""
        clock = Clock()
        source = CanvasVisitSource()
        # Policy comes from the plugin's own storage, which the composition root
        # reaches by default, so the schedule and the screen always read the same
        # configuration. build() hands back that same store regardless of
        # whether one is passed in, which is what lets the cursor ride on it
        # below without this handler naming NamespaceSettingsStore itself.
        parts = build(clock=clock, source=source)
        store: Any = parts["store"]

        now = clock.now()
        cursor = _read_cursor(store.read(), now)

        sweep = Sweep(
            config=parts["config"],
            engine=parts["engine"],
            actions=parts["actions"],
            source=source,
            clock=clock,
        )
        result = sweep.run(since_floor=cursor)

        # The cursor moves forward only once the run above has actually
        # finished, so an exception raised out of sweep.run() reaches the
        # platform with the previous cursor left standing and this window
        # picked up again, in full, on the next tick.
        store.write({SWEEP_CURSOR_KEY: arrow.get(now).to("utc").isoformat()})

        log.info(
            f"attendance sweep covered {result['swept']} patients, "
            f"tagged {result['runs_tagged']} runs, "
            f"emitting {len(result['effects'])} effects"
        )
        effects: list[Effect] = result["effects"]
        return effects
