from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.effects.simple_api import Response
from canvas_sdk.handlers.simple_api import APIKeyCredentials, SimpleAPIRoute
from canvas_sdk.v1.data.claim import Claim, ClaimQueues
from logger import log
from requests import RequestException

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


# Candid's answer when a coverage's payer ID isn't in its Canvas payer crosswalk
UNKNOWN_PAYER_ERROR = "Unable to find payer"
UNKNOWN_PAYER_HINT = (
    " Candid doesn't know this payer ID. Check the payer on the coverage "
    "named in the error; if it's right, ask Candid to add the payer ID to "
    "the practice's Canvas payer mapping, then resubmit."
)


def _rejection_comment(split_label: str, message: str) -> str:
    """The claim comment for a Candid rejection, with a next step when one is known."""
    comment = f"Candid submission rejected ({split_label}): {message}"
    if UNKNOWN_PAYER_ERROR in message:
        comment = comment + UNKNOWN_PAYER_HINT
    return comment


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
    # external_id (the Canvas line-item id) keys the line for future resubmits
    # and adjudication matching. On resubmit, persistent lines are PATCHed in
    # place rather than recreated, so a create only ever carries a brand-new id
    # — it never collides with Candid's per-claim external_id reservation.
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


ICD10_PRINCIPAL = "ABK"
ICD10_OTHER = "ABF"


