"""Tests for the signed link and OAuth state tokens."""

import jwt
import pytest

from oura_ring_viewer.services import magic_link
from oura_ring_viewer.services.magic_link import InvalidToken
from oura_ring_viewer.services.settings import MAGIC_LINK_TTL_SECONDS, STATE_TTL_SECONDS

SECRET = "s" * 40
NOW = 1_793_650_000


class TestRoundTrip:
    def test_link(self) -> None:
        token = magic_link.mint_link("pat-1", "nonce-1", SECRET, now=NOW)
        claims = magic_link.verify_link(token, SECRET, now=NOW + 1)
        assert (claims.patient_id, claims.nonce) == ("pat-1", "nonce-1")
        assert claims.expires_at == NOW + MAGIC_LINK_TTL_SECONDS

    def test_state_has_its_own_short_lifetime(self) -> None:
        # The state only has to survive Oura's sign-in and consent screens. It is
        # signed when the link is opened, so it is timed from then, not from
        # when the (much longer lived) link was sent.
        state = magic_link.sign_state("pat-1", "nonce-1", SECRET, now=NOW)
        claims = magic_link.verify_state(state, SECRET, now=NOW + STATE_TTL_SECONDS - 1)
        assert claims.expires_at == NOW + STATE_TTL_SECONDS
        assert STATE_TTL_SECONDS < MAGIC_LINK_TTL_SECONDS
        with pytest.raises(InvalidToken, match="expired"):
            magic_link.verify_state(state, SECRET, now=NOW + STATE_TTL_SECONDS)

    def test_nonces_are_unique_hex(self) -> None:
        nonces = {magic_link.new_nonce() for _ in range(50)}
        assert len(nonces) == 50
        assert all(len(n) == 32 and int(n, 16) >= 0 for n in nonces)


class TestRejection:
    def test_link_expires_at_exactly_its_ttl(self) -> None:
        token = magic_link.mint_link("pat-1", "n", SECRET, now=NOW)
        magic_link.verify_link(token, SECRET, now=NOW + MAGIC_LINK_TTL_SECONDS - 1)
        with pytest.raises(InvalidToken, match="expired"):
            magic_link.verify_link(token, SECRET, now=NOW + MAGIC_LINK_TTL_SECONDS)

    def test_a_link_cannot_be_replayed_as_state(self) -> None:
        token = magic_link.mint_link("pat-1", "n", SECRET, now=NOW)
        with pytest.raises(InvalidToken, match="wrong kind"):
            magic_link.verify_state(token, SECRET, now=NOW)

    def test_a_state_cannot_be_used_as_a_link(self) -> None:
        state = magic_link.sign_state("pat-1", "n", SECRET, now=NOW)
        with pytest.raises(InvalidToken, match="wrong kind"):
            magic_link.verify_link(state, SECRET, now=NOW)

    def test_wrong_secret(self) -> None:
        token = magic_link.mint_link("pat-1", "n", SECRET, now=NOW)
        with pytest.raises(InvalidToken):
            magic_link.verify_link(token, "t" * 40, now=NOW)

    def test_tampered_payload(self) -> None:
        header, _payload, signature = magic_link.mint_link("pat-1", "n", SECRET, now=NOW).split(".")
        forged = jwt.encode({"typ": "link", "p": "pat-2", "n": "n", "exp": NOW + 900}, "x" * 40)
        with pytest.raises(InvalidToken):
            magic_link.verify_link(f"{header}.{forged.split('.')[1]}.{signature}", SECRET, now=NOW)

    def test_unsigned_alg_none_token(self) -> None:
        unsigned = jwt.encode(
            {"typ": "link", "p": "pat-1", "n": "n", "exp": NOW + 900}, key="", algorithm="none"
        )
        with pytest.raises(InvalidToken):
            magic_link.verify_link(unsigned, SECRET, now=NOW)

    @pytest.mark.parametrize(
        "claims",
        [
            {"typ": "link", "n": "n", "exp": NOW + 900},
            {"typ": "link", "p": "pat-1", "exp": NOW + 900},
            {"typ": "link", "p": "", "n": "n", "exp": NOW + 900},
            {"typ": "link", "p": "pat-1", "n": "n"},
            {"typ": "link", "p": "pat-1", "n": "n", "exp": True},
            {"typ": "link", "p": "pat-1", "n": "n", "exp": "tomorrow"},
            {"p": "pat-1", "n": "n", "exp": NOW + 900},
        ],
    )
    def test_incomplete_claims(self, claims: dict[str, object]) -> None:
        token = jwt.encode(claims, SECRET, algorithm="HS256")
        with pytest.raises(InvalidToken):
            magic_link.verify_link(token, SECRET, now=NOW)

    @pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
    def test_malformed(self, token: str) -> None:
        with pytest.raises(InvalidToken):
            magic_link.verify_link(token, SECRET, now=NOW)


class TestSecretPolicy:
    @pytest.mark.parametrize("secret", ["", "short", "x" * 31])
    def test_short_secret_is_a_configuration_error_not_a_bad_token(self, secret: str) -> None:
        with pytest.raises(ValueError) as minting:
            magic_link.mint_link("pat-1", "n", secret, now=NOW)
        with pytest.raises(ValueError) as verifying:
            magic_link.verify_link("anything", secret, now=NOW)
        assert minting.type is ValueError
        assert verifying.type is ValueError

    @pytest.mark.parametrize("patient_id, nonce", [("", "n"), ("pat-1", "")])
    def test_minting_needs_patient_and_nonce(self, patient_id: str, nonce: str) -> None:
        with pytest.raises(ValueError):
            magic_link.mint_link(patient_id, nonce, SECRET, now=NOW)
