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

PAGE_SIZE = 50


class CandidDashboardAPI(SimpleAPIRoute):
    """List Candid-submitted claims with status for the dashboard application."""

    PATH = "/dashboard"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        return bool(credentials.logged_in_user.get("id"))

    def get(self) -> list[Response | Effect]:
        params = self.request.query_params
        errors_only = params.get("errors_only", "").lower() in ("1", "true", "yes")
        fetch_all = params.get("page", "").lower() == "all"
        try:
            page = max(int(params.get("page", 1)), 1)
        except ValueError:
            page = 1

        base_qs = (
            Claim.objects.filter(
                Q(metadata__key=META_SUBMITTED_AT) | Q(metadata__key=META_SUBMISSION_ERROR)
            )
            .select_related("patient", "current_queue")
            .prefetch_related("metadata")
            .distinct()
            .order_by("-modified")
        )

        if fetch_all:
            all_claims = list(base_qs)
            if errors_only:
                all_claims = [c for c in all_claims if _is_error_or_denied(c)]
            results = [_serialize_claim(c) for c in all_claims]
            return [
                JSONResponse(
                    {
                        "claims": results,
                        "page": 1,
                        "page_size": len(results),
                        "total": len(results),
                        "total_pages": 1,
                    }
                )
            ]

        if errors_only:
            all_claims = list(base_qs)
            filtered = [c for c in all_claims if _is_error_or_denied(c)]
            total = len(filtered)
            start = (page - 1) * PAGE_SIZE
            page_claims = filtered[start : start + PAGE_SIZE]
        else:
            total = base_qs.count()
            start = (page - 1) * PAGE_SIZE
            page_claims = list(base_qs[start : start + PAGE_SIZE])

        total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)

        results = [_serialize_claim(c) for c in page_claims]

        # Distinct filter options across ALL claims (not just this page)
        filter_options = _get_filter_options(base_qs)

        return [
            JSONResponse(
                {
                    "claims": results,
                    "page": page,
                    "page_size": PAGE_SIZE,
                    "total": total,
                    "total_pages": total_pages,
                    "filter_options": filter_options,
                }
            )
        ]


def _get_filter_options(base_qs) -> dict:
    """Return distinct statuses and queues across all matching claims."""
    from canvas_sdk.v1.data.claim import ClaimMetadata

    statuses = set(
        ClaimMetadata.objects.filter(
            claim__in=base_qs,
            key=META_CLAIM_STATUS,
        )
        .exclude(value="")
        .values_list("value", flat=True)
        .distinct()
    )

    queues = set(
        base_qs.exclude(current_queue__isnull=True)
        .values_list("current_queue__display_name", flat=True)
        .distinct()
    )

    return {
        "statuses": sorted(statuses),
        "queues": sorted(q for q in queues if q),
    }


def _is_error_or_denied(claim: Claim) -> bool:
    """Check if a claim has a submission error or denied status."""
    meta = {m.key: m.value for m in claim.metadata.all()}
    candid_status = meta.get(META_CLAIM_STATUS, "")
    parsed_error = parse_metadata_json(meta.get(META_SUBMISSION_ERROR))
    has_error = isinstance(parsed_error, dict) and bool(parsed_error.get("error"))
    is_denied = candid_status.lower() in DENIED_STATUSES
    return has_error or is_denied


def _serialize_claim(claim: Claim) -> dict:
    """Serialize a single claim for the dashboard response."""
    meta = {m.key: m.value for m in claim.metadata.all()}
    candid_status = meta.get(META_CLAIM_STATUS, "")

    parsed_error = parse_metadata_json(meta.get(META_SUBMISSION_ERROR))
    error_obj = (
        parsed_error
        if isinstance(parsed_error, dict) and parsed_error.get("error")
        else None
    )

    patient = getattr(claim, "patient", None)
    if patient:
        first = (patient.first_name or "").strip()
        last = (patient.last_name or "").strip()
        patient_name = f"{first} {last}".strip() or "(unnamed)"
        patient_id = str(patient.id)
    else:
        patient_name = "(no patient)"
        patient_id = ""

    return {
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
        "has_error": error_obj is not None,
        "error_message": error_obj.get("error") if error_obj else None,
        "is_denied": candid_status.lower() in DENIED_STATUSES,
    }
