from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import SchedulingApplication


class SchedulingApp(SchedulingApplication):
    """Example scheduling application that overrides the built-in modal.

    When this plugin is installed, Canvas opens this application instead of its
    built-in scheduling modal at every scheduling entry point (the schedule
    page, the calendar drag-and-drop, the patient chart, and reschedule flows).

    ``on_open`` reads whatever scheduling context the originating entry point
    supplied and forwards it (as query params) to the plugin's scheduling UI,
    which reproduces the core flows of the built-in modal. Entities arrive as
    ``{"id": <external id>}`` objects (resolvable with the conventional
    ``.objects.get(id=...)``); ``mode``/``start``/``end``/``duration``/``origin``
    are plain scalars.
    """

    NAME = "Schedule"

    def on_open(self) -> Effect:
        """Open the scheduling modal, forwarding the received context to the UI."""
        context = self.event.context or {}
        patient = context.get("patient") or {}
        note = context.get("note") or {}
        provider = context.get("provider") or {}
        location = context.get("location") or {}
        appointment = context.get("appointment") or {}

        params = {
            "mode": context.get("mode", ""),
            "origin": context.get("origin", ""),
            "start": context.get("start", ""),
            "end": context.get("end", ""),
            "duration": context.get("duration", ""),
            "provider_id": provider.get("id", ""),
            "location_id": location.get("id", ""),
            "appointment_id": appointment.get("id", ""),
            "patient_id": patient.get("id", ""),
            "note_id": note.get("id", ""),
        }
        # Only forward the keys that were actually supplied.
        query = "&".join(f"{key}={value}" for key, value in params.items() if value)

        url = "/plugin-io/api/scheduling_app/app/modal"
        if query:
            url = f"{url}?{query}"

        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Schedule",
        ).apply()
