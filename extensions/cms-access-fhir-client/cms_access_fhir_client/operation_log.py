"""Helper for appending immutable rows to the ACCESSOperationLog audit table.

Writing an audit row must never break the actual CMS operation, so the create() is
wrapped — a logging failure is recorded and swallowed rather than propagated.
"""
from logger import log

from cms_access_fhir_client.models import ACCESSOperationLog


def record_operation_event(
    *,
    patient,
    track: str,
    operation: str,
    phase: str,
    result_code: str = "",
    result_system: str = "",
    http_status: int = 0,
    detail: str = "",
    content_location: str = "",
    exchange: dict | None = None,
) -> None:
    """Append one ACCESSOperationLog row. Best-effort: never raises into the caller."""
    try:
        ACCESSOperationLog.objects.create(
            patient=patient,
            track=track or "",
            operation=operation or "",
            phase=phase,
            result_code=result_code or "",
            result_system=result_system or ACCESSOperationLog.SYSTEM_FOR_OP.get(operation, ""),
            http_status=http_status or 0,
            detail=detail or "",
            content_location=content_location or "",
            exchange=exchange or {},
        )
    except Exception as exc:  # noqa: BLE001 - audit logging must not break the operation
        log.error(f"[cms-access] failed to write ACCESSOperationLog: {exc}")
