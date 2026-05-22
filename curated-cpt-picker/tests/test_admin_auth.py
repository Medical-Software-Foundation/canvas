"""Tests for the admin auth gate.

The gate is intentionally fail-open when ADMIN_STAFF_IDS is unset (any logged-in
staff allowed). This test file pins that behavior so a future refactor doesn't
silently flip the default.
"""

from curated_cpt_picker.lib.admin_auth import is_admin


def test_returns_false_when_staff_id_missing() -> None:
    """No staff_id (e.g. session header absent) always denies."""
    assert is_admin(None, "any-uuid") is False
    assert is_admin("", "any-uuid") is False


def test_permissive_default_when_secret_unset(caplog) -> None:
    """When ADMIN_STAFF_IDS is empty, any non-empty staff_id is allowed.

    This is a deliberate deviation from CLAUDE.md's fail-closed guidance —
    see lib/admin_auth.py for rationale. If this test fails, someone has
    flipped the default; that should be a deliberate decision, not a slip.
    """
    assert is_admin("8f3a1c2b-staff-uuid", "") is True
    assert is_admin("8f3a1c2b-staff-uuid", "   ") is True
    assert is_admin("8f3a1c2b-staff-uuid", None) is True


def test_warns_when_permissive_default_engages(caplog) -> None:
    """A warning is logged when the permissive default kicks in — so unconfigured
    installs are visible in canvas logs."""
    with caplog.at_level("WARNING"):
        is_admin("8f3a1c2b-staff-uuid", "")
    assert any("ADMIN_STAFF_IDS is not configured" in rec.message for rec in caplog.records)


def test_allows_only_listed_staff_when_secret_set() -> None:
    secret = "uuid-a,uuid-b, uuid-c "
    assert is_admin("uuid-a", secret) is True
    assert is_admin("uuid-b", secret) is True
    assert is_admin("uuid-c", secret) is True
    assert is_admin("uuid-d", secret) is False
    assert is_admin("uuid-A", secret) is False  # case-sensitive


def test_ignores_empty_entries_in_secret() -> None:
    """Comma-separated parsing should tolerate stray commas and whitespace."""
    secret = ", uuid-a,, uuid-b ,"
    assert is_admin("uuid-a", secret) is True
    assert is_admin("uuid-b", secret) is True
    assert is_admin("", secret) is False
