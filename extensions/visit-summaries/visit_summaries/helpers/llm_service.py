"""LLM client wrapper for visit-summaries plugin."""
from __future__ import annotations

import json
import re
from http import HTTPStatus
from typing import Any

from canvas_sdk.clients.llms import LlmAnthropic, LlmGoogle, LlmOpenai
from canvas_sdk.clients.llms.structures.settings import (
    LlmSettingsAnthropic,
    LlmSettingsGemini,
    LlmSettingsGpt4,
)
from logger import log

from visit_summaries.helpers.mock_llm import mock_avs, mock_previous_visit, mock_since_last_visit
from visit_summaries.helpers.summary_renderer import (
    render_avs,
    render_previous_visit,
    render_since_last_visit,
)


# ---------------------------------------------------------------------------
# JSON-based prompts. The LLM returns structured data, not HTML.
# ---------------------------------------------------------------------------

PREVIOUS_VISIT_SYSTEM_PROMPT = """You are a clinical documentation assistant.
You will receive structured data from a visit note. Return ONLY a valid JSON object (no markdown fences, no extra text).

Use this exact structure:

{
  "chief_complaint": "(restate the chief complaint in one clear clinical sentence, or empty string if none)",
  "diagnoses": ["(one entry per diagnosis, a brief clinical detail phrase like 'persistent for two weeks, worsening')"],
  "plan_items": ["(one entry per plan item, reworded concisely for a clinical summary)"]
}

Rules:
- The diagnoses array must have the same number of entries as the diagnoses in the input, in the same order
- Each diagnosis entry is ONLY the brief clinical detail, not the code or name (those are rendered separately)
- Do NOT repeat status tags like [UPDATED], [RESOLVED], [STOPPED], or [REFILL] in your text. Those are rendered separately.
- Keep plan items concise, one sentence each
- If no data exists for a field, use an empty string or empty array"""


SINCE_LAST_VISIT_SYSTEM_PROMPT = """You are a clinical documentation assistant.
You will receive structured interim clinical activity data. Return ONLY a valid JSON object (no markdown fences, no extra text).

Use this exact structure:

{
  "lab_interpretation": "(one sentence summarizing notable lab trends or findings, or empty string if no notable trends)"
}

Rules:
- Only provide interpretation if there are meaningful trends or abnormal values
- Keep it to one sentence
- If nothing notable, return an empty string"""


