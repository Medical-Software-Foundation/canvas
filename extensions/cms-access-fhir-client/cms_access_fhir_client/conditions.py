"""Build track-qualifying FHIR Condition resources from a patient's problem list.

The CMS ACCESS `$align` operation (Operations Manual v0.9.11 §Alignment API) requires
at least one `condition` parameter — a FHIR Condition whose `code` is drawn from the
track-specific diagnosis value set (ACCESSeCKMDiagnosisVS, ACCESSCKMDiagnosisVS,
ACCESSMSKDiagnosisVS, ACCESSBHDiagnosisVS). This module pulls the patient's active
Canvas conditions, keeps only the codings that qualify for the requested track, and
emits profile-conformant Condition resources referencing the embedded Patient.
"""
from canvas_sdk.v1.data.condition import Condition

from cms_access_fhir_client.track_diagnoses import canonical_code_for_track

# Canvas stores ICD-10-CM condition codings under either of these system strings
# (undotted codes, e.g. "E119"); the ACCESS value sets use the canonical dotted form.
_ICD10_SYSTEMS = ("http://hl7.org/fhir/sid/icd-10", "ICD-10")
# The system the ACCESS Condition profiles expect on the emitted resource.
_ICD10_CM_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm"

# IMPL requires meta.profile on every Condition. Track-qualifying diagnoses use the
# track-specific Condition profile; the $unalign "no longer clinically eligible"
# disqualifying diagnosis uses the clinical-exclusion profile.
_SD_BASE = "https://dsacms.github.io/cmmi-access-model/StructureDefinition"
_TRACK_CONDITION_PROFILE = {
    "eCKM": f"{_SD_BASE}/access-eckm-condition",
    "CKM": f"{_SD_BASE}/access-ckm-condition",
    "MSK": f"{_SD_BASE}/access-msk-condition",
    "BH": f"{_SD_BASE}/access-bh-condition",
}
_CLINICAL_EXCLUSION_PROFILE = f"{_SD_BASE}/access-clinical-exclusion-condition"


def build_track_conditions(patient, track: str, patient_fhir_id: str) -> list[dict]:
    """Return FHIR Condition resources for the patient's diagnoses to send with ``$align``.

    Hybrid value-set strategy (gate-softening):
    - Match the patient's active ICD-10 codings against the track's diagnosis value set
      (``track_diagnoses.py``) and send those — the precise, spec-modeled behavior.
    - If NONE match (our embedded value set may be stale/incomplete vs the current IG),
      fall back to sending ALL the patient's active diagnoses so our list can never BLOCK
      a genuinely-qualifying patient. CMS adjudicates — empirically it returns
      ``200 not-aligned-diagnoses`` for non-qualifying codes rather than a 400, and the
      track Condition profile does not hard-reject an out-of-set code at validation.

    Codes are emitted in canonical dotted ICD-10-CM with the track Condition profile and a
    subject reference to the embedded Patient. Returns an empty list ONLY when the patient
    has no active ICD-10 diagnosis at all; the caller still fails closed in that case
    (``$align`` requires at least one condition).
    """
    conditions = (
        Condition.objects.for_patient(patient.id).active().prefetch_related("codings")
    )
    profile = _TRACK_CONDITION_PROFILE.get(track, _CLINICAL_EXCLUSION_PROFILE)

    matched: list[dict] = []
    seen_matched: set[str] = set()
    fallback: list[dict] = []
    seen_fallback: set[str] = set()
    for condition in conditions:
        for coding in condition.codings.all():
            if coding.system not in _ICD10_SYSTEMS:
                continue
            canonical = canonical_code_for_track(track, coding.code)
            if canonical and canonical not in seen_matched:
                seen_matched.add(canonical)
                matched.append(_condition_resource(canonical, coding.display, patient_fhir_id, profile))
            dotted = _dotted_icd10(coding.code)
            if dotted and dotted not in seen_fallback:
                seen_fallback.add(dotted)
                fallback.append(_condition_resource(dotted, coding.display, patient_fhir_id, profile))

    return matched if matched else fallback


def _dotted_icd10(code: str) -> str:
    """Convert an undotted ICD-10-CM code to canonical dotted form (dot after 3 chars).

    Canvas stores codes undotted (e.g. "N186"); ICD-10-CM places the decimal after the
    3-character category ("N18.6"). Already-dotted input is returned unchanged.
    """
    code = code.strip().upper()
    if "." in code or len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


def _condition_resource(code: str, display: str, patient_fhir_id: str, profile: str) -> dict:
    """Build a profile-conformant FHIR Condition.

    IMPL validates against the ACCESS Condition profiles, which inherit the US Core
    problem/health-concern requirements — so clinicalStatus, verificationStatus, and
    category are included alongside the ICD-10-CM code and subject reference.
    """
    return {
        "resourceType": "Condition",
        "meta": {"profile": [profile]},
        "clinicalStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]
        },
        "verificationStatus": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed"}]
        },
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "problem-list-item"}]}
        ],
        "code": {
            "coding": [
                {
                    "system": _ICD10_CM_SYSTEM,
                    "code": code,
                    "display": display or "",
                }
            ]
        },
        "subject": {"reference": f"Patient/{patient_fhir_id}"},
    }


def build_active_conditions(patient, patient_fhir_id: str) -> list[dict]:
    """Return FHIR Condition resources for all of the patient's active ICD-10 diagnoses.

    Used for `$unalign` with reason `no-longer-clinically-eligible`, where v0.9.11 requires
    a disqualifying Condition (ACCESS clinical-exclusion profile). Those exclusion value
    sets are ICD-10 hierarchy filters we cannot enumerate offline, but the manual allows
    "another value" when none in the set applies — so we submit the patient's active
    diagnoses (emitted as dotted ICD-10-CM). Returns an empty list when none exist; the
    caller must fail closed since the condition is then a required parameter.
    """
    conditions = (
        Condition.objects.for_patient(patient.id).active().prefetch_related("codings")
    )

    resources: list[dict] = []
    seen: set[str] = set()
    for condition in conditions:
        for coding in condition.codings.all():
            if coding.system not in _ICD10_SYSTEMS:
                continue
            canonical = _dotted_icd10(coding.code)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            resources.append(
                _condition_resource(canonical, coding.display, patient_fhir_id, _CLINICAL_EXCLUSION_PROFILE)
            )

    return resources
