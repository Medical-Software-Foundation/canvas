"""App-drawer entry point for the waitlist roster."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from scheduling_waitlist.constants import ROSTER_URL


class WaitlistApp(Application):
    """Opens the shared waitlist roster.

    The page is served from a URL rather than passed inline as ``content``.
    The roster issues repeated same-origin requests as staff filter, search,
    and edit, which needs a real document origin so the staff session travels
    with each one; inlining would also push the whole stylesheet and script
    into the effect payload on every open.
    """

    def on_open(self) -> Effect:
        """Launch the roster in a modal."""
        return LaunchModalEffect(
            url=ROSTER_URL,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Scheduling Waitlist",
        ).apply()
