"""Limit the booking window's provider list to the restricted staff member themselves.

Canvas sends the provider list as [{"text", "value", "selected"}], where value is
the staff key. Unrestricted staff, or BOOK_ONLY_SELF set to no, get the list unchanged.
"""

import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from my_schedule.handlers.access import is_restricted, parse_flag, staff_by_user_dbid


class BookOnlySelf(BaseHandler):
    """Restricted staff can only pick themselves as the provider."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT__FORM__PROVIDERS__POST_SEARCH)

    def compute(self) -> list[Effect]:
        if not parse_flag(self.secrets.get("BOOK_ONLY_SELF"), default=True):
            return []
        staff = staff_by_user_dbid(self.event.actor.id)
        if not is_restricted(staff, self.secrets):
            return []
        own_key = str(staff.id)
        providers = self.event.context.get("providers") or []
        own = [p for p in providers if str(p.get("value")) == own_key]
        return [
            Effect(
                type=EffectType.APPOINTMENT__FORM__PROVIDERS__POST_SEARCH_RESULTS,
                payload=json.dumps({"providers": own}),
            )
        ]
