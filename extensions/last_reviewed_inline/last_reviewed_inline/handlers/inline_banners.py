"""Inline 'last reviewed' banners for the Conditions and Medications sections.

Both handlers respond to the per-section chart events
(PATIENT_CHART__CONDITIONS, PATIENT_CHART__MEDICATIONS) and emit a
PatientChartGroup whose single Group carries the review summary as its
name. The empty `items` list is intentional: we are using the group as a
section-level label, not as a real item bucket.

Only Conditions and Medications are reachable through the SDK's per-section
events. The other four chart sections that support 'Mark as reviewed'
(Allergies, Immunizations, Surgical History, Family History) are covered
by the sibling plugin `last_reviewed`, which uses the chart-summary custom
section effect.
"""

import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.effects.group import Group
from canvas_sdk.effects.patient_chart_group import PatientChartGroup
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import NoteStates


# Pinning the banner above any sibling grouping plugin's contributions
# (e.g. high-risk-medications uses priority=1000). The renderer orders
# groups by descending priority within a section, so a higher number wins
# the top slot.
_BANNER_PRIORITY = 10_000


def _committer_name(user) -> str | None:
    if user is None or not user.is_staff:
        return None
    try:
        staff = user.staff
    except Exception:
        return None
    if staff is None:
        return None
    name = f"{staff.first_name} {staff.last_name}".strip()
    return name or None


def _latest_review(patient_id: str, section_value: str) -> Command | None:
    """Return the most recent in-effect chartSectionReview for the section.

    Excludes commands attached to a deleted note -- that's how Canvas's
    "delete review" workflow takes a review out of effect (see the sibling
    plugin's README for the full discussion).
    """
    return (
        Command.objects.filter(
            patient__id=patient_id,
            schema_key="chartSectionReview",
            state="committed",
            entered_in_error__isnull=True,
            data__section=section_value,
        )
        .exclude(note__current_state__state=NoteStates.DELETED)
        .select_related("committer")
        .order_by("-created")
        .first()
    )


def _banner_text(command: Command | None) -> str:
    if command is None:
        return "Never reviewed"
    relative = arrow.get(command.created).humanize()
    name = _committer_name(command.committer)
    if name:
        return f"Last reviewed {relative} by {name}"
    return f"Last reviewed {relative}"


class _InlineLastReviewedBase(BaseHandler):
    """Subclasses set SECTION_VALUE and RESPONDS_TO."""

    SECTION_VALUE: str

    def compute(self) -> list[Effect]:
        patient_id = self.event.target.id
        command = _latest_review(patient_id, self.SECTION_VALUE)
        banner = Group(
            name=_banner_text(command),
            priority=_BANNER_PRIORITY,
            items=[],
        )
        return [PatientChartGroup(items={"last_reviewed": banner}).apply()]


class ConditionsLastReviewed(_InlineLastReviewedBase):
    """Inline banner for the Conditions chart section."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__CONDITIONS)
    SECTION_VALUE = "conditions"


class MedicationsLastReviewed(_InlineLastReviewedBase):
    """Inline banner for the Medications chart section."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__MEDICATIONS)
    SECTION_VALUE = "medications"
