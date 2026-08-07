"""Add-to-waitlist button on the patient chart header."""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient

from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.form import build_form_context, live_entries_for_patient


class AddToWaitlistChartButton(ActionButton):
    """Opens the add-to-waitlist form for the patient whose chart is open."""

    BUTTON_KEY = "scheduling_waitlist_add"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER

    @property
    def BUTTON_TITLE(self) -> str:  # noqa: N802 - overrides an SDK class attribute
        """Label, carrying a count when the patient is already waiting.

        Kept short: the chart header truncates long labels.
        """
        patient = self._patient()
        if patient is None:
            return "Waitlist"
        count = len(live_entries_for_patient(getattr(patient, "dbid", None)))
        return f"Waitlist ({count})" if count else "Waitlist"

    def _patient(self) -> Any | None:
        patient_id = getattr(getattr(self.event, "target", None), "id", None)
        if not patient_id:
            return None
        return Patient.objects.filter(id=patient_id).first()

    def handle(self) -> list[Effect]:
        """Render the form into the chart's side pane."""
        patient = self._patient()
        if patient is None:
            return []

        context = build_form_context(
            patient=patient,
            config=WaitlistConfig.from_secrets(self.secrets),
        )
        html = render_to_string("templates/add_to_waitlist.html", context)

        # Rendered inline rather than served from a URL: everything the form
        # needs is known at click time, and inlining keeps the patient
        # identifier out of an iframe URL and the browser's history.
        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Add to waitlist",
            ).apply()
        ]
