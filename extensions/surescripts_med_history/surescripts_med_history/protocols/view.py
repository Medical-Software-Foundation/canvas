from http import HTTPStatus
from urllib.parse import urlencode
from uuid import uuid4

import requests
from canvas_sdk.commands.commands.medication_statement import MedicationStatementCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.surescripts import (
    SendSurescriptsEligibilityRequestEffect,
    SendSurescriptsMedicationHistoryRequestEffect,
)
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.staff import Staff

from logger import log

from surescripts_med_history.models import MedicationDismissal
from surescripts_med_history.protocols.action_button import build_history_payload
from surescripts_med_history.protocols.audit import logged_in_user_id, staff_label
from surescripts_med_history.protocols.note_metadata import request_metadata_effects
from surescripts_med_history.protocols.settings import (
    COMMIT_SECRET_NAME,
    MOCK_SECRET_NAME,
    parse_commit,
    parse_mock,
)

# Stamped on every MedicationStatement this plugin originates so downstream
# consumers (reporting, other plugins) can tell Surescripts-sourced statements
# apart from ones a provider typed in by hand.
DATA_SOURCE_METADATA_KEY = "data_source"
DATA_SOURCE_METADATA_VALUE = "surescripts"

_OPEN_NOTE_STATES = [
    NoteStates.NEW,
    NoteStates.CONVERTED,
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

        # Who is asking. Resolved once up front so every branch below can name
        # them: the request runs under a provider's SPI that may not be theirs,
        # and this log line is the only record tying the two together.
        initiator = self._get_logged_in_staff()
        initiator_label = staff_label(initiator, logged_in_user_id(self.request))

        # Resolve the provider the request runs under. Precedence:
        #   1. An explicit staff_id chosen from the modal's provider dropdown.
        #   2. The logged-in staff, when they're an SPI-registered provider.
        #   3. The patient's default provider (for non-prescriber users such as
        #      care managers who can't request on their own behalf).
        # In every case the chosen provider MUST have an SPI — Surescripts
        # rejects requests from unregistered staff — so we fail closed.
        requested_staff_id = body.get("staff_id", "")
        staff_id = ""
        if requested_staff_id:
            try:
                chosen = Staff.objects.get(id=requested_staff_id)
            except Staff.DoesNotExist:
                log.warning(
                    "MedHistoryRequestApi: selected provider %s not found"
                    % requested_staff_id
                )
                return [
                    JSONResponse(
                        {"error": "Selected provider not found"},
                        status_code=HTTPStatus.NOT_FOUND,
                    )
                ]
            if not chosen.spi_number:
                log.warning(
                    "MedHistoryRequestApi: selected provider %s has no SPI"
                    % requested_staff_id
                )
                return [
                    JSONResponse(
                        {
                            "error": "Selected provider is not registered with Surescripts"
                        },
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            staff_id = str(chosen.id)
            log.info(
                "Surescripts request: initiator %s requested med history for "
                "patient %s on behalf of selected provider %s"
                % (initiator_label, patient_id, staff_label(chosen))
            )
        else:
            logged_in_staff = initiator
            if logged_in_staff and logged_in_staff.spi_number:
                staff_id = str(logged_in_staff.id)
                log.info(
                    "Surescripts request: initiator %s requested med history for "
                    "patient %s as themselves" % (initiator_label, patient_id)
                )
            else:
                try:
                    patient = Patient.objects.select_related("default_provider").get(
                        id=patient_id
                    )
                except Patient.DoesNotExist:
                    log.warning(
                        "MedHistoryRequestApi: patient %s not found" % patient_id
                    )
                    return [
                        JSONResponse(
                            {"error": "Patient not found"},
                            status_code=HTTPStatus.NOT_FOUND,
                        )
                    ]

                if patient.default_provider is None:
                    return [
                        JSONResponse(
                            {"error": "No default provider assigned to this patient"},
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]
                if not patient.default_provider.spi_number:
                    log.warning(
                        "MedHistoryRequestApi: default provider %s for patient %s has no SPI"
                        % (patient.default_provider.id, patient_id)
                    )
                    return [
                        JSONResponse(
                            {
                                "error": "Default provider for this patient is not registered with Surescripts"
                            },
                            status_code=HTTPStatus.BAD_REQUEST,
                        )
                    ]
                staff_id = str(patient.default_provider.id)
                log.info(
                    "Surescripts request: initiator %s requested med history for "
                    "patient %s on behalf of the patient's default provider %s"
                    % (
                        initiator_label,
                        patient_id,
                        staff_label(patient.default_provider),
                    )
                )

        # Stamp metadata on the patient's most recent open note so providers
        # can tell at a glance when history was last requested.
        open_note = (
            Note.objects.filter(patient__id=patient_id)
            .filter(current_state__state__in=_OPEN_NOTE_STATES)
            .order_by("-datetime_of_service")
            .first()
        )
        note_id = str(open_note.id) if open_note is not None else ""

        # Med history is gated on a completed eligibility check (it needs the
        # ISA-13 interchange control number the 271 returns), so fire eligibility
        # alongside it — otherwise a stale/absent eligibility silently produces
        # an empty med-history result.
        return (
            [
                JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK),
                SendSurescriptsEligibilityRequestEffect(
                    patient_id=patient_id,
                    staff_id=staff_id,
                ).apply(),
                SendSurescriptsMedicationHistoryRequestEffect(
                    patient_id=patient_id,
                    staff_id=staff_id,
                ).apply(),
            ]
            + request_metadata_effects(note_id, "eligibility")
            + request_metadata_effects(note_id, "med_history")
        )

    @api.get("/history")
    def history(self) -> list[Response | Effect]:
        """Return the current med-history modal data as JSON.

        Surescripts responses arrive asynchronously, so the modal polls this
        after a request (and offers a manual refresh) to pick up new results
        without the provider having to close and reopen it. Read-only — stale
        dismissals are cleaned up only when the action button is opened.
        """
        patient_id = self.request.query_params.get("patient_id", "")
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Patient not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        payload, _ = build_history_payload(
            patient, include_mock=parse_mock(self.secrets.get(MOCK_SECRET_NAME))
        )
        return [JSONResponse(payload, status_code=HTTPStatus.OK)]

    def _get_logged_in_staff(self) -> "Staff | None":
        """Return the Staff record for the logged-in user, or None."""
        user_id = logged_in_user_id(self.request)
        if not user_id:
            return None
        try:
            return Staff.objects.get(id=user_id)
        except Staff.DoesNotExist:
            return None

    @api.post("/dismiss")
    def dismiss(self) -> list[Response | Effect]:
        """Dismiss a medication-history group for a patient. The action
        button auto-clears stale dismissals (now matched, or new fill
        after dismissal), so we don't model a separate undismiss flow."""
        body = self.request.json()
        patient_id = body.get("patient_id", "")
        group_key = body.get("group_key", "")
        drug_description = body.get("drug_description", "") or ""

        if not patient_id or not group_key:
            return [
                JSONResponse(
                    {"error": "patient_id and group_key are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            patient_dbid = Patient.objects.values_list("dbid", flat=True).get(
                id=patient_id
            )
        except Patient.DoesNotExist:
            return [
                JSONResponse(
                    {"error": "Patient not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        staff = self._get_logged_in_staff()
        staff_id = str(staff.id) if staff else ""
        staff_name = ""
        if staff:
            first = getattr(staff, "first_name", "") or ""
            last = getattr(staff, "last_name", "") or ""
            staff_name = ("%s %s" % (first, last)).strip()

        MedicationDismissal.objects.update_or_create(
            patient_id=patient_dbid,
            group_key=group_key,
            defaults={
                "drug_description": drug_description,
                "dismissed_by_id": staff_id,
                "dismissed_by": staff_name,
            },
        )
        log.info(
            "Surescripts request: initiator %s dismissed medication group %s "
            "for patient %s" % (staff_label(staff, staff_id), group_key, patient_id)
        )
        return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]

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
                    log.info("FDB alt match: '%s' -> %s" % (alt, fdb_code))
                    break

        if fdb_code is None:
            return [
                JSONResponse(
                    {
                        "error": 'Could not find a coded match for "%s" in FDB. Search for it manually in the note.'
                        % drug_description
                    },
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        commit = parse_commit(self.secrets.get(COMMIT_SECRET_NAME))

        log.info(
            "Surescripts request: initiator %s added %s medication statement for "
            "patient %s: %s (FDB %s)"
            % (
                staff_label(
                    self._get_logged_in_staff(), logged_in_user_id(self.request)
                ),
                "committed" if commit else "uncommitted",
                patient_id,
                drug_description,
                fdb_code,
            )
        )

        cmd = MedicationStatementCommand(
            note_uuid=str(open_note.id),
            fdb_code=str(fdb_code),
            sig=sig,
        )
        # Set the id ourselves so we can chain metadata (and optionally the
        # commit) onto the same command in this single response — originate
        # runs asynchronously and never hands the id back.
        cmd.command_uuid = str(uuid4())

        effects = [
            JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK),
            cmd.originate(),
            cmd.upsert_metadata(
                key=DATA_SOURCE_METADATA_KEY,
                value=DATA_SOURCE_METADATA_VALUE,
            ),
        ]
        if commit:
            effects.append(cmd.commit())
        return effects


def _lookup_fdb_code(
    drug_description: str,
    rxnorm_rxcui: str | None = None,
    ndc_code: str | None = None,
) -> int | None:
    """Look up FDB med_medication_id — tries RxNorm, then NDC, then text search."""
    if rxnorm_rxcui:
        try:
            resp = ontologies_http.get_json(
                "/fdb/grouped-medication/?%s"
                % urlencode({"rxnorm_rxcui": rxnorm_rxcui})
            )
        except requests.RequestException as e:
            log.warning("FDB RxNorm lookup failed for rxcui %s: %s" % (rxnorm_rxcui, e))
        else:
            results = resp.json()
            if isinstance(results, list) and results:
                log.info(
                    "FDB RxNorm hit for rxcui %s: %s"
                    % (rxnorm_rxcui, results[0].get("med_medication_id"))
                )
                return int(results[0]["med_medication_id"])

    if ndc_code:
        try:
            resp = ontologies_http.get_json("/fdb/ndc-to-medication/%s/" % ndc_code)
        except requests.RequestException as e:
            log.warning("FDB NDC lookup failed for %s: %s" % (ndc_code, e))
        else:
            result = resp.json()
            if isinstance(result, dict) and result.get("med_medication_id"):
                log.info(
                    "FDB NDC hit for %s: %s" % (ndc_code, result["med_medication_id"])
                )
                return int(result["med_medication_id"])

    try:
        resp = ontologies_http.get_json(
            "/fdb/grouped-medication/?%s" % urlencode({"search": drug_description})
        )
    except requests.RequestException as e:
        log.warning("FDB text search failed for %s: %s" % (drug_description, e))
        return None
    results = resp.json().get("results", [])
    if results:
        log.info(
            "FDB text search hit for %s: %s"
            % (drug_description, results[0].get("med_medication_id"))
        )
        return int(results[0]["med_medication_id"])

    return None
