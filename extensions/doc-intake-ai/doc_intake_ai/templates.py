"""Template matching, scoring, and prefill building."""

import re
from typing import Any

from pydantic import ValidationError

from canvas_sdk.effects import Effect
from canvas_sdk.effects.data_integration import PrefillDocumentFields
from canvas_sdk.v1.data import (
    ImagingReportTemplate,
    ImagingReportTemplateField,
    LabReportTemplate,
    LabReportTemplateField,
    SpecialtyReportTemplate,
    SpecialtyReportTemplateField,
)
from logger import log

from doc_intake_ai.constants import (
    AnnotationColor,
    GAP_FILL_THRESHOLD,
    KEYWORD_BONUS,
    MAX_FIELDS,
    SCORE_THRESHOLD,
    SOURCE_PROTOCOL,
)
from doc_intake_ai.models import DocumentExtraction


def score_and_match_templates(
    template_type: str,
    extraction: DocumentExtraction,
    content_url: str,
) -> tuple[list[dict[str, Any]], Any, set[str]] | None:
    """Score templates against extraction data and return candidates.

    Returns (candidates, field_model, codes) or None if no matches found.
    """
    template_model, field_model = _get_template_models(template_type)
    if not template_model:
        return None

    codes = _extract_codes(template_type, extraction)
    keywords = _extract_keywords(extraction)

    if not codes:
        log.info("[PREFILL] No codes to match")
        return None

    candidates = _score_candidates(field_model, template_model, codes, keywords, template_type)
    if not candidates:
        log.info("[PREFILL] No matching templates")
        return None

    log.info(
        "[PREFILL] Found %d candidates, top: %s (%.2f)",
        len(candidates),
        candidates[0]["name"],
        candidates[0]["score"],
    )

    return candidates, field_model, codes


