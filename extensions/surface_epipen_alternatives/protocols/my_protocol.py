import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from logger import log


class Protocol(BaseProtocol):

    RESPONDS_TO = EventType.Name(EventType.PRESCRIBE__PRESCRIBE__POST_SEARCH)

    def compute(self) -> list[Effect]:
        results = self.context.get("results")

        post_processed_results = []

        for result in results:
            preferred = False
            for coding in result.get("extra", {}).get("coding", []):
                if coding.get("code") == 576527 and coding.get("system") == "http://www.fdbhealth.com/":
                    preferred = True
                    result["annotations"] = ["Preferred"]
            if preferred:
                post_processed_results.insert(0, result)
            else:
                post_processed_results.append(result)

        return [
            Effect(type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS, payload=json.dumps(post_processed_results))
        ]
