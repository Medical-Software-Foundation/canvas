"""SimpleAPI routes for lab order favorites.

Backs both applications:
- the global config app (CRUD, catalog lookups, CSV bulk upload)
- the patient-scoped app (open-note picker, validated staged LabOrder insert)
"""

import json
from typing import Any

from canvas_sdk.commands import LabOrderCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import CurrentNoteStateEvent, Note, Patient
from canvas_sdk.v1.data.note import NoteStates
from logger import log

API_BASE = "/plugin-io/api/lab_order_favorites"

from lab_order_favorites.services import FavoritesService
from lab_order_favorites.services.csv_parser import generate_template_csv, parse_favorites_csv
from lab_order_favorites.services.lab_catalog import (
    check_availability,
    list_active_partners,
    list_tests_for_partner,
    resolve_partner,
)
from lab_order_favorites.services.providers import list_ordering_providers, resolve_provider

OPEN_NOTE_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.CONVERTED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]


class _FavoritesHelpers:
    """Shared helpers for the favorites routes (staff id, JSON body parsing)."""

    def _staff_id(self) -> str:
        staff_id: str = self.request.headers.get("canvas-logged-in-user-id", "")  # type: ignore[attr-defined]
        return staff_id

    def _json_body(self) -> dict[str, Any]:
        """Parse the request body as a JSON object.

        Prefer the parsed `request.json()`; fall back to decoding the raw body
        when that accessor is unavailable. Raises ValueError on an empty or
        non-object body so callers return 400 rather than an unhandled 500.
        """
        try:
            parsed = self.request.json()  # type: ignore[attr-defined]
        except (ValueError, AttributeError, TypeError):
            raw_body = self.request.body  # type: ignore[attr-defined]
            if not raw_body:
                raise ValueError("empty request body")
            if hasattr(raw_body, "decode"):
                raw_body = raw_body.decode("utf-8")
            parsed = json.loads(raw_body)
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def _service(self) -> FavoritesService:
        return FavoritesService()

    def _editor_keys(self) -> set[str]:
        """Staff keys allowed to edit shared favorites (from a plugin variable)."""
        raw = self.secrets.get("SHARED_FAVORITE_EDITORS", "") or ""  # type: ignore[attr-defined]
        return {key.strip() for key in raw.split(",") if key.strip()}


# Staff keys always permitted to edit/delete any favorite (the Canvas superuser
# session). Independent of the configured allowlist.
ALWAYS_ALLOWED_KEYS = {"root"}


def _can_edit(
    is_shared: bool, created_by_id: str | None, staff_id: str, editor_keys: set[str]
) -> bool:
    """Whether staff_id may edit/delete a favorite.

    root (the Canvas superuser) may edit anything. Personal favorites: author
    only. Shared favorites: the author, or any staff member whose key is in the
    configured editor allowlist (empty list keeps shared favorites author-only).
    """
    if staff_id in ALWAYS_ALLOWED_KEYS:
        return True
    is_author = bool(created_by_id and created_by_id == staff_id)
    if not is_shared:
        return is_author
    return is_author or staff_id in editor_keys


class FavoritesAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """List, create, update, and delete lab order favorites."""

    PATH = "/routes/favorites"

    def get(self) -> list[Response]:
        staff_id = self._staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status_code=400)]

        visibility_filter = self.request.query_params.get("filter", "all").strip()
        search = self.request.query_params.get("search", "").strip()

        favorites = self._service().list_favorites(
            staff_id=staff_id, visibility_filter=visibility_filter, search=search
        )
        # Annotate each with whether this staff member may edit/delete it, so the
        # config UI can show edit/delete controls to authors, allowlisted editors, and root.
        editor_keys = self._editor_keys()
        for fav in favorites:
            fav["can_edit"] = _can_edit(fav["is_shared"], fav.get("created_by_id"), staff_id, editor_keys)
        return [JSONResponse({"favorites": favorites, "count": len(favorites), "success": True})]

    def post(self) -> list[Response]:
        staff_id = self._staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status_code=400)]

        try:
            body = self._json_body()
        except ValueError:
            return [JSONResponse({"error": "Invalid JSON in request body", "success": False}, status_code=400)]

        validation = _validate_partner_and_tests(body)
        if validation is not None:
            return [validation]

        provider_error = _resolve_provider_on_body(body)
        if provider_error is not None:
            return [provider_error]

        try:
            favorite = self._service().create_favorite(body, staff_id)
        except ValueError as e:
            return [JSONResponse({"error": str(e), "success": False}, status_code=400)]

        return [JSONResponse({"favorite": favorite, "success": True})]

    def put(self) -> list[Response]:
        staff_id = self._staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status_code=400)]

        try:
            body = self._json_body()
        except ValueError:
            return [JSONResponse({"error": "Invalid JSON in request body", "success": False}, status_code=400)]

        favorite_id = str(body.get("id", "")).strip()
        if not favorite_id:
            return [JSONResponse({"error": "Favorite ID is required", "success": False}, status_code=400)]

        service = self._service()
        existing = service.get_favorite_model(favorite_id)
        if existing is None:
            return [JSONResponse({"error": "Favorite not found", "success": False}, status_code=404)]
        created_by_id = str(existing.created_by.id) if existing.created_by else None
        if not _can_edit(existing.is_shared, created_by_id, staff_id, self._editor_keys()):
            return [JSONResponse({"error": "Not authorized to edit this favorite", "success": False}, status_code=403)]

        # Re-validate tests when partner or tests are being changed.
        if "tests" in body or "lab_partner_id" in body:
            check_body = {
                "lab_partner_id": body.get("lab_partner_id", existing.lab_partner_id),
                "tests": body.get("tests", existing.tests),
            }
            validation = _validate_partner_and_tests(check_body)
            if validation is not None:
                return [validation]

        provider_error = _resolve_provider_on_body(body)
        if provider_error is not None:
            return [provider_error]

        try:
            updated = service.update_favorite(favorite_id, body, staff_id)
        except ValueError as e:
            return [JSONResponse({"error": str(e), "success": False}, status_code=400)]

        if updated is None:
            return [JSONResponse({"error": "Failed to update favorite", "success": False}, status_code=500)]
        return [JSONResponse({"favorite": updated, "success": True})]

    def delete(self) -> list[Response]:
        staff_id = self._staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status_code=400)]

        favorite_id = self.request.query_params.get("id", "").strip()
        if not favorite_id:
            return [JSONResponse({"error": "Favorite ID is required", "success": False}, status_code=400)]

        service = self._service()
        existing = service.get_favorite_model(favorite_id)
        if existing is None:
            return [JSONResponse({"error": "Favorite not found", "success": False}, status_code=404)]
        created_by_id = str(existing.created_by.id) if existing.created_by else None
        if not _can_edit(existing.is_shared, created_by_id, staff_id, self._editor_keys()):
            return [JSONResponse({"error": "Not authorized to delete this favorite", "success": False}, status_code=403)]

        deleted = service.delete_favorite(favorite_id)
        if not deleted:
            return [JSONResponse({"error": "Failed to delete favorite", "success": False}, status_code=500)]
        return [JSONResponse({"message": f"Favorite {favorite_id} deleted", "success": True})]


class ConfigPageAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """Serve the favorites configuration page (opened in a new tab from the menu)."""

    PATH = "/app/config"

    def get(self) -> list[Response]:
        html = render_to_string("templates/config.html", {"api_base": API_BASE})
        return [HTMLResponse(html, status_code=200)]


class PartnersAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """List active lab partners configured in the instance."""

    PATH = "/routes/partners"

    def get(self) -> list[Response]:
        partners = list_active_partners()
        return [JSONResponse({"partners": partners, "count": len(partners), "success": True})]


class ProvidersAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """List selectable ordering providers (active staff with a usable NPI)."""

    PATH = "/routes/providers"

    def get(self) -> list[Response]:
        search = self.request.query_params.get("search", "").strip()
        providers = list_ordering_providers(search)
        return [JSONResponse({"providers": providers, "count": len(providers), "success": True})]


class PartnerTestsAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """List the tests a given lab partner offers."""

    PATH = "/routes/partners/tests"

    def get(self) -> list[Response]:
        partner_id = self.request.query_params.get("partner_id", "").strip()
        if not partner_id:
            return [JSONResponse({"error": "partner_id is required", "success": False}, status_code=400)]
        search = self.request.query_params.get("search", "").strip()
        tests = list_tests_for_partner(partner_id, search=search)
        return [JSONResponse({"tests": tests, "count": len(tests), "success": True})]


class CSVTemplateAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """Return the favorites CSV upload template."""

    PATH = "/routes/csv-template"

    def get(self) -> list[Response]:
        content = generate_template_csv()
        return [
            Response(
                content.encode("utf-8"),
                status_code=200,
                content_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=lab_favorites_template.csv"},
            )
        ]


class CSVImportAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """Validate and import favorites from an uploaded CSV.

    POST with {"csv": "...", "commit": false} returns a validation preview.
    POST with {"csv": "...", "commit": true} creates the valid favorites.
    """

    PATH = "/routes/csv-import"

    def post(self) -> list[Response]:
        staff_id = self._staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status_code=400)]

        try:
            body = self._json_body()
        except ValueError:
            return [JSONResponse({"error": "Invalid JSON in request body", "success": False}, status_code=400)]

        csv_content = str(body.get("csv", ""))
        if not csv_content.strip():
            return [JSONResponse({"error": "csv content is required", "success": False}, status_code=400)]
        commit = bool(body.get("commit", False))

        parsed = parse_favorites_csv(csv_content)

        ready: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = [
            {"row": e.row_number, "errors": e.errors} for e in parsed.error_rows
        ]

        # Cache partner resolution and each partner's test catalog so a CSV with
        # many panels sharing a lab partner does not re-query the same data per row.
        partner_cache: dict[str, tuple[Any, str]] = {}
        catalog_cache: dict[str, dict[str, dict[str, str]]] = {}

        for row in parsed.parsed_rows:
            if row.lab_partner not in partner_cache:
                partner_cache[row.lab_partner] = resolve_partner(row.lab_partner)
            partner, reason = partner_cache[row.lab_partner]
            if partner is None:
                errors.append({"row": row.row_number, "errors": [reason]})
                continue

            partner_id = str(partner.id)
            if partner_id not in catalog_cache:
                catalog_cache[partner_id] = {
                    t["order_code"]: t for t in list_tests_for_partner(partner_id)
                }
            by_code = catalog_cache[partner_id]

            stale = [code for code in row.order_codes if code not in by_code]
            if stale:
                errors.append(
                    {
                        "row": row.row_number,
                        "errors": [f"unknown test codes for {partner.name}: {', '.join(stale)}"],
                    }
                )
                continue

            ready.append(
                {
                    "row": row.row_number,
                    "name": row.name,
                    "lab_partner_id": partner_id,
                    "lab_partner_name": partner.name or "",
                    "tests": [by_code[code] for code in row.order_codes],
                    "tags": row.tags,
                    "is_shared": row.is_shared,
                    "fasting_required": row.fasting_required,
                    "comment": row.comment,
                    "diagnosis_codes": row.diagnosis_codes,
                }
            )

        if not commit:
            return [
                JSONResponse(
                    {
                        "preview": True,
                        "ready_count": len(ready),
                        "error_count": len(errors),
                        "ready": ready,
                        "errors": errors,
                        "success": True,
                    }
                )
            ]

        service = self._service()
        created = 0
        for item in ready:
            try:
                service.create_favorite(item, staff_id)
                created = created + 1
            except ValueError as e:
                errors.append({"row": item["row"], "errors": [str(e)]})

        return [
            JSONResponse(
                {
                    "preview": False,
                    "created": created,
                    "error_count": len(errors),
                    "errors": errors,
                    "success": True,
                }
            )
        ]


class OpenNotesAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """List a patient's open notes for the insert target picker."""

    PATH = "/routes/notes"

    def get(self) -> list[Response]:
        patient_id = self.request.query_params.get("patient_id", "").strip()
        if not patient_id:
            return [JSONResponse({"error": "patient_id is required", "success": False}, status_code=400)]

        notes = _open_notes_for_patient(patient_id)
        payload = [
            {
                "id": str(note.id),
                "title": note.title or (note.note_type_version.name if note.note_type_version else "Note"),
                "modified": note.modified.isoformat() if note.modified else None,
            }
            for note in notes
        ]
        return [JSONResponse({"notes": payload, "count": len(payload), "success": True})]


class InsertFavoriteAPI(_FavoritesHelpers, StaffSessionAuthMixin, SimpleAPIRoute):
    """Validate a favorite and insert it as a staged LabOrder command.

    The favorite's saved test codes are re-validated against the live catalog.
    If the partner is inactive or any code is stale, nothing is inserted and the
    invalid items are returned so the favorite can be corrected.
    """

    PATH = "/routes/insert"

    def post(self) -> list[Response | Effect]:
        staff_id = self._staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status_code=400)]

        try:
            body = self._json_body()
        except ValueError:
            return [JSONResponse({"error": "Invalid JSON in request body", "success": False}, status_code=400)]

        favorite_ids = _requested_favorite_ids(body)
        patient_id = str(body.get("patient_id", "")).strip()
        note_uuid = str(body.get("note_uuid", "")).strip()
        if not favorite_ids or not patient_id or not note_uuid:
            return [JSONResponse({"error": "favorite_ids, patient_id and note_uuid are required", "success": False}, status_code=400)]

        # The target note must be an open note for this patient.
        open_note_ids = {str(note.id) for note in _open_notes_for_patient(patient_id)}
        if note_uuid not in open_note_ids:
            return [JSONResponse({"error": "Selected note is not an open note for this patient", "success": False}, status_code=400)]

        service = self._service()
        editor_keys = self._editor_keys()
        inserted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        effects: list[Effect] = []

        for favorite_id in favorite_ids:
            favorite = service.get_favorite(favorite_id, staff_id)
            if favorite is None:
                skipped.append({"favorite_id": favorite_id, "name": favorite_id, "reason": "not_found", "can_edit": False})
                continue

            can_edit = _can_edit(favorite["is_shared"], favorite.get("created_by_id"), staff_id, editor_keys)
            order_codes = [t.get("order_code", "") for t in favorite["tests"] if t.get("order_code")]
            availability = check_availability(favorite["lab_partner_id"], order_codes)

            if not availability["partner_found"] or not availability["partner_active"]:
                reason = "partner_missing" if not availability["partner_found"] else "partner_inactive"
                skipped.append({"favorite_id": favorite_id, "name": favorite["name"], "reason": reason, "can_edit": can_edit, "owner_name": favorite.get("created_by_name")})
                continue
            if availability["stale"]:
                skipped.append({"favorite_id": favorite_id, "name": favorite["name"], "reason": "stale_codes", "stale_codes": availability["stale"], "can_edit": can_edit, "owner_name": favorite.get("created_by_name")})
                continue

            # Use the favorite's default ordering provider when it still resolves
            # to a valid provider; otherwise fall back to the inserting staff
            # member. Either can be changed in the lab order command.
            saved_provider = str(favorite.get("ordering_provider_key") or "")
            ordering_provider_key = staff_id
            if saved_provider:
                provider, _reason = resolve_provider(saved_provider)
                ordering_provider_key = provider["id"] if provider else staff_id
            effects.append(
                LabOrderCommand(
                    note_uuid=note_uuid,
                    lab_partner=favorite["lab_partner_id"],
                    tests_order_codes=availability["valid"],
                    ordering_provider_key=ordering_provider_key,
                    diagnosis_codes=favorite.get("diagnosis_codes") or [],
                    fasting_required=bool(favorite.get("fasting_required", False)),
                    comment=favorite.get("comment") or "",
                ).originate()
            )
            inserted.append({"favorite_id": favorite_id, "name": favorite["name"], "test_count": len(availability["valid"])})

        log.info(f"Inserted {len(inserted)} lab order(s), skipped {len(skipped)}, into note {note_uuid}")
        message_parts = []
        if inserted:
            message_parts.append(f"{len(inserted)} lab order(s) staged")
        if skipped:
            message_parts.append(f"{len(skipped)} skipped")
        message = ", ".join(message_parts) if message_parts else "Nothing to insert"

        return [
            JSONResponse(
                {
                    "message": message,
                    "note_uuid": note_uuid,
                    "inserted": inserted,
                    "skipped": skipped,
                    "success": True,
                }
            ),
            *effects,
        ]


