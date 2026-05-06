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
from logger import log


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
        text = _banner_text(command)
        # The renderer drops empty groups, so to make the banner visible we
        # have to put items in it. Pass through the section's existing
        # context items unchanged -- the banner ends up rendering as a
        # header above the same conditions/medications the section was
        # already showing.
        items = list(self.event.context) if self.event.context else []
        banner = Group(
            name=text,
            priority=_BANNER_PRIORITY,
            items=items,
        )
        effect = PatientChartGroup(items={"last_reviewed": banner}).apply()

        # TEMPORARY DIAGNOSTIC -- the empty-group banner isn't rendering on
        # xpc-dev. Log enough to tell whether the handler is firing, what
        # the event context looks like, and what we're emitting. Removed
        # once we know why nothing shows up.
        try:
            ctx = self.event.context
            ctx_len = len(ctx) if ctx is not None else None
            ctx_sample = ctx[:1] if isinstance(ctx, list) and ctx else ctx
            log.info(
                f"[last_reviewed_inline] section={self.SECTION_VALUE} "
                f"patient={patient_id} command_found={command is not None} "
                f"banner_text={text!r} ctx_len={ctx_len} ctx_sample={ctx_sample!r}"
            )
            log.info(
                f"[last_reviewed_inline]   effect.type={effect.type!r} "
                f"effect.payload={effect.payload!r}"
            )
        except Exception as exc:
            log.info(f"[last_reviewed_inline] diagnostic failed: {exc!r}")

        return [effect]


class ConditionsLastReviewed(_InlineLastReviewedBase):
    """Inline banner for the Conditions chart section."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__CONDITIONS)
    SECTION_VALUE = "conditions"


class MedicationsLastReviewed(_InlineLastReviewedBase):
    """Inline banner for the Medications chart section."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART__MEDICATIONS)
    SECTION_VALUE = "medications"
