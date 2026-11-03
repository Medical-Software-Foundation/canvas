"""Originate a follow-up questionnaire when a screener crosses its threshold."""

from __future__ import annotations

from datetime import timedelta

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.questionnaire_result import CreateQuestionnaireResult
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Note
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.questionnaire import Interview, Questionnaire
from django.db.models import Q
from django.utils import timezone
from logger import log

from screening_cascade.config import Coding, Rule, RulesError, is_enabled, load_rules
from screening_cascade.scoring import narrative, passes, total_score

# Typed or dated answers carry no score.
UNSCORED_TYPES = ("TXT", "DATE")


def _norm_staff_id(value: object) -> str:
    return str(value or "").replace("-", "").lower()


class ScreeningCascade(BaseHandler):
    """On a committed screener: score it, and originate the follow-up if positive."""

    RESPONDS_TO = EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT)

    def compute(self) -> list[Effect]:
        """Apply every rule whose trigger matches the committed questionnaire."""
        if not is_enabled(self.secrets):
            return []
        try:
            rules = load_rules(self.secrets)
        except RulesError as exc:
            # Fail closed: a broken override must not fall back to the defaults.
            log.error(f"screening_cascade: rules not loaded, doing nothing: {exc}")
            return []

        try:
            command = Command.objects.get(id=self.event.target.id)
        except Command.DoesNotExist:
            return []
        interview = command.anchor_object
        if interview is None or not interview.committer_id or interview.entered_in_error_id:
            return []

        questionnaire = interview.questionnaires.first()
        if questionnaire is None:
            return []
        matching = [
            r for r in rules if r.trigger.matches(questionnaire.code_system, questionnaire.code)
        ]
        if not matching:
            return []

        score = self._score(interview, questionnaire)
        if score is None:
            log.info(
                f"screening_cascade: {questionnaire.code} not fully answered or not numeric; "
                "no score, no follow-up"
            )
            return []

        note_uuid = (self.event.context.get("note") or {}).get("uuid")
        effects: list[Effect] = []
        originated: set[Coding] = set()
        scored: set[Coding] = set()
        provider_id: str | None = None
        provider_loaded = False

        for rule in matching:
            if rule.result is not None and rule.result not in scored:
                # One result per coding: two rules on the same trigger must not
                # write the same score twice.
                scored.add(rule.result)
                effects.extend(self._result_effects(rule, interview, questionnaire, score))

            if not rule.has_follow_up or not passes(rule, score):
                continue
            if not note_uuid:
                log.warning(f"screening_cascade: {rule.name}: event has no note; cannot originate")
                continue
            if rule.follow_up_by_staff and not provider_loaded:
                provider_id = self._note_provider_id(note_uuid)
                provider_loaded = True
            follow_up = self._preferred_follow_up(rule, provider_id)
            if follow_up is None or follow_up in originated:
                continue

            target = (
                Questionnaire.objects.filter(
                    code_system=follow_up.code_system,
                    code=follow_up.code,
                    can_originate_in_charting=True,
                    status="AC",
                )
                .order_by("-dbid")
                .first()
            )
            if target is None:
                log.warning(
                    f"screening_cascade: {rule.name}: no active questionnaire "
                    f"{follow_up.code_system}|{follow_up.code} that can originate in charting"
                )
                continue
            if self._recently_given(interview, follow_up, rule.cooldown_days):
                log.info(
                    f"screening_cascade: {rule.name}: patient had {follow_up.code} on this note "
                    f"or in the last {rule.cooldown_days} days; not originating"
                )
                continue

            originated.add(follow_up)
            log.info(f"screening_cascade: {rule.name}: score {score}, originating {target.name}")
            effects.append(
                QuestionnaireCommand(
                    note_uuid=note_uuid, questionnaire_id=str(target.id)
                ).originate()
            )
        return effects

    def _score(self, interview: Interview, questionnaire: Questionnaire) -> float | None:
        scorable = set(
            questionnaire.questions.exclude(
                response_option_set__type__in=UNSCORED_TYPES
            ).values_list("dbid", flat=True)
        )
        answers = interview.interview_responses.filter(questionnaire=questionnaire).values_list(
            "question__dbid", "response_option__value"
        )
        return total_score(answers, scorable)

    def _result_effects(
        self, rule: Rule, interview: Interview, questionnaire: Questionnaire, score: float
    ) -> list[Effect]:
        if rule.result is None:
            return []
        if questionnaire.scoring_function_name:
            # Canvas already scores this questionnaire; a second result would
            # show two scores on the command and double-count in trends.
            return []
        abnormal = passes(rule, score) if rule.has_follow_up else False
        return [
            CreateQuestionnaireResult(
                interview_id=str(interview.id),
                score=score,
                abnormal=abnormal,
                narrative=narrative(rule, score),
                code_system=rule.result.code_system,
                code=rule.result.code,
            ).apply()
        ]

    def _note_provider_id(self, note_uuid: str) -> str | None:
        provider = Note.objects.filter(id=note_uuid).values_list("provider__id", flat=True).first()
        return str(provider) if provider else None

    @staticmethod
    def _preferred_follow_up(rule: Rule, provider_id: str | None) -> Coding | None:
        wanted = _norm_staff_id(provider_id)
        if wanted:
            for staff_id, coding in rule.follow_up_by_staff.items():
                if _norm_staff_id(staff_id) == wanted:
                    return coding
        return rule.follow_up

    @staticmethod
    def _recently_given(interview: Interview, follow_up: Coding, cooldown_days: int) -> bool:
        """Has the patient got this follow-up on this note, or within the window?

        Counts uncommitted ones too, so a second commit of the same screener
        does not stack a second copy on the note.
        """
        window = Q(note_id=interview.note_id)
        if cooldown_days > 0:
            window |= Q(created__gte=timezone.now() - timedelta(days=cooldown_days))
        return (
            Interview.objects.filter(
                patient_id=interview.patient_id,
                questionnaires__code_system=follow_up.code_system,
                questionnaires__code=follow_up.code,
                entered_in_error__isnull=True,
                deleted=False,
            )
            .filter(window)
            .exclude(id=interview.id)
            .exists()
        )
