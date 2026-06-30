"""Tests for provider_availability.api._auth."""

from __future__ import annotations

from unittest.mock import MagicMock

from provider_availability.api._auth import (
    _canonical_id,
    current_staff_id,
    is_authorized,
)

_HEX = "5e4fb0011234567890abcdef01234567"
_DASHED = "5e4fb001-1234-5678-90ab-cdef01234567"
_OTHER_HEX = "aa11bb22cc33dd44ee55ff6677889900"


def _request(staff_id: str | None) -> MagicMock:
    req = MagicMock()
    req.headers = {"canvas-logged-in-user-id": staff_id} if staff_id is not None else {}
    return req


# ── _canonical_id ────────────────────────────────────────────────────────


class TestCanonicalId:
    def test_undashed_uuid_passes_through(self):
        assert _canonical_id(_HEX) == _HEX

    def test_dashed_uuid_normalised_to_undashed(self):
        assert _canonical_id(_DASHED) == _HEX

    def test_uppercase_uuid_normalised(self):
        assert _canonical_id(_DASHED.upper()) == _HEX

    def test_non_uuid_kept_verbatim(self):
        """Legacy / fixture ids that aren't UUIDs are passed through unchanged."""
        assert _canonical_id("staff-1") == "staff-1"

    def test_whitespace_trimmed(self):
        assert _canonical_id(f"  {_DASHED}  ") == _HEX

    def test_empty_returns_empty(self):
        assert _canonical_id("") == ""
        assert _canonical_id("   ") == ""


# ── current_staff_id ─────────────────────────────────────────────────────


class TestCurrentStaffId:
    def test_reads_header_undashed(self):
        assert current_staff_id(_request(_HEX)) == _HEX

    def test_reads_header_and_canonicalises_dashed(self):
        assert current_staff_id(_request(_DASHED)) == _HEX

    def test_missing_header_returns_empty(self):
        assert current_staff_id(_request(None)) == ""

    def test_no_headers_attribute_returns_empty(self):
        assert current_staff_id(object()) == ""


# ── is_authorized ────────────────────────────────────────────────────────


class TestIsAuthorized:
    def test_empty_secret_allows_any_staff(self):
        assert is_authorized({}, _request(_HEX)) is True
        assert is_authorized({"allowed-staff-keys": ""}, _request(_HEX)) is True
        assert is_authorized({"allowed-staff-keys": "   "}, _request(_HEX)) is True

    def test_none_secrets_dict_allows(self):
        assert is_authorized(None, _request(_HEX)) is True

    def test_listed_staff_allowed(self):
        secrets = {"allowed-staff-keys": _HEX}
        assert is_authorized(secrets, _request(_HEX)) is True

    def test_dashed_secret_matches_undashed_header(self):
        """Regression for PR #339-comment: operator pastes dashed UUID, Canvas sends undashed."""
        secrets = {"allowed-staff-keys": _DASHED}
        assert is_authorized(secrets, _request(_HEX)) is True

    def test_undashed_secret_matches_dashed_header(self):
        secrets = {"allowed-staff-keys": _HEX}
        assert is_authorized(secrets, _request(_DASHED)) is True

    def test_multi_value_secret_with_whitespace(self):
        secrets = {"allowed-staff-keys": f"  {_OTHER_HEX} , {_DASHED} "}
        assert is_authorized(secrets, _request(_HEX)) is True
        assert is_authorized(secrets, _request(_OTHER_HEX)) is True

    def test_unlisted_staff_denied(self):
        secrets = {"allowed-staff-keys": _HEX}
        assert is_authorized(secrets, _request(_OTHER_HEX)) is False

    def test_missing_header_denied_when_secret_set(self):
        secrets = {"allowed-staff-keys": _HEX}
        assert is_authorized(secrets, _request(None)) is False