def _reconcile_principal_diagnosis(
    client: CandidClient,
    encounter_id: str,
    encounter_diagnoses: list[dict],
    note_diagnoses: list[dict],
) -> list[str]:
    """Bring each existing diagnosis's ICD-10 code_type (ABK principal / ABF
    other) in line with the claim's rank order.

    Candid marks the principal diagnosis by code_type, not by its position in
    the encounter's diagnosis_ids, and PATCH /encounters can't change it. When
    the claim's rank-1 code changes, the old principal is demoted to ABF and
    the new one promoted to ABK via PATCH /api/diagnoses/v2/{diagnosis_id}
    (https://docs.joincandidhealth.com/api-reference/diagnoses/update).
    Demotions run first so the encounter never holds two principals.
    Diagnoses just created already carry the right code_type, and non-ICD-10
    code types are left alone.
    """
    desired = {
        _normalize_dx_code(dx.get("code")): dx.get("code_type")
        for dx in note_diagnoses
        if dx.get("code")
    }
    demote: list[str] = []
    promote: list[str] = []
    for d in encounter_diagnoses:
        current = d.get("code_type")
        if current not in (ICD10_PRINCIPAL, ICD10_OTHER):
            continue
        # A principal that left the claim is demoted too; it's dropped from
        # diagnosis_ids at the end, but must not block the new principal.
        target = desired.get(_normalize_dx_code(d["code"])) or ICD10_OTHER
        if target == current or target not in (ICD10_PRINCIPAL, ICD10_OTHER):
            continue
        (promote if target == ICD10_PRINCIPAL else demote).append(d["diagnosis_id"])

    errors: list[str] = []
    for diagnosis_ids, code_type in ((demote, ICD10_OTHER), (promote, ICD10_PRINCIPAL)):
        for diagnosis_id in diagnosis_ids:
            ok, msg = client.update_diagnosis(diagnosis_id, {"code_type": code_type})
            if ok:
                log.info(
                    f"Candid: set diagnosis {diagnosis_id} code_type to {code_type}"
                )
            else:
                log.warning(
                    f"Candid: failed to set code_type on diagnosis {diagnosis_id}: {msg}"
                )
                errors.append(f"set diagnosis {diagnosis_id} to {code_type}: {msg}")
        if errors:
            return errors
    return errors


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

                    # PATCH can't touch diagnoses or service lines — reconcile
                    # them separately. Any failure fails the whole claim so it
                    # never looks submitted with lines missing on Candid.
                    if success:
                        # Any exception (token fetch, network, bad JSON) must
                        # fail the claim like a rejected write does, or it is
                        # left in QueuedForSubmission with no comment.
                        try:
                            reconcile_errors = self._reconcile_service_lines(
                                client, encounter_id, payload
                            )
                        except Exception as exc:
                            log.exception(
                                f"Candid: service line reconciliation raised for "
                                f"{split_label} of claim {claim_id}"
                            )
                            reconcile_errors = [f"unexpected error: {exc}"]
                        if reconcile_errors:
                            detail = "; ".join(reconcile_errors)
                            log.warning(
                                f"Candid: service line reconciliation failed for "
                                f"{split_label} of claim {claim_id} "
                                f"({len(reconcile_errors)} error(s); see claim comment)"
                            )
                            return handle_submit_failure(
                                claim_effect,
                                f"Candid service line update failed ({split_label}): {detail}",
                            )

            if not success:
                log.warning(
                    f"Candid: {split_label} of claim {claim_id} rejected: {message}"
                )
                return handle_submit_failure(
                    claim_effect, _rejection_comment(split_label, message)
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
    def _reconcile_service_lines(
        client: CandidClient, encounter_id: str, payload: dict
    ) -> list[str]:
        """Reconcile the encounter's diagnoses and service lines with the claim.

        PATCH /encounters can't create diagnoses or modify service lines, so on
        resubmission we:

        1. POST any claim diagnosis the encounter doesn't have yet, so new or
           changed lines can link to it.
        2. Diff the lines already on the encounter against the claim's current
           line items, keyed on external_id (the Canvas line-item id):

           - on both          -> PATCH the existing line in place
           - only on the claim -> POST a new line
           - only on encounter -> DELETE it

        3. PATCH the encounter's diagnosis_ids to the claim's list, in claim
           rank order, once no line still points at a dropped diagnosis.

        Deletes run only after every diagnosis, create and update succeeded. A
        rejected replacement line must never leave the encounter with its old
        line deleted and nothing in its place.

        Updating in place rather than deleting and recreating keeps the Candid
        service line order aligned with the note (reordering a note line creates
        a new line at the bottom, which we mirror) and avoids reusing an
        external_id, which Candid reserves per claim even after a delete and
        rejects with 409 EntityConflictError.

        Returns a list of error messages; empty means everything reconciled.
        """
        try:
            encounter = client.get_encounter(encounter_id)
        except RequestException as e:
            log.warning(
                f"Candid: failed to fetch encounter {encounter_id} "
                f"for service line reconciliation: {e}"
            )
            return [f"could not fetch encounter {encounter_id}: {e}"]

        candid_claims = encounter.get("claims", [])
        claim_id = next(
            (c.get("claim_id") for c in candid_claims if c.get("claim_id")), None
        )
        if not claim_id:
            log.warning(
                f"Candid: encounter {encounter_id} has no claim_id; "
                "cannot reconcile service lines"
            )
            return [f"encounter {encounter_id} has no claim_id"]

        # Candid stores diagnoses at the encounter level, not under claims.
        encounter_diagnoses = [
            d
            for d in encounter.get("diagnoses", [])
            if d.get("code") and d.get("diagnosis_id")
        ]
        code_to_diagnosis_id = {
            _normalize_dx_code(d["code"]): d["diagnosis_id"]
            for d in encounter_diagnoses
        }
        note_diagnoses = payload.get("diagnoses", [])

        # Create diagnoses added to the claim since the last submit. Without
        # them a new line has no diagnosis to link and Candid rejects it (422).
        # The code is sent as Canvas stores it (undotted, e.g. E119), the same
        # form the initial POST /encounters/v4 sends. Candid's ICD-10 format
        # makes the period optional, so both forms are valid input:
        # https://docs.joincandidhealth.com/api-reference/diagnoses/create
        errors: list[str] = []
        for dx in note_diagnoses:
            code = _normalize_dx_code(dx.get("code"))
            if not code or code in code_to_diagnosis_id:
                continue
            ok, msg = client.create_diagnosis(
                encounter_id, dx["code"].strip(), dx.get("code_type", "ABF")
            )
            if ok and not msg:
                ok, msg = False, "Candid returned no diagnosis_id"
            if ok:
                log.info(f"Candid: created diagnosis {msg} on encounter {encounter_id}")
                code_to_diagnosis_id[code] = msg
            else:
                # Code stays out of the log (PHI); it's in the claim comment.
                log.warning(
                    f"Candid: failed to create diagnosis on encounter {encounter_id}: {msg}"
                )
                errors.append(f"diagnosis {dx['code']}: {msg}")
        if errors:
            return errors

        errors = _reconcile_principal_diagnosis(
            client, encounter_id, encounter_diagnoses, note_diagnoses
        )
        if errors:
            return errors

        existing_lines = [
            sl
            for candid_claim in candid_claims
            for sl in candid_claim.get("service_lines", [])
            if sl.get("service_line_id")
        ]
        existing_by_external_id = {
            sl["external_id"]: sl for sl in existing_lines if sl.get("external_id")
        }

        # Update matched lines and create new ones, in note order so created
        # lines append in the note's order.
        current_external_ids: set[str] = set()
        for line in payload.get("service_lines", []):
            standalone = _standalone_service_line(
                line, claim_id, code_to_diagnosis_id, note_diagnoses
            )
            external_id = standalone.get("external_id")
            if external_id:
                current_external_ids.add(external_id)
            existing_line = (
                existing_by_external_id.get(external_id) if external_id else None
            )
            if existing_line:
                service_line_id = existing_line["service_line_id"]
                # PATCH can't take claim_id, and external_id is already set on
                # the line — sending it again risks tripping uniqueness.
                update = {
                    k: v
                    for k, v in standalone.items()
                    if k not in ("claim_id", "external_id")
                }
                # PATCH leaves omitted fields alone, so a slot the line no
                # longer uses would keep pointing at its old diagnosis (which
                # may be dropped from the encounter below). Null out any slot
                # the line currently holds but no longer needs.
                for key in DIAGNOSIS_ID_KEYS:
                    if key not in update and existing_line.get(key):
                        update[key] = None
                ok, msg = client.update_service_line(service_line_id, update)
                if ok:
                    log.info(f"Candid: updated service line {service_line_id}")
                else:
                    log.warning(
                        f"Candid: failed to update service line {service_line_id}: {msg}"
                    )
                    errors.append(
                        f"update {line.get('procedure_code')} line {service_line_id}: {msg}"
                    )
            else:
                ok, msg = client.create_service_line(standalone)
                if ok:
                    log.info(f"Candid: created service line {msg}")
                else:
                    log.warning(f"Candid: failed to create service line: {msg}")
                    errors.append(f"create {line.get('procedure_code')} line: {msg}")

        # Never delete after a failed create or update: the line being replaced
        # is the encounter's only copy of the charge until its replacement lands.
        if errors:
            return errors

        # Delete lines on the encounter that are no longer on the claim
        # (including any legacy line missing an external_id, which can't match).
        for sl in existing_lines:
            if sl.get("external_id") in current_external_ids:
                continue
            sl_id = sl["service_line_id"]
            ok, msg = client.delete_service_line(sl_id)
            if ok:
                log.info(f"Candid: deleted service line {sl_id}")
            else:
                log.warning(f"Candid: failed to delete service line {sl_id}: {msg}")
                errors.append(f"delete line {sl_id}: {msg}")
        if errors:
            return errors

        # Bring the encounter's diagnosis list in line with the claim (adds,
        # drops and rank order). Done last so no line still links a dropped one.
        diagnosis_ids = []
        for dx in note_diagnoses:
            dx_id = code_to_diagnosis_id.get(_normalize_dx_code(dx.get("code")))
            if dx_id and dx_id not in diagnosis_ids:
                diagnosis_ids.append(dx_id)
        if diagnosis_ids:
            ok, msg = client.update_claim(
                encounter_id, {"diagnosis_ids": diagnosis_ids}
            )
            if not ok:
                log.warning(
                    f"Candid: failed to update diagnoses on encounter {encounter_id}: {msg}"
                )
                errors.append(f"update encounter diagnoses: {msg}")

        return errors
