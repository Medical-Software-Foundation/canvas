"""Portal home-page widget showing the patient's membership status.

Responds to the ``PATIENT_PORTAL__WIDGET_CONFIGURATION`` event and injects a
compact widget into the patient portal landing page.

Widget content:
  - Active member   — shows plan name, monthly cost, next billing date, and a
                      "Manage Membership" link to the full membership page.
  - Cancelled       — shows cancellation notice with access-until date and a
                      "Restart Membership" link.
  - Not enrolled    — shows a marketing teaser and a "View Plans" call-to-action.
"""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.widgets import PortalWidget
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.templates import render_to_string

from portal_membership.utils.billing_cycle import cadence_suffix
from portal_membership.utils.membership_store import get_membership


class MembershipPortalWidget(BaseProtocol):
    """Render a membership status widget on the patient portal landing page."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_PORTAL__WIDGET_CONFIGURATION)

    def compute(self) -> list[Effect]:
        """Return a ``PortalWidget`` effect with the patient's membership status."""
        # PATIENT_PORTAL__WIDGET_CONFIGURATION events deliver the logged-in
        # patient as ``event.target`` (same pattern MembershipBanner uses for
        # PATIENT_UPDATED). The event ``context`` dict is empty for this event.
        target = getattr(self.event, "target", None)
        patient_id = getattr(target, "id", "") if target is not None else ""
        record = get_membership(patient_id) if patient_id else None

        instance = self.environment.get("CUSTOMER_IDENTIFIER", "")
        api_base = f"https://{instance}.canvasmedical.com" if instance else ""
        membership_page_url = f"{api_base}/plugin-io/api/portal_membership/membership/page"

        context = _build_widget_context(record=record, membership_page_url=membership_page_url)
        html = render_to_string("templates/membership_widget.html", context)

        widget = PortalWidget(
            content=html,
            size=PortalWidget.Size.EXPANDED,
            priority=1,
        )
        return [widget.apply()]


# ---------------------------------------------------------------------------
# Context builder (module-level for testability)
# ---------------------------------------------------------------------------

def _build_widget_context(
    record: dict | None,
    membership_page_url: str,
) -> dict:
    """Return the template context dict derived from the membership *record*.

    Args:
        record: The raw membership dict from the cache, or ``None``.
        membership_page_url: Absolute URL to the full membership management page.

    Returns:
        A dict with keys consumed by ``templates/membership_widget.html``.
    """
    if record is None:
        status = "none"
    else:
        status = record.get("status", "none")

    plan_name = record.get("plan_name", "") if record else ""
    next_billing = record.get("next_billing_date", "") if record else ""
    amount_cents: int = record.get("amount_cents", 0) if record else 0
    currency: str = record.get("currency", "usd") if record else "usd"
    cadence: str | None = record.get("cadence") if record else None

    amount_display = _format_amount(amount_cents, currency, cadence)

    return {
        "status": status,
        "plan_name": plan_name,
        "next_billing": next_billing,
        "amount_display": amount_display,
        "membership_page_url": membership_page_url,
        "charges_page_url": f"{membership_page_url}?tab=charges",
    }


def _format_amount(amount_cents: int, currency: str, cadence: str | None = None) -> str:
    """Return a human-readable per-cycle charge string (e.g. ``$99.00/mo``)."""
    if not amount_cents:
        return ""
    symbol = "$" if (currency or "usd").lower() == "usd" else ""
    return f"{symbol}{amount_cents / 100:.2f}{cadence_suffix(cadence)}"
