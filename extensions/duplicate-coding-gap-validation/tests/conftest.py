"""Shared test fixtures for the duplicate-coding-gap-validation plugin."""

from unittest.mock import Mock


def make_diagnose_entry(
    code: str, system: str = "ICD-10", display: str = "", value: str | None = None
) -> dict:
    """Build one ``diagnose`` autocomplete pick as the coding-gap command serializes it.

    Top-level ``value`` is the ICD-10 code; ``extra.coding`` holds the coding list.
    """
    return {
        "text": display or f"Condition {code}",
        "value": code if value is None else value,
        "extra": {"coding": [{"code": code, "system": system, "display": display}]},
    }


def make_coding(code: str, system: str = "ICD-10") -> Mock:
    """Build a mock condition coding with ``code`` and ``system`` attributes."""
    coding = Mock()
    coding.code = code
    coding.system = system
    return coding


def make_condition(clinical_status: str, codings: list[Mock]) -> Mock:
    """Build a mock committed condition with a clinical status and its codings."""
    condition = Mock()
    condition.clinical_status = clinical_status
    condition.codings.all.return_value = codings
    return condition


def wire_condition_queryset(mock_condition_cls: Mock, conditions: list[Mock]) -> None:
    """Wire ``Condition.objects.for_patient(...).committed().prefetch_related(...)`` -> conditions."""
    chain = Mock()
    chain.prefetch_related.return_value = conditions
    mock_condition_cls.objects.for_patient.return_value.committed.return_value = chain


def make_detected_issue(evidence_codes: list[str], system: str = "ICD-10") -> Mock:
    """Build a mock coding-gap DetectedIssue whose evidence carries ``evidence_codes``."""
    detected_issue = Mock()
    detected_issue.evidence.all.return_value = [make_coding(c, system) for c in evidence_codes]
    return detected_issue


def make_patient(patient_id: str = "patient-1", detected_issues: list[Mock] | None = None) -> Mock:
    """Build a mock patient.

    ``patient.detected_issues.filter(...).prefetch_related("evidence")`` returns
    ``detected_issues``.
    """
    patient = Mock()
    patient.id = patient_id
    patient.detected_issues.filter.return_value.prefetch_related.return_value = (
        detected_issues or []
    )
    return patient


def make_command(
    diagnose_entries: list[dict],
    patient: Mock | None = "__default__",
) -> Mock:
    """Build a mock coding-gap command whose ``diagnose`` field carries ``diagnose_entries``.

    Pass ``patient=None`` for a command with no patient; omit it for a default patient
    with no detected issues, or pass a patient built with ``make_patient``.
    """
    command = Mock()
    command.id = "coding-gap-command-1"
    command.data = {"diagnose": diagnose_entries}
    command.patient = make_patient() if patient == "__default__" else patient
    return command
