"""SimpleAPI endpoints for ICD-10 coding operations.

Endpoints:
  GET  /api/conditions-missing-icd10   — list conditions with recommendations
  GET  /api/search-icd10               — search for ICD-10 codes via the ontologies service
  POST /api/approve-coding             — approve a single condition update
  POST /api/approve-all                — approve multiple condition updates in bulk
"""

import uuid
from typing import Any
from urllib.parse import urlencode

import arrow
from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands import UpdateDiagnosisCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from logger import log

from icd10_coding_assistant.utils import get_conditions_missing_icd10

# Cache coding-lookup results for ~1 hour to avoid hammering the external API
# on repeated opens or conditions sharing the same display name.
_CODING_LOOKUP_CACHE_TTL_SECONDS = 3600


class ICD10CodingAPI(StaffSessionAuthMixin, SimpleAPI):
    """Backend API endpoints for ICD-10 coding operations.

    Authenticated via StaffSessionAuthMixin: callers must have an active Canvas
    staff session (session cookie present). Endpoints are only reachable from
    within the Canvas UI where the user is already logged in.
    """

    PREFIX = "/api"

    # ------------------------------------------------------------------
    # Endpoint: GET /api/conditions-missing-icd10
    # ------------------------------------------------------------------

    @api.get("/conditions-missing-icd10")
    def get_conditions(self) -> list[Response | Effect]:
        """Return all conditions missing ICD-10 codes, with recommendations."""
        patient_id: str | None = self.request.query_params.get("patient_id")
        if not patient_id:
            log.error("[ICD-10 Coding] No patient_id provided to get_conditions")
            return [
                JSONResponse(
                    {"error": "patient_id parameter required"}, status_code=400
                )
            ]

        log.info(
            f"[ICD-10 Coding] Getting conditions missing ICD-10 for patient {patient_id}"
        )
        conditions = get_conditions_missing_icd10(patient_id)

        # Bulk query for pending staged UpdateDiagnosis commands — one DB hit
        # instead of one per condition.
        all_dbids = [c.dbid for c in conditions]
        pending_dbids: set[int] = set(
            Command.objects.filter(
                schema_key="updateDiagnosis",
                state="staged",
                data__condition__value__in=all_dbids,
            ).values_list("data__condition__value", flat=True)
        )

        results = [
            {
                "id": str(condition.id),
                "name": self._get_display_name(condition),
                "current_system": self._get_current_system(condition),
                "current_code": self._get_current_code(condition),
                "recommendations": self._get_icd10_recommendations(condition),
                "has_pending_command": condition.dbid in pending_dbids,
            }
            for condition in conditions
        ]

        return [JSONResponse({"conditions": results})]

    # ------------------------------------------------------------------
    # Endpoint: GET /api/search-icd10
    # ------------------------------------------------------------------

    @api.get("/search-icd10")
    def search_icd10(self) -> list[Response | Effect]:
        """Search for ICD-10 codes via the ontologies service."""
        query: str = self.request.query_params.get("query", "").strip()
        log.info(f"[ICD-10 Coding] Searching ICD-10 codes for query: {query}")
        data = self._search_ontologies_icd10(query)
        log.info(f"[ICD-10 Coding] Found {data.get('count', 0)} ICD-10 search results")
        return [JSONResponse(data)]

    # ------------------------------------------------------------------
    # Endpoint: POST /api/approve-coding
    # ------------------------------------------------------------------

    @api.post("/approve-coding")
    def approve_coding(self) -> list[Response | Effect]:
        """Approve and update a single condition with a selected ICD-10 code."""
        try:
            data: dict[str, str] = self.request.json()
        except ValueError as exc:
            log.error(f"[ICD-10 Coding] Invalid JSON in approve request: {exc}")
            return [JSONResponse({"error": "Invalid JSON"}, status_code=400)]

        patient_id = data.get("patient_id")
        condition_id = data.get("condition_id")
        icd10_code = data.get("icd10_code")
        icd10_display: str = data.get("icd10_display", "")

        if not all([patient_id, condition_id, icd10_code]):
            return [JSONResponse({"error": "Missing required fields"}, status_code=400)]

        log.info(
            f"[ICD-10 Coding] Approving ICD-10 code {icd10_code} for condition {condition_id}"
        )

        return self._create_condition_update_effects(
            patient_id=str(patient_id),
            conditions_data=[
                {
                    "condition_id": str(condition_id),
                    "icd10_code": str(icd10_code),
                    "icd10_display": icd10_display,
                }
            ],
            note_title="ICD-10 Coding Update",
        )

    # ------------------------------------------------------------------
    # Endpoint: POST /api/approve-all
    # ------------------------------------------------------------------

    @api.post("/approve-all")
    def approve_all(self) -> list[Response | Effect]:
        """Approve and update multiple conditions in a single Chart Review Note."""
        try:
            data: dict[str, Any] = self.request.json()
        except ValueError as exc:
            log.error(f"[ICD-10 Coding] Invalid JSON in approve-all request: {exc}")
            return [JSONResponse({"error": "Invalid JSON"}, status_code=400)]

        patient_id = data.get("patient_id")
        raw_conditions = data.get("conditions")

        if not patient_id or not raw_conditions:
            return [
                JSONResponse(
                    {"error": "Missing required fields (patient_id, conditions)"},
                    status_code=400,
                )
            ]

        # raw_conditions is Any from the dict[str, Any] parse; validate its shape
        if not isinstance(raw_conditions, list):
            return [
                JSONResponse({"error": "conditions must be a list"}, status_code=400)
            ]

        conditions_to_update: list[dict[str, str]] = raw_conditions
        log.info(
            f"[ICD-10 Coding] Approving {len(conditions_to_update)} conditions for patient {patient_id}"
        )

        return self._create_condition_update_effects(
            patient_id=str(patient_id),
            conditions_data=conditions_to_update,
            note_title="ICD-10 Coding Update",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_note_context(
        self,
    ) -> tuple[tuple[NoteType, str, str | None] | None, list[Response | Effect] | None]:
        """Resolve common note-creation context (note type, provider, location).

        Returns:
            (result_tuple, None)  on success
            (None, error_list)    on validation failure — fail closed, return error
        """
        note_type = NoteType.objects.filter(category="review", is_active=True).first()
        if not note_type:
            log.error("[ICD-10 Coding] Chart Review note type not found")
            return None, [
                JSONResponse(
                    {"error": "Chart Review note type not configured"}, status_code=500
                )
            ]

        provider_id: str | None = self.request.headers.get("canvas-logged-in-user-id")
        if not provider_id:
            log.error(
                "[ICD-10 Coding] No logged-in user ID in request — failing closed"
            )
            return None, [
                JSONResponse({"error": "Authentication required"}, status_code=401)
            ]

        practice_location_id: str | None = (
            PracticeLocation.objects.filter(active=True)
            .values_list("id", flat=True)
            .first()
        )

        return (note_type, provider_id, practice_location_id), None

    def _create_condition_update_effects(
        self,
        patient_id: str,
        conditions_data: list[dict[str, str]],
        note_title: str,
    ) -> list[Response | Effect]:
        """Build the effect list (Note + UpdateDiagnosisCommand per condition + response)."""
        result, error = self._get_note_context()
        if error:
            return error

        note_type, provider_id, practice_location_id = result  # type: ignore[misc]

        note_uuid = str(uuid.uuid4())
        effects: list[Response | Effect] = []

        note_effect = NoteEffect(
            instance_id=note_uuid,
            note_type_id=str(note_type.id),
            datetime_of_service=arrow.utcnow().datetime,
            patient_id=patient_id,
            practice_location_id=practice_location_id,
            provider_id=provider_id,
            title=note_title,
        )
        effects.append(note_effect.create())

        for condition_data in conditions_data:
            condition_id = condition_data.get("condition_id")
            icd10_code = condition_data.get("icd10_code")

            if not all([condition_id, icd10_code]):
                log.warning(
                    f"[ICD-10 Coding] Skipping condition with missing data: {condition_data}"
                )
                continue

            # Guard against DoesNotExist — skip + log, never 500.
            try:
                condition = Condition.objects.get(id=condition_id)
            except Condition.DoesNotExist:
                log.warning(
                    f"[ICD-10 Coding] Condition {condition_id} not found, skipping"
                )
                continue

            current_code: str | None = self._get_current_code(condition)
            if current_code is None:
                log.warning(
                    f"[ICD-10 Coding] No current code for condition {condition_id}, skipping"
                )
                continue

            update_command = UpdateDiagnosisCommand(
                note_uuid=note_uuid,
                condition_code=current_code,
                new_condition_code=str(icd10_code),
            )
            log.info(
                f"[ICD-10 Coding] Staging UpdateDiagnosisCommand for note {note_uuid}: "
                f"{current_code} -> {icd10_code}"
            )
            effects.append(update_command.originate())

        effects.append(JSONResponse({"success": True, "note_id": note_uuid}))
        return effects

    def _search_ontologies_icd10(self, search_text: str) -> dict[str, Any]:
        """Search ICD-10 codes via the platform ontologies service.

        Calls the ontologies endpoint directly through the SDK's `ontologies_http`
        client (the same backend the `coding_lookup` plugin wrapped). This works in
        every environment with no DNS or API-key plumbing. Results are cached
        briefly, keyed by search text.

        A failed lookup degrades to an empty result rather than 500-ing the
        conditions listing, which does not depend on recommendations.

        Returns:
            dict with 'count' and 'results' (each {'value', 'text'}) keys.
        """
        cache = get_cache()
        cache_key = f"icd10_search_{search_text}"

        cached: dict[str, Any] | None = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            response_json = ontologies_http.get_json(
                f"/icd/condition?{urlencode({'search': search_text})}"
            ).json()
        except OSError as exc:
            # requests' exceptions (ConnectionError, Timeout, ...) subclass OSError.
            # Ontologies is platform infra and normally reachable; degrade gracefully
            # on a transient failure rather than 500 the listing.
            log.error(f"[ICD-10 Coding] ontologies lookup failed: {exc}")
            return {"count": 0, "results": []}

        results: list[dict[str, str]] = [
            {
                "value": str(obj.get("icd10_code", "")),
                "text": str(obj.get("icd10_text", "")),
            }
            for obj in (response_json or {}).get("results", [])
        ]

        result: dict[str, Any] = {"count": len(results), "results": results}
        cache.set(cache_key, result, timeout_seconds=_CODING_LOOKUP_CACHE_TTL_SECONDS)
        return result

    def _get_display_name(self, condition: Condition) -> str:
        """Return the condition display name, resolved from prefetched codings."""
        for coding in condition.codings.all():
            if coding.display:
                return str(coding.display)
        return f"Condition {condition.id}"

    def _get_current_system(self, condition: Condition) -> str:
        """Return the coding system URI, resolved from prefetched codings."""
        for coding in condition.codings.all():
            if coding.system:
                return str(coding.system)
        return "None"

    def _get_current_code(self, condition: Condition) -> str | None:
        """Return the current code value, or None if no codings exist.

        Never returns a placeholder string — callers must handle None explicitly.
        """
        for coding in condition.codings.all():
            if coding.code:
                return str(coding.code)
        return None

    def _get_icd10_recommendations(self, condition: Condition) -> list[dict[str, str]]:
        """Fetch ICD-10 recommendations for a condition from the ontologies service.

        Resolves display name from prefetched codings. Returns [] if no meaningful
        display text is available or if the API returns nothing.
        """
        display_text = self._get_display_name(condition)

        if display_text.startswith("Condition "):
            return []

        log.info(f"[ICD-10 Coding] Getting recommendations for: {display_text}")
        data = self._search_ontologies_icd10(display_text)
        raw_results = data.get("results", [])
        results: list[dict[str, Any]] = (
            list(raw_results) if isinstance(raw_results, list) else []
        )

        recommendations: list[dict[str, str]] = []
        for item in results:
            recommendations.append(
                {
                    "code": str(item.get("value", "")),
                    "display": str(item.get("text", "")),
                }
            )

        log.info(
            f"[ICD-10 Coding] Found {len(recommendations)} recommendations for '{display_text}'"
        )
        return recommendations

    def _has_pending_update_diagnosis_command_for_condition(
        self, condition: Condition
    ) -> bool:
        """Single-condition check; prefer the bulk path in get_conditions()."""
        return bool(
            Command.objects.filter(
                schema_key="updateDiagnosis",
                state="staged",
                data__condition__value=condition.dbid,
            ).exists()
        )
