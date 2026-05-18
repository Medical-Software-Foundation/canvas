"""Membership status banner displayed in the patient chart and on appointment cards.

Responds to patient-update and plugin lifecycle events to surface an
AddBannerAlert showing the patient's current membership level and status.

The banner is keyed as ``membership-status`` (distinct from the cancellation
flow's ``membership-cancelled`` key used by membership_api.py).

Placements:
  - ``CHART``            — under the patient name in the chart header
  - ``APPOINTMENT_CARD`` — on the appointment card in the calendar view

Only active and cancelled members receive a banner.  Patients with no
membership record produce no effects.
"""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol

from portal_membership.models import Membership
from portal_membership.utils.billing_cycle import cadence_suffix
from portal_membership.utils.membership_store import get_membership

BANNER_KEY = "membership-status"

# Legacy banner key — an older plugin version emitted a separate
# "Cancelled Membership" banner alongside the status banner. We now rely on
# the status banner to state the cancellation, but may still need to clean
# up leftover instances on charts that were flagged under the old behavior.
_LEGACY_CANCELLED_BANNER_KEY = "membership-cancelled"

_PLACEMENTS = [
    AddBannerAlert.Placement.CHART,
    AddBannerAlert.Placement.APPOINTMENT_CARD,
]


def _format_amount(
    amount_cents: int | None,
    currency: str | None,
    cadence: str | None = None,
) -> str:
    """Return a human-readable per-cycle charge string, e.g. ``$99.00/mo``."""
    if not amount_cents:
        return ""
    dollars = amount_cents / 100
    symbol = "$" if (currency or "usd").lower() == "usd" else ""
    return f"{symbol}{dollars:.2f}{cadence_suffix(cadence)}"


def _build_narrative(record: dict) -> str:
    """Build a banner narrative (≤ 90 chars) from a membership *record*.

    Returns an empty string when the status is not ``active`` or ``cancelled``
    (i.e. no banner should be shown).
    """
    status = record.get("status", "none")
    plan_name: str = record.get("plan_name") or ""
    amount_cents: int | None = record.get("amount_cents")
    currency: str | None = record.get("currency")
    cadence: str | None = record.get("cadence")
    next_billing: str = record.get("next_billing_date") or ""

    if status == "active":
        parts: list[str] = []
        if plan_name:
            parts.append(plan_name)
        charge = _format_amount(amount_cents, currency, cadence)
        if charge:
            parts.append(charge)
        narrative = " — ".join(parts) if parts else "Active Membership"
        # Append billing date if it fits within the 90-char limit.
        if next_billing:
            candidate = f"{narrative} · Next: {next_billing}"
            if len(candidate) <= 90:
                narrative = candidate
        return narrative

    if status == "cancelled":
        base = plan_name or "Membership"
        # Always include the cancelled indicator so the banner is unambiguous.
        cancelled_label = f"{base} (Cancelled)"
        if next_billing:
            candidate = f"{cancelled_label} · Effective: {next_billing}"
            if len(candidate) <= 90:
                return candidate
        return cancelled_label
    return ""


class MembershipBanner(BaseProtocol):
    """Emit an AddBannerAlert with the patient's membership level.

    Fires on:
    * ``PATIENT_UPDATED``  — keeps the banner fresh as the patient record changes.
    * ``PLUGIN_CREATED``   — seeds the banner for all active patients on first deploy.
    * ``PLUGIN_UPDATED``   — refreshes the banner when the plugin is re-deployed.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.PLUGIN_CREATED),
        EventType.Name(EventType.PLUGIN_UPDATED),
    ]

    def compute(self) -> list[Effect]:
        """Build and return banner alert effect(s)."""
        is_plugin_event = self.event.type in (
            EventType.PLUGIN_CREATED,
            EventType.PLUGIN_UPDATED,
        )

        if is_plugin_event:
            return self._banners_for_all_members()

        patient_id: str = self.event.target.id
        return self._banner_for_patient(patient_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _banner_for_patient(self, patient_id: str) -> list[Effect]:
        """Return a banner effect for a single patient, or [] if not a member."""
        record = get_membership(patient_id)
        if record is None:
            return []
        return _build_banner_effects(patient_id=patient_id, record=record)

    def _banners_for_all_members(self) -> list[Effect]:
        """Emit banners for every member (active and cancelled) on plugin events.

        Cancelled members still need their banners refreshed — e.g. when the
        plugin is redeployed after a narrative change. Cancelled members also
        get a RemoveBannerAlert for the legacy duplicate banner that older
        plugin versions used to emit.
        """
        effects: list[Effect] = []
        for instance in Membership.objects.exclude(status="").select_related("patient"):
            patient_id = str(instance.patient.id)
            record = get_membership(patient_id)
            if record is None:
                continue
            effects.extend(_build_banner_effects(patient_id=patient_id, record=record))
            if record.get("status") == "cancelled":
                effects.append(
                    RemoveBannerAlert(
                        key=_LEGACY_CANCELLED_BANNER_KEY,
                        patient_id=patient_id,
                    ).apply()
                )
        return effects


# ---------------------------------------------------------------------------
# Banner builder (module-level so it is easily unit-testable)
# ---------------------------------------------------------------------------

def _build_banner_effects(
    patient_id: str,
    record: dict,
) -> list[Effect]:
    """Return a list containing one ``AddBannerAlert`` effect, or empty list.

    Returns an empty list when the membership status warrants no banner
    (e.g. ``none`` / unknown status).
    """
    narrative = _build_narrative(record)
    if not narrative:
        return []

    status = record.get("status", "none")
    intent = (
        AddBannerAlert.Intent.INFO
        if status == "active"
        else AddBannerAlert.Intent.WARNING
    )

    banner = AddBannerAlert(
        patient_id=patient_id,
        key=BANNER_KEY,
        narrative=narrative,
        placement=_PLACEMENTS,
        intent=intent,
    )
    return [banner.apply()]
