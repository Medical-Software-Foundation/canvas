"""Claim, release, and prune the once-only markers in ``SendClaim``.

See ``models/claims.py`` for why these are rows rather than cache entries.

Exposed through ``claim_store()`` rather than as bare functions, mirroring the
SDK's own ``get_cache()`` idiom. That gives callers one seam to substitute in
tests, which matters here: the value of a claim is entirely in its concurrency
behavior, and a test that cannot express "the second caller loses" is not
testing the thing that protects patients from duplicate messages.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from canvas_sdk.caching.plugins import get_cache
from logger import log

from appointment_reminders.models.claims import SendClaim

REMINDER = "reminder"
TELEHEALTH = "telehealth"
INBOUND = "inbound"

# Legacy cache keys, still consulted for one release so a deploy mid-window does
# not re-send to everyone the running version already handled. Those markers were
# written by the cache-based implementation and are invisible to the table, so
# without this the first scan after deploy treats every one of them as unclaimed.
# Safe to delete once every instance has run a version past this one.
_LEGACY_CACHE_KEY = {
    REMINDER: "cr:reminder_sent:{key}",
    TELEHEALTH: "cr:telehealth_sent:{key}",
    INBOUND: "cr:inbound_seen:{key}",
}

# How far past the widest configured interval a claim is kept. A reminder claim
# has to outlive its whole send window, and the scan horizon already pads a
# day-out interval to cover its target date plus an hour for a DST fall-back.
# Two days on top puts the cutoff well clear of anything still in play; the cost
# of holding too long is a few thousand rows, and of holding too briefly is a
# duplicate message.
_RETENTION_MARGIN = timedelta(days=2)


class _ClaimStore:
    """Once-only markers backed by the ``SendClaim`` table."""

    def _legacy_claimed(self, scope: str, key: str) -> bool:
        """Whether the pre-table implementation already handled this action."""
        template = _LEGACY_CACHE_KEY.get(scope)
        if not template:
            return False
        try:
            return bool(get_cache().get(template.format(key=key)))
        except Exception:
            # The fallback is a transitional courtesy, not the guarantee. An
            # unavailable cache must not stop the table-backed path working.
            log.warning(f"[claims] Legacy cache check failed for {scope}; continuing")
            return False

    def already_claimed(self, scope: str, key: str) -> bool:
        """Cheap indexed read used to skip work before doing it.

        Advisory only: two invocations can both see False. ``claim`` is what
        decides, and only one of them wins there. This exists so an
        already-handled action does not pay for template rendering first.

        Deliberately does *not* consult the legacy cache. This runs for every
        appointment in the scan window, while ``claim`` runs only for the ones
        actually firing — a far smaller set. Since the plugins cache is itself
        Postgres-backed, putting the transitional lookup here would have added a
        second query per candidate for the whole of the cutover release.
        """
        return SendClaim.objects.filter(scope=scope, key=key).exists()

    def claim(self, scope: str, key: str) -> bool:
        """Atomically take ownership of one action. True means this caller owns it.

        Atomic because of the unique constraint on (scope, key): of two
        concurrent callers the database rejects one insert, Django catches the
        IntegrityError and re-reads, and that caller gets ``created=False``.

        The legacy check runs here rather than in ``already_claimed`` so it costs
        one query per action actually taken rather than per candidate examined.
        """
        if self._legacy_claimed(scope, key):
            return False
        _, created = SendClaim.objects.get_or_create(scope=scope, key=key)
        return created

    def release(self, scope: str, key: str) -> None:
        """Give a claim back so a later attempt can retry it."""
        SendClaim.objects.filter(scope=scope, key=key).delete()

    def prune(self, max_interval_minutes: int, limit: int = 500) -> int:
        """Delete claims old enough that nothing can still be acting on them.

        A table has none of the cache's automatic expiry, so without this the
        markers grow without bound — trading the eviction problem for an
        unbounded-growth one.

        Bounded by ``limit`` per run so the prune cannot become the batch problem
        this module exists to avoid. It runs every scan, so a backlog drains over
        successive ticks.
        """
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(minutes=max_interval_minutes)
            - _RETENTION_MARGIN
        )
        stale = list(
            SendClaim.objects.filter(claimed_at__lt=cutoff).values_list(
                "dbid", flat=True
            )[:limit]
        )
        if not stale:
            return 0
        SendClaim.objects.filter(dbid__in=stale).delete()
        log.info(f"[claims] Pruned {len(stale)} expired send claims")
        return len(stale)


_STORE = _ClaimStore()


def claim_store() -> _ClaimStore:
    """The process-wide claim store. Stateless, so a singleton is fine."""
    return _STORE
