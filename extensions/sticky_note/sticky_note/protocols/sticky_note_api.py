import json
from datetime import datetime, timezone
from hmac import compare_digest

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, BearerCredentials
from canvas_sdk.v1.data import Patient, Staff

from logger import log

from sticky_note.models import StickyNote, StickyNoteAudit

MAX_CONTENT_LENGTH = 4096
VALID_NOTE_TYPES = ("shared", "user")
VALID_ACTIONS = ("created", "edited", "cleared")


def _resolve_patient_dbid(patient_uuid: str) -> int:
    """Resolve a patient UUID to its integer dbid for FK lookups."""
    return Patient.objects.values_list("dbid", flat=True).get(id=patient_uuid)


def _resolve_staff_dbid(staff_uuid: str) -> int:
    """Resolve a staff UUID to its integer dbid for FK lookups."""
    return Staff.objects.values_list("dbid", flat=True).get(id=staff_uuid)


def _resolve_staff(staff_uuid: str) -> tuple:
    """Resolve staff UUID to (dbid, display_name) in a single query.

    Returns a tuple of (int, str). Raises Staff.DoesNotExist if not found.
    """
    row = (
        Staff.objects.filter(id=staff_uuid)
        .values_list("dbid", "first_name", "last_name")
        .first()
    )
    if not row:
        raise Staff.DoesNotExist
    dbid, first, last = row
    first = first or ""
    last = last or ""
    name = ("%s %s" % (first, last)).strip() or "Unknown"
    return (dbid, name)


def _write_audit(patient_dbid, patient_uuid, owner_id, note_type,
                 action, content, staff_uuid, staff_name):
    """Append an immutable audit record.

    Validates action against VALID_ACTIONS before writing.
    """
    if action not in VALID_ACTIONS:
        log.error("StickyNote: invalid audit action '%s'" % action)
        return

    StickyNoteAudit.objects.create(
        patient_dbid=patient_dbid,
        patient_uuid=patient_uuid,
        note_type=note_type,
        owner_dbid=owner_id,
        action=action,
        content=content,
        edited_by_id=staff_uuid,
        edited_by_name=staff_name,
    )


def _read_current_state(patient_dbid, owner_id) -> dict:
    """Read current note state for conflict response."""
    row = (
        StickyNote.objects.filter(patient_id=patient_dbid, owner_id=owner_id)
        .values("content", "version", "updated_by", "updated_at")
        .first()
    )
    if not row:
        return {}
    return {
        "status": "conflict",
        "content": row["content"],
        "version": row["version"],
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
    }


def _save_note(patient_dbid, patient_uuid, owner_id, note_type,
               content, staff_uuid, staff_name, expected_version,
               audit=False) -> dict:
    """Save a sticky note with atomic optimistic locking and optional audit.

    Uses QuerySet.update() with a version filter for database-level atomicity.
    When audit=True, writes a single audit entry for the session.
    Returns a dict with status ("ok" or "conflict") and current version.
    """
    lookup = {"patient_id": patient_dbid, "owner_id": owner_id}
    existing = (
        StickyNote.objects.filter(**lookup)
        .values("content", "version", "updated_by", "updated_by_id", "updated_at")
        .first()
    )

    if existing:
        # No-op: content unchanged — don't bump version
        if existing["content"] == content:
            if audit:
                action = "cleared" if not content else "edited"
                _write_audit(
                    patient_dbid=patient_dbid,
                    patient_uuid=patient_uuid,
                    owner_id=owner_id,
                    note_type=note_type,
                    action=action,
                    content=content,
                    staff_uuid=staff_uuid,
                    staff_name=staff_name,
                )
            return {"status": "ok", "version": existing["version"]}

        # Atomic conditional update — only succeeds if version still matches
        new_version = expected_version + 1
        now = datetime.now(timezone.utc)

        updated_rows = StickyNote.objects.filter(
            patient_id=patient_dbid,
            owner_id=owner_id,
            version=expected_version,
        ).update(
            content=content,
            updated_by=staff_name,
            updated_by_id=staff_uuid,
            version=new_version,
            updated_at=now,
        )

        if updated_rows == 0:
            # Version conflict — return current state
            conflict = _read_current_state(patient_dbid, owner_id)
            if conflict:
                return conflict
            return {"status": "error", "message": "Note not found"}

        # Write audit only when explicitly requested (session end)
        if audit:
            action = "cleared" if not content else "edited"
            _write_audit(
                patient_dbid=patient_dbid,
                patient_uuid=patient_uuid,
                owner_id=owner_id,
                note_type=note_type,
                action=action,
                content=content,
                staff_uuid=staff_uuid,
                staff_name=staff_name,
            )

        return {"status": "ok", "version": new_version}
    else:
        StickyNote.objects.create(
            patient_id=patient_dbid,
            owner_id=owner_id,
            content=content,
            updated_by=staff_name,
            updated_by_id=staff_uuid,
            version=1,
            history=[],
        )

        if audit and content:
            _write_audit(
                patient_dbid=patient_dbid,
                patient_uuid=patient_uuid,
                owner_id=owner_id,
                note_type=note_type,
                action="created",
                content=content,
                staff_uuid=staff_uuid,
                staff_name=staff_name,
            )

        return {"status": "ok", "version": 1}