def _resolve_provider_on_body(body: dict[str, Any]) -> JSONResponse | None:
    """Validate and normalize a create/update payload's ordering provider.

    Leaves the body untouched when `ordering_provider_key` is absent. An empty
    value clears the provider (fall back to the inserting user). A non-empty
    value must resolve to an active provider with a usable NPI; the resolved
    name is written back so the stored display name is trustworthy.
    """
    if "ordering_provider_key" not in body:
        return None

    key = str(body.get("ordering_provider_key", "")).strip()
    if not key:
        body["ordering_provider_key"] = ""
        body["ordering_provider_name"] = ""
        return None

    provider, reason = resolve_provider(key)
    if provider is None:
        return JSONResponse({"error": reason, "success": False}, status_code=400)

    body["ordering_provider_key"] = provider["id"]
    body["ordering_provider_name"] = provider["name"]
    return None


def _requested_favorite_ids(body: dict[str, Any]) -> list[str]:
    """Read the favorite ids to insert from the body.

    Accepts `favorite_ids` (list) or a single `favorite_id`, de-duplicated and
    order-preserving.
    """
    raw = body.get("favorite_ids")
    if not isinstance(raw, list):
        single = str(body.get("favorite_id", "")).strip()
        raw = [single] if single else []
    seen: set[str] = set()
    result: list[str] = []
    for value in raw:
        fid = str(value).strip()
        if fid and fid not in seen:
            seen.add(fid)
            result.append(fid)
    return result


def _validate_partner_and_tests(body: dict[str, Any]) -> JSONResponse | None:
    """Validate a create/update payload's partner and tests against the catalog.

    Returns a JSONResponse error to send, or None when everything is valid.
    """
    lab_partner_id = str(body.get("lab_partner_id", "")).strip()
    tests = body.get("tests") or []
    order_codes = [str(t.get("order_code", "")).strip() for t in tests if isinstance(t, dict) and t.get("order_code")]
    if not lab_partner_id:
        return JSONResponse({"error": "lab_partner_id is required", "success": False}, status_code=400)
    if not order_codes:
        return JSONResponse({"error": "at least one test with an order code is required", "success": False}, status_code=400)

    availability = check_availability(lab_partner_id, order_codes)
    if not availability["partner_found"]:
        return JSONResponse({"error": "Lab partner not found", "success": False}, status_code=400)
    if not availability["partner_active"]:
        return JSONResponse({"error": f"Lab partner '{availability['partner_name']}' is not active", "success": False}, status_code=400)
    if availability["stale"]:
        return JSONResponse(
            {
                "error": f"Unknown test codes for this lab partner: {', '.join(availability['stale'])}",
                "stale_codes": availability["stale"],
                "success": False,
            },
            status_code=400,
        )
    return None


def _open_notes_for_patient(patient_id: str):  # type: ignore[no-untyped-def]
    """Return the patient's open notes, most recently modified first."""
    try:
        patient = Patient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        return Note.objects.none()

    open_note_ids = CurrentNoteStateEvent.objects.filter(
        state__in=OPEN_NOTE_STATES
    ).values_list("note_id", flat=True)

    return (
        Note.objects.filter(dbid__in=open_note_ids, patient=patient)
        .select_related("note_type_version")
        .order_by("-modified")
    )
