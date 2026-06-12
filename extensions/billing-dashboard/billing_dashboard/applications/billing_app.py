"""Billing Dashboard Application handler."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class BillingDashboard(Application):
    """
    Billing Dashboard Application — accessible from the provider menu.

    Opens a full-page dashboard showing financial metrics, payer analysis,
    and reimbursement trends for practice managers and billing staff.
    """

    def on_open(self) -> Effect:
        """Launch the billing dashboard as a full-page modal."""
        return LaunchModalEffect(
            url="/plugin-io/api/billing_dashboard/dashboard",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Billing Dashboard",
        ).apply()
