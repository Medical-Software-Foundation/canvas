from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import requests

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

# POST /service-lines/v2 links diagnoses by Candid diagnosis_id, not the
# integer diagnosis_pointers used inside the encounter payload.
DIAGNOSIS_ID_KEYS = (
    "diagnosis_id_zero",
    "diagnosis_id_one",
    "diagnosis_id_two",
    "diagnosis_id_three",
)


def _normalize_dx_code(code: str | None) -> str:
    """Canvas stores ICD-10 codes without the decimal point (E119); Candid
    returns them in canonical dotted form (E11.9). Strip the dot so the two
    sides match."""
    return (code or "").replace(".", "").strip().upper()


def _standalone_service_line(
    line: dict, claim_id: str, code_to_diagnosis_id: dict, note_diagnoses: list
) -> dict:
    """Translate an encounter-embedded service line into the standalone
    POST /service-lines/v2 schema.

    The standalone endpoint references diagnoses by Candid diagnosis_id
    (diagnosis_id_zero..three), so each integer diagnosis_pointer is resolved
    back to its code via the note diagnosis list, then to the encounter's
    diagnosis_id. The endpoint has no ordering field — service line order is
    the order they are created, so callers must POST in note order.
    """
    standalone: dict = {
        "claim_id": claim_id,
        "procedure_code": line["procedure_code"],
        "units": line.get("units", "UN"),
        "quantity": line.get("quantity", "1"),
    }
    if "charge_amount_cents" in line:
        standalone["charge_amount_cents"] = int(line["charge_amount_cents"])
    if line.get("modifiers"):
        standalone["modifiers"] = line["modifiers"]
    if line.get("external_id"):
        standalone["external_id"] = line["external_id"]

    diagnosis_ids: list = []
    for pointer in line.get("diagnosis_pointers", []):
        if 0 <= pointer < len(note_diagnoses):
            code = _normalize_dx_code(note_diagnoses[pointer].get("code"))
            dx_id = code_to_diagnosis_id.get(code)
            if dx_id and dx_id not in diagnosis_ids:
                diagnosis_ids.append(dx_id)
    standalone.update(zip(DIAGNOSIS_ID_KEYS, diagnosis_ids))

    return standalone


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

                    # PATCH can't touch service lines — replace them wholesale
                    if success:
                        self._replace_service_lines(client, encounter_id, payload)

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

    @staticmethod
    def _replace_service_lines(
        client: CandidClient, encounter_id: str, payload: dict
    ) -> None:
        """Delete the encounter's existing service lines and create new ones.

        PATCH /encounters can't modify service lines, so on resubmission we
        replace them wholesale: delete every line from the prior submission,
        then POST the current line items to /service-lines/v2. This avoids
        stale or mis-ordered lines lingering when the claim changed between
        submissions.
        """
        try:
            encounter = client.get_encounter(encounter_id)
        except requests.RequestException as e:
            log.warning(
                f"Candid: failed to fetch encounter {encounter_id} "
                f"for service line replacement: {e}"
            )
            return

        candid_claims = encounter.get("claims", [])
        claim_id = next(
            (c.get("claim_id") for c in candid_claims if c.get("claim_id")), None
        )
        if not claim_id:
            log.warning(
                f"Candid: encounter {encounter_id} has no claim_id; "
                "cannot replace service lines"
            )
            return

        # Candid stores diagnoses at the encounter level, not under claims.
        code_to_diagnosis_id = {
            _normalize_dx_code(d.get("code")): d.get("diagnosis_id")
            for d in encounter.get("diagnoses", [])
            if d.get("code") and d.get("diagnosis_id")
        }
        note_diagnoses = payload.get("diagnoses", [])

        for candid_claim in candid_claims:
            for sl in candid_claim.get("service_lines", []):
                sl_id = sl.get("service_line_id")
                if not sl_id:
                    continue
                ok, msg = client.delete_service_line(sl_id)
                if ok:
                    log.info(f"Candid: deleted service line {sl_id}")
                else:
                    log.warning(
                        f"Candid: failed to delete service line {sl_id}: {msg}"
                    )

        # POST in note order — the create endpoint has no ordering field, so
        # service line order on the claim follows creation order.
        for line in payload.get("service_lines", []):
            standalone = _standalone_service_line(
                line, claim_id, code_to_diagnosis_id, note_diagnoses
            )
            ok, msg = client.create_service_line(standalone)
            if ok:
                log.info(f"Candid: created service line {msg}")
            else:
                log.warning(f"Candid: failed to create service line: {msg}")
