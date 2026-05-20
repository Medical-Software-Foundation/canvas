from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPIRoute
from canvas_sdk.v1.data.claim import Claim, ClaimQueues
from logger import log

from candid.api.broadcast import notify_claim_updated
from candid.api.client import CandidClient
from candid.api.payload_builder import build_split_payloads
from candid.effect_helpers import (
    check_internal_auth,
    handle_submit_failure,
    handle_submit_success,
)

SUBMISSION_QUEUE = ClaimQueues.QUEUED_FOR_SUBMISSION

# Fields from the POST /encounters/v4 payload that are not accepted by
# PATCH /encounters/v4/{encounter_id}. The PATCH schema (EncounterUpdate)
# uses diagnosis_ids instead of diagnoses, and does not accept service_lines.
PATCH_EXCLUDED_FIELDS = {"diagnoses", "service_lines"}


class CandidSubmitAPI(SimpleAPIRoute):
    """SimpleAPI endpoint that submits a claim to Candid after the grace period.

    Invoked by the plugin's own ``OnClaimQueueMoved`` handler via a delayed
    (``GRACE_PERIOD_SECONDS``) ``HttpRequestEffect``. Before submitting, the
    route re-checks that the claim is still in ``QueuedForSubmission`` and
    skips if the user moved it elsewhere during the grace period.
    Authentication uses ``CANDID_CLIENT_SECRET`` as a shared API key.
    """

    PATH = "/submit"

    def authenticate(self, credentials: APIKeyCredentials) -> bool:
        return check_internal_auth(credentials.key, self.secrets)

    def _get_claim(self) -> Claim | None:
        body = self.request.json()
        claim_id = body.get("claim_id")
        if not claim_id:
            return None

        claim = Claim.objects.filter(id=claim_id).first()
        if not claim:
            log.warning(f"Candid: claim {claim_id} not found")
            return None

        # Grace period check: user may have moved the claim out of the submission queue
        current_queue = claim.current_queue
        if current_queue.queue_sort_ordering != SUBMISSION_QUEUE:
            log.info(
                f"Candid: claim {claim_id} is no longer in {SUBMISSION_QUEUE.label} "
                f"(now in {current_queue.name}). Skipping submission."
            )
            return None

        return claim

    def post(self) -> list[Response | Effect]:
        if not (claim := self._get_claim()):
            return []

        effects = self._submit(claim)
        effects.append(notify_claim_updated(str(claim.id)))
        return effects

    def _submit(self, claim: Claim) -> list[Effect]:
        claim_id = claim.id
        tz_name = self.environment.get("INSTALLATION_TIME_ZONE")
        tz = ZoneInfo(tz_name) if tz_name else None
        split_payloads = build_split_payloads(claim, tz=tz)
        claim_effect = ClaimEffect(claim_id=claim_id)

        for payload, errors in split_payloads:
            if errors:
                e = "; ".join(errors)
                message = f"Candid: claim {claim_id} has validation errors: {e}"
                log.warning(message)
                return handle_submit_failure(claim_effect, message)

        client = CandidClient.from_secrets(self.secrets)

        total_splits = len(split_payloads)
        encounter_records: list[dict] = []

        for split_index, (payload, _) in enumerate(split_payloads):
            split_num = split_index + 1
            split_label = (
                f"split {split_num}/{total_splits}" if total_splits > 1 else "claim"
            )
            ext_id = payload.get("external_id", "")

            try:
                success, message = client.submit_claim(payload)
            except Exception as e:
                log.exception(
                    f"Candid: submission failed for {split_label} of claim {claim_id}"
                )
                return handle_submit_failure(
                    claim_effect, f"Candid submission failed ({split_label}): {e}"
                )

            # If POST failed due to duplicate external_id, look up the
            # existing encounter and PATCH it instead.
            if not success and "EncounterExternalIdUniquenessError" in message:
                encounter_id = client.find_encounter_by_external_id(ext_id)
                if encounter_id:
                    log.info(
                        f"Candid: {split_label} of claim {claim_id} already exists "
                        f"(encounter_id={encounter_id}) — updating via PATCH"
                    )
                    # PATCH accepts a different schema than POST — remove
                    # fields that are only valid on create.
                    patch_payload = {
                        k: v
                        for k, v in payload.items()
                        if k not in PATCH_EXCLUDED_FIELDS
                    }
                    try:
                        success, message = client.update_claim(
                            encounter_id, patch_payload
                        )
                    except Exception as e:
                        log.exception(
                            f"Candid: update failed for {split_label} of claim {claim_id}"
                        )
                        return handle_submit_failure(
                            claim_effect,
                            f"Candid update failed ({split_label}): {e}",
                        )

            if not success:
                log.warning(
                    f"Candid: {split_label} of claim {claim_id} rejected: {message}"
                )
                return handle_submit_failure(
                    claim_effect,
                    f"Candid submission rejected ({split_label}): {message}",
                )

            encounter_records.append(
                {
                    "split": split_num,
                    "candid_encounter_id": message,
                    "external_id": ext_id,
                }
            )
            log.info(
                f"Candid: {split_label} of claim {claim_id} submitted "
                f"(encounter_id={message})"
            )

        submitted_at = datetime.now(UTC).isoformat()
        return handle_submit_success(
            claim_effect, encounter_records, submitted_at, total_splits
        )
