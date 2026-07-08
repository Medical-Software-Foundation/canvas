"""Canvas SDK effect builders for document processing."""

from typing import Any

from pydantic import ValidationError

from canvas_sdk.effects import Effect
from canvas_sdk.effects.data_integration import (
    AssignDocumentReviewer,
    CategorizeDocument,
    LinkDocumentToPatient,
    ReviewMode,
)
from canvas_sdk.effects.data_integration.types import ReportType, TemplateType
from logger import log

from doc_intake_ai.constants import AnnotationColor


def _coerce_report_type(value: str | None) -> ReportType | None:
    """Coerce a string to ReportType enum for strict pydantic validation."""
    if value is None:
        return None
    try:
        return ReportType(value)
    except ValueError:
        return None


def _coerce_template_type(value: str | None) -> TemplateType | None:
    """Coerce a string to TemplateType enum for strict pydantic validation."""
    if value is None:
        return None
    try:
        return TemplateType(value)
    except ValueError:
        return None


def build_categorize_effect(
    doc_id: str,
    doc_type: dict[str, Any],
    confidence: float | None,
    patient_error: str | None = None,
) -> Effect | None:
    """Build CategorizeDocument effect with confidence annotation."""
    report_type = _coerce_report_type(doc_type.get("report_type"))
    if report_type is None:
        log.warning("[EFFECTS] Unknown report_type: %s", doc_type.get("report_type"))
        return None

    try:
        return CategorizeDocument(
            document_id=str(doc_id),
            document_type={
                "key": doc_type["key"],
                "name": doc_type["name"],
                "report_type": report_type,
                "template_type": _coerce_template_type(doc_type.get("template_type")),
            },
            annotations=_confidence_annotation(confidence, patient_error),

        ).apply()
    except (ValidationError, KeyError) as e:
        log.error("[EFFECTS] Categorize error: %s", e)
        return None


def build_link_patient_effect(
    doc_id: str,
    patient: Any,
    confidence: float | None,
) -> Effect | None:
    """Build LinkDocumentToPatient effect."""
    try:
        return LinkDocumentToPatient(
            document_id=str(doc_id),
            patient_key=str(patient.id),
            annotations=_confidence_annotation(confidence),

        ).apply()
    except ValidationError as e:
        log.error("[EFFECTS] Link patient error: %s", e)
        return None


def build_assign_reviewer_effect(
    doc_id: str,
    reviewer: Any,
    auto_assigned: bool,
    confidence: float | None,
    patient_error: str | None = None,
) -> Effect | None:
    """Build AssignDocumentReviewer effect with REVIEW_REQUIRED mode."""
    if auto_assigned:
        annotations = [{"text": "Auto-assigned", "color": AnnotationColor.AUTO_ASSIGNED}]
    else:
        annotations = _confidence_annotation(confidence, patient_error)

    try:
        return AssignDocumentReviewer(
            document_id=str(doc_id),
            reviewer_id=str(reviewer.id),
            review_mode=ReviewMode.REVIEW_NOT_REQUIRED,
            annotations=annotations,

        ).apply()
    except ValidationError as e:
        log.error("[EFFECTS] Assign reviewer error: %s", e)
        return None


def _confidence_annotation(
    confidence: float | None,
    error: str | None = None,
) -> list[dict[str, str]]:
    """Build annotation list based on confidence level or error.

    Green >= 80%, yellow >= 50%, red < 50%.
    """
    if confidence is not None and 0 <= confidence <= 1:
        return [{"text": f"AI {round(confidence * 100)}%", "color": AnnotationColor.CONFIDENCE}]
    if error:
        return [{"text": error, "color": AnnotationColor.ERROR}]
    return []
