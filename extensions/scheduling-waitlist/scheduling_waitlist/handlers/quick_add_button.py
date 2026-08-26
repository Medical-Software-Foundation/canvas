"""One click to put the patient in front of you on the waitlist.

The full form already opens with every field on its broadest setting -- any
appointment type, any provider, any location, the configured default priority,
no time preference -- so the common request was costing a modal load and a second
click to accept answers that were already correct. This button skips both: the
click *is* the submission.

It sits beside ``handlers/chart_button.py`` rather than replacing it, because the
other half of the job is still real. A scheduler who knows the patient wants Dr
Chen on a Tuesday needs the form, and folding both into one control would mean
either losing the detail or keeping the modal.

Deliberately not offered on a freed appointment's note. The button there already
knows the slot's service, provider and location, so its whole value is the
pre-fill; a general entry from that surface would throw away the one piece of
information the surface has.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import ReloadPatientActionButtonsEffect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data import Patient
from logger import log

from scheduling_waitlist.constants import add_form_url
from scheduling_waitlist.services.banner import banner_effects, banner_effects_for_entry
from scheduling_waitlist.services.chart_buttons import reload_chart_buttons
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.entries import (
    DuplicateEntryError,
    get_entry,
    has_live_general_entry,
)
from scheduling_waitlist.services.permissions import staff_from_actor
from scheduling_waitlist.services.quick_add import QuickAddRefused, quick_add

# Says what it does and what it costs the reader in three words: no form, no
# choices, on the list for anything. The sibling button keeps "Add to waitlist",
# so the pair reads as the quick way and the considered way.
QUICK_TITLE = "Waitlist: any"
FORM_MODAL_TITLE = "Add to waitlist"


class QuickAddToWaitlistButton(ActionButton):
    """Creates the broadest possible waitlist entry, with no form in between."""

    BUTTON_TITLE = QUICK_TITLE
    BUTTON_KEY = "scheduling_waitlist__quick_add"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def _patient(self) -> Any | None:
        """The chart's patient, or ``None`` if the event named nobody we hold."""
        target_id = getattr(getattr(self.event, "target", None), "id", None)
        if not target_id:
            return None
        return Patient.objects.filter(id=str(target_id)).only("id", "dbid").first()

    def visible(self) -> bool:
        """Only while a general entry is still something this patient could get.

        Hidden once they have one, rather than shown and then refused: the click
        writes immediately, so there is no form to carry an "already on the list"
        message back to. The sibling button stays visible and switches to "On
        waitlist", so the chart still says what is true.
        """
        patient = self._patient()
        if patient is None:
            return False
        return not has_live_general_entry(getattr(patient, "dbid", None))

    def handle(self) -> list[Effect]:
        """Write the entry, or fall back to the form if we cannot attribute it.

        The actor matters more than it looks. Every other write in this plugin
        arrives on an authenticated request and takes its staff member from the
        session header; a button click has no request, so the identity comes off
        the event instead. When that fails there is no safe way to continue -- an
        entry created by nobody can be edited or removed only by a configured
        manager, not by the person who created it -- so the click degrades to
        opening the ordinary form, which is authenticated and attributes
        correctly. One click slower, and never wrong.
        """
        patient = self._patient()
        if patient is None:
            return []

        patient_id = str(getattr(patient, "id", "") or "")
        staff = staff_from_actor(getattr(getattr(self.event, "actor", None), "id", None))
        if staff is None:
            log.warning(
                "scheduling_waitlist: quick add could not identify the clicking "
                "staff member, opening the add form instead"
            )
            return [self._open_form(patient_id)]

        config = WaitlistConfig.from_secrets(self.secrets)
        try:
            entry = quick_add(
                patient_id,
                created_by_dbid=getattr(staff, "dbid", None),
                config=config,
                today=datetime.now(timezone.utc).date(),
            )
        except DuplicateEntryError:
            # Lost a race with another click or another surface. The list is
            # already in the state the click asked for, so all that is left is
            # making the chart say so.
            log.info(
                "scheduling_waitlist: quick add skipped, patient is already "
                "waiting for any appointment type"
            )
            return self._refresh(patient)
        except QuickAddRefused as exc:
            # The broadest possible request was refused, which is a fault rather
            # than a scheduler's mistake. The form will show them the reason.
            log.error(f"scheduling_waitlist: quick add refused: {exc}")
            return [self._open_form(patient_id)]

        # Re-read so the banner names the service and the reload sees the related
        # rows, exactly as the API's create route does.
        stored = get_entry(getattr(entry, "dbid", None)) or entry
        log.info(
            "scheduling_waitlist: quick added a general waitlist entry from a "
            "chart header"
        )
        return [*banner_effects_for_entry(stored), *reload_chart_buttons(stored)]

    @staticmethod
    def _open_form(patient_id: str) -> Effect:
        """The ordinary add form, as a fallback rather than a first choice."""
        return LaunchModalEffect(
            url=add_form_url(patient_id),
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title=FORM_MODAL_TITLE,
        ).apply()

    @staticmethod
    def _refresh(patient: Any) -> list[Effect]:
        """Bring the chart into line having written nothing.

        Addresses the chart header directly instead of going through
        ``reload_chart_buttons``, which takes an entry: there is no entry in hand,
        and a general entry names no service, so the note reloads that function
        would work out have nothing to redraw anyway.
        """
        patient_id = getattr(patient, "id", None)
        if not patient_id:
            return []
        return [
            *banner_effects(patient),
            ReloadPatientActionButtonsEffect(id=str(patient_id)).apply(),
        ]