def get_template_extraction_context(
    candidate: dict[str, Any],
    extracted_codes: set[str],
    matched_codes: set[str],
    field_model: Any,
    is_gap_fill: bool,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Build schema and key_map for a single candidate if it qualifies.

    Returns (schema, key_map) or None if the candidate should be skipped.
    """
    threshold = GAP_FILL_THRESHOLD if is_gap_fill else SCORE_THRESHOLD

    if candidate["score"] < threshold:
        return None

    new_codes = set(candidate["codes"]) - matched_codes
    if not new_codes:
        return None

    fields = list(field_model.objects.filter(
        report_template_id=candidate["id"],
    ).order_by("sequence"))

    if not fields:
        return None

    schema, key_map = _build_field_schema(fields, extracted_codes)
    if not schema["schema"]["properties"]:
        return None

    return schema, key_map


def build_prefill_fields_for_candidate(
    extraction_data: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    key_map: dict[str, Any],
    candidate: dict[str, Any],
    confidence: float | None,
) -> dict[str, Any] | None:
    """Build a single template dict with prefill fields for one candidate.

    Returns {"template_id": ..., "template_name": ..., "fields": ...} or None.
    """
    prefill_fields = _build_prefill_fields(extraction_data, metadata, key_map, confidence)
    if not prefill_fields:
        log.info("[PREFILL] No prefill fields for template %s", candidate.get("name"))
        return None

    return {
        "template_id": candidate["id"],
        "template_name": candidate["name"],
        "fields": prefill_fields,
    }


def build_prefill_effect(
    doc_id: str,
    templates: list[dict[str, Any]],
    confidence: float | None,
) -> Effect | None:
    """Build a single PrefillDocumentFields effect from collected template dicts."""
    return _build_prefill_effect(doc_id, templates, confidence)


def _get_template_models(template_type: str) -> tuple[Any, Any]:
    """Return (TemplateModel, FieldModel) pair based on template_type string."""
    return {
        "LabReportTemplate": (LabReportTemplate, LabReportTemplateField),
        "ImagingReportTemplate": (ImagingReportTemplate, ImagingReportTemplateField),
        "SpecialtyReportTemplate": (SpecialtyReportTemplate, SpecialtyReportTemplateField),
    }.get(template_type, (None, None))


def _extract_codes(template_type: str, extraction: DocumentExtraction) -> set[str]:
    """Extract matching codes (LOINC or SNOMED) based on template type."""
    if template_type == "LabReportTemplate":
        raw = extraction.loinc_codes
    else:
        raw = extraction.snomed_codes
    return {c.strip() for c in _to_list(raw) if _is_valid_code(c)}


def _extract_keywords(extraction: DocumentExtraction) -> list[str]:
    """Extract keywords from test/study names, modality, body part."""
    keywords: list[str] = []
    for val in [extraction.test_names, extraction.study_names, extraction.modality, extraction.body_part]:
        keywords.extend(_to_list(val))
    return [k.strip() for k in keywords if k and k.strip()]


def _score_candidates(
    field_model: Any,
    template_model: Any,
    codes: set[str],
    keywords: list[str],
    template_type: str,
) -> list[dict[str, Any]]:
    """Score templates by field code overlap with extracted codes (IDF-weighted)."""
    code_filter = "snomed" if template_type == "ImagingReportTemplate" else None

    queryset = field_model.objects.filter(code__in=codes)
    if code_filter:
        queryset = queryset.filter(code_system__icontains=code_filter)
    fields = list(queryset.select_related("report_template"))

    if not fields:
        return _keyword_fallback(template_model, keywords)

    code_templates = _build_code_template_map(fields)
    if not code_templates:
        return []

    weights = {code: 1.0 / len(tids) for code, tids in code_templates.items()}
    total_weight = sum(weights.values())

    scores: dict[int, float] = {}
    template_codes: dict[int, set[str]] = {}
    template_refs: dict[int, Any] = {}

    for f in fields:
        if f.code not in weights:
            continue
        tid = f.report_template_id
        scores[tid] = scores.get(tid, 0) + weights[f.code]
        template_codes.setdefault(tid, set()).add(f.code)
        template_refs.setdefault(tid, f.report_template)

    results = []
    for tid, score in scores.items():
        template = template_refs.get(tid)
        if not template:
            continue

        bonus = _keyword_bonus(template, keywords)
        final_score = min(1.0, (score / total_weight) + bonus)

        results.append({
            "id": tid,
            "name": template.name,
            "score": final_score,
            "codes": sorted(template_codes.get(tid, set())),
        })

    results.sort(key=lambda x: (x["score"], len(x["codes"])), reverse=True)
    return results


def _build_field_schema(
    fields: list[Any],
    preferred_codes: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build Extend AI extraction schema from a template's field definitions."""
    sorted_fields = sorted(
        fields,
        key=lambda f: (getattr(f, "code", None) not in preferred_codes, getattr(f, "sequence", 0)),
    )

    properties: dict[str, Any] = {}
    key_map: dict[str, Any] = {}

    for f in sorted_fields[:MAX_FIELDS]:
        key = _field_key(f)
        if not key or key in properties:
            continue

        label = getattr(f, "label", "") or key
        desc_parts: list[str] = []
        if code := getattr(f, "code", ""):
            desc_parts.append(f"code={code}")
        if units := getattr(f, "units", None):
            desc_parts.append(f"units={units}")
        desc = f"{label} ({'; '.join(desc_parts)})" if desc_parts else label

        properties[key] = {"type": ["string", "null"], "description": desc}
        key_map[key] = f

    return {
        "type": "EXTRACT",
        "baseProcessor": "extraction_performance",
        "baseVersion": "4.6.0",
        "schema": {"type": "object", "properties": properties},
        "advancedOptions": {"citationsEnabled": True},
    }, key_map


def _build_prefill_fields(
    extraction_data: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    key_map: dict[str, Any],
    fallback_confidence: float | None,
) -> dict[str, Any]:
    """Convert extraction to prefill format with value normalization."""
    if not extraction_data:
        return {}

    result: dict[str, Any] = {}
    for key, raw in extraction_data.items():
        value = _normalize_value(raw)
        if not value:
            continue

        field = key_map.get(key)
        payload: dict[str, Any] = {"value": value}

        if field and (units := getattr(field, "units", None)):
            payload["unit"] = units

        conf = None
        if isinstance(metadata, dict) and isinstance(metadata.get(key), dict):
            conf = metadata[key].get("ocrConfidence")
        conf = conf or fallback_confidence
        if conf is not None and 0 <= conf <= 1:
            payload["annotations"] = [{"text": f"AI {round(conf * 100)}%", "color": AnnotationColor.CONFIDENCE}]

        result[key] = payload

    return result


def _build_prefill_effect(
    doc_id: str,
    matched_templates: list[dict[str, Any]],
    confidence: float | None,
) -> Effect | None:
    """Construct and .apply() PrefillDocumentFields effect."""
    try:
        return PrefillDocumentFields(
            document_id=str(doc_id),
            templates=matched_templates,
            annotations=[],
            source_protocol=SOURCE_PROTOCOL,
        ).apply()
    except ValidationError as e:
        log.error("[PREFILL] Effect error: %s", e)
        return None


# --- Utility functions ---

def _is_valid_code(code: str) -> bool:
    """Check if code is valid (not N/A, empty, etc)."""
    if not code:
        return False
    stripped = code.strip().upper()
    return bool(stripped) and stripped not in {"N/A", "NA", "NONE"}


def _to_list(value: Any) -> list[str]:
    """Convert value to list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_to_list(item))
        return result
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[,;\n]+", value) if p.strip()]
    return [str(value)]


def _keyword_fallback(template_model: Any, keywords: list[str]) -> list[dict[str, Any]]:
    """Fallback to keyword search when no code matches."""
    if not keywords:
        return []
    results = template_model.objects.active().search(" ".join(keywords)).values_list("id", "name")[:3]
    return [{"id": tid, "name": name, "score": 0.1, "codes": []} for tid, name in results]


def _build_code_template_map(fields: list[Any]) -> dict[str, set[int]]:
    """Map codes to template IDs."""
    code_templates: dict[str, set[int]] = {}
    for f in fields:
        if f.code and _is_valid_code(f.code):
            code_templates.setdefault(f.code, set()).add(f.report_template_id)
    return code_templates


def _keyword_bonus(template: Any, keywords: list[str]) -> float:
    """Calculate keyword match bonus."""
    if not keywords:
        return 0.0
    haystack = f"{template.name} {getattr(template, 'search_keywords', '')}".lower()
    hits = sum(1 for kw in keywords if kw.lower() in haystack)
    return KEYWORD_BONUS * hits


def _field_key(field: Any) -> str | None:
    """Get unique key for field (by code or label)."""
    code = getattr(field, "code", None)
    if isinstance(code, str) and _is_valid_code(code):
        return code.strip()
    label = getattr(field, "label", None)
    if isinstance(label, str) and label.strip():
        return label.strip()
    return None


def _normalize_value(value: Any) -> str | None:
    """Normalize field value to string."""
    if value is None:
        return None
    if isinstance(value, list):
        parts = [_normalize_value(v) for v in value]
        filtered = [p for p in parts if p is not None]
        return ", ".join(filtered) if filtered else None
    if isinstance(value, dict) and "value" in value:
        return _normalize_value(value["value"])
    text = str(value).strip()
    return text if text else None
