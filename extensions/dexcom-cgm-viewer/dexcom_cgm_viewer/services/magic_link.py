"""Short-lived signed tokens for the patient connection magic link.

Implementation uses ``PyJWT`` (which the Canvas plugin sandbox allows). The
token encodes ``patient_id`` and a single-use ``nonce``; expiry is enforced
server-side and the nonce is invalidated after first use via
``DexcomSyncState.last_link_nonce``.

OAuth ``state`` for the redirect round-trip uses a separate, no-expiry JWT
encoding ``patient_id`` and ``nonce`` with the same secret. State is short-
lived in practice (the OAuth round-trip) and Dexcom also tracks it.
"""

import time
from dataclasses import dataclass
from uuid import uuid4

import jwt

from dexcom_cgm_viewer.services.settings import MAGIC_LINK_TTL_SECONDS

_ALG = "HS256"


@dataclass
class MagicLinkClaims:
    """Verified claims extracted from a magic-link token."""

    patient_id: str
    nonce: str
    issued_at: int
    expires_at: int


def mint(patient_id: str, secret: str, *, now: int | None = None) -> tuple[str, str]:
    """Mint a fresh magic-link token. Returns ``(token, nonce)``.

    The caller must persist ``nonce`` so it can be invalidated after first use.
    """
    if not patient_id:
        raise ValueError("patient_id is required")
    if not secret:
        raise ValueError("magic-link secret is required")
    issued_at = int(now if now is not None else time.time())
    nonce = uuid4().hex
    payload = {
        "p": patient_id,
        "n": nonce,
        "iat": issued_at,
        "exp": issued_at + MAGIC_LINK_TTL_SECONDS,
    }
    token = jwt.encode(payload, secret, algorithm=_ALG)
    return token, nonce


def verify(token: str, secret: str, *, now: int | None = None) -> MagicLinkClaims:
    """Verify a magic-link token and return its claims.

    Raises ``ValueError`` for any failure: malformed, bad signature, expired.
    """
    if not token:
        raise ValueError("malformed magic-link token")
    if not secret:
        raise ValueError("magic-link secret is required")
    try:
        # PyJWT 2.x verifies exp claim natively when ``leeway=0`` and the
        # current time exceeds ``exp``. We pass our own ``now`` via leeway
        # math so tests can pin time deterministically.
        payload = jwt.decode(
            token, secret, algorithms=[_ALG],
            options={"verify_exp": now is None},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("magic-link token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"magic-link rejected: {exc}") from exc

    patient_id = payload.get("p")
    nonce = payload.get("n")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not (
        isinstance(patient_id, str) and patient_id
        and isinstance(nonce, str) and nonce
        and isinstance(issued_at, int) and isinstance(expires_at, int)
    ):
        raise ValueError("magic-link payload missing required claims")
    if now is not None and now >= expires_at:
        raise ValueError("magic-link token expired")
    return MagicLinkClaims(
        patient_id=patient_id,
        nonce=nonce,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def sign_state(patient_id: str, nonce: str, secret: str) -> str:
    """Build the OAuth ``state`` value as a non-expiring signed JWT."""
    if not patient_id or not nonce:
        raise ValueError("patient_id and nonce are required")
    return jwt.encode({"p": patient_id, "n": nonce}, secret, algorithm=_ALG)


def verify_state(state: str, secret: str) -> tuple[str, str]:
    """Verify the OAuth ``state`` JWT.

    Returns ``(patient_id, nonce)``. Raises ``ValueError`` on tampered input.
    """
    if not state:
        raise ValueError("malformed oauth state")
    try:
        payload = jwt.decode(state, secret, algorithms=[_ALG], options={"verify_exp": False})
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"oauth state rejected: {exc}") from exc
    patient_id = payload.get("p")
    nonce = payload.get("n")
    if not (isinstance(patient_id, str) and patient_id and isinstance(nonce, str) and nonce):
        raise ValueError("oauth state missing required claims")
    return patient_id, nonce
