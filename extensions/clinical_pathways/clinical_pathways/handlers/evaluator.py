"""Pathway runtime evaluator.

Subscribes to `INTERVIEW_UPDATED` and advances any active `PathwayRun` for
the note the interview belongs to. When the run's current questionnaire is
committed, evaluates the active node's rules against the captured
responses, and emits the next questionnaire — or the recommendation
custom command — via `BatchOriginateCommandEffect`.

Pathway definition shape (v2):
    {
      "version": 2,
      "start_node_id": "n_...",
      "nodes": [
        { "node_id": "n_...", "questionnaire_id": "<uuid>",
          "rules": [
            { "rule_id": "r_...", "combinator": "all"|"any",
              "conditions": [
                { "question_id": "<uuid>", "operator": "eq"|"neq"|...,
                  "value_option_id": ?, "value_option_ids": [?],
                  "value_text": ?, "value_number": ? }
              ],
              "then": { "type": "node"|"recommendation", "target_id": "..." }
            }
          ] }
      ],
      "recommendations": [
        { "recommendation_id": "rec_...", "name": "...",
          "command_key": "pathway_classification",
          "params": { title, severity, body, recommended_action } }
      ]
    }

On-commit semantics: the evaluator gates strictly on
`interview.committer_id` being set; events during in-progress edits are
ignored.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import Interview
from logger import log

from clinical_pathways.models import Pathway, PathwayRun
from clinical_pathways.terminal_commands import TERMINAL_COMMANDS


# ---------- Captured responses ----------


def _collect_responses_for_interview(interview: Interview) -> dict[str, dict[str, Any]]:
    """Return {question_uuid_str: {"text": str, "option_ids": [dbid_str], "values": [str]}}.

    Keyed by the Question's UUID to match the builder's storage. `r.question_id`
    on the response is the FK column value (Question.dbid), so we resolve the
    related Question instance to obtain its UUID.
    """
    responses: dict[str, dict[str, Any]] = {}
    for r in interview.interview_responses.all():
        if not r.question_id:
            continue
        try:
            question_uuid = str(r.question.id) if r.question else None
        except Exception:
            question_uuid = None
        if not question_uuid:
            continue
        bucket = responses.setdefault(
            question_uuid,
            {"text": "", "option_ids": [], "values": []},
        )
        if r.response_option_id:
            bucket["option_ids"].append(str(r.response_option_id))
        if r.response_option_value:
            bucket["values"].append(r.response_option_value)
            if not bucket["text"]:
                bucket["text"] = r.response_option_value
    return responses


# ---------- Condition evaluation ----------


def _op_eq(answer: Any, expected: Any) -> bool:
    return str(answer or "").strip().lower() == str(expected or "").strip().lower()


def _op_contains(answer: Any, expected: Any) -> bool:
    return str(expected or "").strip().lower() in str(answer or "").strip().lower()


def _op_num(answer: Any, expected: Any, cmp: str) -> bool:
    try:
        a = float(answer)
        e = float(expected)
    except (TypeError, ValueError):
        return False
    return {
        "lt": a < e,
        "lte": a <= e,
        "gt": a > e,
        "gte": a >= e,
    }.get(cmp, False)


def _set_overlap(actuals: list[str], expected: list[str]) -> bool:
    a = {str(x).strip().lower() for x in actuals or []}
    e = {str(x).strip().lower() for x in expected or []}
    return bool(a & e)


def _set_superset(actuals: list[str], expected: list[str]) -> bool:
    a = {str(x).strip().lower() for x in actuals or []}
    e = {str(x).strip().lower() for x in expected or []}
    return e.issubset(a)


def _evaluate_condition(comp: dict[str, Any], captured: dict[str, dict[str, Any]]) -> bool:
    """Evaluate a single condition against the captured responses."""
    qid = str(comp.get("question_id") or "")
    if not qid:
        return False
    op = comp.get("operator", "eq")
    bucket = captured.get(qid)
    if op == "any_answer":
        return bucket is not None and (
            bool(bucket.get("text")) or bool(bucket.get("option_ids"))
        )
    if op == "no_answer":
        return bucket is None or (
            not bucket.get("text") and not bucket.get("option_ids")
        )
    if bucket is None:
        return False

    if op in ("contains_any", "contains_all", "contains_none"):
        expected = comp.get("value_option_ids") or []
        if not expected and comp.get("value_option_id"):
            expected = [comp["value_option_id"]]
        actuals = bucket.get("option_ids", [])
        if op == "contains_any":
            return _set_overlap(actuals, expected)
        if op == "contains_all":
            return _set_superset(actuals, expected)
        return not _set_overlap(actuals, expected)

    answer_text = bucket.get("text", "")
    if op == "eq":
        if comp.get("value_option_id"):
            return comp["value_option_id"] in bucket.get("option_ids", [])
        return _op_eq(answer_text, comp.get("value_text"))
    if op == "neq":
        if comp.get("value_option_id"):
            return comp["value_option_id"] not in bucket.get("option_ids", [])
        return not _op_eq(answer_text, comp.get("value_text"))
    if op == "contains":
        return _op_contains(answer_text, comp.get("value_text"))
    if op in ("lt", "lte", "gt", "gte"):
        return _op_num(answer_text, comp.get("value_number"), op)
    return False


def _evaluate_rule(rule: dict[str, Any], captured: dict[str, dict[str, Any]]) -> bool:
    """Evaluate a single rule's flat conditions list under the rule's combinator."""
    conditions = rule.get("conditions") or []
    if not conditions:
        return False
    combinator = rule.get("combinator", "all")
    if combinator == "any":
        return any(_evaluate_condition(c, captured) for c in conditions)
    # default: all
    return all(_evaluate_condition(c, captured) for c in conditions)


# ---------- Definition lookups ----------


def _find_node(definition: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    if not node_id:
        return None
    for n in definition.get("nodes") or []:
        if isinstance(n, dict) and n.get("node_id") == node_id:
            return n
    return None


def _find_recommendation(
    definition: dict[str, Any], recommendation_id: str
) -> dict[str, Any] | None:
    if not recommendation_id:
        return None
    for r in definition.get("recommendations") or []:
        if isinstance(r, dict) and r.get("recommendation_id") == recommendation_id:
            return r
    return None


# ---------- Templating ----------

_TEMPLATE_REF = re.compile(r"\{\{\s*([^}|]+?)\s*\}\}")


def _resolve_template(value: Any, captured: dict[str, dict[str, Any]]) -> str:
    if not isinstance(value, str):
        return "" if value is None else str(value)

    def _replace(match: re.Match[str]) -> str:
        question_id = match.group(1).strip()
        bucket = captured.get(question_id)
        if not bucket:
            return ""
        if bucket.get("text"):
            return bucket["text"]
        return ", ".join(bucket.get("values", []) or [])

    return _TEMPLATE_REF.sub(_replace, value)


def _severity_label(spec: dict[str, Any], severity_value: str) -> str:
    for field in spec.get("fields", []):
        if field.get("key") != "severity":
            continue
        for opt in field.get("options", []) or []:
            if opt.get("value") == severity_value:
                return opt.get("label", "")
    return severity_value.title() if severity_value else ""


# ---------- Command construction ----------


def _recommendation_command(
    recommendation: dict[str, Any],
    pathway: Pathway,
    note_uuid: str,
    captured: dict[str, dict[str, Any]],
) -> CustomCommand | None:
    cmd_key = recommendation.get("command_key") or ""
    spec = TERMINAL_COMMANDS.get(cmd_key)
    if not spec:
        log.warning(
            "clinical_pathways: unknown recommendation command_key '%s'", cmd_key
        )
        return None
    params = recommendation.get("params") or {}
    resolved: dict[str, Any] = {}
    for field in spec.get("fields", []):
        key = field["key"]
        resolved[key] = _resolve_template(params.get(key, ""), captured)

    template_context = {
        "pathway_title": pathway.title,
        "recommendation_name": recommendation.get("name", ""),
        "title": resolved.get("title", ""),
        "severity": resolved.get("severity", ""),
        "severity_label": _severity_label(spec, resolved.get("severity", "")),
        "body": resolved.get("body", ""),
        "recommended_action": resolved.get("recommended_action", ""),
    }
    html = render_to_string("templates/pathway_classification.html", template_context)
    print_html = render_to_string(
        "templates/pathway_classification_print.html", template_context
    )

    cmd = CustomCommand(
        schema_key=spec.get("schema_key", "pathwayClassification"),
        content=html,
        print_content=print_html,
    )
    cmd.command_uuid = str(uuid4())
    cmd.note_uuid = note_uuid
    return cmd


def _questionnaire_command(target_node: dict[str, Any], note_uuid: str) -> QuestionnaireCommand | None:
    qid = target_node.get("questionnaire_id")
    if not qid:
        return None
    cmd = QuestionnaireCommand()
    cmd.note_uuid = note_uuid
    cmd.command_uuid = str(uuid4())
    cmd.questionnaire_id = str(qid)
    return cmd


# ---------- Handler ----------


class PathwayEvaluator(BaseHandler):
    """Advances active pathway runs each time an interview is committed."""

    RESPONDS_TO = EventType.Name(EventType.INTERVIEW_UPDATED)

    def compute(self) -> list[Effect]:
        interview_id = self.event.target.id if self.event and self.event.target else None
        if not interview_id:
            return []
        interview = Interview.objects.filter(id=interview_id).first()
        if not interview:
            return []
        if not interview.committer_id or interview.entered_in_error_id:
            return []

        note_id = interview.note_id
        if not note_id:
            return []
        note = Note.objects.filter(dbid=note_id).first()
        if not note:
            return []
        note_uuid = note.id

        runs = PathwayRun.objects.filter(note_uuid=note_uuid, status="active")
        if not runs.exists():
            return []

        captured = _collect_responses_for_interview(interview)
        interview_questionnaire_ids = {
            str(q.id) for q in interview.questionnaires.all()
        }

        effects: list[Effect] = []
        for run in runs:
            pathway = Pathway.objects.filter(dbid=run.pathway_id).first()
            if not pathway:
                continue
            definition = pathway.definition or {}
            if definition.get("version") != 2:
                log.info(
                    "clinical_pathways: skipping run %s — pathway %s uses an "
                    "unsupported (pre-v2) definition format",
                    run.dbid,
                    pathway.dbid,
                )
                continue

            current_node = _find_node(definition, run.current_node_id)
            if not current_node:
                continue
            node_questionnaire_id = str(current_node.get("questionnaire_id") or "")
            if node_questionnaire_id not in interview_questionnaire_ids:
                # The interview that committed wasn't the one this run was
                # waiting on — ignore and let other runs handle it.
                continue

            merged = dict(run.captured_responses or {})
            merged.update(captured)
            run.captured_responses = merged

            # First-match rule evaluation.
            matched_rule: dict[str, Any] | None = None
            for rule in current_node.get("rules") or []:
                if _evaluate_rule(rule, merged):
                    matched_rule = rule
                    break

            if matched_rule is None:
                log.info(
                    "clinical_pathways: no rule matched for node %s in pathway %s",
                    run.current_node_id,
                    pathway.dbid,
                )
                run.status = "completed"
                run.save()
                continue

            then = matched_rule.get("then") or {}
            target_type = then.get("type")
            target_id = then.get("target_id")
            new_command: Any = None
            advance_to_node_id: str | None = None
            mark_completed = False

            if target_type == "node":
                target_node = _find_node(definition, target_id)
                if not target_node:
                    log.warning(
                        "clinical_pathways: rule %s points to missing node %s",
                        matched_rule.get("rule_id"),
                        target_id,
                    )
                    run.status = "completed"
                    run.save()
                    continue
                new_command = _questionnaire_command(target_node, note_uuid)
                advance_to_node_id = target_id
            elif target_type == "recommendation":
                recommendation = _find_recommendation(definition, target_id)
                if not recommendation:
                    log.warning(
                        "clinical_pathways: rule %s points to missing recommendation %s",
                        matched_rule.get("rule_id"),
                        target_id,
                    )
                    run.status = "completed"
                    run.save()
                    continue
                new_command = _recommendation_command(
                    recommendation, pathway, note_uuid, merged
                )
                mark_completed = True
            else:
                log.warning(
                    "clinical_pathways: rule %s has invalid then.type '%s'",
                    matched_rule.get("rule_id"),
                    target_type,
                )
                run.save()
                continue

            if new_command is None:
                run.save()
                continue
            effects.append(BatchOriginateCommandEffect(commands=[new_command]).apply())
            if mark_completed:
                run.status = "completed"
            if advance_to_node_id:
                run.current_node_id = advance_to_node_id
            run.save()

        return effects
