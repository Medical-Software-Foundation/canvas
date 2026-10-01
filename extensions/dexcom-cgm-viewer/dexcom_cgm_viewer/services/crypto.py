"""Token storage abstraction.

The Canvas plugin sandbox blocks ``cryptography.fernet``, so true encryption
at rest is not currently possible inside the plugin runtime. This module
keeps the ``encrypt`` / ``decrypt`` API as a seam so that real encryption
can be added later (e.g. via a Canvas-side encrypted-field type) without
touching call-sites in ``oauth.py`` or ``storage.py``.

For now the operations are pass-through. Tokens are still scoped to the
plugin's namespaced custom-data tables and are never exposed via plugin
APIs (only the staff-authenticated ``/data`` route is exposed, and it never
returns token material). Refresh tokens remain single-use and rotated on
every refresh, which is the more important defense.
"""

class TokenCipher:
    """Pass-through token wrapper.

    ``key`` is accepted for forward compatibility with a real encryption
    implementation; it is currently ignored.
    """

    def __init__(self, key: str = "") -> None:
        self._key = key  # retained for diagnostic / future use

    def encrypt(self, plaintext: str) -> str:
        """Return ``plaintext`` unchanged. Future: real symmetric encryption."""
        return plaintext

    def decrypt(self, ciphertext: str) -> str:
        """Return ``ciphertext`` unchanged. Future: real decryption."""
        return ciphertext
