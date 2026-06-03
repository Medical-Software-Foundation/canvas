from __future__ import annotations

from typing import Any

from chart_command_search.searchers.constants import (
    SKIP_DATA_KEYS,
    _CODE_IN_HEADING,
    _DETAIL_FIELDS,
    _HEADING_KEY,
    _MAX_HEADING_LEN,
)


def readable_value(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        if len(val) > 100 and " " not in val:
            return ""
        return val.strip()
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        texts = []
        for item in val:
            if isinstance(item, dict):
                text = str(
                    item.get("text", "")
                    or item.get("label", "")
                    or item.get("display", "")
                    or item.get("name", "")
                ).strip()
                if text:
                    texts.append(text)
            elif isinstance(item, str):
                texts.append(item.strip())
        return ", ".join(texts)
    if isinstance(val, dict):
        result = str(
            val.get("text", "")
            or val.get("label", "")
            or val.get("display", "")
            or val.get("name", "")
        ).strip()
        if result:
            return result
        return str(
            val.get("date", "") or val.get("input", "") or val.get("value", "")
        ).strip()
    return str(val).strip()


def extract_code(obj: dict) -> str:
    return str(obj.get("value", "") or obj.get("code", "")).strip()


def extract_command_heading(schema_key: str, data: dict | None) -> str:
    if not data:
        return ""

    if schema_key in ("plan", "hpi"):
        text = str(data.get("narrative", "")).strip()
        return (text[:_MAX_HEADING_LEN] + "...") if len(text) > _MAX_HEADING_LEN else text
    if schema_key == "reasonForVisit":
        coding = data.get("coding")
        if isinstance(coding, dict):
            text = str(coding.get("text", "") or coding.get("display", "")).strip()
            code = extract_code(coding)
            if text and code:
                return f"{text} \u00b7 {code}"
            if text:
                return text
        comment = str(data.get("comment", "")).strip()
        return (comment[:_MAX_HEADING_LEN] + "...") if len(comment) > _MAX_HEADING_LEN else comment
    if schema_key == "task":
        return str(data.get("title", "")).strip()

    _QUESTIONNAIRE_KEYS = ("ros", "exam", "questionnaire", "structuredAssessment")
    if schema_key in _QUESTIONNAIRE_KEYS:
        q = data.get("questionnaire")
        if isinstance(q, dict):
            return str(q.get("text", "") or q.get("extra", {}).get("name", "")).strip()
        return str(q or "").strip()

    if schema_key == "labOrder":
        tests = data.get("tests") or []
        if isinstance(tests, list):
            names = [
                str(t.get("text", ""))
                for t in tests
                if isinstance(t, dict) and t.get("text")
            ]
            return ", ".join(names)
        return ""

    nested_key = _HEADING_KEY.get(schema_key)
    if nested_key:
        obj = data.get(nested_key)
        if isinstance(obj, dict):
            text = str(
                obj.get("text", "") or obj.get("display", "") or obj.get("label", "")
            ).strip()
            if text and schema_key in _CODE_IN_HEADING:
                code = extract_code(obj)
                if code and code != text:
                    return f"{text} \u00b7 {code}"
            return text
        if isinstance(obj, str):
            return obj.strip()

    return ""


def extract_command_details(schema_key: str, data: dict) -> list[dict[str, str]]:
    if not data:
        return []

    _QUESTIONNAIRE_KEYS = ("ros", "exam", "questionnaire", "structuredAssessment")
    if schema_key in _QUESTIONNAIRE_KEYS:
        details: list[dict[str, str]] = []
        label_map: dict[str, str] = {}
        q = data.get("questionnaire")
        if isinstance(q, dict):
            questions = (q.get("extra") or {}).get("questions") or []
            for question in questions:
                if isinstance(question, dict):
                    pk = str(question.get("pk", ""))
                    label = str(question.get("label", "")).strip()
                    if pk and label:
                        label_map[pk] = label
        skip_prefix = ""
        question_prefix = ""
        for key in data:
            kl = key.lower()
            if kl.startswith("skip-") and not skip_prefix:
                skip_prefix = key[: len("skip-")]
            elif kl.startswith("question-") and not question_prefix:
                question_prefix = key[: len("question-")]
        if not skip_prefix:
            skip_prefix = "skip-"
        if not question_prefix:
            question_prefix = "question-"
        yes_codes: set[str] = set()
        for key, val in data.items():
            if key.startswith(skip_prefix) and str(val).strip().lower() == "yes":
                yes_codes.add(key[len(skip_prefix):])
        for key, val in data.items():
            if key.startswith(question_prefix):
                code = key[len(question_prefix):]
                if code in yes_codes:
                    val_str = str(val).strip()
                    if val_str:
                        label = label_map.get(code, "")
                        details.append({"label": label, "value": val_str})
        return details

    heading_key = _HEADING_KEY.get(schema_key)
    if schema_key in ("plan", "hpi"):
        heading_key = "narrative"
    elif schema_key == "reasonForVisit":
        heading_key = "coding"
    elif schema_key == "task":
        heading_key = "title"
    elif schema_key == "labOrder":
        heading_key = "tests"

    details: list[dict[str, str]] = []
    processed_keys: set[str] = set()

    field_order = _DETAIL_FIELDS.get(schema_key)
    if field_order:
        for data_key, label in field_order:
            if data_key == "$qty":
                processed_keys.add("quantity_to_dispense")
                processed_keys.add("type_to_dispense")
                qty = readable_value(data.get("quantity_to_dispense"))
                ttype = readable_value(data.get("type_to_dispense"))
                if qty and ttype:
                    details.append({"label": label, "value": f"{qty} {ttype}"})
                elif qty:
                    details.append({"label": label, "value": qty})
                continue
            processed_keys.add(data_key)
            if data_key == heading_key:
                continue
            val = data.get(data_key)
            val_str = readable_value(val)
            if val_str:
                details.append({"label": label, "value": val_str})

    for key, val in data.items():
        if key in processed_keys or key.lower() in SKIP_DATA_KEYS:
            continue
        if key == heading_key:
            continue
        label = key.replace("_", " ").title()
        val_str = readable_value(val)
        if val_str:
            details.append({"label": label, "value": val_str[:300]})

    return details
