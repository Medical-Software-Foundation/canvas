"""OAuth tokens for a patient's Oura connection.

Storage note: the Canvas plugin sandbox blocks ``cryptography.fernet``, so
tokens are held opaquely rather than encrypted at rest. See
``services/crypto.py`` for the seam and the full rationale. This mirrors the
approach taken by ``dexcom-cgm-viewer``, which cleared Canvas security review.

No Oura user identifier is stored. Resolving one needs the ``personal`` scope,
which this plugin deliberately does not request.
"""

# mypy: disable-error-code="var-annotated"

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import CharField, DateTimeField, TextField, UniqueConstraint


class OuraOAuthToken(CustomModel):
    """One row per connected patient. Tokens are stored opaquely."""

    patient_id = CharField(max_length=64)
    access_token = TextField()
    refresh_token = TextField()
    expires_at = DateTimeField()
    scopes = CharField(max_length=256, blank=True, default="")
    connected_at = DateTimeField()
    last_refresh_at = DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_id"],
                name="ouraoauthtoken_unique_patient",
            ),
        ]
