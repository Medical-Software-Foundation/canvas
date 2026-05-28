from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.patient import Patient


class ChatApp(Application):
    """Render the chat panel inside the patient chart's right drawer.

    Reads the active patient from the application's event context and threads
    the id (and display name) into the template so the chat UI can include it
    in every /chat request.
    """

    TARGET = LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE

    def on_open(self) -> Effect:
        """Launch the chat UI in the configured target surface."""
        patient_id = ((self.event.context or {}).get("patient") or {}).get("id") or ""
        patient_name = ""
        if patient_id:
            try:
                p = Patient.objects.get(id=patient_id)
                patient_name = f"{p.first_name} {p.last_name}".strip()
            except Patient.DoesNotExist:
                pass

        content = render_to_string(
            "templates/chat.html",
            {
                "chat_url": "/plugin-io/api/assistant/chat",
                "patient_id": patient_id,
                "patient_name": patient_name,
            },
        )
        return LaunchModalEffect(
            content=content,
            target=self.TARGET,
            title="Assistant",
        ).apply()


class ChatAppGlobal(ChatApp):
    """Global launcher variant: no patient context.

    Same target surface as the patient-specific ChatApp — the only
    difference is the manifest scope (`global` vs `patient_specific`)
    so the app appears in both places.
    """

    TARGET = LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE


# ---- Provider Companion variants -----------------------------------------
#
# Companion apps load their UI by URL (iframe) rather than inline HTML, so
# these subclasses return a LaunchModalEffect with url=... pointing at the
# Assistant SimpleAPI's GET /ui endpoint. The patient_id (if any) is passed
# as a query param so the rendered template can scope itself.

_UI_URL = "/plugin-io/api/assistant/ui"


class ChatAppCompanionPatient(Application):
    """Provider Companion variant on a patient page."""

    def on_open(self) -> Effect:
        """Launch the chat UI in the companion modal, scoped to the active patient."""
        patient_id = ((self.event.context or {}).get("patient") or {}).get("id") or ""
        url = f"{_UI_URL}?patient_id={patient_id}" if patient_id else _UI_URL
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()


class ChatAppCompanionGlobal(Application):
    """Provider Companion variant on the companion main page (no patient)."""

    def on_open(self) -> Effect:
        """Launch the chat UI in the companion modal with no patient context."""
        return LaunchModalEffect(
            url=_UI_URL,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
