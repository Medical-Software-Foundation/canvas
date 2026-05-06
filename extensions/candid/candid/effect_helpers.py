"""Candid claim banner, metadata, and shared lookup helpers."""

import json
from datetime import UTC, datetime
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import BannerAlertIntent, ClaimEffect
from canvas_sdk.v1.data import Claim
from canvas_sdk.v1.data.claim import ClaimQueues

BANNER_KEY = "candid-clearinghouse-status"

META_SUBMITTED_AT = "candid_submitted_at"
META_CLAIM_STATUS = "candid_claim_status"
META_LAST_SYNC = "candid_last_sync_at"
META_ENCOUNTERS = "candid_encounters"
META_REPORTED_PAYMENT_IDS = "candid_reported_payment_ids"
META_SYNCED_ERA_IDS = "candid_synced_adjudication_ids"
META_SYNCED_PAYMENT_IDS = "candid_synced_payment_ids"
META_SUBMISSION_ERROR = "candid_submission_error"

PATIENT_COVERAGE_ID = "patient"
DEFAULT_CLAIM_STATUS = "synced"
DENIED_STATUSES = {"denied", "finalized_denied", "rejected", "failed"}
MISSING_PAYER_ORDER = 99

FAILURE_QUEUE = ClaimQueues.NEEDS_CODING_REVIEW
SUCCESS_QUEUE = ClaimQueues.FILED_AWAITING_RESPONSE


def get_claim_metadata(claim: Claim, key: str) -> Any:
    """Read a metadata value from a claim, returning parsed JSON or raw string."""
    meta = claim.metadata.filter(key=key).first()
    if not meta:
        return None
    try:
        return json.loads(meta.value)
    except (ValueError, TypeError):
        return meta.value


def get_claim_metadata_set(claim: Claim, key: str) -> set[str]:
    """Read a metadata value as a set of strings, defaulting to empty."""
    raw = get_claim_metadata(claim, key)
    return set(raw) if isinstance(raw, list) else set()


def active_coverages_ordered(claim: Claim) -> list:
    """Return the claim's active coverages sorted by payer_order (primary first)."""
    return sorted(
        (c for c in claim.coverages.all() if c.active),
        key=lambda c: (
            c.payer_order if c.payer_order is not None else MISSING_PAYER_ORDER
        ),
    )


def submission_banner(
    claim_effect: ClaimEffect, submitted_at: str, split_count: int
) -> Effect:
    date_display = submitted_at[:10]
    splits_note = f" ({split_count} encounters)" if split_count > 1 else ""
    narrative = f"Candid: Submitted {date_display}{splits_note} | Awaiting response"
    return claim_effect.add_banner(
        key=BANNER_KEY,
        narrative=narrative,
        intent=BannerAlertIntent.INFO,
    )


def sync_banner(
    claim_id: str,
    claim_status: str,
    last_sync_at: str,
    submitted_at: str | None = None,
) -> Effect:
    sync_date = last_sync_at[:10]
    status_display = claim_status.replace("_", " ").title()

    parts = [f"Candid: {status_display}"]
    if submitted_at:
        parts.append(f"Submitted {submitted_at[:10]}")
    parts.append(f"Last synced {sync_date}")

    narrative = " | ".join(parts)
    intent = (
        BannerAlertIntent.WARNING
        if claim_status.lower() in DENIED_STATUSES
        else BannerAlertIntent.INFO
    )

    return ClaimEffect(claim_id=claim_id).add_banner(
        key=BANNER_KEY,
        narrative=narrative,
        intent=intent,
    )


def claim_metadata(
    claim_effect: ClaimEffect, encounters: list[dict], date_submitted: str
) -> list[Effect]:
    return [
        claim_effect.upsert_metadata(key=META_ENCOUNTERS, value=json.dumps(encounters)),
        claim_effect.upsert_metadata(key=META_SUBMITTED_AT, value=date_submitted),
    ]


def handle_submit_success(
    claim_effect: ClaimEffect,
    encounter_records: list[dict],
    submitted_at: str,
    total_splits: int,
) -> list[Effect]:
    date_display = submitted_at[:10]
    splits_note = f" across {total_splits} encounters" if total_splits > 1 else ""
    encounter_ids = (
        ", ".join(
            r["candid_encounter_id"]
            for r in encounter_records
            if r.get("candid_encounter_id")
        )
        or "(none)"
    )
    comment = (
        f"Claim submitted to Candid on {date_display}{splits_note}. "
        f"Encounter IDs: {encounter_ids}"
    )

    return [
        *claim_metadata(claim_effect, encounter_records, submitted_at),
        claim_effect.upsert_metadata(key=META_SUBMISSION_ERROR, value=""),
        claim_effect.add_comment(comment=comment),
        submission_banner(claim_effect, submitted_at, total_splits),
        claim_effect.move_to_queue(SUCCESS_QUEUE.label),
    ]


def handle_submit_failure(claim_effect: ClaimEffect, comment: str) -> list[Effect]:
    date_display = datetime.now(UTC).strftime("%Y-%m-%d")
    error_value = json.dumps({"error": comment, "date": date_display})
    return [
        claim_effect.add_comment(comment),
        claim_effect.upsert_metadata(key=META_SUBMISSION_ERROR, value=error_value),
        claim_effect.add_banner(
            key=BANNER_KEY,
            narrative=f"Candid: Submission failed {date_display}",
            intent=BannerAlertIntent.WARNING,
        ),
        claim_effect.move_to_queue(FAILURE_QUEUE.label),
    ]
