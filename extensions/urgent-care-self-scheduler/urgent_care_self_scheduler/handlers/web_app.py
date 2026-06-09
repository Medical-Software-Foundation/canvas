from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPIRoute
from canvas_sdk.templates import render_to_string


def _wizard_html() -> str:
    return render_to_string("templates/wizard.html") or ""


class UrgentCareWebApp(PatientSessionAuthMixin, SimpleAPIRoute):
    """Serves the urgent-care self-scheduling wizard HTML page."""

    PATH = "/wizard"

    def get(self) -> list[Response | Effect]:
        return [HTMLResponse(_wizard_html())]
