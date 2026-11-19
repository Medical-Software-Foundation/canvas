"""Signed, short-lived tokens for the patient connection flow.

Two token kinds share one HMAC secret:

* the **link** token, carried in the URL staff send to the patient, expiring
  after ``MAGIC_LINK_TTL_SECONDS``; and
* the OAuth **state** token, carried through Oura's consent screen and back,
  expiring after ``STATE_TTL_SECONDS``.

Each carries a ``typ`` claim that verification checks, so one kind can never
be replayed as the other. Both carry the patient id and a nonce; the nonce is
also stored on ``OuraSyncState`` and cleared when the connection completes, so
a link works only until it has been used once.

Expiry is checked against an explicit ``now`` rather than PyJWT's wall clock,
which keeps the behavior deterministic under test. The algorithm is pinned to
HS256, so a token claiming ``alg: none`` is rejected.
"""

import time
from dataclasses import dataclass
from uuid import uuid4

import jwt

from oura_ring_viewer.services.settings import (
    MAGIC_LINK_TTL_SECONDS,
    MIN_SECRET_LENGTH,
    STATE_TTL_SECONDS,
)

_ALG = "HS256"
_TYP_LINK = "link"
_TYP_STATE = "state"


class InvalidToken(ValueError):
    """Any verification failure: malformed, tampered, wrong kind or expired."""


@dataclass(frozen=True)
class Claims:
    """Verified claims from a link or state token."""

    patient_id: str
    nonce: str
    expires_at: int


def new_nonce() -> str:
    """Return a fresh random nonce."""
    return uuid4().hex


def mint_link(patient_id: str, nonce: str, secret: str, *, now: int | None = None) -> str:
    """Sign a connection-link token for ``patient_id``."""
    return _sign(_TYP_LINK, patient_id, nonce, secret, MAGIC_LINK_TTL_SECONDS, now)


def verify_link(token: str, secret: str, *, now: int | None = None) -> Claims:
    """Verify a connection-link token. Raises InvalidToken on any failure."""
    return _verify(_TYP_LINK, token, secret, now)


def sign_state(patient_id: str, nonce: str, secret: str, *, now: int | None = None) -> str:
    """Sign the OAuth ``state`` value for the round trip through Oura."""
    return _sign(_TYP_STATE, patient_id, nonce, secret, STATE_TTL_SECONDS, now)


def verify_state(state: str, secret: str, *, now: int | None = None) -> Claims:
    """Verify the OAuth ``state`` value. Raises InvalidToken on any failure."""
    return _verify(_TYP_STATE, state, secret, now)


def link_is_authentic(token: str, secret: str) -> bool:
    """Whether this is a link token this plugin signed, expired or not."""
    return _is_authentic(_TYP_LINK, token, secret)


def state_is_authentic(state: str, secret: str) -> bool:
    """Whether this is a state token this plugin signed, expired or not."""
    return _is_authentic(_TYP_STATE, state, secret)


def _is_authentic(typ: str, token: str, secret: str) -> bool:
    try:
        _verify(typ, token, secret, None, check_expiry=False)
    except InvalidToken:
        return False
    return True


def _sign(typ: str, patient_id: str, nonce: str, secret: str, ttl: int, now: int | None) -> str:
    _require_secret(secret)
    if not patient_id or not nonce:
        raise ValueError("patient_id and nonce are required")
    issued_at = int(time.time()) if now is None else now
    claims = {"typ": typ, "p": patient_id, "n": nonce, "iat": issued_at, "exp": issued_at + ttl}
    return jwt.encode(claims, secret, algorithm=_ALG)


def _verify(
    typ: str, token: str, secret: str, now: int | None, *, check_expiry: bool = True
) -> Claims:
    _require_secret(secret)
    if not token:
        raise InvalidToken("token is empty")
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALG], options={"verify_exp": False})
    except jwt.InvalidTokenError as exc:
        raise InvalidToken(f"token rejected: {type(exc).__name__}") from exc

    patient_id = payload.get("p")
    nonce = payload.get("n")
    expires_at = payload.get("exp")
    if payload.get("typ") != typ:
        raise InvalidToken("token is the wrong kind")
    if not (isinstance(patient_id, str) and patient_id and isinstance(nonce, str) and nonce):
        raise InvalidToken("token is missing required claims")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise InvalidToken("token has no valid expiry")
    current = int(time.time()) if now is None else now
    if check_expiry and current >= expires_at:
        raise InvalidToken("token has expired")
    return Claims(patient_id=patient_id, nonce=nonce, expires_at=expires_at)


def _require_secret(secret: str) -> None:
    if len(secret or "") < MIN_SECRET_LENGTH:
        raise ValueError(f"signing secret must be at least {MIN_SECRET_LENGTH} characters")
