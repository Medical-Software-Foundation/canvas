from canvas_sdk.effects import Effect
from canvas_sdk.effects.widgets import PortalWidget
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.templates import render_to_string

WIZARD_PATH = "/plugin-io/api/urgent_care_self_scheduler/wizard"


def _widget_html() -> str:
    return render_to_string("templates/widget.html", {"wizard_path": WIZARD_PATH}) or ""


class UrgentCareWidget(BaseProtocol):
    """Renders the urgent-care scheduling card on the patient portal home page."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_PORTAL__WIDGET_CONFIGURATION)

    def compute(self) -> list[Effect]:
        widget = PortalWidget(
            content=_widget_html(),
            size=PortalWidget.Size.EXPANDED,
            priority=1,
        )
        return [widget.apply()]