AVS_SYSTEM_PROMPT = """You are a patient communication specialist.
You will receive clinical visit data. Return ONLY a valid JSON object (no markdown fences, no extra text).
Write at a 6th-grade reading level using plain language. Use "you" and "your" language. Avoid medical jargon.

Use this exact structure:

{
  "discussion": "(2-3 sentences in plain, warm language explaining what was discussed during the visit)",
  "medications": ["(one entry per medication, rewrite the dose and instructions in simple everyday language)"],
  "next_steps": ["(one entry per plan item, rewritten as a clear action the patient should take)"],
  "warning_signs": ["(3-5 red-flag symptoms relevant to the diagnoses, in plain language a patient can understand)"]
}

Rules:
- The medications array must have the same number of entries as medications in the input, in the same order
- Each medication entry is ONLY the plain-language instructions, not the drug name (that is rendered separately)
- Warning signs must be relevant to the specific diagnoses, not generic
- Do not include HTML, markdown, or any formatting in the values"""


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract and parse JSON from LLM response, handling markdown fences."""
    text = raw.strip()
    match = _JSON_BLOCK_RE.search(text)
    if match:
        text = match.group(1).strip()
    result: dict[str, Any] = json.loads(text)
    return result


# ---------------------------------------------------------------------------
# Sanitizer (kept for legacy/fallback paths)
# ---------------------------------------------------------------------------

_BLOCK_TAG_RE = re.compile(
    r"<\s*(script|style)\b[^>]*>[\s\S]*?<\s*/\s*\1\s*>",
    re.IGNORECASE,
)
_DANGEROUS_TAG_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|form|base|link|meta|style)\b[^>]*>",
    re.IGNORECASE,
)
_EVENT_HANDLER_RE = re.compile(r"\s+on\w+\s*=\s*[\"'][^\"']*[\"']", re.IGNORECASE)
_JS_URL_RE = re.compile(r"(href|src|action)\s*=\s*[\"']\s*javascript:", re.IGNORECASE)


def sanitize_llm_html(html: str) -> str:
    """Remove dangerous HTML elements and attributes from LLM-generated content."""
    html = _BLOCK_TAG_RE.sub("", html)
    html = _DANGEROUS_TAG_RE.sub("", html)
    html = _EVENT_HANDLER_RE.sub("", html)
    html = _JS_URL_RE.sub(r'\1="', html)
    return html


# ---------------------------------------------------------------------------
# Provider utilities
# ---------------------------------------------------------------------------

def _is_mock_provider(secrets: dict[str, str]) -> bool:
    """Check if the mock provider is configured."""
    return (secrets.get("LLM_PROVIDER") or "").lower() == "mock"


_VALID_PROVIDERS = {"anthropic", "openai", "google"}


def validate_llm_secrets(secrets: dict[str, str]) -> list[str]:
    """Return a list of missing secret names required for LLM calls.

    LLM_API_KEY and LLM_PROVIDER are required. LLM_MODEL is optional
    because each provider SDK falls back to its own default.
    Mock mode skips API key validation.
    """
    if _is_mock_provider(secrets):
        return []

    missing: list[str] = []
    provider = (secrets.get("LLM_PROVIDER") or "").strip()
    api_key = (secrets.get("LLM_API_KEY") or "").strip()

    if not provider:
        missing.append("LLM_PROVIDER")
    elif provider.lower() not in _VALID_PROVIDERS:
        missing.append("LLM_PROVIDER")

    if not api_key:
        missing.append("LLM_API_KEY")

    return missing


def render_missing_config_html(missing_keys: list[str]) -> str:
    """Return a self-contained HTML warning listing which secrets are not configured."""
    items = "".join(
        f'<li style="margin-bottom:4px;"><strong>{key}</strong> is not set</li>'
        for key in missing_keys
    )
    return (
        '<div style="'
        "margin:24px auto;max-width:480px;padding:20px 24px;"
        "border:1px solid #f59e0b;border-radius:8px;"
        "background:#fffbeb;color:#92400e;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
        'font-size:14px;line-height:1.5;">'
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">'
        '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" style="flex-shrink:0;">'
        '<path d="M10 2L1 18h18L10 2z" fill="#f59e0b"/>'
        '<path d="M10 8v4M10 14h.01" stroke="#92400e" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>"
        '<strong style="font-size:15px;">Configuration Required</strong>'
        "</div>"
        f'<ul style="margin:0 0 12px 0;padding-left:20px;">{items}</ul>'
        '<p style="margin:0;font-size:13px;color:#a16207;">'
        "Set these values in the Canvas plugin secrets UI, then try again."
        "</p>"
        "</div>"
    )


_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5-20250929",
    "openai": "gpt-4o",
    "google": "models/gemini-2.0-flash",
}


def _build_client(secrets: dict[str, str]) -> Any:
    """Build the appropriate LLM client based on plugin secrets.

    Caller must run validate_llm_secrets() first. This function assumes
    LLM_PROVIDER and LLM_API_KEY are present.
    """
    provider = secrets["LLM_PROVIDER"].strip().lower()
    api_key = secrets.get("LLM_API_KEY") or ""
    model = (secrets.get("LLM_MODEL") or "").strip() or _DEFAULT_MODELS.get(provider, "")

    if provider == "openai":
        return LlmOpenai(LlmSettingsGpt4(api_key=api_key, model=model, temperature=0.3))

    if provider == "google":
        return LlmGoogle(LlmSettingsGemini(api_key=api_key, model=model, temperature=0.3))

    return LlmAnthropic(
        LlmSettingsAnthropic(api_key=api_key, model=model, temperature=0.3, max_tokens=4096)
    )


def _call_llm_json(client: Any, system_prompt: str, user_content: str, summary_type: str) -> dict:
    """Call the LLM and parse the JSON response. Returns empty dict on failure."""
    client.set_system_prompt([system_prompt])
    client.set_user_prompt([user_content])
    responses = client.attempt_requests(attempts=2)
    last = responses[-1]
    if last.code != HTTPStatus.OK:
        log.error(f"[visit_summaries] LLM error for {summary_type}: {last.response}")
        return {}
    try:
        return _parse_llm_json(last.response)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error(f"[visit_summaries] JSON parse error for {summary_type}: {exc}")
        log.error(f"[visit_summaries] Raw LLM response: {last.response[:500]}")
        return {}


# ---------------------------------------------------------------------------
# Public generate functions
# ---------------------------------------------------------------------------

def generate_previous_visit_summary(
    note_context: str,
    secrets: dict,
    chief_complaint: str = "",
    diagnoses: list[dict[str, str]] | None = None,
    medications: list[dict[str, str]] | None = None,
    plan_items: list[dict[str, str]] | None = None,
    vitals: dict[str, str | None] | None = None,
) -> str:
    """Generate previous visit summary: LLM provides phrasing, renderer builds HTML."""
    missing = validate_llm_secrets(secrets)
    if missing:
        return render_missing_config_html(missing)
    if _is_mock_provider(secrets):
        return mock_previous_visit(note_context)

    client = _build_client(secrets)
    llm_data = _call_llm_json(
        client,
        PREVIOUS_VISIT_SYSTEM_PROMPT,
        f"Visit note data:\n\n{note_context}",
        "previous_visit",
    )

    return render_previous_visit(
        llm_data=llm_data,
        chief_complaint=chief_complaint,
        diagnoses=diagnoses or [],
        medications=medications or [],
        plan_items=plan_items or [],
        vitals=vitals or {},
    )


def generate_since_last_visit_summary(
    interim_context: str,
    secrets: dict,
    lab_reports: list[dict] | None = None,
    medication_changes: dict[str, list] | None = None,
    condition_changes: dict[str, list] | None = None,
    completed_tasks: list[str] | None = None,
    other_encounters: list[str] | None = None,
) -> str:
    """Generate since-last-visit summary: LLM provides interpretation, renderer builds HTML."""
    missing = validate_llm_secrets(secrets)
    if missing:
        return render_missing_config_html(missing)
    if _is_mock_provider(secrets):
        return mock_since_last_visit(interim_context)

    client = _build_client(secrets)
    llm_data = _call_llm_json(
        client,
        SINCE_LAST_VISIT_SYSTEM_PROMPT,
        f"Interim clinical activity:\n\n{interim_context}",
        "since_last_visit",
    )

    return render_since_last_visit(
        llm_data=llm_data,
        lab_reports=lab_reports or [],
        medication_changes=medication_changes or {"new": [], "stopped": []},
        condition_changes=condition_changes or {"new": [], "resolved": []},
        completed_tasks=completed_tasks or [],
        other_encounters=other_encounters or [],
    )


def generate_avs(
    note_context: str,
    patient_info: dict,
    secrets: dict,
    medications: list[dict[str, str]] | None = None,
    plan_items: list[dict[str, str]] | None = None,
) -> str:
    """Generate After Visit Summary: LLM provides plain-language phrasing, renderer builds HTML."""
    missing = validate_llm_secrets(secrets)
    if missing:
        return render_missing_config_html(missing)
    if _is_mock_provider(secrets):
        return mock_avs(patient_info)

    client = _build_client(secrets)
    user_content = (
        f"Patient: {patient_info.get('first_name', 'Patient')} {patient_info.get('last_name', '')}\n"
        f"Provider: {patient_info.get('provider_name', 'Your Provider')}\n"
        f"Visit date: {patient_info.get('visit_date', 'today')}\n\n"
        f"Visit note data:\n{note_context}"
    )
    llm_data = _call_llm_json(client, AVS_SYSTEM_PROMPT, user_content, "avs")

    return render_avs(
        llm_data=llm_data,
        patient_info=patient_info,
        medications=medications or [],
        plan_items=plan_items or [],
    )
