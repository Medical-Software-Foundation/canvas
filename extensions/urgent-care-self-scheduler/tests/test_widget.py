import json
import pathlib
from unittest.mock import Mock, patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from urgent_care_self_scheduler.handlers.widget import WIZARD_PATH, UrgentCareWidget

TEMPLATE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "urgent_care_self_scheduler"
    / "templates"
    / "widget.html"
)


def _make_handler() -> UrgentCareWidget:
    event = Mock()
    event.type = EventType.PATIENT_PORTAL__WIDGET_CONFIGURATION
    event.context = {}
    return UrgentCareWidget(event=event)


def test_responds_to_widget_configuration_event() -> None:
    assert UrgentCareWidget.RESPONDS_TO == EventType.Name(
        EventType.PATIENT_PORTAL__WIDGET_CONFIGURATION
    )


@patch("urgent_care_self_scheduler.handlers.widget.render_to_string")
def test_compute_returns_one_portal_widget_effect(mock_render: Mock) -> None:
    mock_render.return_value = "<div>widget</div>"
    effects = _make_handler().compute()
    assert len(effects) == 1
    assert effects[0].type == EffectType.PORTAL_WIDGET


@patch("urgent_care_self_scheduler.handlers.widget.render_to_string")
def test_compute_renders_widget_template_with_wizard_path(mock_render: Mock) -> None:
    mock_render.return_value = "<div>widget</div>"
    _make_handler().compute()
    mock_render.assert_called_once_with(
        "templates/widget.html", {"wizard_path": WIZARD_PATH}
    )


@patch("urgent_care_self_scheduler.handlers.widget.render_to_string")
def test_compute_passes_rendered_html_as_content(mock_render: Mock) -> None:
    mock_render.return_value = "<div>RENDERED-MARKER</div>"
    effect = _make_handler().compute()[0]
    payload = json.loads(effect.payload)
    assert "RENDERED-MARKER" in payload["data"]["content"]


@patch("urgent_care_self_scheduler.handlers.widget.render_to_string")
def test_widget_size_and_priority(mock_render: Mock) -> None:
    mock_render.return_value = "<div>widget</div>"
    effect = _make_handler().compute()[0]
    payload = json.loads(effect.payload)
    data = payload["data"]
    assert data["size"] == "expanded"
    # Priority < 50 keeps it near the top of the portal home grid.
    assert isinstance(data["priority"], int) and data["priority"] < 50


def test_widget_template_links_to_wizard_route() -> None:
    # The template links to the wizard via the injected `wizard_path` context,
    # and opens it in the top frame so it escapes the portal widget iframe.
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{{ wizard_path }}" in html
    assert 'target="_top"' in html
    assert WIZARD_PATH == "/plugin-io/api/urgent_care_self_scheduler/wizard"


def test_widget_template_has_heading_and_cta_text() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    # Patient-facing copy should mention urgent care and a clear action.
    assert "urgent care" in html.lower()
    assert "schedule" in html.lower() or "book" in html.lower()
