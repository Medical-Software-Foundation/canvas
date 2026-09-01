"""The roster page shell and its static assets."""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

from scheduling_waitlist import CACHE_BUST
from scheduling_waitlist.constants import edit_form_url
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
            "search": "",
        }

    def test_the_roster_ignores_a_patient_parameter(self, rendered_context):
        # The roster is the practice-wide list. Narrowing it to one patient by key
        # was a decision that got reverted; the ticket's filters are service,
        # provider, location and keyword search.
        _api(query_params={"patient": "abc-123"}).get_roster_page()

        config = json.loads(rendered_context()["config_json"])
        assert set(config) == {"apiBase", "cacheBust", "search"}
        assert config["search"] == ""

    def test_a_search_term_reaches_the_page(self, rendered_context):
        # Pre-typed into the box the roster already has, so a patient with several
        # entries opens with their rows at the top instead of somewhere in a table
        # that can run to thousands.
        _api(query_params={"q": "Nikola Tesla"}).get_roster_page()

        assert json.loads(rendered_context()["config_json"])["search"] == "Nikola Tesla"

    def test_a_blank_search_term_is_treated_as_absent(self, rendered_context):
        _api(query_params={"q": "   "}).get_roster_page()

        assert json.loads(rendered_context()["config_json"])["search"] == ""

    def test_the_search_term_is_the_only_thing_baked_into_the_page(
        self, rendered_context
    ):
        # Everything else the roster shows arrives over the authenticated API. The
        # term is the caller's own text and is shown in the search box, so it has
        # to be in the document.
        _api(query_params={"q": "Tesla"}).get_roster_page()

        config = json.loads(rendered_context()["config_json"])
        assert set(config) == {"apiBase", "cacheBust", "search"}


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

        assert "templates/entry_form.html" in responses[0].body

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
        assert set(config) == {"apiBase", "cacheBust", "mode", "patientId", "prefill"}

    def test_the_page_is_told_it_is_adding(self, rendered_context):
        # One template serves both, and it chooses its verb from this.
        _api(query_params={"patient": "abc-123"}).get_add_form()

        assert json.loads(rendered_context()["config_json"])["mode"] == "add"


