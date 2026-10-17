"""Notification delivery history logging via Cache API."""
import json
from datetime import datetime, timezone
from typing import Any

from canvas_sdk.caching.plugins import get_cache

CACHE_TTL = 1209600  # 14 days in seconds


def get_patient_log(patient_id: str) -> list[dict]:
    """Read the patient's notification history log from cache."""
    cache = get_cache()
    data = cache.get(f"cr:log:{patient_id}", default="[]")
    result: list[dict[Any, Any]] = json.loads(data)
    return result


def log_delivery_to_cache(
    appointment_id: str,
    patient_id: str,
    campaign_type: str,
    results: list,
) -> None:
    """Log notification delivery attempts to cache for history display.

    Each DeliveryResult becomes a separate log entry with its own channel,
    status, and error fields.
    """
    cache = get_cache()
    timestamp = datetime.now(timezone.utc).isoformat()

    entries = []
    for result in results:
        entries.append({
            "timestamp": timestamp,
            "appointment_id": appointment_id,
            "patient_id": patient_id,
            "campaign_type": campaign_type,
            "channel": result.channel,
            "status": "delivered" if result.success else "failed",
            "error": result.error,
            "error_code": getattr(result, "error_code", None),
        })

    if not entries:
        return

    # Update patient log (last 100 entries)
    log_key = f"cr:log:{patient_id}"
    existing = cache.get(log_key, default="[]")
    log_entries = json.loads(existing)
    log_entries.extend(entries)
    log_entries = log_entries[-100:]
    cache.set(log_key, json.dumps(log_entries), timeout_seconds=CACHE_TTL)

    # Update global log (last 1000 entries)
    global_log_key = "cr:global_log"
    existing_global = cache.get(global_log_key, default="[]")
    global_log_entries = json.loads(existing_global)
    global_log_entries.extend(entries)
    global_log_entries = global_log_entries[-1000:]
    cache.set(global_log_key, json.dumps(global_log_entries), timeout_seconds=CACHE_TTL)
