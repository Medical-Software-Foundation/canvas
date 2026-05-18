"""SimpleAPI endpoint serving aggregated Candid claim data for the dashboard."""

from django.db.models import Q

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SessionCredentials, SimpleAPIRoute
from canvas_sdk.v1.data.claim import Claim

from candid.effect_helpers import (
    DENIED_STATUSES,
    META_CLAIM_STATUS,
    META_LAST_SYNC,
    META_SUBMISSION_ERROR,
    META_SUBMITTED_AT,
    parse_metadata_json,
)

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class CandidDashboardAPI(SimpleAPIRoute):
    """List Candid-submitted claims with status for the dashboard application."""

    PATH = "/dashboard"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        return bool(credentials.logged_in_user.get("id"))

    def get(self) -> list[Response | Effect]:
        params = self.request.query_params
        errors_only = params.get("errors_only", "").lower() in ("1", "true", "yes")
        try:
            limit = min(int(params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
        except ValueError:
            limit = DEFAULT_LIMIT

        # Include claims that were submitted OR that have a submission error
        # (rejected claims never get META_SUBMITTED_AT but do get META_SUBMISSION_ERROR)
        fetch_size = limit * 3 if errors_only else limit
        claims = (
            Claim.objects.filter(
                Q(metadata__key=META_SUBMITTED_AT) | Q(metadata__key=META_SUBMISSION_ERROR)
            )
            .select_related("patient", "current_queue")
            .prefetch_related("metadata")
            .distinct()
            .order_by("-modified")[:fetch_size]
        )

        results = []
        for claim in claims:
            meta = {m.key: m.value for m in claim.metadata.all()}
            candid_status = meta.get(META_CLAIM_STATUS, "")

            parsed_error = parse_metadata_json(meta.get(META_SUBMISSION_ERROR))
            error_obj = (
                parsed_error
                if isinstance(parsed_error, dict) and parsed_error.get("error")
                else None
            )

            has_error = error_obj is not None
            is_denied = candid_status.lower() in DENIED_STATUSES

            if errors_only and not (has_error or is_denied):
                continue

            patient = getattr(claim, "patient", None)
            if patient:
                first = (patient.first_name or "").strip()
                last = (patient.last_name or "").strip()
                patient_name = f"{first} {last}".strip() or "(unnamed)"
                patient_id = str(patient.id)
            else:
                patient_name = "(no patient)"
                patient_id = ""

            results.append(
                {
                    "id": str(claim.id),
                    "dbid": claim.dbid,
                    "patient_name": patient_name,
                    "patient_id": patient_id,
                    "candid_status": candid_status,
                    "submitted_at": meta.get(META_SUBMITTED_AT, ""),
                    "last_sync_at": meta.get(META_LAST_SYNC, ""),
                    "current_queue": claim.current_queue.display_name
                    if claim.current_queue
                    else "",
                    "has_error": has_error,
                    "error_message": error_obj.get("error") if error_obj else None,
                    "is_denied": is_denied,
                }
            )
            if len(results) >= limit:
                break

        return [JSONResponse({"claims": results, "count": len(results)})]
