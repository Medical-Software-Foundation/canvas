import json
import random

from canvas_sdk.events import EventType
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.protocols import BaseProtocol


class RandomDrugPriceAnnotationExample(BaseProtocol):
    RESPONDS_TO = EventType.Name(EventType.PRESCRIBE__PRESCRIBE__POST_SEARCH)

    def compute(self):
        results = self.context.get("results")

        if results is None:
            return [Effect(type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS, payload=json.dumps(None))]

        post_processed_results = []
        for result in results:
            price = 100 * random.random() * random.random()
            formatted_price = f"${price:.2f}"
            result["annotations"] = [formatted_price]
            post_processed_results.append(result)
        return [
            Effect(
                type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS,
                payload=json.dumps(post_processed_results),
            )
        ]
