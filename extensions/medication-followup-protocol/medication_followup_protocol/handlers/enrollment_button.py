"""Puts the Follow ups control in the note header and opens the pane scoped to that note.

The header rather than the footer, so the control sits inline with the note's own
title, and it shows only once a committed prescription on the note in front of the
provider matches a configured class's coverage, the eligibility check eligibility.py
owns.

It carries the same name and opens the same page as the chart wide control in
all_programs_button.py. The two differ only in what they scope that page to, this one to
the note in front of the provider and that one to every note of the patient, which is
the whole reason there is one page rather than an enrolment form and a panel that drifted
into showing different things about the same prescription.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from medication_followup_protocol.api.routes import page
from medication_followup_protocol.services.eligibility import has_matching_prescription


class EnrollmentButton(ActionButton):
    """The note scoped door into the follow ups pane."""

    BUTTON_TITLE = "Follow ups"
    BUTTON_KEY = "mfp_enroll"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        """Show the control only once a committed prescription on this note matches a class.

        This fires on SHOW_NOTE_HEADER_BUTTON, well before any click, so it reads the
        note's own database id off self.event.context["note_id"], the show event's own
        shape, and hands that id straight to eligibility.py, which owns the whole of what
        counts as a match. A note carrying nothing yet, or nothing a configured class
        covers, shows no control at all rather than one that opens onto an empty form.
        """
        note_dbid = (self.event.context or {}).get("note_id")
        if not note_dbid:
            return False
        return has_matching_prescription(note_dbid)

    def handle(self) -> list[Effect]:
        """Open the follow ups pane in the right chart pane, scoped to this note.

        A button on the note opening the right pane is the pairing the design system names as
        standard, for the reason that applies here exactly, the provider has to read the note
        to decide what to enrol the patient on. A modal covers that note, which is why this is
        not a modal.

        The ordinary pane rather than the large one. The large variant was tried and the
        content, three fields and a short list, did not fill it, so it only pushed the note
        aside for no gain. Design for a narrow column here.

        The platform treats right_chart_pane and right_chart_pane_large as one slot, so this
        replaces whatever else is in the pane rather than stacking beside it.

        This fires on ACTION_BUTTON_CLICKED rather than on the show event visible() above
        reads, and the click's own context carries note_id under the same key with no
        guarantee it is the same shape the show event handed visible(), a database id
        there and whichever the platform hands the click here. The enrolment page's own
        API resolves whichever shape arrives rather than assuming one, which is what keeps
        this handler from having to settle the question itself.
        """
        note_id = (self.event.context or {}).get("note_id", "")
        return [
            LaunchModalEffect(
                url=page(f"/panel?note_id={note_id}"),
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Follow ups",
            ).apply()
        ]
