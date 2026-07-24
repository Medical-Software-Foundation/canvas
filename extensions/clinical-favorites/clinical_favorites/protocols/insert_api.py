"""Insert favorites into an explicit open note."""

import json
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.commands import DiagnoseCommand, PrescribeCommand
from canvas_sdk.commands.constants import ClinicalQuantity
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data.note import Note
from logger import log

from clinical_favorites.protocols.open_notes_api import LOCKED_STATE_VALUES, PICKABLE_STATES
from clinical_favorites.services import FavoritesService


def _medication_code_resolves(fdb_code: str) -> bool | None:
    """Check an FDB code against the live ontology before originating.

    Returns True when the code resolves, False when it clearly does not, and
    None when we could not check, for example the service was unreachable. A
    None result fails open so a transient ontology outage does not block every
    insert. The medication detail endpoint is the same one the search view
    uses for hydration, so a code that no longer resolves comes back empty.
    """
    try:
        payload = ontologies_http.get_json(f"/fdb/grouped-medication/{fdb_code}").json()
    except OSError:
        return None
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return bool(
        payload.get("med_medication_id")
        or payload.get("med_medication_description")
        or payload.get("clinical_quantities")
    )


def _condition_code_resolves(icd10_code: str) -> bool | None:
    """Check an ICD-10 code against the live ontology before originating.

    Returns True when an exact code match comes back, False when the search
    returns rows but none match, and None when we could not check. None fails
    open. There is no by code ICD lookup in the SDK, only a text search, so we
    search the code and require an exact match after stripping the dot. A build
    time probe on vicert-testing confirms a direct by code path can replace
    this, see journal 001. Codes that are not seeded locally will not resolve,
    which is expected, real verification is on vicert-testing.
    """
    try:
        payload = ontologies_http.get_json(
            f"/icd/condition?{urlencode({'search': icd10_code})}"
        ).json()
    except OSError:
        return None
    except Exception:
        return None
    results = payload.get("results", []) if isinstance(payload, dict) else []
    if not results:
        return False
    target = icd10_code.replace(".", "").strip().casefold()
    for row in results:
        candidate = (row.get("icd10_code") or "").replace(".", "").strip().casefold()
        if candidate == target:
            return True
    return False


def _parse_body(request: Any) -> dict[str, Any]:
    try:
        return request.json()
    except Exception:
        raw = request.body
        if hasattr(raw, "decode"):
            raw = raw.decode("utf-8")
        return json.loads(raw) if raw else {}


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class InsertFavoritesAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Insert selected favorites into a specific open note."""

    PATH = "/routes/insert"

    def _service(self) -> FavoritesService:
        return FavoritesService()

    def _staff_id(self) -> str:
        return self.request.headers.get("canvas-logged-in-user-id", "")

    def post(self) -> list[Response | Effect]:
        staff_id = self._staff_id()
        if not staff_id:
            return [
                JSONResponse(
                    {"success": False, "error": "Staff ID not found"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            payload = _parse_body(self.request)
        except Exception as exc:
            return [
                JSONResponse(
                    {"success": False, "error": f"Invalid JSON, {exc}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        note_id = (payload.get("note_id") or "").strip()
        if not note_id:
            return [
                JSONResponse(
                    {"success": False, "error": "note_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        patient_id = (payload.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"success": False, "error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        favorite_ids = payload.get("favorite_ids") or []
        if not favorite_ids:
            return [
                JSONResponse(
                    {"success": False, "error": "favorite_ids is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            note = (
                Note.objects.select_related(
                    "current_state", "note_type_version", "patient"
                )
                .get(id=note_id)
            )
        except Note.DoesNotExist:
            return [
                JSONResponse(
                    {"success": False, "error": "Note not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        note_patient_id = getattr(note.patient, "id", None)
        if str(note_patient_id) != patient_id:
            return [
                JSONResponse(
                    {"success": False, "error": "Note does not belong to the specified patient"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        current_state = ""
        state_event = getattr(note, "current_state", None)
        if state_event is not None:
            current_state = state_event.state or ""

        if current_state in LOCKED_STATE_VALUES:
            return [
                JSONResponse(
                    {
                        "success": False,
                        "error": "Note is locked. Unlock it before inserting favorites.",
                        "state": current_state,
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if current_state and current_state not in [s.value for s in PICKABLE_STATES]:
            return [
                JSONResponse(
                    {
                        "success": False,
                        "error": f"Note is not in a state that accepts inserts ({current_state})",
                        "state": current_state,
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        note_type = ""
        try:
            note_type = note.note_type_version.name or ""
        except Exception:
            note_type = ""

        dos = getattr(note, "datetime_of_service", None) or getattr(note, "created", None)

        service = self._service()
        favorites = service.get_favorites_by_ids(favorite_ids, staff_id=staff_id)

        effects: list[Effect] = []
        skipped: list[str] = []
        unresolved: list[dict[str, Any]] = []

        for fid in favorite_ids:
            fav = favorites.get(fid)
            if not fav:
                skipped.append(fid)
                continue

            if fav["favorite_type"] == "medication":
                if not fav.get("fdb_code") or not fav.get("sig"):
                    skipped.append(fav["display_name"])
                    continue
                if _medication_code_resolves(fav["fdb_code"]) is False:
                    unresolved.append({
                        "id": fid,
                        "display_name": fav["display_name"],
                        "favorite_type": "medication",
                        "code": fav["fdb_code"],
                        "reason": "This medication no longer resolves on this environment",
                    })
                    continue
                effects.append(
                    PrescribeCommand(
                        note_uuid=note_id,
                        fdb_code=fav["fdb_code"],
                        sig=fav["sig"],
                        days_supply=fav["days_supply"],
                        refills=fav["refills"],
                        quantity_to_dispense=fav["quantity_to_dispense"],
                        type_to_dispense=ClinicalQuantity(
                            representative_ndc=fav["representative_ndc"],
                            ncpdp_quantity_qualifier_code=fav["ncpdp_quantity_qualifier_code"],
                        ),
                        prescriber_id=staff_id,
                        pharmacy=fav.get("default_pharmacy_ncpdp_id"),
                    ).originate()
                )
            elif fav["favorite_type"] == "condition":
                if not fav.get("code"):
                    skipped.append(fav["display_name"])
                    continue
                if _condition_code_resolves(fav["code"]) is False:
                    unresolved.append({
                        "id": fid,
                        "display_name": fav["display_name"],
                        "favorite_type": "condition",
                        "code": fav["code"],
                        "reason": "This condition no longer resolves on this environment",
                    })
                    continue
                effects.append(
                    DiagnoseCommand(
                        note_uuid=note_id,
                        icd10_code=fav["code"],
                    ).originate()
                )
            else:
                skipped.append(fid)

        if not effects:
            payload_err: dict[str, Any] = {
                "success": False,
                "error": "Could not insert any of the selected favorites",
                "skipped": skipped,
            }
            if unresolved:
                payload_err["unresolved"] = unresolved
            return [
                JSONResponse(payload_err, status_code=HTTPStatus.BAD_REQUEST)
            ]

        payload_out: dict[str, Any] = {
            "success": True,
            "count": len(effects),
            "note_id": note_id,
            "note_type": note_type,
            "datetime_of_service": _iso(dos),
        }
        if skipped:
            payload_out["skipped"] = skipped
        if unresolved:
            payload_out["unresolved"] = unresolved

        log.info(
            f"Inserted {len(effects)} favorites into note {note_id} ({note_type}), "
            f"skipped {len(skipped)}, unresolved {len(unresolved)}"
        )
        return [JSONResponse(payload_out), *effects]
