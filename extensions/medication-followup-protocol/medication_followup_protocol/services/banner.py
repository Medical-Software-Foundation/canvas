"""Applies and removes the per enrolment chart banner.

One banner per running enrolment rather than one per patient naming several, each
identified by its own key, so a program stopping removes exactly its own banner while
every other running enrolment's banner for the same patient is left standing.
Reapplying AddBannerAlert on the same key and patient updates that banner in place
rather than creating a second one, so a caller never has to pair a reapply with a
preceding remove.

The banner carries no href. A banner alert that carries one renders on the chart as a
single anchor whose target is hardcoded to open a new browser tab, and sending a
provider through a tab and back to the chart is more steps than the pane the note
header control already opens in place, so this banner says what is running and where
its next step falls due, and nothing more. A future reader tempted to add a link back
should read this comment first rather than restoring one the platform can only open
away from the chart.
"""

from __future__ import annotations

import datetime
import uuid

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert

from medication_followup_protocol.models.enrollment import EnrolledStep, Enrollment, StepStatus

#: The platform truncates a banner narrative past this many characters, since it is a
#: single escaped text node with no markup, so the wording below is built to fit the
#: cap rather than handed to the platform to cut wherever ninety characters lands.
NARRATIVE_LIMIT = 90

#: The trailing wording for a narrative naming no upcoming step, appended to the
#: program name for an enrolment whose steps have all fired, skipped or failed.
_RUNNING_SUFFIX = " follow up running."


def new_banner_key() -> str:
    """Mint a fresh banner key for a new enrolment.

    A uuid rather than anything derived from the enrolment's own row, because the key
    has to be unique from the moment the enrolment is created and an unsaved row has no
    database id yet to derive one from.
    """
    return f"mfp_{uuid.uuid4()}"


def _next_due_date(enrollment: Enrollment) -> datetime.date | None:
    """The due date of this enrolment's next step still pending, or None when none are.

    Filtered on the enrolment's own dbid rather than on the enrolment object. The
    foreign key is declared to_field dbid, and on the instance a lookup handed the
    object itself is refused with Cannot query, Must be Enrollment instance, while the
    same lookup passes against the test database. That cost a live enrolment its banner
    with every test green, so every read of a step here goes through the value the way
    program_pane.py already reads them.
    """
    step = (
        EnrolledStep.objects.filter(
            enrollment__dbid=enrollment.dbid, status=StepStatus.PENDING
        )
        .order_by("due_date", "sequence")
        .first()
    )
    return step.due_date if step else None


def _narrative(enrollment: Enrollment) -> str:
    """The banner's text, naming the program and its next due date, within the cap.

    Built to fit ninety characters rather than truncated after the fact, because
    cutting a finished sentence wherever the limit lands can leave a date cut in half,
    and a provider scanning the chart should read whatever is there as whole.
    """
    program = enrollment.medication_class.name or enrollment.medication_label
    due = _next_due_date(enrollment)
    suffix = f" follow up running. Next step due {due.isoformat()}." if due else _RUNNING_SUFFIX

    narrative = f"{program}{suffix}"
    if len(narrative) <= NARRATIVE_LIMIT:
        return narrative

    # The program name is the part a practice writes and the part most likely to run
    # long, so it gives way first, cut to whatever room is left after the fixed wording
    # and marked with an ellipsis rather than dropping the due date silently.
    budget = NARRATIVE_LIMIT - len(suffix) - 3
    if budget < 1:
        return narrative[:NARRATIVE_LIMIT]
    return f"{program[:budget]}...{suffix}"


def apply_banner(enrollment: Enrollment) -> Effect:
    """The AddBannerAlert effect for one enrolment.

    Call this when an enrolment starts, and again whenever the fact its narrative
    reports, the next step still pending, changes, since reapplying on the same key
    and patient updates the existing banner rather than creating a second one.
    """
    return AddBannerAlert(
        patient_id=str(enrollment.patient.id),
        key=enrollment.banner_key,
        narrative=_narrative(enrollment),
        placement=[AddBannerAlert.Placement.CHART],
        intent=AddBannerAlert.Intent.INFO,
    ).apply()


def remove_banner(enrollment: Enrollment) -> Effect:
    """The RemoveBannerAlert effect for one enrolment.

    Keyed on this enrolment's own banner_key rather than on the patient alone, which is
    what keeps a second running enrolment's banner standing when this one leaves active
    status, whether by completing, being stopped, or being guarded off for a deceased
    or inactive patient.
    """
    return RemoveBannerAlert(
        patient_id=str(enrollment.patient.id),
        key=enrollment.banner_key,
    ).apply()
