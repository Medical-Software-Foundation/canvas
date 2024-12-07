import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log


class PriorAuthorization(BaseHandler):
    RESPONDS_TO = [
        EventType.Name(EventType.QUESTIONNAIRE_COMMAND__POST_UPDATE),
    ]

    def compute(self) -> list[Effect]:
        return []
