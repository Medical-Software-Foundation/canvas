"""Global panel button that opens the scheduling modal with no context.

``SchedulingWithRoomsApp`` covers Canvas's own scheduling entry points, but
customers running their own landing page need a way to reach the modal
directly. This is that door: a plain globally-scoped ``Application`` in the
panel, opening an empty modal for the user to fill in from scratch.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from scheduling_with_rooms.utils.scheduling_context import ORIGIN_GLOBAL_PANEL, modal_url


class GlobalPanelSchedulingWithRoomsApp(Application):
    """Opens the scheduling modal from the global application panel."""

    def on_open(self) -> Effect:
        """Handle the on_open event by launching an empty scheduling modal.

        Tags the launch with our own ``origin`` so the modal knows it was
        opened standalone rather than routed to by Canvas, and can close itself
        once the appointment is booked.
        """
        return LaunchModalEffect(
            url=modal_url(origin=ORIGIN_GLOBAL_PANEL),
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Schedule Appointment",
        ).apply()
