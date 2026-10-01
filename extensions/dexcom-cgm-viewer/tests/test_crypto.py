"""TokenCipher pass-through wrapper.

The Canvas plugin sandbox blocks ``cryptography``, so this layer is a no-op
seam that lets the rest of the codebase stay agnostic to whether real
encryption is in place. Tests verify the contract — round-trip stability —
without asserting actual confidentiality.
"""

from __future__ import annotations

from dexcom_cgm_viewer.services.crypto import TokenCipher


def test_round_trip_returns_input_unchanged() -> None:
    cipher = TokenCipher("any-key")
    assert cipher.encrypt("super-secret-access-token") == "super-secret-access-token"
    assert cipher.decrypt("super-secret-access-token") == "super-secret-access-token"


def test_default_key_is_empty_and_does_not_raise() -> None:
    cipher = TokenCipher()
    assert cipher.encrypt("x") == "x"
    assert cipher.decrypt("y") == "y"


def test_two_instances_with_different_keys_round_trip_each_other() -> None:
    a = TokenCipher("key-a")
    b = TokenCipher("key-b")
    # Pass-through: any cipher decrypts any other's "ciphertext" identically.
    assert b.decrypt(a.encrypt("payload")) == "payload"
