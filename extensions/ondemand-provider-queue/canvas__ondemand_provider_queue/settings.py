"""Plugin settings, read once per request from the plugin's variables.

Every setting has a safe default: the queue is off until ``QUEUE_ENABLED`` is
``true``, demo tools are off, and storage is Canvas custom data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
DEFAULT_S3_OBJECT_KEY = "ondemand-provider-queue/queue.json"


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def _id_list(value: str | None) -> frozenset[str]:
    return frozenset(part.strip() for part in (value or "").split(",") if part.strip())


def _text(secrets: dict[str, str], key: str, default: str = "") -> str:
    return (secrets.get(key) or default).strip()


@dataclass(frozen=True)
class Settings:
    """Typed view of the plugin's variables."""

    enabled: bool
    api_key: str = field(repr=False)
    staff_ids: frozenset[str]
    note_type_id: str
    practice_location_id: str
    demo_mode: bool
    demo_patient_ids: frozenset[str]
    storage: str
    aws_access_key: str = field(repr=False)
    aws_secret_key: str = field(repr=False)
    s3_bucket: str
    s3_region: str
    s3_object_key: str

    @classmethod
    def from_secrets(cls, secrets: dict[str, str]) -> Settings:
        """Build settings from ``self.secrets``."""
        storage = _text(secrets, "QUEUE_STORAGE", "canvas").lower()
        return cls(
            enabled=_flag(secrets.get("QUEUE_ENABLED")),
            api_key=_text(secrets, "QUEUE_API_KEY"),
            staff_ids=_id_list(secrets.get("QUEUE_STAFF_IDS")),
            note_type_id=_text(secrets, "DEFAULT_NOTE_TYPE_ID"),
            practice_location_id=_text(secrets, "DEFAULT_PRACTICE_LOCATION_ID"),
            demo_mode=_flag(secrets.get("DEMO_MODE_ENABLED")),
            demo_patient_ids=_id_list(secrets.get("DEMO_PATIENT_IDS")),
            storage="s3" if storage == "s3" else "canvas",
            aws_access_key=_text(secrets, "AWS_ACCESS_KEY"),
            aws_secret_key=_text(secrets, "AWS_SECRET_KEY"),
            s3_bucket=_text(secrets, "S3_BUCKET"),
            s3_region=_text(secrets, "S3_REGION"),
            s3_object_key=_text(secrets, "S3_OBJECT_KEY", DEFAULT_S3_OBJECT_KEY),
        )
