"""Note-header dropdown items: Mark as cash pay / Unmark as cash pay.

Two buttons because BUTTON_TITLE is static. Only one is visible at a time,
based on whether the note's claim already carries the Cash Pay label. Neither
is visible unless the plugin is enabled.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from logger import log

from mark_note_as_cash_pay.helpers.cash_pay import (
    actor_name,
    build_mark_effects,
    build_unmark_effects,
    claim_for_note,
    claim_has_label,
    config_problem,
    error_modal,
    get_config,
    note_from_context,
    note_is_billable,
)


class _CashPayButton(ActionButton):
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER_DROPDOWN
    PRIORITY = 10
    SHOW_WHEN_LABELED: bool

    def visible(self) -> bool:
        cfg = get_config(self.secrets)
        if not cfg.enabled:
            return False
        note = note_from_context(self.event.context)
        if note is None or not note_is_billable(note):
            return False
        claim = claim_for_note(note)
        if claim is None:
            return False
        return claim_has_label(claim, cfg.label_name) == self.SHOW_WHEN_LABELED

    def handle(self) -> list[Effect]:
        cfg = get_config(self.secrets)
        if not cfg.enabled:
            log.warning("[cash_pay] click ignored: %s is off", "CASH_PAY_ENABLED")
            return []
        problem = config_problem(cfg)
        if problem:
            log.error("[cash_pay] not configured: %s", problem)
            return [error_modal(problem)]
        note = note_from_context(self.event.context)
        claim = claim_for_note(note) if note else None
        if claim is None:
            message = "This note has no claim yet, so there is nothing to mark."
            log.warning("[cash_pay] %s", message)
            return [error_modal(message)]
        who = actor_name(self.event.context)
        if who is None:
            message = (
                "Could not tell which staff member clicked, so nothing was recorded."
            )
            log.warning("[cash_pay] click refused: no staff member on the event")
            return [error_modal(message)]
        return self.build(claim, cfg, who)

    def build(self, claim, cfg, who) -> list[Effect]:  # type: ignore[no-untyped-def]
        raise NotImplementedError


class MarkAsCashPayButton(_CashPayButton):
    """Shown on billable notes whose claim is not labeled Cash Pay."""

    BUTTON_TITLE = "Mark as cash pay"
    BUTTON_KEY = "MARK_AS_CASH_PAY"
    SHOW_WHEN_LABELED = False

    def build(self, claim, cfg, who) -> list[Effect]:  # type: ignore[no-untyped-def]
        return build_mark_effects(claim, cfg, who)


class UnmarkCashPayButton(_CashPayButton):
    """Shown on billable notes whose claim is labeled Cash Pay."""

    BUTTON_TITLE = "Unmark as cash pay"
    BUTTON_KEY = "UNMARK_AS_CASH_PAY"
    SHOW_WHEN_LABELED = True

    def build(self, claim, cfg, who) -> list[Effect]:  # type: ignore[no-untyped-def]
        return build_unmark_effects(claim, cfg, who)
