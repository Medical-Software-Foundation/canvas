"""Adding the patient in front of you to the waitlist, from their chart.

The chart carries two separate questions, and they need separate controls. The
banner in ``services/banner.py`` answers "is this patient already waiting?" --
passive, always visible, no click. This button answers "put them on the list",
which is an action and needs an affordance.

Serving only the first left the chart read-only: a scheduler had to open the app
drawer and search for the patient whose chart was already on screen.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data import Patient

from scheduling_waitlist.constants import ROSTER_URL, add_form_url
from scheduling_waitlist.services.entries import has_live_entry

ADD_TITLE = "Add to waitlist"
LISTED_TITLE = "On waitlist"
ADD_MODAL_TITLE = "Add to waitlist"
LISTED_MODAL_TITLE = "Scheduling Waitlist"


class AddToWaitlistButton(ActionButton):
    """A chart-header button that opens the waitlist for this patient."""

    BUTTON_TITLE = ADD_TITLE
    BUTTON_KEY = "scheduling_waitlist__add"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def patient_id(self) -> str:
        """The chart's patient, as a string key."""
        target_id = getattr(getattr(self.event, "target", None), "id", None)
        return str(target_id) if target_id else ""

    def visible(self) -> bool:
        """Whether to draw the button, and under which label.

        The platform reads ``BUTTON_TITLE`` immediately after this returns, so
        the label is decided here from live data. Assigned to ``self`` rather
        than the class: a class attribute would carry one patient's label onto
        the next patient's chart.
        """
        patient_id = self.patient_id()
        if not patient_id:
            return False

        patient = (
            Patient.objects.filter(id=patient_id).only("id", "dbid").first()
        )
        if patient is None:
            # A form for a patient the plugin cannot resolve would only fail on
            # submit, so there is nothing useful to offer.
            return False

        waiting = has_live_entry(getattr(patient, "dbid", None))
        self.BUTTON_TITLE = LISTED_TITLE if waiting else ADD_TITLE
        return True

    def handle(self) -> list[Effect]:
        """Open whichever surface the button's own label promised.

        "Add to waitlist" opens the compact form -- its own small page rather
        than the roster, because opening a full-width table to collect six fields
        is not a dialog. "On waitlist" instead opens the roster, where editing,
        marking scheduled and removing already live; handing over an add form
        there refuses the obvious resubmission with a 409 and manages nothing.

        The lookup is repeated rather than carried over from ``visible()``: that
        is a separate invocation, so there is no state to reuse.
        """
        patient_id = self.patient_id()
        if not patient_id:
            return []

        patient = Patient.objects.filter(id=patient_id).only("id", "dbid").first()
        if patient is None:
            return []

        if has_live_entry(getattr(patient, "dbid", None)):
            url, title = ROSTER_URL, LISTED_MODAL_TITLE
        else:
            url, title = add_form_url(patient_id), ADD_MODAL_TITLE

        return [
            LaunchModalEffect(
                url=url,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title=title,
            ).apply()
        ]
