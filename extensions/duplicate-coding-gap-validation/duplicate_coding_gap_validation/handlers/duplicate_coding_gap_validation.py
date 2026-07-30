"""Block creation of a coding gap that duplicates a condition or an existing coding gap.

When a ``Create Coding Gap`` command is validated, this handler reads the ICD-10 code(s)
selected in the command's ``diagnose`` field and blocks the commit when:

1. the code is already documented as a committed ``Condition`` on the chart, or
2. an active coding gap (``DetectedIssue``) already carries that code for the patient.

If nothing matches (or the patient/code can't be resolved) the commit proceeds.
"""

from typing import Any

from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.condition import ClinicalStatus, Condition
from canvas_sdk.v1.data.detected_issue import DetectedIssue
from logger import log

# DetectedIssue.code value for coding gaps (DetectedIssue.Code.CODING_GAP in home-app).
CODING_GAP_ISSUE_CODE = "CODINGGAP"

# Clinical statuses that count as "currently documented on the chart".
ACTIVE_LIKE_STATUSES: frozenset[str] = frozenset(
    {ClinicalStatus.ACTIVE,}
)

# DetectedIssue statuses that count as an existing/live coding gap (excludes cancelled
# and entered-in-error). Mirrors the daymark command_validation reference plugin.
ACTIVE_DETECTED_ISSUE_STATUSES: tuple[str, ...] = (
    DetectedIssue.Status.REGISTERED,
    DetectedIssue.Status.PRELIMINARY,
    DetectedIssue.Status.FINAL,
    DetectedIssue.Status.AMENDED,
    DetectedIssue.Status.CORRECTED,
)

ACTIVE_CONDITION_MESSAGE = (
    "This condition is already documented in the patient's chart. "
    "Reassess this condition instead of creating a new coding gap."
)
RESOLVED_CONDITION_MESSAGE = (
    "This condition is documented as resolved in the patient's chart. "
    "Activate the existing condition instead of creating a new coding gap."
)
DUPLICATE_GAP_MESSAGE = "A coding gap for this condition already exists for this patient."


def _normalize_icd10(code: str | None) -> str:
    """Uppercase and strip dots/whitespace so ``E11.65`` and ``e11 65`` compare equal."""
    if not code:
        return ""
    return code.strip().upper().replace(".", "").replace(" ", "")


def _is_icd10(system: Any) -> bool:
    """Return True if a coding ``system`` value denotes ICD-10 (tolerant of URL/short forms)."""
    if not isinstance(system, str):
        return False
    lowered = system.lower()
    return "icd-10" in lowered or "icd10" in lowered


def matching_condition_statuses(patient_id: str, icd10_codes: set[str]) -> set[str]:
    """Return the clinical statuses of committed conditions matching ``icd10_codes`` (empty if none)."""
    if not icd10_codes:
        return set()

    statuses: set[str] = set()
    conditions = (
        Condition.objects.for_patient(patient_id).committed().prefetch_related("codings")
    )
    for condition in conditions:
        condition_codes = {
            _normalize_icd10(coding.code)
            for coding in condition.codings.all()
            if _is_icd10(coding.system)
        }
        if condition_codes & icd10_codes:
            statuses.add(condition.clinical_status)
    return statuses


def has_duplicate_coding_gap(patient: Any, icd10_codes: set[str]) -> bool:
    """Return True if an active coding gap already carries one of ``icd10_codes``.

    Coding gaps are ``DetectedIssue`` records (``code="CODINGGAP"``) whose ICD-10 codes
    live on the related ``evidence`` (``DetectedIssueEvidence``, a Coding). We read them
    off the patient's reverse relation — ``patient.detected_issues`` — rather than filtering
    ``DetectedIssueEvidence`` by ``detected_issue__patient_id`` (that FK column is the
    integer ``dbid``, not the patient UUID, so it never matches). Compare on the normalized
    code so dotted/undotted formatting differences still match.
    """
    if not icd10_codes:
        return False

    existing_gap_codes = {
        _normalize_icd10(evidence.code)
        for detected_issue in patient.detected_issues.filter(
            code=CODING_GAP_ISSUE_CODE,
            deleted=False,
            status__in=ACTIVE_DETECTED_ISSUE_STATUSES,
        ).prefetch_related("evidence")
        for evidence in detected_issue.evidence.all()
        if _is_icd10(evidence.system)
    }
    return bool(icd10_codes & existing_gap_codes)


class BlockDuplicateCodingGapHandler(BaseHandler):
    """Prevent a coding gap for a condition/gap already present on the patient's chart."""

    RESPONDS_TO = [
        EventType.Name(EventType.CREATE_CODING_GAP_COMMAND__POST_VALIDATION),
    ]

    @staticmethod
    def _selected_icd10s(data: dict) -> list[tuple[str, str]]:
        """Extract selected ICD-10 code(s) from the createCodingGap field data.

        data["diagnose"] is a list; each pick has a top-level "value" (the ICD-10
        code) and "extra"."coding" holding the coding list, e.g.
        {"code": "G4730", "system": "ICD-10", "display": "..."}.
        """
        out: list[tuple[str, str]] = []
        diagnoses = data.get("diagnose") or []
        if isinstance(diagnoses, dict):
            diagnoses = [diagnoses]
        for entry in diagnoses:
            if not isinstance(entry, dict):
                continue
            code, display = None, entry.get("text") or ""
            for coding in (entry.get("extra") or {}).get("coding", []):
                if _is_icd10(coding.get("system")):
                    code = str(coding.get("code"))
                    display = coding.get("display") or display
                    break
            if not code and entry.get("value"):
                code = str(entry.get("value"))
            if code:
                out.append((code, display))
        return out

    def compute(self) -> list[Effect]:
        """Block the coding-gap commit when its ICD-10 duplicates a charted condition or gap."""
        command = Command.objects.get(id=self.event.target.id)

        selections = self._selected_icd10s(command.data)
        icd10_codes = {_normalize_icd10(code) for code, _display in selections}
        icd10_codes.discard("")
        patient = command.patient

        # Fail open: if we can't resolve a patient or a code, don't block the reviewer.
        if patient is None or not icd10_codes:
            return []

        patient_id = str(patient.id)

        # 1 & 2: the condition is already documented in the chart (active-like, then resolved).
        statuses = matching_condition_statuses(patient_id, icd10_codes)
        if statuses & ACTIVE_LIKE_STATUSES:
            message = ACTIVE_CONDITION_MESSAGE
        elif ClinicalStatus.RESOLVED in statuses:
            message = RESOLVED_CONDITION_MESSAGE
        # 3: an active coding gap already exists for this code for this patient.
        elif has_duplicate_coding_gap(patient, icd10_codes):
            message = DUPLICATE_GAP_MESSAGE
        else:
            return []

        log.info(
            f"[BlockDuplicateCodingGapHandler] Blocking duplicate coding gap for command "
            f"{command.id}: codes={sorted(icd10_codes)}"
        )
        effect = CommandValidationErrorEffect()
        effect.add_error(message)
        return [effect.apply()]
