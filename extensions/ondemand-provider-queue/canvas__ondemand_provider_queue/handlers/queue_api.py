"""HTTP routes for the on-demand provider queue.

Two handlers, each with one way in:

* ``QueueIntakeAPI`` (``/intake/queue-request``) is for the outside system that
  sends patients to the queue. It needs ``Authorization: Bearer <QUEUE_API_KEY>``
  and refuses every request while that key is unset.
* ``QueueAPI`` (``/routes/...``) serves the queue screen. Every route needs a
  signed-in Canvas staff session (optionally limited by ``QUEUE_STAFF_IDS``).

While ``QUEUE_ENABLED`` is off, both answer 503 and change nothing.
"""

from __future__ import annotations

import json
from hmac import compare_digest
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    Credentials,
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient, Staff
from django.utils import timezone
from logger import log

from canvas__ondemand_provider_queue.handlers.common import (
    notify,
    staff_allowed,
    staff_name,
    with_patient_details,
)
from canvas__ondemand_provider_queue.settings import Settings
from canvas__ondemand_provider_queue.storage import QueueStore, StoreUnavailableError, get_store
from canvas__ondemand_provider_queue.storage.base import (
    ACTIVE_STATUSES,
    QueueEntryPriority,
    QueueEntryStatus,
)

MAX_REASON_LENGTH = 500
MAX_ID_LENGTH = 100
COMPLETED_LIMIT = 200
PRIORITIES = frozenset(p.value for p in QueueEntryPriority)
DEMO_REASONS = (
    "Follow-up visit",
    "Medication question",
    "New symptom check",
    "Test results review",
)


def _error(message: str, status: HTTPStatus) -> list[Response | Effect]:
    return [JSONResponse({"success": False, "error": message}, status_code=status)]


def _text_field(body: dict[str, Any], key: str, limit: int = MAX_ID_LENGTH) -> str:
    value = body.get(key)
    return value.strip()[:limit] if isinstance(value, str) else ""


