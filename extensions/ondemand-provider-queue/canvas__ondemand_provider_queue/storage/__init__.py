"""Queue storage: Canvas custom data by default, S3 only when selected."""

from __future__ import annotations

from canvas__ondemand_provider_queue.settings import Settings
from canvas__ondemand_provider_queue.storage.base import QueueStore
from canvas__ondemand_provider_queue.storage.canvas_store import CanvasQueueStore
from canvas__ondemand_provider_queue.storage.s3_store import S3QueueStore, StoreUnavailableError

__all__ = ["QueueStore", "StoreUnavailableError", "get_store"]


def get_store(settings: Settings) -> QueueStore:
    """Return the configured store. Raises StoreUnavailableError if S3 is half set up."""
    if settings.storage == "s3":
        return S3QueueStore.from_settings(
            key=settings.aws_access_key,
            secret=settings.aws_secret_key,
            region=settings.s3_region,
            bucket=settings.s3_bucket,
            object_key=settings.s3_object_key,
        )
    return CanvasQueueStore()
