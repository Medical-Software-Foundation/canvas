import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log


class BenefitVerification(BaseHandler):
    RESPONDS_TO = [
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_UPDATE),
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_COMMIT),
        EventType.Name(EventType.COVERAGE_CREATED),
        EventType.Name(EventType.COVERAGE_UPDATED),
    ]

    def compute(self) -> list[Effect]:
        return []
