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
        }

    def test_the_roster_ignores_a_patient_parameter(self, rendered_context):
        # The roster is the practice-wide list. Narrowing it to one patient was a
        # decision that got reverted; the ticket's filters are service, provider
        # and location.
        _api(query_params={"patient": "abc-123"}).get_roster_page()

        config = json.loads(rendered_context()["config_json"])
        assert set(config) == {"apiBase", "cacheBust"}


class TestAddForm:
    """The compact form the chart button opens.

    A page of its own rather than the roster with a parameter: a dialog and a
    full-width table want different sizes from the host modal, and opening the
    roster from a chart put a whole table on screen to collect six fields.
    """

    def test_returns_a_single_html_response(self):
        responses = _api(query_params={"patient": "abc-123"}).get_add_form()

        assert len(responses) == 1
        assert responses[0].content_type == "text/html"
        assert responses[0].status_code == 200

    def test_renders_the_compact_template_not_the_roster(self):
        responses = _api(query_params={"patient": "abc-123"}).get_add_form()

        assert "templates/add_patient.html" in responses[0].body

    def test_the_response_is_not_cached(self):
        responses = _api(query_params={"patient": "abc-123"}).get_add_form()

        assert responses[0].headers["Cache-Control"] == "no-cache"

    def test_the_patient_key_reaches_the_page(self, rendered_context):
        _api(query_params={"patient": "abc-123"}).get_add_form()

        assert json.loads(rendered_context()["config_json"])["patientId"] == "abc-123"

    def test_a_blank_patient_parameter_is_treated_as_absent(self, rendered_context):
        _api(query_params={"patient": "   "}).get_add_form()

        assert json.loads(rendered_context()["config_json"])["patientId"] == ""

    def test_a_missing_patient_parameter_is_treated_as_absent(self, rendered_context):
        _api().get_add_form()

        assert json.loads(rendered_context()["config_json"])["patientId"] == ""

    def test_the_page_carries_only_wiring_and_keys(self, rendered_context):
        # The name and date of birth behind the patient key, and the names behind
        # the prefill keys, are all fetched over the authenticated API -- nothing
        # identifiable is baked into a document the browser may cache.
        _api(query_params={"patient": "abc-123"}).get_add_form()

        config = json.loads(rendered_context()["config_json"])
        assert set(config) == {"apiBase", "cacheBust", "patientId", "prefill"}


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

    TEMPLATES = sorted(Path("scheduling_waitlist/templates").glob("*.html"))

    def test_there_are_templates_to_check(self):
        # A glob that silently matches nothing would make every test below pass.
        assert self.TEMPLATES

    def test_every_config_payload_is_emitted_unescaped(self):
        # Without |safe, autoescaping turns " into &quot; and JSON.parse throws.
        for template in self.TEMPLATES:
            source = template.read_text()
            if "config_json" in source:
                assert "{{ config_json|safe }}" in source, template.name

    def test_no_json_payload_is_interpolated_without_safe(self):
        """Guards the whole class of bug across every template.

        Any JSON dropped into a document has to be marked safe, so a second
        payload or a second page cannot repeat the mistake.
        """
        for template in self.TEMPLATES:
            for match in re.finditer(
                r"\{\{\s*(\w+_json)\s*(\|[^}]*)?\}\}", template.read_text()
            ):
                name, filters = match.group(1), match.group(2) or ""
                assert "safe" in filters, f"{template.name}: {name} lacks |safe"

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

    TEMPLATES = sorted(Path("scheduling_waitlist/templates").glob("*.html"))

    def test_every_short_comment_closes_on_its_own_line(self):
        for template in self.TEMPLATES:
            for number, line in enumerate(template.read_text().splitlines(), start=1):
                if "{#" in line:
                    assert "#}" in line, (
                        f"{template.name} line {number}: a hash comment spans lines, "
                        "so its tail renders as page text -- use the comment tag"
                    )

    def test_multi_line_notes_use_a_balanced_comment_tag(self):
        for template in self.TEMPLATES:
            source = template.read_text()
            assert source.count("{% comment %}") == source.count("{% endcomment %}"), (
                template.name
            )


