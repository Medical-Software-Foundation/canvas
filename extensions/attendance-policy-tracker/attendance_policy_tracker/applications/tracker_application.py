"""The top bar application.

Declared with global scope and show_in_panel true, which is what puts the icon in
the persistent top bar beside the built in calendar and task icons rather than in
the grid drawer. It draws no count on itself, because the patients who need
attention already have tasks in Canvas's own task list a few pixels away and two
numbers describing the same work can disagree.

Opening it puts a working surface over whatever page the user was on, which for
this plugin is almost always the schedule, and the page underneath is never
navigated away from.
"""

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# The same reasoning as the token in the API module, applied to the page this
# effect opens. Without it a browser can reopen a cached copy of the surface
# itself, which would then never ask for the new assets at all.
_CACHE_BUST = f"{arrow.utcnow().int_timestamp}"


class AttendancePolicyTrackerApplication(Application):
    """Opens the attendance policy surface over the current page."""

    def on_open(self) -> Effect:
        """Open the review surface without leaving the page underneath."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/attendance_policy_tracker/app/index?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
