"""Move a Cash Pay-labeled claim to the Cash Pay queue when it enters coding.

Canvas moves a claim into NeedsCodingReview when its note is signed. A note
marked before signing would otherwise land in coding like any other claim.
Listens only to CLAIM_QUEUE_MOVED (not CLAIM_UPDATED), and exits after one
indexed read for any claim that did not just enter the coding queue.
"""

from __future__ import annotations

from typing import ClassVar

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.claim import Claim
from logger import log

from mark_note_as_cash_pay.helpers.cash_pay import (
    CODING_QUEUE,
    build_route_effects,
    claim_has_label,
    config_problem,
    get_config,
)


class RouteLabeledClaims(BaseHandler):
    RESPONDS_TO: ClassVar[list[str]] = [EventType.Name(EventType.CLAIM_QUEUE_MOVED)]

    def compute(self) -> list[Effect]:
        cfg = get_config(self.secrets)
        if not cfg.enabled:
            return []
        claim = (
            Claim.objects.select_related("current_queue")
            .filter(id=self.event.target.id, current_queue__name=CODING_QUEUE)
            .first()
        )
        if claim is None or not claim_has_label(claim, cfg.label_name):
            return []
        problem = config_problem(cfg)
        if problem:
            # Leave the claim in coding where staff will see it; never create a queue.
            log.error(
                "[cash_pay] claim %s is labeled '%s' but was not moved: %s",
                claim.id,
                cfg.label_name,
                problem,
            )
            return []
        log.info("[cash_pay] routing claim %s to '%s'", claim.id, cfg.queue_name)
        return build_route_effects(claim, cfg)