class TestTheRosterCanBeClosed:
    """The roster had no way out of its own modal.

    The compact add form has always sent ``CLOSE_MODAL``; the roster only ever
    sent ``RESIZE``, so it relied entirely on whatever chrome the host drew around
    it. The button is hidden until the port arrives, because that port is the only
    thing that can close the modal and the page is also reachable outside one.
    """

    ROSTER_HTML = Path("scheduling_waitlist/templates/roster.html")
    ROSTER_JS = Path("scheduling_waitlist/static/js/roster.js")

    def test_the_roster_has_a_close_control(self):
        assert 'id="wl-close"' in self.ROSTER_HTML.read_text()

    def test_it_ships_hidden(self):
        markup = self.ROSTER_HTML.read_text()
        button = markup[markup.index('id="wl-close"') :]

        assert "hidden" in button[: button.index(">")], (
            "a close button that appears before the port arrives cannot close anything"
        )

    def test_the_roster_sends_close_modal(self):
        assert "CLOSE_MODAL" in self.ROSTER_JS.read_text()

    def test_it_is_revealed_and_wired_only_once_the_port_exists(self):
        source = self.ROSTER_JS.read_text()
        handshake = source[source.index("INIT_CHANNEL") :]

        assert handshake.index("wl-close") < handshake.index("CLOSE_MODAL")
        assert "close.hidden = false" in handshake


class TestEveryFormOffersAnyForAllThreeMatchedFields:
    """A form must be able to express every state the model can hold.

    Provider and location both led with an "any" option; service did not, even
    though ``note_type`` is nullable for exactly that purpose and the serializer
    and banner both render it. So the service field defaulted to whichever
    bookable type sorted first, an entry could be created for a service nobody
    books, and it then matched no slot at all -- silently, because the entry
    looked perfectly well-formed on the roster.

    Asserted across all three forms, because the fix had to be made three times:
    the chart's compact form and the roster's own add and edit dialogs each build
    their own selects.
    """

    SOURCES = (
        Path("scheduling_waitlist/templates/add_patient.html"),
        Path("scheduling_waitlist/static/js/roster.js"),
    )

    ANY_LABELS = ("Any appointment type", "Any provider", "Any location")

    def test_each_source_offers_an_any_option_for_every_matched_field(self):
        for source in self.SOURCES:
            text = source.read_text()
            for label in self.ANY_LABELS:
                assert label in text, (
                    f"{source.name} builds a form without an \"{label}\" option, so a "
                    "state the model supports cannot be entered"
                )

    def test_the_roster_offers_it_in_both_of_its_dialogs(self):
        # One dialog having it is not enough: add and edit are separate builders,
        # and an entry that cannot be edited back to "any" is a one-way door.
        text = Path("scheduling_waitlist/static/js/roster.js").read_text()

        assert text.count("Any appointment type") == 2, (
            "both the add and the edit dialog need the option"
        )

    # Where each form builds its service select. Scoped to the block rather than
    # the whole file, because the roster also populates a service *filter*, which
    # legitimately mentions the instance's types earlier and is not a default.
    SERVICE_SELECTS = (
        (Path("scheduling_waitlist/templates/add_patient.html"), "els.service,"),
        (Path("scheduling_waitlist/static/js/roster.js"), '"wl-add-type"'),
        (Path("scheduling_waitlist/static/js/roster.js"), '"wl-edit-type"'),
    )

    def test_any_appointment_type_is_offered_before_the_instances_own_types(self):
        # Order is the behaviour under test: the first option is the default, and
        # defaulting to a concrete service is the bug this class exists for.
        for source, anchor in self.SERVICE_SELECTS:
            text = source.read_text()
            block = text[text.index(anchor) : text.index(anchor) + 400]

            assert "Any appointment type" in block, (
                f"{source.name}: the select at {anchor} offers no any option"
            )
            assert block.index("Any appointment type") < block.index("appointment_types"), (
                f"{source.name}: the select at {anchor} lists the instance's types "
                "first, so the default is a concrete service again"
            )


class TestAddFormPrefill:
    """What the cancelled appointment already told us reaches the form.

    Keys only. The form matches them against dropdowns it fetches itself, so an
    unknown key fails to pre-select rather than inventing an unbookable option.
    """

    def _config(self, rendered_context, query):
        _api(query_params=query).get_add_form()
        return json.loads(rendered_context()["config_json"])

    def test_service_provider_and_location_reach_the_page(self, rendered_context):
        config = self._config(
            rendered_context,
            {"patient": "abc-123", "service": "7", "provider": "101", "location": "3"},
        )

        assert config["prefill"] == {"service": "7", "provider": "101", "location": "3"}

    def test_a_chart_opened_form_carries_no_prefill(self, rendered_context):
        # There is no freed slot to copy from a chart header.
        config = self._config(rendered_context, {"patient": "abc-123"})

        assert config["prefill"] == {"service": "", "provider": "", "location": ""}

    def test_prefill_keys_are_trimmed(self, rendered_context):
        config = self._config(rendered_context, {"patient": "abc-123", "service": "  7  "})

        assert config["prefill"]["service"] == "7"