def _authenticate_request(secrets, credentials) -> bool:
    """Validate bearer token against the namespace secret."""
    expected = secrets.get("namespace_read_write_access_key", "")
    if not expected:
        log.error("StickyNote: namespace_read_write_access_key not configured")
        return False
    return compare_digest(credentials.token, expected)


class StickyNoteAPI(SimpleAPIRoute):
    PATH = "/sticky-note/notes"

    def authenticate(self, credentials: BearerCredentials) -> bool:
        return _authenticate_request(self.secrets, credentials)

    def get(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        staff_id = self.request.query_params.get("staff_id")

        if not patient_id or not staff_id:
            return [
                JSONResponse(
                    {"status": "error", "message": "Missing patient_id or staff_id"}
                )
            ]

        try:
            patient_dbid = _resolve_patient_dbid(patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"status": "error", "message": "Patient not found"})]

        try:
            staff_dbid = _resolve_staff_dbid(staff_id)
        except Staff.DoesNotExist:
            return [JSONResponse({"status": "error", "message": "Staff not found"})]

        try:
            shared = (
                StickyNote.objects.filter(
                    patient_id=patient_dbid, owner_id__isnull=True
                )
                .values("content", "updated_by", "updated_by_id",
                        "updated_at", "version")
                .first()
            )
            user_row = (
                StickyNote.objects.filter(
                    patient_id=patient_dbid, owner_id=staff_dbid
                )
                .values("content", "version")
                .first()
            )

            shared_meta = {}
            if shared and shared.get("updated_by"):
                updated_at = shared.get("updated_at")
                shared_meta = {
                    "updated_by": shared["updated_by"],
                    "updated_by_id": shared.get("updated_by_id", ""),
                    "updated_at": updated_at.isoformat() if updated_at else "",
                }

            log.info(
                "StickyNoteAPI: staff %s viewed notes for patient %s"
                % (staff_id, patient_id)
            )

            return [
                JSONResponse(
                    {
                        "status": "ok",
                        "shared_note": (shared or {}).get("content", ""),
                        "shared_version": (shared or {}).get("version", 0),
                        "shared_meta": shared_meta,
                        "user_note": (user_row or {}).get("content", ""),
                        "user_version": (user_row or {}).get("version", 0),
                    }
                )
            ]
        except Exception as e:
            log.error("StickyNoteAPI GET error: %s" % e)
            return [JSONResponse({"status": "error", "message": "Internal error"})]

    def post(self) -> list[Response | Effect]:
        try:
            data = json.loads(self.request.body)
        except Exception:
            return [JSONResponse({"status": "error", "message": "Invalid JSON"})]

        patient_id = data.get("patient_id")
        staff_id = data.get("staff_id")
        note_type = data.get("type")  # "shared" or "user"
        content = data.get("content", "")
        version = data.get("version", 0)
        audit = bool(data.get("audit", False))

        if not patient_id or not staff_id or not note_type:
            return [
                JSONResponse({"status": "error", "message": "Missing required fields"})
            ]

        if note_type not in VALID_NOTE_TYPES:
            return [JSONResponse({"status": "error", "message": "Invalid type"})]

        if not isinstance(version, int) or version < 0:
            return [JSONResponse({"status": "error", "message": "Invalid version"})]

        if len(content) > MAX_CONTENT_LENGTH:
            return [
                JSONResponse({
                    "status": "error",
                    "message": "Content exceeds %s characters" % MAX_CONTENT_LENGTH,
                })
            ]

        try:
            patient_dbid = _resolve_patient_dbid(patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"status": "error", "message": "Patient not found"})]

        try:
            staff_dbid, staff_name = _resolve_staff(staff_id)

            if note_type == "shared":
                owner_id = None
            else:
                owner_id = staff_dbid

            result = _save_note(
                patient_dbid=patient_dbid,
                patient_uuid=patient_id,
                owner_id=owner_id,
                note_type=note_type,
                content=content,
                staff_uuid=staff_id,
                staff_name=staff_name,
                expected_version=version,
                audit=audit,
            )

            if result["status"] == "ok":
                log.info(
                    "StickyNoteAPI: saved %s note (v%s) for patient %s by %s"
                    % (note_type, result["version"], patient_id, staff_id)
                )
            else:
                log.info(
                    "StickyNoteAPI: conflict on %s note for patient %s by %s"
                    % (note_type, patient_id, staff_id)
                )

            return [JSONResponse(result)]
        except Staff.DoesNotExist:
            return [JSONResponse({"status": "error", "message": "Staff not found"})]
        except Exception as e:
            log.error("StickyNoteAPI POST error: %s" % e)
            return [JSONResponse({"status": "error", "message": "Internal error"})]


