from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.commands.commands.medication_statement import MedicationStatementCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.surescripts import SendSurescriptsMedicationHistoryRequestEffect
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.patient import Patient

from rx_history.protocols._care_event import (
    CARE_EVENT_WINDOW_DAYS,
    has_care_event_within,
)
from rx_history.protocols.action_button import build_modal_context
from rx_history.protocols.dismissal_store import dismiss, undo_dismissal

from logger import log

_OPEN_NOTE_STATES = [
    NoteStates.NEW,
    NoteStates.PUSHED,
    NoteStates.UNLOCKED,
    NoteStates.RESTORED,
    NoteStates.UNDELETED,
]


class MedHistoryRequestApi(StaffSessionAuthMixin, SimpleAPI):
    """API endpoints for the medication history modal."""

    PREFIX = "/routes"

    @api.post("/request")
    def request_med_history(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id", "")

        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient = Patient.objects.select_related("default_provider").get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            log.warning("MedHistoryRequestApi: patient %s not found" % patient_id)
            return [
                JSONResponse(
                    {"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]

        if patient.default_provider is None:
            return [
                JSONResponse(
                    {"error": "No default provider assigned to this patient"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not has_care_event_within(patient_id):
            log.info(
                "request_med_history refused for patient %s. no care event in %s days"
                % (patient_id, CARE_EVENT_WINDOW_DAYS)
            )
            return [
                JSONResponse(
                    {
                        "error": "no_care_event",
                        "message": (
                            "Medication history requests require an appointment "
                            "within the next %s days." % CARE_EVENT_WINDOW_DAYS
                        ),
                        "window_days": CARE_EVENT_WINDOW_DAYS,
                    },
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        staff_id = str(patient.default_provider.id)
        log.info(
            "Manual medication history request for patient %s via provider %s"
            % (patient_id, staff_id)
        )

        return [
            JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK),
            SendSurescriptsMedicationHistoryRequestEffect(
                patient_id=patient_id,
                staff_id=staff_id,
            ).apply(),
        ]

    @api.post("/state")
    def state(self) -> list[Response]:
        body = self.request.json()
        patient_id = body.get("patient_id", "")

        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient = Patient.objects.select_related("default_provider").get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            log.warning("MedHistoryRequestApi.state: patient %s not found" % patient_id)
            return [
                JSONResponse(
                    {"error": "Patient not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        ctx = build_modal_context(patient)
        return [
            JSONResponse(
                {
                    "grouped_items": ctx["grouped_items"],
                    "dismissed_items": ctx["dismissed_items"],
                    "dismissed_count": ctx["dismissed_count"],
                    "active_rxnorm": ctx["active_rxnorm"],
                    "active_ndc": ctx["active_ndc"],
                    "active_descriptions": ctx["active_descriptions"],
                    "active_meds": ctx["active_meds"],
                    "open_notes": ctx["open_notes"],
                    "last_pulled_iso": ctx["last_pulled_iso"],
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/add-medication")
    def add_medication(self) -> list[Response | Effect]:
        body = self.request.json()
        patient_id = body.get("patient_id", "")
        drug_description = body.get("drug_description", "")
        sig = body.get("sig", "") or None

        if not patient_id or not drug_description:
            return [
                JSONResponse(
                    {"error": "patient_id and drug_description are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            log.warning("AddMedication: patient %s not found" % patient_id)
            return [
                JSONResponse(
                    {"error": "Patient not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]

        note_id = body.get("note_id", "")
        if note_id:
            open_note = (
                Note.objects.filter(id=note_id, patient=patient)
                .filter(current_state__state__in=_OPEN_NOTE_STATES)
                .first()
            )
            if not open_note:
                return [
                    JSONResponse(
                        {"error": "Note not found or not in an open state."},
                        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                    )
                ]
        else:
            open_note = (
                Note.objects.filter(patient=patient)
                .filter(current_state__state__in=_OPEN_NOTE_STATES)
                .order_by("-datetime_of_service")
                .first()
            )

        if not open_note:
            return [
                JSONResponse(
                    {
                        "error": "No open note found. Open a note for this patient first."
                    },
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        rxnorm_rxcui = body.get("rxnorm_rxcui", "") or None
        ndc_codes = body.get("ndc_codes", []) or []
        alt_descriptions = body.get("alt_descriptions", []) or []
        first_ndc = ndc_codes[0] if ndc_codes else None

        fdb_code = _lookup_fdb_code(drug_description, rxnorm_rxcui, first_ndc)

        # Try alternate descriptions (fill name vs claim name)
        if fdb_code is None and alt_descriptions:
            for alt in alt_descriptions:
                fdb_code = _lookup_fdb_code(alt)
                if fdb_code is not None:
                    break

        if fdb_code is None:
            log.warning(
                "AddMedication no FDB match. desc=%r rxnorm=%s first_ndc=%s tried_alts=%s"
                % (drug_description, rxnorm_rxcui, first_ndc, alt_descriptions)
            )
            return [
                JSONResponse(
                    {
                        "error": 'Could not find a coded match for "%s" in FDB. Search for it manually in the note.'
                        % drug_description
                    },
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        log.info(
            "Adding medication statement for patient %s: %s (FDB %s)"
            % (patient_id, drug_description, fdb_code)
        )

        cmd = MedicationStatementCommand(
            note_uuid=str(open_note.id),
            fdb_code=str(fdb_code),
            sig=sig,
        )

        return [
            JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK),
            cmd.originate(),
        ]

    @api.post("/dismiss")
    def dismiss_medication(self) -> list[Response]:
        body = self.request.json()
        patient_id = body.get("patient_id", "")
        drug_description = body.get("drug_description", "")
        ndc_code = body.get("ndc_code", "")
        last_fill_date = body.get("last_fill_date", "")

        if not patient_id or not drug_description:
            return [
                JSONResponse(
                    {"error": "patient_id and drug_description are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        staff_id = self.request.headers.get("canvas-logged-in-user-id", "")
        if not staff_id:
            return [
                JSONResponse(
                    {"error": "Missing authenticated staff context"},
                    status_code=HTTPStatus.UNAUTHORIZED,
                )
            ]

        dismiss(patient_id, staff_id, drug_description, ndc_code, last_fill_date)
        return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]

    @api.post("/undo-dismiss")
    def undo_dismiss_medication(self) -> list[Response]:
        body = self.request.json()
        patient_id = body.get("patient_id", "")
        drug_description = body.get("drug_description", "")
        ndc_code = body.get("ndc_code", "")
        last_fill_date = body.get("last_fill_date", "")

        if not patient_id or not drug_description:
            return [
                JSONResponse(
                    {"error": "patient_id and drug_description are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        removed = undo_dismissal(
            patient_id, drug_description, ndc_code, last_fill_date
        )
        if removed:
            return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]
        return [
            JSONResponse(
                {"error": "No matching dismissal found"},
                status_code=HTTPStatus.NOT_FOUND,
            )
        ]


def _extract_rxnorm_cui(raw: str | None) -> str | None:
    """Return just the numeric RxNorm CUI, stripping any term type suffix.

    Surescripts coding values can arrive as `"1014571 SCD"` or
    `"1660196 SBD"`, where the trailing token is the RxNorm term type.
    FDB expects the bare numeric CUI, so pull that out before querying.
    """
    if not raw:
        return None
    token = raw.strip().split()[0]
    return token if token.isdigit() else None


def _extract_med_medication_id(payload: Any) -> tuple[int | None, str]:
    """Pull med_medication_id from the three response shapes FDB endpoints return.

    Returns a tuple (id, shape_tag) where shape_tag identifies which shape was
    picked so callers can log the chosen branch. id is None when no match.

    Accepted shapes.
    - list of dicts. `[{"med_medication_id": ...}]`. Take the first.
    - dict with a results list. `{"results": [{"med_medication_id": ...}]}`.
    - dict that is itself the match. `{"med_medication_id": ...}`.
    """
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and first.get("med_medication_id"):
            return int(first["med_medication_id"]), "list"
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict) and first.get("med_medication_id"):
                return int(first["med_medication_id"]), "dict.results"
        if payload.get("med_medication_id"):
            return int(payload["med_medication_id"]), "dict.direct"
    return None, "empty"


def _lookup_fdb_code(
    drug_description: str,
    rxnorm_rxcui: str | None = None,
    ndc_code: str | None = None,
) -> int | None:
    """Look up FDB med_medication_id. Tries RxNorm, then NDC, then text search."""
    clean_cui = _extract_rxnorm_cui(rxnorm_rxcui)
    if clean_cui:
        try:
            resp = ontologies_http.get_json(
                "/fdb/grouped-medication/?%s"
                % urlencode({"rxnorm_rxcui": clean_cui})
            )
            med_id, _ = _extract_med_medication_id(resp.json())
            if med_id is not None:
                return med_id
        except Exception as e:
            log.warning("FDB RxNorm lookup failed for rxcui %s: %s" % (clean_cui, e))

    if ndc_code:
        try:
            resp = ontologies_http.get_json("/fdb/ndc-to-medication/%s/" % ndc_code)
            med_id, _ = _extract_med_medication_id(resp.json())
            if med_id is not None:
                return med_id
        except Exception as e:
            log.warning("FDB NDC lookup failed for %s: %s" % (ndc_code, e))

    try:
        resp = ontologies_http.get_json(
            "/fdb/grouped-medication/?%s" % urlencode({"search": drug_description})
        )
        med_id, _ = _extract_med_medication_id(resp.json())
        if med_id is not None:
            return med_id
    except Exception as e:
        log.warning("FDB text search failed for %r: %s" % (drug_description, e))

    return None
