"""Putting the patient in front of you on the waitlist, from their chart.

The chart carries two separate questions, and they need separate controls. The
banner in ``services/banner.py`` answers "is this patient already waiting?" --
passive, always visible, no click. This button answers "put them on the list",
which is an action and needs an affordance.

**One click, no form.** The form it used to open had every field already on its
broadest setting -- any appointment type, any provider, any location, the
configured default priority, no time preference -- so the modal and the second
click were only confirming answers that were correct on arrival. Reviewers asked
for the clicks back, and a second button offering the shortcut alongside the form
was worse than either: a chart header truncates labels at roughly twelve
characters, so "Add to waitlist" and "Waitlist: any" both rendered as an
ellipsis and became impossible to tell apart.

Stating a *specific* want from the chart -- "she'll only see Dr Chen" -- is the
second click, on the same button. Once the patient is listed the button reads "On
waitlist" and opens the compact form on the entry that was just written, so the
broad add can be narrowed in place. That is deliberately the order: the patient is
on the list before anything can go wrong, and the detail is optional.

It opens a form about one entry rather than the roster because a full-width table
is not a dialog -- the same reason the add form has its own page. The roster is
still where a patient with *several* live entries goes, because there is no single
entry to edit there, and it is still reachable in one click from the chart banner.

The write goes through ``services/quick_add.py`` and therefore through the same
``validate_entry`` the two forms post to, rather than assembling model fields
here.
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

from scheduling_waitlist.constants import (
    BUTTON_ADD_TITLE,
    BUTTON_LISTED_TITLE,
    LISTED_BUTTON_BACKGROUND,
    LISTED_BUTTON_TEXT,
    add_form_url,
    edit_form_url,
    roster_url_for_search,
)
from scheduling_waitlist.services.banner import banner_effects, banner_effects_for_entry
from scheduling_waitlist.services.chart_buttons import reload_chart_buttons
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.display import UNNAMED_PATIENT, patient_name
from scheduling_waitlist.services.entries import (
    DuplicateEntryError,
    get_entry,
    has_live_entry,
    live_entries_for_patient,
)
from scheduling_waitlist.services.permissions import staff_from_actor
from scheduling_waitlist.services.quick_add import QuickAddRefused, quick_add

ADD_MODAL_TITLE = "Add to waitlist"
EDIT_MODAL_TITLE = "Edit waitlist entry"
LISTED_MODAL_TITLE = "Scheduling Waitlist"


class AddToWaitlistButton(ActionButton):
    """A chart-header button that puts this patient on the waitlist in one click."""

    BUTTON_TITLE = BUTTON_ADD_TITLE
    BUTTON_KEY = "scheduling_waitlist__add"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    def patient_id(self) -> str:
        """The chart's patient, as a string key."""
        target_id = getattr(getattr(self.event, "target", None), "id", None)
        return str(target_id) if target_id else ""

    def _patient(self) -> Any | None:
        """The chart's patient, or ``None`` if the event named nobody we hold."""
        patient_id = self.patient_id()
        if not patient_id:
            return None
        return Patient.objects.filter(id=patient_id).only("id", "dbid").first()

    def visible(self) -> bool:
        """Whether to draw the button, and under which label and colour.

        The platform reads ``BUTTON_TITLE`` immediately after this returns, so
        the label is decided here from live data. Assigned to ``self`` rather
        than the class: a class attribute would carry one patient's label onto
        the next patient's chart.
        """
        patient = self._patient()
        if patient is None:
            # Nothing to add, and a control that would only fail on click is
            # worse than no control.
            return False

        waiting = has_live_entry(getattr(patient, "dbid", None))
        self.BUTTON_TITLE = BUTTON_LISTED_TITLE if waiting else BUTTON_ADD_TITLE
        # Only the listed state is coloured. Leaving the action state on the
        # platform's own styling keeps it looking like every other chart button,
        # so the filled one reads as the exception it is.
        self.BUTTON_BACKGROUND_COLOR = LISTED_BUTTON_BACKGROUND if waiting else None
        self.BUTTON_TEXT_COLOR = LISTED_BUTTON_TEXT if waiting else None
        return True

    def handle(self) -> list[Effect]:
        """Add them, or -- if they are already listed -- open what they asked for.

        The label promised one of two things and this has to deliver whichever it
        was, so the lookup is repeated: ``visible()`` is a separate invocation
        with no state to carry over.

        The entries themselves are fetched here, not just the yes/no
        ``visible()`` needs, because "On waitlist" now has to name one of them.
        One query either way.

        Neither branch offers to add again: the duplicate guard would refuse it,
        and a scheduler who wants a *second*, differently-specified entry for the
        same patient is doing something deliberate enough to belong on the
        roster's own add form.
        """
        patient = self._patient()
        if patient is None:
            return []

        entries = live_entries_for_patient(getattr(patient, "dbid", None))
        if entries:
            return [self._open_listed(entries)]

        return self._add(patient, str(getattr(patient, "id", "") or ""))

    def _open_listed(self, entries: list[Any]) -> Effect:
        """Where "On waitlist" goes.

        One live entry -- the ordinary case, and what the quick add leaves behind
        -- opens that entry's own form. This is the click reviewers were really
        asking about: the add commits the broadest possible entry, so narrowing it
        to "only Dr Chen" has to be reachable from the chart rather than by
        opening the practice-wide roster and searching for the patient whose chart
        is already on screen.

        Several live entries have no single subject, so those open the roster,
        where the rows can be told apart, edited, marked scheduled or removed --
        with the patient's name already in the search box, because a thousand-row
        table is no easier to search from a chart than it was before.

        That is the roster's own keyword search, pre-typed: visible in the box,
        cleared by Reset, and counted as a filtered view. It is not the
        patient-scoped roster reverted in cf94418, which added a dbid filter the
        UI did not show, a "Show everyone" control to escape it, and a count line
        that reported the narrowed total as the practice-wide one.
        """
        if len(entries) == 1:
            return self._open(
                edit_form_url(getattr(entries[0], "dbid", None)), EDIT_MODAL_TITLE
            )

        return self._open(
            roster_url_for_search(self._search_term(entries[0])), LISTED_MODAL_TITLE
        )

    @staticmethod
    def _search_term(entry: Any) -> str:
        """The patient's name to pre-type, or nothing.

        ``patient_name`` answers "Unnamed patient" for a record it cannot read,
        which as a search term matches nobody and would present an empty roster
        as this patient's rows. An empty term opens the practice-wide list
        instead, which is at least true.
        """
        patient = getattr(entry, "patient", None)
        if patient is None:
            return ""
        name = patient_name(patient)
        return "" if name == UNNAMED_PATIENT else name

    def _add(self, patient: Any, patient_id: str) -> list[Effect]:
        """Write the entry, or fall back to the form if we cannot attribute it.

        The actor matters more than it looks. Every other write in this plugin
        arrives on an authenticated request and takes its staff member from the
        session header; a button click has no request, so the identity comes off
        the event instead. When that fails there is no safe way to continue -- an
        entry created by nobody can be edited or removed only by a configured
        manager, not by the person who created it -- so the click degrades to
        opening the old form, which is authenticated and attributes correctly.
        One click slower, and never wrong.
        """
        staff = staff_from_actor(getattr(getattr(self.event, "actor", None), "id", None))
        if staff is None:
            log.warning(
                "scheduling_waitlist: could not identify the clicking staff "
                "member, opening the add form instead"
            )
            return [self._open(add_form_url(patient_id), ADD_MODAL_TITLE)]

        try:
            entry = quick_add(
                patient_id,
                created_by_dbid=getattr(staff, "dbid", None),
                config=WaitlistConfig.from_secrets(self.secrets),
                today=datetime.now(timezone.utc).date(),
            )
        except DuplicateEntryError:
            # Lost a race with another click or another surface. The list is
            # already in the state the click asked for, so all that is left is
            # making the chart say so.
            log.info(
                "scheduling_waitlist: add skipped, patient is already waiting "
                "for any appointment type"
            )
            return self._refresh(patient)
        except QuickAddRefused as exc:
            # The broadest possible request was refused, which is a fault rather
            # than a scheduler's mistake. The form will show them the reason.
            log.error(f"scheduling_waitlist: add refused: {exc}")
            return [self._open(add_form_url(patient_id), ADD_MODAL_TITLE)]

        # Re-read so the banner names the service and the reload sees the related
        # rows, exactly as the API's create route does.
        stored = get_entry(getattr(entry, "dbid", None)) or entry
        log.info(
            "scheduling_waitlist: added a general waitlist entry from a chart header"
        )
        return [*banner_effects_for_entry(stored), *reload_chart_buttons(stored)]

    @staticmethod
    def _open(url: str, title: str) -> Effect:
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title=title,
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
