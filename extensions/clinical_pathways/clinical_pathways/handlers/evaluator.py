"""Pathway runtime evaluator (v0.4).

Subscribes to `INTERVIEW_UPDATED` and advances any active `PathwayRun`
attached to the note the interview belongs to.

Step-by-step semantics:
- Each step in the pathway references one Canvas (questionnaire, question)
  pair. A step is "answered" once its questionnaire has been committed.
- The evaluator walks forward from `run.current_step_id` after each
  commit, consuming steps whose answers are now captured, routing per
  each step's rules / otherwise. It pauses when it hits a step whose
  questionnaire has not yet been inserted into the note (it inserts the
  questionnaire and waits for the next commit).
- Multiple consecutive steps that share a questionnaire are processed in
  a single commit — the runtime only inserts a new questionnaire when
  the next step actually requires one that isn't already in the note.

Pathway definition shape (v3):
    {
      "version": 3,
      "start_step_id": "s_...",
      "loaded_questionnaires": [{ "questionnaire_id", "questionnaire_name_snapshot" }],
      "steps": [
        { "step_id": "s_...",
          "questionnaire_id": "<uuid>",
          "question_id": "<uuid>",
          "rules": [
            { "rule_id": "r_...",
              "combinator": "all"|"any",
              "conditions": [{question_id, operator, value_*...}],
              "then": { "type": "step"|"recommendation", "target_id": "..." } }
          ],
          "otherwise": { "type": "step"|"recommendation", "target_id": "..." } | null }
      ],
      "recommendations": [
        { "recommendation_id", "name", "command_key", "params" }
      ]
    }

On-commit semantics: the evaluator gates on `interview.committer_id`
being set; in-progress edits are ignored.
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

    Keyed by the Question's UUID. `r.question_id` is the FK column (Question.dbid),
    so we resolve the related Question to obtain its UUID.
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
    qid = str(comp.get("question_id") or "")
    if not qid:
        return False
    op = comp.get("operator", "eq")
    bucket = captured.get(qid)
    if op == "any_answer":
        return bucket is not None and (bool(bucket.get("text")) or bool(bucket.get("option_ids")))
    if op == "no_answer":
        return bucket is None or (not bucket.get("text") and not bucket.get("option_ids"))
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
    conditions = rule.get("conditions") or []
    if not conditions:
        return False
    if rule.get("combinator", "all") == "any":
        return any(_evaluate_condition(c, captured) for c in conditions)
    return all(_evaluate_condition(c, captured) for c in conditions)


# ---------- Definition lookups ----------


def _find_step(definition: dict[str, Any], step_id: str) -> dict[str, Any] | None:
    if not step_id:
        return None
    for s in definition.get("steps") or []:
        if isinstance(s, dict) and s.get("step_id") == step_id:
            return s
    return None


def _find_recommendation(definition: dict[str, Any], rec_id: str) -> dict[str, Any] | None:
    if not rec_id:
        return None
    for r in definition.get("recommendations") or []:
        if isinstance(r, dict) and r.get("recommendation_id") == rec_id:
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
        log.warning("clinical_pathways: unknown recommendation command_key '%s'", cmd_key)
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


def _questionnaire_command(questionnaire_id: str, note_uuid: str) -> QuestionnaireCommand:
    cmd = QuestionnaireCommand()
    cmd.note_uuid = note_uuid
    cmd.command_uuid = str(uuid4())
    cmd.questionnaire_id = str(questionnaire_id)
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
        # `Note.id` is a UUID object; the QuestionnaireCommand and CustomCommand
        # fields are typed `str`, so stringify here so the downstream pydantic
        # validation accepts the value.
        note_uuid = str(note.id)

        runs = PathwayRun.objects.filter(note_uuid=note_uuid, status="active")
        if not runs.exists():
            return []

        new_captured = _collect_responses_for_interview(interview)
        interview_questionnaire_ids = {str(q.id) for q in interview.questionnaires.all()}

        # Coordinate concurrent workers handling the same event: build a
        # token unique to this interview-update (interview_id + modified
        # timestamp), then atomically claim it via UPDATE-where on each run.
        # Only the worker whose UPDATE changes a row proceeds; the others
        # skip. Re-edits of the same interview produce a new token via the
        # updated modified timestamp and re-trigger processing.
        event_token = str(interview_id)
        try:
            if interview.modified:
                event_token += ":" + interview.modified.isoformat()
        except Exception:
            pass

        effects: list[Effect] = []
        for run in runs:
            pathway = Pathway.objects.filter(dbid=run.pathway_id).first()
            if not pathway:
                continue
            definition = pathway.definition or {}
            if definition.get("version") != 3:
                log.info(
                    "clinical_pathways: skipping run %s — pathway %s uses pre-v3 definition",
                    run.dbid,
                    pathway.dbid,
                )
                continue

            prior_token = run.last_processed_event_token or ""
            if prior_token == event_token:
                # We already processed this exact event for this run.
                continue
            updated_rows = PathwayRun.objects.filter(
                dbid=run.dbid,
                last_processed_event_token=prior_token,
            ).update(last_processed_event_token=event_token)
            if updated_rows == 0:
                # Another worker claimed this event first.
                log.info(
                    "clinical_pathways: run %s skipped — event %s claimed by another worker",
                    run.dbid,
                    event_token,
                )
                continue
            # We won the race; refresh our in-memory copy so subsequent
            # field updates (current_step_id, inserted_questionnaires, ...)
            # save on top of the claimed token.
            run.last_processed_event_token = event_token

            # Merge this interview's responses into the run's accumulator.
            merged = dict(run.captured_responses or {})
            merged.update(new_captured)
            run.captured_responses = merged

            inserted = list(run.inserted_questionnaires or [])
            committed = set(run.committed_questionnaires or [])
            # Anything the user just committed counts as fully-committed
            # going forward, even if specific questions were left blank.
            committed.update(interview_questionnaire_ids)
            current_step_id = run.current_step_id or definition.get("start_step_id")
            run_effects = self._advance(
                run,
                pathway,
                definition,
                current_step_id,
                merged,
                interview_questionnaire_ids,
                committed,
                inserted,
                note_uuid,
            )
            run.inserted_questionnaires = inserted
            run.committed_questionnaires = sorted(committed)
            run.save()
            effects.extend(run_effects)

        return effects

    def _advance(
        self,
        run: PathwayRun,
        pathway: Pathway,
        definition: dict[str, Any],
        start_step_id: str | None,
        merged: dict[str, dict[str, Any]],
        committed_this_event_ids: set[str],
        committed_ever: set[str],
        inserted: list[str],
        note_uuid: str,
    ) -> list[Effect]:
        """Walk forward through the step list, emitting effects for each
        questionnaire to insert and for any recommendation reached. Mutates
        `run.current_step_id`, `run.status`, and `inserted`.
        """
        effects: list[Effect] = []
        current_step_id: str | None = start_step_id
        safety_counter = 0
        while True:
            safety_counter += 1
            if safety_counter > 256:
                log.warning(
                    "clinical_pathways: evaluator advance loop guard tripped on run %s",
                    run.dbid,
                )
                run.status = "completed"
                return effects

            if not current_step_id:
                run.current_step_id = ""
                run.status = "completed"
                return effects

            step = _find_step(definition, current_step_id)
            if not step:
                # Walk fell off the end; nothing to do.
                run.current_step_id = ""
                run.status = "completed"
                return effects

            questionnaire_id = str(step.get("questionnaire_id") or "")
            question_id = str(step.get("question_id") or "")
            if not questionnaire_id or not question_id:
                # Malformed step — stop here rather than thrash.
                run.current_step_id = step.get("step_id", "")
                run.status = "completed"
                return effects

            answered = question_id in merged
            committed_ever_q = questionnaire_id in committed_ever
            already_inserted = questionnaire_id in inserted

            if not answered and not committed_ever_q:
                # The step's questionnaire has never been committed. Insert
                # it (if not already in the note) and wait for the user.
                run.current_step_id = step.get("step_id", "")
                if not already_inserted:
                    effects.append(
                        BatchOriginateCommandEffect(
                            commands=[_questionnaire_command(questionnaire_id, note_uuid)]
                        ).apply()
                    )
                    inserted.append(questionnaire_id)
                return effects

            # The questionnaire has been committed at some point.
            # Treat the step's question as "answered" (possibly blank).
            matched_rule: dict[str, Any] | None = None
            for rule in step.get("rules") or []:
                if _evaluate_rule(rule, merged):
                    matched_rule = rule
                    break

            target: dict[str, Any] | None
            if matched_rule is not None:
                target = matched_rule.get("then")
            else:
                target = step.get("otherwise")

            if not target or not isinstance(target, dict):
                run.current_step_id = step.get("step_id", "")
                run.status = "completed"
                return effects

            target_type = target.get("type")
            target_id = target.get("target_id")
            if target_type == "recommendation":
                rec = _find_recommendation(definition, target_id)
                if rec is None:
                    log.warning(
                        "clinical_pathways: missing recommendation %s referenced by step %s",
                        target_id,
                        step.get("step_id"),
                    )
                    run.current_step_id = step.get("step_id", "")
                    run.status = "completed"
                    return effects
                cmd = _recommendation_command(rec, pathway, note_uuid, merged)
                if cmd is None:
                    run.current_step_id = step.get("step_id", "")
                    run.status = "completed"
                    return effects
                # CustomCommand uses its own `.originate()` effect rather
                # than BatchOriginateCommandEffect (the docs example for
                # CustomCommand shows it that way, and we hit a frontend
                # render crash when batching a CustomCommand alongside the
                # other SDK command types).
                effects.append(cmd.originate())
                run.current_step_id = step.get("step_id", "")
                run.status = "completed"
                return effects

            if target_type == "step":
                if not _find_step(definition, target_id):
                    log.warning(
                        "clinical_pathways: missing step %s referenced by step %s",
                        target_id,
                        step.get("step_id"),
                    )
                    run.current_step_id = step.get("step_id", "")
                    run.status = "completed"
                    return effects
                current_step_id = target_id
                continue

            # Unknown target type — terminate to avoid looping.
            log.warning(
                "clinical_pathways: unknown target type '%s' on step %s",
                target_type,
                step.get("step_id"),
            )
            run.current_step_id = step.get("step_id", "")
            run.status = "completed"
            return effects