class _QueueBase(SimpleAPI):
    """Settings, storage and request-body helpers shared by both handlers."""

    @property
    def settings(self) -> Settings:
        return Settings.from_secrets(self.secrets)

    def _store_or_error(self) -> tuple[QueueStore | None, list[Response | Effect]]:
        if not self.settings.enabled:
            return None, _error("The provider queue is turned off", HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            return get_store(self.settings), []
        except StoreUnavailableError as exc:
            log.error("ondemand_provider_queue: storage unavailable: %s", exc)
            return None, _error("Queue storage is unavailable", HTTPStatus.SERVICE_UNAVAILABLE)

    def _body(self) -> dict[str, Any]:
        try:
            body = self.request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return body if isinstance(body, dict) else {}


class QueueIntakeAPI(_QueueBase):
    """Lets an outside system add a patient to the queue."""

    PREFIX = "/intake"

    def authenticate(self, credentials: Credentials) -> bool:
        """Accept only ``Bearer <QUEUE_API_KEY>``; refuse everything while the key is unset."""
        expected = self.settings.api_key
        header = self.request.headers.get("authorization") or ""
        scheme, _, token = header.partition(" ")
        if not expected:
            log.warning("ondemand_provider_queue: QUEUE_API_KEY is not set; refusing intake")
            return False
        if scheme.lower() != "bearer" or not token:
            return False
        if not compare_digest(token.strip().encode(), expected.encode()):
            log.warning("ondemand_provider_queue: intake request with a wrong key refused")
            return False
        return True

    @api.post("/queue-request")
    def queue_request(self) -> list[Response | Effect]:
        """Add a patient. Repeating an ``external_id`` returns the first entry instead."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        body = self._body()
        patient_id = _text_field(body, "patient_id")
        reason = _text_field(body, "reason_for_visit", MAX_REASON_LENGTH)
        priority = _text_field(body, "priority") or QueueEntryPriority.ROUTINE.value
        if not patient_id or not reason:
            return _error("patient_id and reason_for_visit are required", HTTPStatus.BAD_REQUEST)
        if priority not in PRIORITIES:
            return _error("priority must be routine, urgent or emergent", HTTPStatus.BAD_REQUEST)
        if not Patient.objects.filter(id=patient_id).exists():
            return _error("Patient not found", HTTPStatus.NOT_FOUND)
        entry, created = store.create_entry(
            patient_id=patient_id,
            reason_for_visit=reason,
            priority=priority,
            external_id=_text_field(body, "external_id") or None,
            practice_location_id=_text_field(body, "practice_location_id") or None,
        )
        log.info("ondemand_provider_queue: entry %s created=%s", entry.id, created)
        response = JSONResponse(
            {"success": True, "created": created, "entry_id": entry.id, "status": entry.status},
            status_code=HTTPStatus.CREATED if created else HTTPStatus.OK,
        )
        return [response, notify("ENTRY_ADDED", entry)] if created else [response]


class QueueAPI(StaffSessionAuthMixin, _QueueBase):
    """The queue screen and the actions staff take on it."""

    PREFIX = "/routes"

    def authenticate(self, credentials: SessionCredentials) -> bool:  # type: ignore[override]
        """Signed-in staff only (the SDK mixin), then the optional QUEUE_STAFF_IDS list."""
        super().authenticate(credentials)  # raises unless the session user is staff
        user = credentials.logged_in_user
        return staff_allowed(self.settings, user["type"], user["id"])

    @property
    def user_id(self) -> str:
        """The signed-in staff member's id (set by Canvas from the session)."""
        return self.request.headers.get("canvas-logged-in-user-id") or ""

    # --- reads ---

    @api.get("/ui/queue")
    def queue_page(self) -> list[Response | Effect]:
        """Serve the queue screen."""
        return [HTMLResponse(render_to_string("templates/queue.html"), status_code=HTTPStatus.OK)]

    @api.get("/config")
    def config(self) -> list[Response | Effect]:
        """Tell the screen which optional tools to show."""
        return [
            JSONResponse(
                {"enabled": self.settings.enabled, "demo_mode_enabled": self.settings.demo_mode}
            )
        ]

    @api.get("/staff")
    def staff(self) -> list[Response | Effect]:
        """List active staff for the assignment menu, plus the signed-in user's id."""
        staff = Staff.objects.filter(active=True).only("id", "first_name", "last_name")
        rows = sorted(
            ({"id": s.id, "name": staff_name(s)} for s in staff), key=lambda r: r["name"].lower()
        )
        return [JSONResponse({"staff": rows, "current_user": {"id": self.user_id}})]

    @api.get("/queue")
    def queue(self) -> list[Response | Effect]:
        """List open entries, or the most recent completed ones with ``?view=completed``."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        params = self.request.query_params
        if params.get("view") == "completed":
            entries = store.list_entries((QueueEntryStatus.COMPLETE.value,))[-COMPLETED_LIMIT:]
            entries.reverse()
        else:
            entries = store.list_entries(
                ACTIVE_STATUSES,
                practice_location_id=params.get("practice_location_id") or None,
                priority=params.get("priority") or None,
            )
        return [JSONResponse({"entries": with_patient_details(entries)})]

    # --- assignment ---

    def _assign(self, store: QueueStore, entry_id: str, staff_id: str) -> list[Response | Effect]:
        staff = Staff.objects.filter(id=staff_id, active=True).first()
        if staff is None:
            return _error("Staff member not found", HTTPStatus.NOT_FOUND)
        entry, error = store.claim_entry(entry_id, staff.id, staff_name(staff))
        return self._result(entry, error, "ENTRY_CLAIMED")

    def _result(self, entry: Any, error: str | None, event_type: str) -> list[Response | Effect]:
        if entry is None:
            status = HTTPStatus.NOT_FOUND if error == "Entry not found" else HTTPStatus.CONFLICT
            return _error(error or "Request refused", status)
        return [
            JSONResponse({"success": True, "entry": entry.to_dict()}),
            notify(event_type, entry),
        ]

    @api.post("/claim-entry")
    def claim_entry(self) -> list[Response | Effect]:
        """Assign an unassigned entry to the signed-in staff member."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        entry_id = _text_field(self._body(), "entry_id")
        if not entry_id:
            return _error("entry_id is required", HTTPStatus.BAD_REQUEST)
        return self._assign(store, entry_id, self.user_id)

    @api.post("/update-assignment")
    def update_assignment(self) -> list[Response | Effect]:
        """Assign an entry to a staff member, or put it back in the queue."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        body = self._body()
        entry_id = _text_field(body, "entry_id")
        action = _text_field(body, "action")
        if not entry_id or action not in ("assign", "unassign"):
            return _error(
                "entry_id and action (assign or unassign) are required", HTTPStatus.BAD_REQUEST
            )
        if action == "unassign":
            entry, error = store.release_entry(entry_id)
            return self._result(entry, error, "STATUS_CHANGED")
        staff_id = _text_field(body, "staff_id")
        if not staff_id:
            return _error("staff_id is required to assign", HTTPStatus.BAD_REQUEST)
        return self._assign(store, entry_id, staff_id)

    # --- visit lifecycle ---

    @api.post("/start-visit")
    def start_visit(self) -> list[Response | Effect]:
        """Start the visit and create its note. A repeat click returns the same note."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        entry_id = _text_field(self._body(), "entry_id")
        current = store.get_entry(entry_id) if entry_id else None
        if current is None:
            return _error("Entry not found", HTTPStatus.NOT_FOUND)
        if current.status == QueueEntryStatus.IN_PROGRESS.value and current.note_id:
            # Already started (double click, or a retry after a dropped response).
            return [JSONResponse({"success": True, "note_id": current.note_id})]
        location_id = current.practice_location_id or self.settings.practice_location_id
        if not self.settings.note_type_id or not location_id or not current.assigned_provider_id:
            return _error(
                "Set DEFAULT_NOTE_TYPE_ID and DEFAULT_PRACTICE_LOCATION_ID, and assign a "
                "provider, before starting a visit",
                HTTPStatus.BAD_REQUEST,
            )
        note_id = str(uuid4())
        entry, error = store.start_entry(entry_id, note_id)
        if entry is None:
            return self._result(entry, error, "ENTRY_STARTED")
        note = Note(
            instance_id=note_id,
            note_type_id=self.settings.note_type_id,
            datetime_of_service=timezone.now(),
            patient_id=entry.patient_id,
            practice_location_id=location_id,
            provider_id=entry.assigned_provider_id,
        )
        log.info("ondemand_provider_queue: entry %s started note %s", entry.id, note_id)
        return [
            JSONResponse({"success": True, "note_id": note_id, "entry": entry.to_dict()}),
            note.create(),
            notify("ENTRY_STARTED", entry),
        ]

    @api.post("/pause-visit")
    def pause_visit(self) -> list[Response | Effect]:
        """Pause an in-progress visit."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        entry, error = store.pause_entry(_text_field(self._body(), "entry_id"))
        return self._result(entry, error, "STATUS_CHANGED")

    @api.post("/resume-visit")
    def resume_visit(self) -> list[Response | Effect]:
        """Resume a paused visit."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        entry, error = store.resume_entry(_text_field(self._body(), "entry_id"))
        return self._result(entry, error, "STATUS_CHANGED")

    # --- demo tools (DEMO_MODE_ENABLED only) ---

    @api.post("/demo-add-patient")
    def demo_add_patient(self) -> list[Response | Effect]:
        """Add one of the DEMO_PATIENT_IDS test patients that is not already waiting."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        if not self.settings.demo_mode:
            return _error("Demo mode is off", HTTPStatus.FORBIDDEN)
        active = store.list_entries(ACTIVE_STATUSES)
        waiting = {e.patient_id for e in active}
        candidates = sorted(self.settings.demo_patient_ids - waiting)
        if not candidates:
            return _error("No test patients left: set DEMO_PATIENT_IDS", HTTPStatus.CONFLICT)
        entry, _ = store.create_entry(
            patient_id=candidates[0],
            reason_for_visit=DEMO_REASONS[len(active) % len(DEMO_REASONS)],
        )
        return [JSONResponse({"success": True, "entry_id": entry.id}), notify("ENTRY_ADDED", entry)]

    @api.post("/demo-clear-queue")
    def demo_clear_queue(self) -> list[Response | Effect]:
        """Remove every open entry (completed history is kept)."""
        store, refused = self._store_or_error()
        if store is None:
            return refused
        if not self.settings.demo_mode:
            return _error("Demo mode is off", HTTPStatus.FORBIDDEN)
        removed = store.clear_active()
        log.info("ondemand_provider_queue: demo clear removed %s entries", removed)
        return [JSONResponse({"success": True, "removed": removed}), notify("QUEUE_CLEARED")]
