"""Encrypted OAuth tokens for a patient's Dexcom connection."""

# mypy: disable-error-code="var-annotated"

from django.db.models import CharField, DateTimeField, TextField, UniqueConstraint

from canvas_sdk.v1.data.base import CustomModel


class DexcomOAuthToken(CustomModel):
    """One row per connected patient. Tokens are stored opaquely."""

    patient_id = CharField(max_length=64)
    access_token = TextField()
    refresh_token = TextField()
    expires_at = DateTimeField()
    dexcom_user_id = CharField(max_length=128, blank=True, default="")
    connected_at = DateTimeField()
    last_refresh_at = DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["patient_id"],
                name="dexcomoauthtoken_unique_patient",
            ),
        ]
