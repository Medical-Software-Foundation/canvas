"""Builders shared by the failed-fax dashboard tests."""

from datetime import datetime, timedelta, timezone
from typing import Any

from canvas_sdk.test_utils.factories import (
    FaxFactory,
    ImagingOrderActionEventFactory,
    IntegrationTaskActionEventFactory,
    LabOrderActionEventFactory,
    LetterActionEventFactory,
    NoteActionEventFactory,
    ReferralActionEventFactory,
)

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