class StickyNoteHistoryAPI(SimpleAPIRoute):
    """Return edit history for a sticky note from the audit table."""

    PATH = "/sticky-note/history"

    def authenticate(self, credentials: BearerCredentials) -> bool:
        return _authenticate_request(self.secrets, credentials)

    def get(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient_id")
        staff_id = self.request.query_params.get("staff_id")
        note_type = self.request.query_params.get("type", "shared")

        if not patient_id or not staff_id:
            return [
                JSONResponse(
                    {"status": "error", "message": "Missing patient_id or staff_id"}
                )
            ]

        if note_type not in VALID_NOTE_TYPES:
            return [JSONResponse({"status": "error", "message": "Invalid type"})]

        try:
            patient_dbid = _resolve_patient_dbid(patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"status": "error", "message": "Patient not found"})]

        try:
            # Resolve staff dbid upfront so it's available for both paths
            staff_dbid = None
            if note_type == "user":
                staff_dbid = _resolve_staff_dbid(staff_id)

            # Build audit table filters
            audit_filters = {
                "patient_dbid": patient_dbid,
                "note_type": note_type,
            }
            if staff_dbid is not None:
                audit_filters["owner_dbid"] = staff_dbid

            # Read from audit table — newest first, up to 50 entries
            rows = (
                StickyNoteAudit.objects
                .filter(**audit_filters)
                .order_by("-edited_at")
                .values(
                    "content", "edited_by_name", "edited_by_id",
                    "edited_at", "action",
                )[:50]
            )

            history = [
                {
                    "content": r["content"],
                    "edited_by": r["edited_by_name"],
                    "edited_by_id": r["edited_by_id"],
                    "edited_at": (
                        r["edited_at"].isoformat() if r["edited_at"] else ""
                    ),
                    "action": r["action"],
                }
                for r in rows
            ]

            # Fallback: if audit table is empty, check legacy JSONField
            if not history:
                legacy_lookup = {"patient_id": patient_dbid}
                if note_type == "shared":
                    legacy_lookup["owner_id__isnull"] = True
                else:
                    legacy_lookup["owner_id"] = staff_dbid

                legacy_row = (
                    StickyNote.objects.filter(**legacy_lookup)
                    .values_list("history", flat=True)
                    .first()
                )
                if legacy_row and isinstance(legacy_row, list):
                    history = [
                        entry for entry in reversed(legacy_row)
                        if isinstance(entry, dict)
                    ]

            log.info(
                "StickyNoteHistoryAPI: staff %s viewed %s history for patient %s"
                % (staff_id, note_type, patient_id)
            )

            return [JSONResponse({"status": "ok", "history": history})]
        except Staff.DoesNotExist:
            return [JSONResponse({"status": "error", "message": "Staff not found"})]
        except Exception as e:
            log.error("StickyNoteHistoryAPI GET error: %s" % e)
            return [JSONResponse({"status": "error", "message": "Internal error"})]
