"""SimpleAPI endpoint serving Candid claim detail data for the application UI."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SessionCredentials, SimpleAPIRoute
from canvas_sdk.v1.data.claim import Claim
from logger import log

from candid.adjudication_sync import ERA_DESC_PREFIX, PATIENT_PAYMENT_DESC_PREFIX
from candid.adjudication_sync import sync_claim_adjudications
from candid.models.sync_state import SyncLog
from candid.effect_helpers import (
    BANNER_KEY,
    META_CLAIM_STATUS,
    META_ENCOUNTERS,
    META_LAST_SYNC,
    META_REPORTED_PAYMENT_IDS,
    META_SUBMITTED_AT,
    META_SUBMISSION_ERROR,
    META_SYNCED_ERA_IDS,
    META_SYNCED_PAYMENT_IDS,
    get_claim_metadata,
)

MAX_SYNC_HISTORY = 20


def _get_posting_info(claim: Claim) -> dict[str, dict]:
    """Map posting descriptions to their created timestamps and paid amounts.

    Returns ``{description: {posted_at, paid_amount}}`` for all active Candid
    postings on this claim (matched by description prefix).
    """
    info: dict[str, dict] = {}
    for posting in claim.postings.active().filter(description__startswith="Candid "):
        if posting.description and posting.created:
            info[posting.description] = {
                "posted_at": posting.created.isoformat(),
                "paid_amount": str(posting.paid_amount),
            }
    return info


class CandidClaimDetailAPI(SimpleAPIRoute):
    """Serve Candid timeline data and trigger syncs for a single claim."""

    PATH = "/claim-detail"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        return bool(credentials.logged_in_user.get("id"))

    def get(self) -> list[Response | Effect]:
        """Return Candid metadata timeline for a claim."""
        canvas_claim_id = self.request.query_params.get("claim_id", "")
        if not canvas_claim_id:
            return [JSONResponse({"error": "claim_id required"}, status_code=400)]

        claim = Claim.objects.filter(id=canvas_claim_id).first()
        if not claim:
            return [JSONResponse({"error": "claim not found"}, status_code=404)]

        encounters = get_claim_metadata(claim, META_ENCOUNTERS) or []
        submitted_at = get_claim_metadata(claim, META_SUBMITTED_AT)
        last_sync = get_claim_metadata(claim, META_LAST_SYNC)
        claim_status = get_claim_metadata(claim, META_CLAIM_STATUS)
        synced_era_ids = get_claim_metadata(claim, META_SYNCED_ERA_IDS) or []
        synced_payment_ids = get_claim_metadata(claim, META_SYNCED_PAYMENT_IDS) or []
        reported_payment_ids = (
            get_claim_metadata(claim, META_REPORTED_PAYMENT_IDS) or []
        )
        submission_error = get_claim_metadata(claim, META_SUBMISSION_ERROR)

        posting_info = _get_posting_info(claim)

        try:
            sync_history = [
                {
                    "synced_at": s.synced_at.isoformat() if s.synced_at else None,
                    "log_type": s.log_type,
                    "status": s.candid_claim_status,
                    "effects": s.payment_effects_count,
                    "era_ids": s.era_ids.split(",") if s.era_ids else [],
                    "detail": s.detail,
                }
                for s in SyncLog.objects.filter(
                    canvas_claim_id=canvas_claim_id
                ).order_by("-synced_at")[:MAX_SYNC_HISTORY]
            ]
        except Exception:
            sync_history = []

        banner_alert = claim.banner_alerts.filter(
            key=BANNER_KEY, status="active"
        ).first()
        banner_text = banner_alert.narrative if banner_alert else None

        comments = [
            {
                "comment": c.comment,
                "created": c.created.isoformat() if c.created else None,
            }
            for c in claim.comments.filter(comment__startswith="Candid").order_by(
                "-created"
            )
        ]

        return [
            JSONResponse(
                {
                    "claim_id": canvas_claim_id,
                    "submitted_at": submitted_at,
                    "last_sync_at": last_sync,
                    "candid_claim_status": claim_status,
                    "banner": banner_text,
                    "encounters": encounters,
                    "synced_era_ids": [
                        {
                            "id": eid,
                            "posted_at": (posting_info.get(f"{ERA_DESC_PREFIX}{eid}") or {}).get("posted_at"),
                        }
                        for eid in synced_era_ids
                    ],
                    "synced_payment_ids": [
                        {
                            "id": pid,
                            "posted_at": (posting_info.get(f"{PATIENT_PAYMENT_DESC_PREFIX}{pid}") or {}).get("posted_at"),
                            "paid_amount": (posting_info.get(f"{PATIENT_PAYMENT_DESC_PREFIX}{pid}") or {}).get("paid_amount"),
                        }
                        for pid in synced_payment_ids
                    ],
                    "reported_payment_ids": reported_payment_ids,
                    "submission_error": submission_error,
                    "comments": comments,
                    "sync_history": sync_history,
                    "current_queue": claim.current_queue.name,
                }
            )
        ]

    def post(self) -> list[Response | Effect]:
        """Trigger a full adjudication sync for a claim."""
        body = self.request.json()
        canvas_claim_id = body.get("claim_id", "")
        if not canvas_claim_id:
            return [JSONResponse({"error": "claim_id required"}, status_code=400)]

        claim = Claim.objects.filter(id=canvas_claim_id).first()
        if not claim:
            return [JSONResponse({"error": "claim not found"}, status_code=404)]

        log.info(f"Candid app: manual sync triggered for claim {canvas_claim_id}")
        effects = sync_claim_adjudications(claim, self.secrets)

        return effects + [
            JSONResponse({"status": "synced", "effects_count": len(effects)})
        ]
