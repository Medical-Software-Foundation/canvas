"""Puts the all programs control in the patient header and opens the patient scoped pane.

This is a separate handler from EnrollmentButton rather than a second location on the same
class, because the chart carries no note in front of the provider, so the patient is the
only value either the show event or the click event here ever hands over. This control
computes no eligibility of its own. It only asks whether the patient already has a program
running, and eligibility.py, the check EnrollmentButton runs against a note's own
prescriptions, has nothing to say about a patient viewed away from any note.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from medication_followup_protocol.api.routes import page
from medication_followup_protocol.models import Enrollment, EnrollmentStatus


class AllProgramsButton(ActionButton):
    """The chart wide door to every program a patient is on."""

    # --- Why the label is one word, when the pane it opens is named in full
    #
    # The patient header renders an action button at a fixed width and truncates the label
    # with an ellipsis, so Follow up programs arrived on the chart reading Follow up and
    # three dots, which named nothing. The label has to survive that width on its own, and
    # the pane's own title below still carries the full wording, so the header stays legible
    # and nothing is lost once it is open.
    BUTTON_TITLE = "Programs"
    BUTTON_KEY = "mfp_all_programs"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def visible(self) -> bool:
        """Show the control only when this patient has at least one active enrolment.

        A patient with nothing running gets no control at all rather than one opening
        onto an empty pane, since compute() on the base class emits nothing when this
        returns false, and there is no empty state to design for a patient the plugin has
        nothing to say about. The active enrolment count is the plugin's own query, there
        is no platform concept of a program to ask instead.
        """
        patient_id = self.event.target.id
        if not patient_id:
            return False
        return Enrollment.objects.filter(
            status=EnrollmentStatus.ACTIVE, patient__id=patient_id
        ).exists()

    def handle(self) -> list[Effect]:
        """Open the patient scoped pane, listing every program this patient is on.

        The patient arrives as the click event's own target, the same accessor visible()
        reads above, since this control carries no note to read one off. The pane itself
        shares its section rendering with the note scoped pane EnrollmentButton opens,
        through program_pane.py, but each caller scopes what it asks that module to
        render, this one to every program the patient is on rather than only the ones one
        note's prescriptions matched.
        """
        patient_id = self.event.target.id
        return [
            LaunchModalEffect(
                url=page(f"/panel?patient_id={patient_id}"),
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Follow up programs",
            ).apply()
        ]
