"""Tests for services/claims.py — the durable once-only markers.

The fake store in test_reminder_scheduler covers how the scheduler *uses* these.
This file covers the real implementation: that the atomicity rests on a database
constraint rather than on a read-then-write, that the legacy cache fallback is
consulted during the cutover, and that the prune cannot delete a live claim.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from appointment_reminders.models.claims import SendClaim
from appointment_reminders.services.claims import (
    INBOUND,
    REMINDER,
    TELEHEALTH,
    claim_store,
)

_MOD = "appointment_reminders.services.claims"


# ---- the constraint is the mechanism ----

def test_unique_constraint_is_declared_on_scope_and_key() -> None:
    """The atomicity of `claim` is the database's, not Python's.

    `get_or_create` is a SELECT followed by an INSERT. It is only safe against a
    concurrent caller because the unique index makes the loser's INSERT fail.
    Without this constraint both callers read "absent" and both send, which is
    the exact duplicate this module exists to prevent — and nothing else in the
    test suite would notice, because a single-threaded test never races.
    """
    constraints = SendClaim._meta.constraints
    assert len(constraints) == 1
    assert set(constraints[0].fields) == {"scope", "key"}
    assert type(constraints[0]).__name__ == "UniqueConstraint"


def test_constraint_and_index_names_survive_postgres_truncation() -> None:
    """The DDL pipeline emits "{schema}_{table}_{name}" and Postgres truncates
    identifiers at 63 bytes silently. This plugin's schema is 29 of them, and
    this table already lost indexes to that once."""
    schema = "canvas__appointment_reminders"
    table = SendClaim._meta.db_table
    names = [c.name for c in SendClaim._meta.constraints]
    names += [i.name for i in SendClaim._meta.indexes]
    emitted = [f"{schema}_{table}_{n}" for n in names]
    for full in emitted:
        assert len(full) <= 63, f"{full} is {len(full)} bytes and will truncate"
    # And they must stay distinct after truncation, which is how the sibling
    # model lost two of three indexes.
    assert len({e[:63] for e in emitted}) == len(emitted)


def test_scopes_are_distinct() -> None:
    """A reminder and a telehealth send for the same appointment and interval
    share a key, so only the scope keeps them from colliding."""
    assert len({REMINDER, TELEHEALTH, INBOUND}) == 3


# ---- claim / release ----

def test_claim_reports_whether_this_caller_created_the_row() -> None:
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model, patch(f"{_MOD}.get_cache") as cache:
        cache.return_value.get.return_value = None
        model.objects.get_or_create.return_value = (MagicMock(), True)
        assert store.claim(REMINDER, "appt-1:1440") is True
        model.objects.get_or_create.return_value = (MagicMock(), False)
        assert store.claim(REMINDER, "appt-1:1440") is False
    assert model.objects.get_or_create.call_args.kwargs == {
        "scope": REMINDER,
        "key": "appt-1:1440",
    }


def test_release_deletes_only_the_matching_claim() -> None:
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model:
        store.release(TELEHEALTH, "appt-9:30")
    assert model.objects.filter.call_args.kwargs == {
        "scope": TELEHEALTH,
        "key": "appt-9:30",
    }
    model.objects.filter.return_value.delete.assert_called_once()


# ---- the cutover fallback ----

def test_claim_refuses_what_the_cache_based_version_already_handled() -> None:
    """Deploying mid-window must not re-send to everyone the old version already
    handled: its markers live in the cache and are invisible to the new table."""
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model, patch(f"{_MOD}.get_cache") as cache:
        cache.return_value.get.return_value = "1"
        assert store.claim(REMINDER, "appt-1:1440") is False
    cache.return_value.get.assert_called_once_with("cr:reminder_sent:appt-1:1440")
    model.objects.get_or_create.assert_not_called()


def test_already_claimed_does_not_pay_for_the_legacy_lookup() -> None:
    """It runs per candidate in the scan window, where `claim` runs only per
    action taken. The plugins cache is Postgres-backed, so a lookup here would
    have been a second query on every appointment for the whole cutover."""
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model, patch(f"{_MOD}.get_cache") as cache:
        model.objects.filter.return_value.exists.return_value = False
        assert store.already_claimed(REMINDER, "appt-1:1440") is False
    cache.assert_not_called()


def test_legacy_key_matches_what_the_old_implementation_wrote() -> None:
    """The fallback is worthless if the key is spelled differently."""
    store = claim_store()
    seen = []
    with patch(f"{_MOD}.SendClaim") as model, patch(f"{_MOD}.get_cache") as cache:
        model.objects.get_or_create.return_value = (MagicMock(), True)
        cache.return_value.get.side_effect = lambda k: seen.append(k)
        store.claim(REMINDER, "a:1")
        store.claim(TELEHEALTH, "a:1")
        store.claim(INBOUND, "SM123")
    assert seen == [
        "cr:reminder_sent:a:1",
        "cr:telehealth_sent:a:1",
        "cr:inbound_seen:SM123",
    ]


def test_a_broken_cache_does_not_break_the_claim_path() -> None:
    """The fallback is a transitional courtesy. An unavailable cache must not
    take down the table-backed guarantee with it."""
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model, patch(f"{_MOD}.get_cache") as cache:
        cache.side_effect = RuntimeError("cache down")
        model.objects.get_or_create.return_value = (MagicMock(), True)
        assert store.claim(REMINDER, "appt-1:1440") is True


def test_already_claimed_reads_the_table() -> None:
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model:
        model.objects.filter.return_value.exists.return_value = True
        assert store.already_claimed(REMINDER, "appt-1:1440") is True
    assert model.objects.filter.call_args.kwargs == {
        "scope": REMINDER,
        "key": "appt-1:1440",
    }


# ---- prune ----

def _captured_cutoff(model) -> datetime:
    return model.objects.filter.call_args.kwargs["claimed_at__lt"]


def test_prune_cutoff_clears_the_widest_send_window() -> None:
    """The one way this becomes a patient-visible bug: a cutoff that deletes a
    claim still inside its window lets the reminder send a second time.

    A 1440-minute interval's claim has to survive the padded scan horizon, which
    already reaches a day past the target date. The cutoff must sit older than
    that, not merely older than the interval.
    """
    store = claim_store()
    interval = 1440
    with patch(f"{_MOD}.SendClaim") as model:
        model.objects.filter.return_value.values_list.return_value.__getitem__.return_value = []
        store.prune(interval)

    cutoff = _captured_cutoff(model)
    age = datetime.now(timezone.utc) - cutoff
    assert age > timedelta(minutes=interval) + timedelta(days=1), (
        "cutoff is inside the scan horizon; a live claim could be pruned"
    )


def test_prune_is_bounded_per_run() -> None:
    """Unbounded, the prune becomes the batch problem this module avoids."""
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model:
        sliced = model.objects.filter.return_value.values_list.return_value
        sliced.__getitem__.return_value = []
        store.prune(1440, limit=250)
    assert sliced.__getitem__.call_args[0][0] == slice(None, 250)


def test_prune_does_nothing_when_there_is_nothing_stale() -> None:
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model:
        model.objects.filter.return_value.values_list.return_value.__getitem__.return_value = []
        assert store.prune(1440) == 0
    model.objects.filter.return_value.delete.assert_not_called()


def test_prune_deletes_by_primary_key_not_by_id() -> None:
    """CustomModels are keyed on dbid; `id` does not resolve on them."""
    store = claim_store()
    with patch(f"{_MOD}.SendClaim") as model:
        model.objects.filter.return_value.values_list.return_value.__getitem__.return_value = [1, 2, 3]
        assert store.prune(1440) == 3
    assert model.objects.filter.call_args.kwargs == {"dbid__in": [1, 2, 3]}
    assert "dbid" in str(model.objects.filter.call_args_list)
