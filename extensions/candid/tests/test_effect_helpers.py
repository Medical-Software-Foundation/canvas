"""Tests for effect_helpers: banners, metadata accessors, coverage ordering."""

from unittest.mock import MagicMock, patch

from canvas_sdk.effects.claim import BannerAlertIntent

from candid.effect_helpers import (
    BANNER_KEY,
    DENIED_STATUSES,
    active_coverages_ordered,
    schedule_async_post,
    sync_banner,
)


# ---------------------------------------------------------------------------
# sync_banner
# ---------------------------------------------------------------------------


def _capture_banner(claim_status: str) -> dict:
    with patch("candid.effect_helpers.ClaimEffect") as MCE:
        sync_banner(
            claim_id="claim-1",
            claim_status=claim_status,
            last_sync_at="2026-04-28T12:00:00+00:00",
        )
        MCE.assert_called_once_with(claim_id="claim-1")
        return MCE.return_value.add_banner.call_args.kwargs


def test_sync_banner_uses_warning_intent_for_denied_status() -> None:
    for status in DENIED_STATUSES:
        kwargs = _capture_banner(status)
        assert kwargs["key"] == BANNER_KEY
        assert kwargs["intent"] == BannerAlertIntent.WARNING, (
            f"Status {status!r} should map to WARNING"
        )


def test_sync_banner_uses_info_intent_for_normal_status() -> None:
    kwargs = _capture_banner("era_received")
    assert kwargs["intent"] == BannerAlertIntent.INFO


def test_sync_banner_includes_status_and_dates_in_narrative() -> None:
    with patch("candid.effect_helpers.ClaimEffect") as MCE:
        sync_banner(
            claim_id="claim-1",
            claim_status="finalized_paid",
            last_sync_at="2026-04-28T12:00:00+00:00",
            submitted_at="2026-04-24T08:00:00+00:00",
        )
        narrative = MCE.return_value.add_banner.call_args.kwargs["narrative"]
        assert "Finalized Paid" in narrative
        assert "04-24-2026" in narrative
        assert "04-28-2026" in narrative


# ---------------------------------------------------------------------------
# active_coverages_ordered
# ---------------------------------------------------------------------------


def _coverage(coverage_id: str, payer_order: str | None, active: bool = True) -> MagicMock:
    cov = MagicMock()
    cov.id = coverage_id
    cov.payer_order = payer_order
    cov.active = active
    return cov


def test_active_coverages_ordered_drops_inactive() -> None:
    claim = MagicMock()
    all_covs = [
        _coverage("c1", "Primary", active=True),
        _coverage("c2", "Secondary", active=False),
    ]
    claim.coverages.active.return_value = [c for c in all_covs if c.active]
    result = active_coverages_ordered(claim)
    assert [c.id for c in result] == ["c1"]


def test_active_coverages_ordered_sorts_by_payer_order() -> None:
    claim = MagicMock()
    covs = [
        _coverage("c-tertiary", "Tertiary"),
        _coverage("c-primary", "Primary"),
        _coverage("c-secondary", "Secondary"),
    ]
    claim.coverages.active.return_value = covs
    result = active_coverages_ordered(claim)
    assert [c.id for c in result] == ["c-primary", "c-secondary", "c-tertiary"]


def test_active_coverages_ordered_puts_missing_payer_order_last() -> None:
    claim = MagicMock()
    covs = [
        _coverage("c-none", None),
        _coverage("c-primary", "Primary"),
    ]
    claim.coverages.active.return_value = covs
    result = active_coverages_ordered(claim)
    assert [c.id for c in result] == ["c-primary", "c-none"]


# ---------------------------------------------------------------------------
# schedule_async_post: comma encoding in Authorization header
# ---------------------------------------------------------------------------


def test_schedule_async_post_encodes_commas_in_authorization() -> None:
    """Commas in CANDID_CLIENT_SECRET are %2C-encoded in the Authorization header.

    The Canvas SDK's separate_headers helper (canvas_sdk/handlers/simple_api/tools.py)
    splits every inbound header value on ``,`` and exposes only the first segment via
    ``request.headers.get(...)``. A Candid OAuth client secret that contains commas
    therefore fails the receiver's ``credentials.key == self.secrets[...]`` check
    on /submit, /sync, /sync-patient-payments, and /report-payment.

    See canvas-plugins#1709 for the SDK fix. Until that ships, %2C-encode commas
    on the sender; the receiver routes restore them before comparison.
    """
    secrets = {"CANDID_CLIENT_SECRET": "abc,def,ghi"}
    environment = {"CUSTOMER_IDENTIFIER": "test-instance"}

    with patch("candid.effect_helpers.HttpRequestEffect") as MockEffect:
        schedule_async_post(environment, secrets, "submit", {"claim_id": "x"})

        kwargs = MockEffect.call_args.kwargs
        auth = kwargs["headers"]["Authorization"]

        assert "," not in auth, "commas must be encoded to survive SDK header parse"
        assert auth == "abc%2Cdef%2Cghi"
        # Round-trip on the receiver side reconstructs the original secret.
        assert auth.replace("%2C", ",") == secrets["CANDID_CLIENT_SECRET"]


def test_schedule_async_post_passes_comma_free_secret_through() -> None:
    """A comma-free secret is unaffected — Authorization header equals the secret."""
    secrets = {"CANDID_CLIENT_SECRET": "no-commas-here"}
    environment = {"CUSTOMER_IDENTIFIER": "test-instance"}

    with patch("candid.effect_helpers.HttpRequestEffect") as MockEffect:
        schedule_async_post(environment, secrets, "submit", {"claim_id": "x"})

        auth = MockEffect.call_args.kwargs["headers"]["Authorization"]
        assert auth == "no-commas-here"
