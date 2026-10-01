"""Builders shared by the failed-fax dashboard tests."""

from datetime import datetime, timedelta, timezone
from typing import Any

from canvas_sdk.test_utils.factories import (
    FaxFactory,
    StaffFactory,
    ImagingOrderActionEventFactory,
    IntegrationTaskActionEventFactory,
    LabOrderActionEventFactory,
    LetterActionEventFactory,
    NoteActionEventFactory,
    ReferralActionEventFactory,
)

from failed_fax_dashboard.models import FaxAlert
from failed_fax_dashboard.services.sources import SOURCES_BY_KEY
from failed_fax_dashboard.services.util import BOT_STAFF_ID, to_e164

FACTORIES: dict[str, Any] = {
    "note": NoteActionEventFactory,
    "referral": ReferralActionEventFactory,
    "imaging_order": ImagingOrderActionEventFactory,
    "lab_order": LabOrderActionEventFactory,
    "letter": LetterActionEventFactory,
    "integration_task": IntegrationTaskActionEventFactory,
}


def make_event(
    type_key: str = "note",
    *,
    delivered: bool | None = False,
    number: str = "+15555550100",
    event_type: str = "FAXED",
    age_days: float = 0,
    reason: str = "No answer",
    **kwargs: Any,
) -> Any:
    """Create an action event of the given item type with a Fax to ``number``."""
    fax = kwargs.pop("fax", None) or FaxFactory.create(to_fax_number=number)
    event = FACTORIES[type_key].create(
        delivered_by_fax=delivered,
        event_type=event_type,
        fax=fax,
        fax_result_msg=reason,
        **kwargs,
    )
    set_created(event, age_days)
    return event


def set_created(event: Any, age_days: float) -> None:
    """Backdate ``created`` (it is auto-set on insert)."""
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    type(event).objects.filter(pk=event.pk).update(created=created)
    event.refresh_from_db()


def make_staff(first_name: str = "Dana", last_name: str = "Whitfield", **kwargs: Any) -> Any:
    """A staff member with a login user (the action events' originator)."""
    return StaffFactory.create(first_name=first_name, last_name=last_name, **kwargs)


def make_bot() -> Any:
    """The Canvas Bot staff record."""
    return StaffFactory.create(id=BOT_STAFF_ID, first_name="Canvas", last_name="Bot")


def make_alert(
    event: Any,
    type_key: str,
    task: Any,
    *,
    last_handled: Any = None,
    **kwargs: Any,
) -> Any:
    """The alert row tying a failed item's task to the item and number."""
    spec = SOURCES_BY_KEY[type_key]
    item = getattr(event, spec.item_field)
    return FaxAlert.objects.create(
        source_type=type_key,
        item_id=str(item.id),
        fax_number=to_e164(event.fax.to_fax_number),
        task_id=str(task.id),
        last_handled_event_id=str((last_handled or event).id),
        last_handled_at=(last_handled or event).created,
        assignee=kwargs.pop("assignee", ""),
        **kwargs,
    )
