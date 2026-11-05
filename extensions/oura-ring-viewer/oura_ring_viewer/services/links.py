"""Rules for the outstanding connection link, shared by staff and portal routes.

A staff-sent link is identified by the nonce stored on ``OuraSyncState``. The
link itself is never stored: it can be re-signed from the nonce and the time
it was sent, which reproduces the same expiry. That lets staff copy or resend
the link that is already out without cancelling it, and lets a patient who
starts from the portal finish with the same nonce, so neither path silently
breaks the other.
"""

import datetime as dt

from oura_ring_viewer.models import OuraSyncState
from oura_ring_viewer.services.settings import MAGIC_LINK_TTL_SECONDS


def link_expires_at(state: OuraSyncState | None) -> dt.datetime | None:
    """When the outstanding staff link expires, or None if there is none."""
    if state is None or not state.link_pending or not state.last_link_sent_at:
        return None
    sent_at: dt.datetime = state.last_link_sent_at
    return sent_at + dt.timedelta(seconds=MAGIC_LINK_TTL_SECONDS)


def link_expired(state: OuraSyncState | None, now: dt.datetime) -> bool:
    """True if a staff link was sent and has since expired unused."""
    expires_at = link_expires_at(state)
    return expires_at is not None and now >= expires_at


def live_link_nonce(state: OuraSyncState | None, now: dt.datetime) -> str | None:
    """The nonce of a staff link that is still usable, if there is one."""
    expires_at = link_expires_at(state)
    if state is None or expires_at is None or now >= expires_at or not state.last_link_nonce:
        return None
    nonce: str = state.last_link_nonce
    return nonce
