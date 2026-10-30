"""Puts the Follow ups control in the patient header and opens the patient scoped pane.

This is a separate handler from EnrollmentButton rather than a second location on the same
class, because the chart carries no note in front of the provider, so the patient is the
only value either the show event or the click event here ever hands over.

The control's own gate widened alongside eligibility.py's query. It used to ask only
whether the patient already had a program running. It now also asks whether the
patient carries an active prescription that matches a class, carries no enrolment yet,
and falls inside that class's own eligibility window, the same widened, patient scoped
match eligibility.py exposes to the Eligible tab this pane also carries. This handler
renders neither tab itself. It only decides whether the control shows at all and, on a
click, which pane address to open.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from medication_followup_protocol.api.routes import page
from medication_followup_protocol.models import Enrollment, EnrollmentStatus
from medication_followup_protocol.services.eligibility import (
    has_eligible_unenrolled_prescription,
)


class AllProgramsButton(ActionButton):
    """The chart wide door to every program a patient is on or could start."""

    # --- Why the label is Follow ups rather than the pane's own full title
    #
    # The patient header renders an action button at a fixed width and truncates a
    # label that runs long with an ellipsis, so the label has to survive that width on
    # its own. Follow ups is also the name this control carries throughout the pane it
    # opens, so the header and the pane title agree rather than one abbreviating the
    # other. It replaces the earlier title, Programs, now that the control shows for
    # more than a patient already enrolled.
    BUTTON_TITLE = "Follow ups"
    BUTTON_KEY = "mfp_all_programs"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def visible(self) -> bool:
        """Show the control for a patient already enrolled or newly eligible to be.

        True the moment this patient carries at least one active Enrollment, the
        Ongoing tab's own source, or at least one eligible, unenrolled prescription
        within its class's window, the Eligible tab's own source, per behaviour step
        43. A patient with neither gets no control at all rather than one opening onto
        an empty pane, since compute() on the base class emits nothing when this
        returns false, and there is no empty state to design for a patient the plugin
        has nothing to say about.
        """
        patient_id = self.event.target.id
        if not patient_id:
            return False
        if Enrollment.objects.filter(
            status=EnrollmentStatus.ACTIVE, patient__id=patient_id
        ).exists():
            return True
        return has_eligible_unenrolled_prescription(patient_id)

    def handle(self) -> list[Effect]:
        """Open the patient scoped pane, carrying the Ongoing and Eligible tabs.

        The patient arrives as the click event's own target, the same accessor visible()
        reads above, since this control carries no note to read one off. The pane itself
        shares its section rendering with the note scoped pane EnrollmentButton opens,
        through program_pane.py, but each caller scopes what it asks that module to
        render, this one to every program the patient is on and every prescription of
        theirs still eligible, rather than only the ones one note's prescriptions
        matched. Which tab opens by default and what each tab lists is the pane's own
        concern, not this handler's, so the URL carries only the patient.
        """
        patient_id = self.event.target.id
        return [
            LaunchModalEffect(
                url=page(f"/panel?patient_id={patient_id}"),
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Follow ups",
            ).apply()
        ]
