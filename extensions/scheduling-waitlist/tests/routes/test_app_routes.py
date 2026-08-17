"""The roster page shell and its static assets."""

import json
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
