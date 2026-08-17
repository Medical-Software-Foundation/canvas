"""The roster page shell and its static assets."""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from scheduling_waitlist import CACHE_BUST
from scheduling_waitlist.routes.app_routes import WaitlistAppAPI


def _api(query_params=None) -> WaitlistAppAPI:
    api = WaitlistAppAPI.__new__(WaitlistAppAPI)
    api.request = MagicMock(query_params=query_params or {})
    return api


class TestRosterPage:
    def test_returns_a_single_html_response(self):
        responses = _api().get_roster_page()

        assert len(responses) == 1
        assert responses[0].content_type == "text/html"
        assert responses[0].status_code == 200

    def test_renders_the_roster_template(self):
        responses = _api().get_roster_page()

        assert "templates/roster.html" in responses[0].body

    def test_context_carries_the_current_cache_bust_token(self, rendered_context):
        _api().get_roster_page()

        assert rendered_context()["cache_bust"] == CACHE_BUST

    def test_asset_base_points_at_this_plugins_app_prefix(self, rendered_context):
        _api().get_roster_page()

        assert rendered_context()["asset_base"] == "/plugin-io/api/scheduling_waitlist/app"

    def test_embedded_config_is_valid_json_with_the_api_base(self, rendered_context):
        _api().get_roster_page()

        assert json.loads(rendered_context()["config_json"]) == {
            "apiBase": "/plugin-io/api/scheduling_waitlist",
            "cacheBust": CACHE_BUST,
            "addForPatientId": "",
        }

    def test_embedded_config_contains_no_identifiable_patient_data(
        self, rendered_context
    ):
        # The page fetches entries itself, so nothing identifiable is baked into
        # a document that may be cached or copied out of the browser. The patient
        # key below is the one the chart button already put in this page's URL.
        _api(query_params={"patient": "abc-123"}).get_roster_page()

        config = json.loads(rendered_context()["config_json"])
        assert set(config) == {"apiBase", "cacheBust", "addForPatientId"}

    def test_no_patient_is_requested_by_default(self, rendered_context):
        _api().get_roster_page()

        assert json.loads(rendered_context()["config_json"])["addForPatientId"] == ""

    def test_the_chart_buttons_patient_is_passed_to_the_page(self, rendered_context):
        # This is what makes the chart button land on a filled-in add dialog
        # rather than an empty patient picker.
        _api(query_params={"patient": "abc-123"}).get_roster_page()

        assert (
            json.loads(rendered_context()["config_json"])["addForPatientId"] == "abc-123"
        )

    def test_a_blank_patient_parameter_is_treated_as_absent(self, rendered_context):
        _api(query_params={"patient": "   "}).get_roster_page()

        assert json.loads(rendered_context()["config_json"])["addForPatientId"] == ""


class TestAssets:
    def test_css_is_served_as_text_css(self):
        responses = _api().get_css()

        assert len(responses) == 1
        assert responses[0].content_type == "text/css"

    def test_css_body_comes_from_the_stylesheet_file(self):
        responses = _api().get_css()

        assert b"static/css/roster.css" in responses[0].body

    def test_js_is_served_as_javascript(self):
        responses = _api().get_js()

        assert len(responses) == 1
        assert responses[0].content_type == "application/javascript"

    def test_js_body_comes_from_the_script_file(self):
        responses = _api().get_js()

        assert b"static/js/roster.js" in responses[0].body


class TestTemplateEscaping:
    """The rendered page, not just the context that goes into it.

    Every other test here asserts on the context dict, which is why a real bug
    shipped: the JSON was valid going in and Django's autoescaping mangled it on
    the way out, leaving the page with no apiBase and a "configuration is
    missing" error. These read the template source instead.
    """

    TEMPLATE = Path("scheduling_waitlist/templates/roster.html")

    def _source(self):
        return self.TEMPLATE.read_text()

    def test_the_config_payload_is_emitted_unescaped(self):
        # Without |safe, autoescaping turns " into &quot; and JSON.parse throws.
        assert "{{ config_json|safe }}" in self._source()

    def test_no_json_payload_is_interpolated_without_safe(self):
        """Guards the whole class of bug, not just this one tag.

        Any JSON dropped into the document has to be marked safe, so a second
        payload added later cannot repeat the mistake.
        """
        source = self._source()
        for match in re.finditer(r"\{\{\s*(\w+_json)\s*(\|[^}]*)?\}\}", source):
            name, filters = match.group(1), match.group(2) or ""
            assert "safe" in filters, f"{name} is interpolated without |safe"

    def test_safe_json_leaves_no_raw_angle_brackets_or_ampersands(self):
        """The other half of the bargain that makes |safe acceptable.

        Marking the value safe is only defensible because safe_json has already
        neutralised the characters that could close the script tag early.
        """
        from scheduling_waitlist.services.html import safe_json

        payload = safe_json({"note": "</script><img src=x onerror=alert(1)>", "amp": "a&b"})

        assert "<" not in payload
        assert ">" not in payload
        assert "&" not in payload
        assert json.loads(payload)["note"] == "</script><img src=x onerror=alert(1)>"


class TestTemplateComments:
    """Django's ``{# #}`` is single-line only.

    A multi-line one comments out its first line and renders the rest as visible
    page text. That shipped once -- a five-line note about escaping appeared in
    the middle of the roster -- so the shape is pinned here rather than trusted.
    """

    TEMPLATE = Path("scheduling_waitlist/templates/roster.html")

    def test_every_short_comment_closes_on_its_own_line(self):
        for number, line in enumerate(self.TEMPLATE.read_text().splitlines(), start=1):
            if "{#" in line:
                assert "#}" in line, (
                    f"line {number}: {{# #}} spans lines, so its tail renders as "
                    "page text -- use {% comment %} instead"
                )

    def test_multi_line_notes_use_the_comment_tag(self):
        source = self.TEMPLATE.read_text()

        assert source.count("{% comment %}") == source.count("{% endcomment %}")