class TestEditForm:
    """The same compact form, opened on an entry that already exists.

    Where the chart button's "On waitlist" goes. The quick add commits the
    broadest possible entry, so this is how a scheduler narrows it to "only Dr
    Chen" without opening the practice-wide roster and searching for the patient
    whose chart is already on screen.
    """

    def test_returns_a_single_html_response(self):
        responses = _api(query_params={"entry": "42"}).get_edit_form()

        assert len(responses) == 1
        assert responses[0].content_type == "text/html"
        assert responses[0].status_code == 200

    def test_renders_the_same_compact_template_as_the_add_form(self):
        # Two templates asking for the same six fields would drift, and the pair
        # that drifted last time disagreed about whether "any" was on offer.
        responses = _api(query_params={"entry": "42"}).get_edit_form()

        assert "templates/entry_form.html" in responses[0].body

    def test_the_response_is_not_cached(self):
        responses = _api(query_params={"entry": "42"}).get_edit_form()

        assert responses[0].headers["Cache-Control"] == "no-cache"

    def test_the_entry_key_reaches_the_page(self, rendered_context):
        _api(query_params={"entry": "42"}).get_edit_form()

        assert json.loads(rendered_context()["config_json"])["entryId"] == "42"

    def test_the_page_is_told_it_is_editing(self, rendered_context):
        _api(query_params={"entry": "42"}).get_edit_form()

        assert json.loads(rendered_context()["config_json"])["mode"] == "edit"

    def test_a_blank_entry_parameter_is_treated_as_absent(self, rendered_context):
        # The form then refuses to start rather than PUTting to an empty key.
        _api(query_params={"entry": "   "}).get_edit_form()

        assert json.loads(rendered_context()["config_json"])["entryId"] == ""

    def test_a_missing_entry_parameter_is_treated_as_absent(self, rendered_context):
        _api().get_edit_form()

        assert json.loads(rendered_context()["config_json"])["entryId"] == ""

    def test_the_page_carries_only_wiring_and_the_entry_key(self, rendered_context):
        # Whose entry it is, and whether the caller may change it, are decided by
        # the API the page then calls -- not by having been handed this document.
        _api(query_params={"entry": "42"}).get_edit_form()

        config = json.loads(rendered_context()["config_json"])
        assert set(config) == {"apiBase", "cacheBust", "mode", "entryId"}

    def test_the_url_the_button_builds_is_the_url_this_route_reads(
        self, rendered_context
    ):
        # The two halves are written in different files and agree only by the name
        # of one query parameter. A rename on either side would leave the form
        # opening with no entry, which looks exactly like a broken page.
        from urllib.parse import parse_qs, urlparse

        url = edit_form_url(777)
        _api(
            query_params={k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        ).get_edit_form()

        assert json.loads(rendered_context()["config_json"])["entryId"] == "777"

    def test_the_entry_key_is_escaped_into_the_url(self):
        # Defensive: a dbid is an integer today. An unescaped value would truncate
        # the query string and take the cache-bust token with it.
        assert "entry=7%267" in edit_form_url("7&7")

    def test_no_patient_is_named(self, rendered_context):
        # An edit cannot reassign the patient, so naming one here could only
        # disagree with the entry.
        _api(query_params={"entry": "42", "patient": "abc-123"}).get_edit_form()

        assert "patientId" not in json.loads(rendered_context()["config_json"])


class TestTheFormLooksLikeTheRostersOwnDialog:
    """The compact form and the roster's dialogs are the same form.

    They were not: the compact form inlined its own styles, its own spacing and
    sentence-case labels, and had no action bar, so opening one from a chart and
    one from the roster showed two visibly different dialogs. Reviewers compared
    them side by side and rejected it.

    Pinned by reading the source, because there is no browser here. Each of these
    is something that has to hold for the two to look alike.
    """

    FORM = Path("scheduling_waitlist/templates/entry_form.html")
    CSS = Path("scheduling_waitlist/static/css/roster.css")

    def test_the_form_wears_the_rosters_stylesheet_rather_than_a_copy(self):
        text = self.FORM.read_text()

        assert "roster.css" in text
        # A third copy of the tokens is exactly what drifted.
        assert "--wl-accent:" not in text, "the form is redefining the palette"

    def test_the_form_uses_the_dialogs_own_class_names(self):
        text = self.FORM.read_text()

        for name in (
            "wl-dialog-body",
            "wl-form-grid",
            "wl-field",
            "wl-field-full",
            "wl-dialog-actions",
            "wl-btn",
            "wl-btn-primary",
            "wl-dialog-sub",
        ):
            assert name in text, f"the form does not use {name}"

    def test_every_class_the_form_borrows_is_defined_in_that_stylesheet(self):
        # A class name that only the form uses is an unstyled element, and one
        # that looks fine locally because the browser fell back to defaults.
        css = self.CSS.read_text()

        for name in ("wl-modal-page", "wl-modal-note", "wl-dialog-body", "wl-form-grid"):
            assert "." + name in css, f"{name} has no rule in roster.css"

    def test_the_page_level_classes_reach_the_form_outside_a_dialog(self):
        # .wl-dialog h2 and .wl-dialog textarea only match inside <dialog>. The
        # form is a page, so those rules have to name it too or its heading and
        # note box fall back to browser defaults.
        css = self.CSS.read_text()

        assert ".wl-modal-page h2" in css
        assert ".wl-modal-page textarea" in css

    def test_the_fields_are_in_the_rosters_order(self):
        # Service, Provider, Location, Priority, Preferred time, Note -- the order
        # in the screenshot reviewers approved, and the order roster.js builds.
        text = self.FORM.read_text()
        positions = [
            text.index('id="wl-service"'),
            text.index('id="wl-provider"'),
            text.index('id="wl-location"'),
            text.index('id="wl-priority"'),
            text.index('id="wl-window"'),
            text.index('id="wl-note"'),
        ]

        assert positions == sorted(positions)

    def test_the_note_spans_both_columns(self):
        text = self.FORM.read_text()
        note_field = text[text.index('id="wl-note"') - 400 : text.index('id="wl-note"')]

        assert "wl-field-full" in note_field

    def test_labels_are_sentence_case_and_uppercased_by_the_stylesheet(self):
        # Two places deciding the case is how the pair diverged. The stylesheet
        # decides.
        text = self.FORM.read_text()

        assert ">Preferred time<" in text
        assert "PREFERRED TIME" not in text
        assert "text-transform: uppercase" in self.CSS.read_text()

    def test_there_is_no_patient_field(self):
        # The chart already knows who this is about, and an edit cannot reassign
        # the patient. The roster's add dialog is the one that has to ask.
        text = self.FORM.read_text()

        assert "wl-picker" not in text
        assert "Search by name" not in text

    def test_the_actions_are_cancel_and_one_primary_button(self):
        text = self.FORM.read_text()
        actions = text[text.index("wl-dialog-actions") :][:400]

        assert 'id="wl-cancel"' in actions
        assert 'id="wl-save"' in actions
        assert actions.index('id="wl-cancel"') < actions.index('id="wl-save"')

    def test_the_hidden_attribute_outranks_the_layout_rules(self):
        # .wl-modal-page and .wl-pager both set a display, which the browser's own
        # [hidden] rule loses to -- so the form would be on screen while it was
        # still loading its options.
        assert "[hidden] { display: none !important; }" in self.CSS.read_text()

    def test_the_modal_asks_for_the_dialogs_own_width(self):
        # 520px is .wl-dialog's width. A wider modal makes the same markup look
        # like a different form.
        assert "width: 520" in self.FORM.read_text()
        assert "width: min(520px, 92vw)" in self.CSS.read_text()


class TestTheFormServesBothModes:
    """The one template that adds and edits.

    There is no JS harness here, so these read the source. They pin the three
    things that differ between the modes -- and that would each fail silently: a
    PUT sent as a POST creates a duplicate rather than an edit, a patient key sent
    on an edit suggests the patient can be reassigned, and a stored time window
    that is not matched back to its named option silently clears a preference the
    patient gave.
    """

    FORM = Path("scheduling_waitlist/templates/entry_form.html")

    def test_editing_puts_to_the_entry_rather_than_posting_a_new_one(self):
        text = self.FORM.read_text()

        assert 'method: isEdit ? "PUT" : "POST"' in text
        assert '"/waitlist/entries/" + window.encodeURIComponent(entryId)' in text

    def test_the_patient_is_named_only_when_adding(self):
        text = self.FORM.read_text()

        assert "if (!isEdit) body.patient_id = patientId;" in text

    def test_a_stored_time_window_is_matched_back_to_its_named_option(self):
        text = self.FORM.read_text()

        assert "storedWindowValue" in text
        for shape in ("weekday_am", "weekday_pm", "weekend"):
            assert shape in text, f"{shape} has no shape to match against"

    def test_the_window_shapes_agree_with_the_rosters_own(self):
        # Two copies, because the two forms share no script. They describe the
        # same server-side TIME_WINDOWS, so a disagreement means one of them
        # reconstructs the wrong window.
        pattern = re.compile(
            r"weekday_am:\s*\"([^\"]+)\",\s*weekday_pm:\s*\"([^\"]+)\",\s*weekend:\s*\"([^\"]+)\""
        )
        form = pattern.search(re.sub(r"\s+", " ", self.FORM.read_text()))
        roster = pattern.search(
            re.sub(r"\s+", " ", Path("scheduling_waitlist/static/js/roster.js").read_text())
        )

        assert form is not None and roster is not None
        assert form.groups() == roster.groups()

    def test_an_unknown_mode_is_treated_as_adding(self):
        # A typo in a URL must not leave the form PUTting to an entry key it never
        # read.
        assert 'var isEdit = config.mode === "edit";' in self.FORM.read_text()


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
        Path("scheduling_waitlist/templates/entry_form.html"),
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
        (Path("scheduling_waitlist/templates/entry_form.html"), "els.service,"),
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


class TestTheNextAppointmentColumn:
    """A column showing what each waiting patient already has booked.

    The list goes stale quietly: an entry is closed only when a booking satisfies
    what it asked for, so someone seen through any other route keeps a row that
    claims they are still waiting. Schedulers then stop trusting the page.
    """

    ROSTER_HTML = Path("scheduling_waitlist/templates/roster.html")
    ROSTER_JS = Path("scheduling_waitlist/static/js/roster.js")
    ROSTER_CSS = Path("scheduling_waitlist/static/css/roster.css")

    def test_the_table_has_the_column(self):
        assert "<th scope=\"col\">Next appointment</th>" in self.ROSTER_HTML.read_text()

    def test_it_sits_beside_waiting(self):
        # "Waiting 40 days" and "seen last week" are two halves of one question.
        markup = self.ROSTER_HTML.read_text()

        assert markup.index("Next appointment") < markup.index(">Waiting<")

    def test_the_header_count_matches_the_rendered_cells(self):
        # COLUMN_COUNT spans the empty-state row. A stale value leaves the "no
        # entries" message short of the table it sits in.
        headers = self.ROSTER_HTML.read_text().count('<th scope="col">')
        source = self.ROSTER_JS.read_text()
        declared = source[source.index("var COLUMN_COUNT = ") :].split(";")[0]

        assert declared.endswith(str(headers))

    def test_an_attended_visit_is_flagged_on_the_row(self):
        # So a long table can be scanned for the stale rows without reading each
        # cell.
        source = self.ROSTER_JS.read_text()

        assert '"data-appointment-state"' in source

    def test_the_flag_survives_hovering(self):
        # The hover tint would otherwise replace the flag on the one row the
        # reader has just pointed at.
        css = self.ROSTER_CSS.read_text()
        rule = css[css.index('tr[data-appointment-state="attended"]') :]

        assert ":hover" in rule[: rule.index("{")]

    def test_only_the_attended_state_is_tinted(self):
        # Booked is reassurance, not a warning; colouring both would leave
        # nothing standing out.
        css = self.ROSTER_CSS.read_text()

        assert 'tr[data-appointment-state="upcoming"]' not in css
