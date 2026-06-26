"""Tests for the redesigned admin console template and its asset routes.

The console was rebuilt onto the Canvas plugin web component design system. These
tests pin the contract that keeps it native, the three head tags load the design
system, the markup is built from canvas components rather than raw primitives, no
banned characters leak in, and the two asset routes serve the bundled files with
the right content type.
"""

from __future__ import annotations

import json
from base64 import b64decode
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import salesforce_to_canvas_integration
from salesforce_to_canvas_integration.handlers import status_api
from salesforce_to_canvas_integration.handlers.status_api import SalesforceStatusAPI
from salesforce_to_canvas_integration.templates import ASSET_VERSION, render_admin_page

PLUGIN = "salesforce_to_canvas_integration"
_PACKAGE_DIR = Path(salesforce_to_canvas_integration.__file__).parent


def test_head_loads_the_design_system() -> None:
    """The page pulls in Lato, the design system stylesheet, and the script."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert "fonts.googleapis.com/css?family=Lato" in html
    assert f"/plugin-io/api/{PLUGIN}/canvas-plugin-ui.css?v={ASSET_VERSION}" in html
    assert f"/plugin-io/api/{PLUGIN}/canvas-plugin-ui.js?v={ASSET_VERSION}" in html


def test_placeholder_is_fully_substituted() -> None:
    """No unrendered token survives in the served HTML in either secret state."""
    for available in (True, False):
        html = render_admin_page(
            plugin_name=PLUGIN, secret_field_mapping_available=available
        )
        assert "__PLUGIN_NAME__" not in html
        assert "__ASSET_VERSION__" not in html
        assert "__SECRET_OPTION_DISABLED__" not in html
        assert "__SECRET_OPTION_BADGE__" not in html
        assert "__COPY_SECRET_DISABLED__" not in html


def test_secret_profile_grayed_when_no_secret() -> None:
    """With no field map secret the Secret option is disabled and badged."""
    html = render_admin_page(plugin_name=PLUGIN, secret_field_mapping_available=False)

    secret_option = html.split('value="secret"', 1)[1].split("</canvas-option>", 1)[0]
    assert "disabled" in secret_option
    assert "Not specified" in secret_option


def test_secret_profile_selectable_when_secret_set() -> None:
    """With the secret set the Secret option carries no disabled flag or badge."""
    html = render_admin_page(plugin_name=PLUGIN, secret_field_mapping_available=True)

    secret_option = html.split('value="secret"', 1)[1].split("</canvas-option>", 1)[0]
    assert "disabled" not in secret_option
    assert "Not specified" not in secret_option


def test_asset_version_matches_the_manifest() -> None:
    """The cache busting stamp on the asset URLs tracks the plugin version.

    A stale cached bundle next to fresh page HTML breaks the page silently, so
    every release must move the asset URLs. Pinning the stamp to the manifest
    version makes the bump automatic to forget loudly, this test fails until
    ASSET_VERSION is raised together with plugin_version.
    """
    manifest = json.loads((_PACKAGE_DIR / "CANVAS_MANIFEST.json").read_text())

    assert ASSET_VERSION == manifest["plugin_version"]


def test_built_from_canvas_components() -> None:
    """Every primitive uses a canvas web component."""
    html = render_admin_page(plugin_name=PLUGIN)

    for tag in (
        "<canvas-card",
        "<canvas-card-body",
        "<canvas-badge",
        "<canvas-button",
        "<canvas-tabs",
        "<canvas-tab ",
        "<canvas-tab-panel",
        "<canvas-table",
        "<canvas-scroll-area",
        "<canvas-accordion",
        "<canvas-modal",
        "<canvas-loader",
    ):
        assert tag in html, f"missing {tag}"

    # The banner is created from the status script on a failure path.
    assert "canvas-banner" in html


def test_no_raw_primitives_remain() -> None:
    """The hand rolled table, native disclosure, and browser confirm are gone."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert "<table" not in html
    assert "<details" not in html
    assert "<summary" not in html
    assert "window.confirm" not in html
    assert "status-pill" not in html


def test_no_banned_characters() -> None:
    """No em dash, en dash, or curly quotes reach the rendered page."""
    html = render_admin_page(plugin_name=PLUGIN)

    for ch in ("—", "–", "“", "”", "‘", "’"):
        assert ch not in html


def test_phone_formatter_shipped_and_wired() -> None:
    """The page carries the fmtPhone display helper and routes phone reads through it.

    Every read surface that prints a phone must format to the Canvas mask, so the
    helper has to be defined and the raw esc(row.phone) and esc(d.phone) prints must
    be gone. See journal cnv-941/029 and cnv-941/030.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const fmtPhone = (value) =>" in html
    assert "fmtPhone(row.phone)" in html
    assert "fmtPhone(t.phone)" in html
    assert "fmtPhone(d.phone)" in html
    assert "fmtPhone(d.mobile)" in html
    # The old raw prints must not survive on the wired surfaces.
    assert "esc(row.phone)" not in html
    assert "(d) => esc(d.phone)" not in html


def test_sex_column_is_renamed_to_sex_at_birth() -> None:
    """The Sex header reads Sex at birth and the bare Sex header is gone."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert "Sex at birth" in html
    assert ">Sex</canvas-table-cell>" not in html


def test_collapsing_columns_use_the_fit_class() -> None:
    """The col-fit token exists and is applied to content width columns.

    Address left the records table, so it is no longer the expanding column. The
    col-fit class and its CSS rule still ship for the remaining fit columns.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert ".col-fit { width: 1%; white-space: nowrap; }" in html
    assert 'class="col-fit"' in html


def test_details_modal_is_retired_for_the_inline_expand() -> None:
    """The Details modal is gone, records details ride the inline row expand.

    The old payload only modal stayed gone, and the Details modal that replaced
    it is now retired too. Its content, the context banners, the demographics,
    the overridden history, and the raw payload, paints into the expanded row
    through populateRowDetail instead. See journal cnv-928/007 and cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # Both retired modals and their sinks are gone.
    assert '<canvas-modal id="payload-modal">' not in html
    assert 'id="payload-json"' not in html
    assert '<canvas-modal id="details-modal">' not in html
    assert 'id="details-context"' not in html
    assert 'id="details-received-item"' not in html
    assert 'id="details-payload-item"' not in html
    assert "const showDetails" not in html
    assert "data-details-id" not in html

    # The inline detail keeps the same content through its own builders.
    assert 'class="row-detail-context"' in html
    assert "buildDetailsContext(opts.record)" in html
    assert "buildOverriddenBanner(opts.record)" in html
    assert "const fillRecordDemographics = async (demo, row) => {" in html


def test_subtitle_is_removed() -> None:
    """The page no longer carries the one line subtitle below the title."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert "One way patient sync from Salesforce to Canvas." not in html
    assert 'class="subtitle"' not in html


def test_top_level_tabs_are_records_activity_and_settings() -> None:
    """The page renders Records, Activity, and Settings tabs at the top level.

    The redesign renames the History tab to Activity, the surface for the joined
    event and decision ledger. See journal cnv-909/104.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'id="tab-records"' in html
    assert "<canvas-tab-label>Records</canvas-tab-label>" in html
    assert 'id="tab-activity"' in html
    assert "<canvas-tab-label>Activity</canvas-tab-label>" in html
    assert 'id="tab-settings"' in html
    assert "<canvas-tab-label>Settings</canvas-tab-label>" in html
    assert 'id="panel-records"' in html
    assert 'id="panel-activity"' in html
    assert 'id="panel-settings"' in html

    # Tab order reads Records, then Activity, then Settings.
    assert html.index('id="tab-records"') < html.index('id="tab-activity"') < html.index('id="tab-settings"')


def test_last_open_tab_persists_for_the_session() -> None:
    """The page wires sessionStorage tab persistence with a restore at boot.

    The last open tab is remembered per browser session so a reload returns to
    it instead of snapping back to Records. The store is sessionStorage keyed to
    this app, restored synchronously before canvas-tabs reads its active tab, and
    recorded in the tab-change handler. See journal cnv-938/051 and cnv-938/052.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The store key and the storage mechanism are both present.
    assert '"sf-sync.active-tab"' in html
    assert "window.sessionStorage" in html

    # Restore reads the stored panel and the writer records the chosen one.
    assert "const restoreTab = () =>" in html
    assert "restoreTab();" in html
    assert "if (panel) writeStoredTab(panel);" in html

    # Restore moves the active attribute rather than driving the rendered component.
    assert 'target.setAttribute("active", "");' in html


def test_synced_folds_into_records_as_a_collapsed_accordion_item() -> None:
    """Synced is no longer a top level tab, it folds into the Records accordion.

    The standalone Synced tab and panel are gone. Synced becomes the third
    accordion item at the foot of the Records page, after Needs action and
    Skipped, rendered without the open attribute so it lands collapsed. The top
    level surfaces read Records, Activity, Settings. See journal cnv-941/002.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The standalone tab and panel are gone.
    assert 'id="tab-synced"' not in html
    assert 'id="panel-synced"' not in html
    assert "<canvas-tab-label>Synced</canvas-tab-label>" not in html

    # Synced is now an accordion item inside the Records panel, after Skipped.
    assert 'id="synced-item"' in html
    records_panel = html.index('id="panel-records"')
    activity_panel = html.index('id="panel-activity"')
    synced_item = html.index('id="synced-item"')
    skipped_item = html.index('id="skipped-item"')
    assert records_panel < skipped_item < synced_item < activity_panel

    # The item carries a count badge and renders collapsed, no open attribute.
    item_start = html.index('id="synced-item"')
    item_open = html.index(">", item_start)
    assert " open" not in html[item_start:item_open]
    assert 'id="synced-count-badge"' in html


def test_synced_panel_has_the_registry_table_columns() -> None:
    """The Synced table carries the labeled demographic columns in order.

    First name, Last name, Date of birth, Sex at birth, Phone number, then Last
    synced. The Salesforce and Patient chart links are no longer summary columns at
    all, they live in the expanded detail links bar, so the head carries only the
    leading caret span and the six demographic labels. The folded item title names
    the section, so the old h4 heading is dropped. See journal cnv-928/014 and 030,
    cnv-941/002 and 010.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'id="synced-body"' in html

    start = html.index('aria-label="Synced patients"')
    end = html.index('id="synced-body"', start)
    head = html[start:end]
    for column in (
        ">First name<",
        ">Last name<",
        ">Date of birth<",
        ">Sex at birth<",
        ">Phone number<",
        ">Last synced<",
    ):
        assert column in head, f"missing synced column {column}"
    assert head.index(">Phone number<") < head.index(">Last synced<")
    # The link columns are gone from the summary row, no header text for them.
    assert ">Salesforce<" not in head
    assert ">Patient Chart<" not in head


def test_synced_row_links_salesforce_and_patient_chart() -> None:
    """The Synced row carries its link urls as data attributes for the detail bar.

    The link columns are gone from the summary row, matching Activity. The
    Salesforce url from the server payload and the patient chart url built from the
    page origin plus the Canvas patient id ride the summary row as data attributes,
    and readDetailOpts resolves them into the expanded detail links bar. The caret
    leads the row. See journal cnv-928/014 and 015, cnv-941/003 and 010.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const syncedRow = (row) =>" in html
    assert "linkCell" not in html
    assert '\'" data-sf-url="\' + esc(row.salesforce_url || "")' in html
    assert "'\" data-chart-url=\"' + esc(patientChartUrl(row))" in html
    assert 'window.location.origin + "/patient/"' in html
    # readDetailOpts falls back to the row attributes when no cached feed item
    # rides along, the Synced path.
    assert 'summary.getAttribute("data-sf-url")' in html
    assert 'summary.getAttribute("data-chart-url")' in html
    # The Details button is retired, the row is an expandable summary carrying the
    # trail id, the caret leads, and it ends in the shared detail block.
    assert "const syncedDetailsButton" not in html
    assert 'class="dash-row expandable-summary"' in html
    assert "+ detailRow();" in html
    synced_start = html.index("const syncedRow = (row) =>")
    synced_block = html[synced_start : html.index("+ detailRow();", synced_start)]
    assert synced_block.index("caret-cell") < synced_block.index("row.first_name")


def test_link_cell_renders_a_ghost_button_with_an_external_icon() -> None:
    """The detail bar link is a small gray ghost button, not an anchor.

    The Salesforce and patient chart links read as ghost xs buttons inside the
    expanded detail links bar, each carrying the open in external glyph and the
    destination url on a data attribute. The linkCell column helper is gone with the
    summary link columns, linkButton serves both tables. The old ext-link anchor is
    gone. See journal cnv-928/033 and 034, cnv-941/010.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const linkButton = (url, label) =>" in html
    assert 'variant="ghost" size="xs" data-ext-url="' in html
    assert "const EXT_ICON =" in html
    assert 'class="ext-btn-icon"' in html
    # The label still names the destination, and the button is aria labeled for it.
    assert 'aria-label="Open ' in html
    # The anchor markup the cell used before is no longer emitted by the helper.
    assert '<a class="ext-link" href="' not in html


def test_link_button_opens_its_destination_in_a_new_tab() -> None:
    """The click listener opens a link button's url in a new tab.

    A canvas-button does not navigate on its own the way the old anchor did, so the
    capture phase listener reads the url off data-ext-url and opens it. See journal
    cnv-928/034.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'target.closest("canvas-button[data-ext-url]")' in html
    assert 'window.open(extBtn.getAttribute("data-ext-url"), "_blank", "noopener,noreferrer")' in html


def test_synced_head_columns_read_in_order() -> None:
    """The Synced div grid head lists its columns in order.

    A leading caret span, then First name, Last name, Date of birth, Sex at birth,
    Phone number, and Last synced. The link columns are gone, the links live in the
    expanded detail bar. The list is a div grid, not a canvas-table, so the headers
    are plain spans, and it rides inside a canvas-scroll-area like Activity. See
    journal cnv-941/004, cnv-941/009, and cnv-941/010.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index('class="dash-synced"')
    end = html.index('id="synced-body"', start)
    head = html[start:end]
    for column in (
        ">First name<",
        ">Last name<",
        ">Date of birth<",
        ">Sex at birth<",
        ">Phone number<",
        ">Last synced<",
    ):
        assert column in head, f"missing synced column {column}"
    assert head.index(">Phone number<") < head.index(">Last synced<")


def test_synced_loads_at_boot_and_refreshes_while_records_is_active() -> None:
    """Synced loads on boot and stays fresh while Records is the open surface.

    Folded into Records, the registry can no longer wait for its own tab
    activation. It fetches at boot so the collapsed item shows the right count,
    its count rides the accordion title badge, and the poll plus post mutation
    refresh track it through the Records surface. See journal cnv-941/002.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const fetchSynced = async () => {" in html
    assert "/synced" in html
    # The count now lands on the accordion title badge, not a tab badge.
    assert 'setCountBadge("synced-count-badge"' in html
    # Synced tracks the Records surface and fetches once on boot.
    assert 'syncedActive = panel === "panel-records"' in html
    assert "fetchStatus();\n      fetchSynced();" in html


def test_activity_row_marks_arrivals_with_an_arrived_badge() -> None:
    """The Activity row builder branches on kind and marks arrivals arrived.

    The widened feed renders inbound arrivals alongside decisions, an arrival
    shows an arrived marker in the Action column, a decision shows its resolution
    badge. See journal cnv-928/014 and 030.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'const ARRIVED_BADGE = ' in html
    assert ">Arrived</canvas-badge>" in html
    assert 'e.kind === "received" ? ARRIVED_BADGE : decisionBadge(e.action_taken)' in html
    # The row reads the unified ts field, not the decision only created_at.
    assert "(fmtDateTime(e.ts) || EMPTY)" in html


def test_records_tab_has_needs_action_and_skipped_only() -> None:
    """Needs action and Skipped accordion items carry open, Applied is gone.

    The redesign drops the Applied region from the Records screen since an applied
    event has no action left, leaving the two actionable regions. The full
    applied story lives in the Activity ledger. See journal cnv-909/104.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<canvas-accordion-item id="pending-item" open>' in html
    assert '<canvas-accordion-item id="skipped-item" open>' in html
    # The accordion title labels are plain spans now, the flex: 1 spacer is gone so
    # the count badge sits left next to the label rather than pushed to the right.
    assert '<span>Needs action</span>' in html
    assert '<span>Skipped</span>' in html
    assert '<span style="flex: 1">Needs action</span>' not in html
    assert '<span style="flex: 1">Skipped</span>' not in html
    # The Applied region is gone from the Records screen.
    assert '<canvas-accordion-item id="applied-item" open>' not in html
    assert '<span style="flex: 1">Applied</span>' not in html
    # Needs action sits directly above Skipped now.
    assert html.index('id="pending-item"') < html.index('id="skipped-item"')


def test_field_mapping_is_not_wrapped_in_accordion() -> None:
    """Field mapping is a plain section in Settings, not an accordion item."""
    html = render_admin_page(plugin_name=PLUGIN)

    # The records accordion is the only accordion left on the page. The one that
    # lived inside the Records Details modal retired with the modal when records
    # details moved to the inline row expand, see cnv-941/012. Field mapping is
    # never wrapped in it.
    assert '<canvas-accordion aria-label="Inbound Salesforce records">' in html
    assert html.count("<canvas-accordion ") == 1
    assert 'id="field-mapping-section"' in html
    assert '<h4 class="section-title">Field mapping</h4>' in html
    # The old accordion title wrapper for field mapping is gone.
    assert "<canvas-accordion-title>Field mapping</canvas-accordion-title>" not in html


def test_settings_panel_holds_webhook_card_and_no_connection_card() -> None:
    """The Settings tab carries the webhook card. The connection card is gone for the SF to Canvas phase."""
    html = render_admin_page(plugin_name=PLUGIN)

    records_idx = html.index('id="panel-records"')
    settings_idx = html.index('id="panel-settings"')

    # The records panel does not carry the Webhook card title.
    records_block = html[records_idx:settings_idx]
    assert '<h4 class="card-title">Webhook</h4>' not in records_block

    # The Webhook card lives after the Settings panel opens.
    settings_block = html[settings_idx:]
    assert '<h4 class="card-title">Webhook</h4>' in settings_block

    # The Connection card and its outbound connect button are removed everywhere.
    assert '<h4 class="card-title">Connection</h4>' not in html
    assert "Connect to Salesforce" not in html
    assert 'id="connect-btn"' not in html
    assert 'id="disconnect-modal"' not in html


def test_settings_card_grid_is_width_capped() -> None:
    """The settings card grid is capped so cards do not stretch edge to edge."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert "max-width: 960px;" in html


def test_settings_cards_are_equalized_via_min_height_script() -> None:
    """The page ships the JS that matches the two settings card heights."""
    html = render_admin_page(plugin_name=PLUGIN)

    # The function exists, runs on render, on tab-change to settings, and on resize.
    assert "const equalizeSettingsCards = () => {" in html
    assert '#panel-settings .card-grid canvas-card-body' in html
    assert "scheduleEqualize();" in html
    assert '"tab-change"' in html
    assert 'panel === "panel-settings"' in html
    assert 'window.addEventListener("resize", scheduleEqualize)' in html


def test_copy_webhook_button_is_default_size() -> None:
    """The Copy button next to the webhook URL renders at the regular button size."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<canvas-button id="copy-webhook-btn" variant="ghost">Copy</canvas-button>' in html
    assert 'id="copy-webhook-btn" variant="ghost" size="xs"' not in html


def test_body_text_uses_the_lato_font_token() -> None:
    """The body sets the design system font token so light DOM text is Lato.

    Without this the subtitle, the muted spans, and the modal copy inherit no
    font and fall back to the browser serif default. The code areas keep their
    own monospace token and must not pick up the body font.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "body { font-family: var(--font-family);" in html
    assert ".code-block {\n      font-family: var(--code-font);" in html
    assert ".code-inline { font-family: var(--code-font);" in html


def test_design_system_assets_are_shipped() -> None:
    """Both bundled asset files exist in the package static directory."""
    css = _PACKAGE_DIR / "static" / "canvas-plugin-ui.css"
    js = _PACKAGE_DIR / "static" / "canvas-plugin-ui.js"

    assert css.is_file() and css.stat().st_size > 0
    assert js.is_file() and js.stat().st_size > 0


def _content_type(effect: object) -> str:
    """Pull the Content-Type header out of an applied SimpleAPI response effect."""
    payload = json.loads(effect.payload)  # type: ignore[attr-defined]
    return str(payload["headers"]["Content-Type"])


def _body(effect: object) -> bytes:
    payload = json.loads(effect.payload)  # type: ignore[attr-defined]
    return b64decode(payload["body"])


def _make_api() -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = {}
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    return handler


def test_css_route_serves_text_css(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CSS route reads the bundled file and labels it text/css."""
    monkeypatch.setattr(status_api, "render_to_string", lambda name: "body{color:red}")
    effect = _make_api().plugin_ui_css()[0]

    assert _content_type(effect) == "text/css"
    assert _body(effect) == b"body{color:red}"


def test_js_route_serves_javascript(monkeypatch: pytest.MonkeyPatch) -> None:
    """The JS route reads the bundled file and labels it application/javascript."""
    monkeypatch.setattr(status_api, "render_to_string", lambda name: "console.log(1)")
    effect = _make_api().plugin_ui_js()[0]

    assert _content_type(effect) == "application/javascript"
    assert _body(effect) == b"console.log(1)"


def test_pending_row_renders_create_button() -> None:
    """The verb button wires a Create to the accept route by external id.

    Create is the verb for an unlinked sync, and a stored create posts to accept
    via data-create-id. The verb attribute is chosen dynamically now, so the
    attribute name appears quoted in the builder. See journal cnv-928/041 and
    cnv-938/018.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert '"data-create-id"' in html
    assert ">Create</canvas-button>" in html
    assert ">Create patient</canvas-button>" not in html


def test_pending_row_renders_skip_in_the_caret_menu() -> None:
    """Skip rides the caret menu of the two part action, keyed on external id.

    The standalone ghost Skip button left the row at 0.0.86, the caret part of
    the split button opens a menu holding Skip alone. See journal cnv-941/015.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'data-menu-skip-id="' in html
    assert '<canvas-option value="skip">Skip</canvas-option>' in html
    # The row level ghost Skip button is gone, the modal confirm button stays.
    assert 'data-skip-id="' not in html
    assert '<canvas-button variant="ghost" size="xs" data-skip-id' not in html


def test_audit_modal_is_present_with_form_inputs() -> None:
    """The audit modal exists with canvas inputs for every editable field."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<canvas-modal id="audit-modal"' in html
    for input_id in (
        "audit-first-name",
        "audit-last-name",
        "audit-dob",
        "audit-sex",
        "audit-email",
        "audit-phone",
        "audit-mobile",
        "audit-address-1",
        "audit-address-2",
        "audit-city",
        "audit-state",
        "audit-postal",
        "audit-country",
    ):
        assert f'id="{input_id}"' in html, f"missing {input_id}"


def test_audit_modal_uses_canvas_components_only() -> None:
    """The audit modal has no raw input, select, or button primitives."""
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index('<canvas-modal id="audit-modal"')
    end = html.index("</canvas-modal>", start)
    modal_block = html[start:end]

    assert "<input " not in modal_block
    assert "<select" not in modal_block
    # Plain <button> is fine to exclude, only canvas-button should sit in the modal.
    assert "<button " not in modal_block


def test_audit_modal_first_name_input_is_required() -> None:
    """The first name input carries the required attribute so screen readers see it."""
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index('<canvas-modal id="audit-modal"')
    end = html.index("</canvas-modal>", start)
    modal_block = html[start:end]

    assert '<canvas-input id="audit-first-name" name="first_name" required>' in modal_block


def test_audit_modal_required_labels_carry_asterisk_class() -> None:
    """Required field labels carry the asterisk pseudo element class.

    canvas-input[required] only sets aria-required, no visual cue. The asterisk
    pseudo element is the visual parity hook with the home app Quick Add. Pin
    all four required fields so the cue cannot regress unnoticed.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "label.audit-label.required::after" in html
    for input_id in ("audit-first-name", "audit-last-name", "audit-dob", "audit-sex"):
        assert (
            f'<label class="audit-label required" for="{input_id}">'
            in html
        ), f"missing required label for {input_id}"


def test_audit_modal_email_is_full_width_and_phones_share_a_row() -> None:
    """Email sits in its own full width row, Phone and Mobile phone share a row.

    Mobile phone, address line 1, and address line 2 used to each live in a
    lonely single column block that capped at 360 pixels and floated on the
    left of the modal. The regrouped layout pairs Phone with Mobile phone and
    pairs Address line 1 with Address line 2 so the modal reads as a clean
    two column form. Email goes full width because email strings are long.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index('<canvas-modal id="audit-modal"')
    end = html.index("</canvas-modal>", start)
    modal_block = html[start:end]

    email_idx = modal_block.index('id="audit-email"')
    phone_idx = modal_block.index('id="audit-phone"')
    mobile_idx = modal_block.index('id="audit-mobile"')
    address_1_idx = modal_block.index('id="audit-address-1"')
    address_2_idx = modal_block.index('id="audit-address-2"')

    # Email lives in an audit-field-full block, not an audit-row.
    email_field_open = modal_block.rfind('<div class="audit-field audit-field-full">', 0, email_idx)
    assert email_field_open >= 0, "email is not in an audit-field-full block"

    # Phone and Mobile phone share the same audit-row.
    phone_row_open = modal_block.rfind('<div class="audit-row">', 0, phone_idx)
    mobile_row_open = modal_block.rfind('<div class="audit-row">', 0, mobile_idx)
    assert phone_row_open == mobile_row_open, "phone and mobile are not in the same row"

    # Address line 1 and Address line 2 share the same audit-row.
    addr1_row_open = modal_block.rfind('<div class="audit-row">', 0, address_1_idx)
    addr2_row_open = modal_block.rfind('<div class="audit-row">', 0, address_2_idx)
    assert addr1_row_open == addr2_row_open, "address lines are not in the same row"

    # The CSS modifier exists so the full width email actually stretches.
    assert ".audit-form .audit-field-full canvas-input" in html


def test_audit_modal_keeps_audit_error_region_for_network_failures() -> None:
    """The bottom audit-error region stays for non field errors like network failures.

    Per field validation is now the surface for required and format errors, so
    the bottom paragraph only carries server and network failure messages.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<p id="audit-error" class="audit-error" role="alert" hidden></p>' in html


def test_audit_modal_carries_confirm_and_cancel_buttons() -> None:
    """The audit modal footer has Cancel, Add and open, and Add buttons."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<canvas-button id="audit-cancel"' in html
    assert (
        '<canvas-button id="audit-confirm-open" variant="secondary">Add and open</canvas-button>'
        in html
    )
    assert '<canvas-button id="audit-confirm">Add</canvas-button>' in html


def test_skip_confirm_modal_exists() -> None:
    """The skip confirm modal exists with Cancel and Skip buttons."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<canvas-modal id="skip-modal"' in html
    assert '<canvas-button id="skip-cancel"' in html
    assert '<canvas-button id="skip-confirm">Skip</canvas-button>' in html


def test_skip_modal_carries_an_optional_reason_textarea() -> None:
    """The skip modal holds a canvas textarea labelled as the optional reason.

    Skip stays optional, so the textarea copy says optional and the Skip button
    is never disabled by it. The Cancel and Skip buttons stay in place. See
    journal cnv-928/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index('<canvas-modal id="skip-modal"')
    end = html.index("</canvas-modal>", start)
    modal_block = html[start:end]

    assert '<canvas-textarea id="skip-reason"' in modal_block
    assert "Reason for skipping (optional)" in modal_block
    # The two footer buttons stay.
    assert '<canvas-button id="skip-cancel"' in modal_block
    assert '<canvas-button id="skip-confirm">Skip</canvas-button>' in modal_block


def test_open_and_cancel_skip_clear_the_reason_textarea() -> None:
    """openSkip and cancelSkip both wipe the reason so a prior one never carries.

    See journal cnv-928/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const clearSkipReason = () => {" in html
    open_start = html.index("const openSkip = (id, eventId) => {")
    open_end = html.index("const cancelSkip", open_start)
    assert "clearSkipReason();" in html[open_start:open_end]

    cancel_start = html.index("const cancelSkip = () => {")
    cancel_end = html.index("const submitSkip", cancel_start)
    assert "clearSkipReason();" in html[cancel_start:cancel_end]


def test_submit_skip_posts_the_trimmed_note_as_json() -> None:
    """submitSkip reads the textarea, trims it, and posts a JSON note body.

    An empty value posts an empty note. The post carries the JSON content type
    header. See journal cnv-928/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const submitSkip = async () => {")
    end = html.index("const markInactiveConfirm", start)
    body = html[start:end]

    assert 'const note = reasonEl ? String(reasonEl.value || "").trim() : "";' in body
    assert 'headers: { "Content-Type": "application/json" },' in body
    assert "body: JSON.stringify({ note: note })," in body


def test_details_context_surfaces_the_latest_skip_reason() -> None:
    """A skipped row renders a yellow attribution banner in its expanded detail.

    The warning banner names who skipped and when in its header, gated on the
    skip time so it rides only on skipped rows. The reason sits beneath under a
    Reason for skipping label, shown only when a reason is present. See journal
    cnv-928/012, cnv-928/013, and cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const buildDetailsContext = (row) => {")
    end = html.index("const AUDIT_INPUT_IDS", start)
    body = html[start:end]

    assert "if (row.skipped_at) {" in body
    assert '"Skipped by " + esc(row.skipped_by)' in body
    assert "fmtDateTime(row.skipped_at)" in body
    assert 'variant="warning" header="' in body
    assert "<strong>Reason for skipping</strong>" in body
    assert "esc(row.skip_reason)" in body


def test_decision_badge_surfaces_skipped_not_dismissed() -> None:
    """The decision badge maps the persisted dismissed token to the word Skipped.

    The badge label is assembled at runtime from the DECISION_LABELS map, so the
    contract is pinned on the map entry rather than a literal markup string. The
    operator never sees the raw Dismissed token. See journal cnv-909/091.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'skipped: "Skipped"' in html
    assert 'reopened: "Reopened"' in html
    assert ">Dismissed</canvas-badge>" not in html


def test_pending_row_carries_the_split_action_verb_then_caret() -> None:
    """The Pending summary closes with one cell holding the two part action.

    The verb leads as the immediate main part, the caret menu trails holding
    Skip alone, both joined in one fluid button group. Details rides the row
    expand. See journal cnv-941/015.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const pendingRow = (row) =>")
    block = html[start:html.index("const skippedRow", start)]
    assert "data-details-id" not in block
    assert '\'<span class="dash-cell">\' + splitAction(row) + "</span>"' in block

    start = html.index("const splitAction = (row) =>")
    split = html[start:html.index("const pendingRow", start)]
    assert '<canvas-button-group fluid class="action-split">' in split
    verb_idx = split.index("verbButton(row)")
    menu_idx = split.index("<canvas-menu-button")
    skip_idx = split.index('<canvas-option value="skip">Skip</canvas-option>')
    assert verb_idx < menu_idx < skip_idx
    # The caret trigger is icon only, so it names itself for assistive tech.
    assert 'slot="trigger" size="xs" aria-label="More actions"' in split
    # The menu hugs the right edge of the action column and the open panel
    # wears the canvas-tooltip treatment with the arrow pointing at the caret.
    assert '<canvas-menu-button align="end" arrow' in split
    # The host carries both ids the Skip modal needs.
    assert 'data-menu-skip-id="' in split
    assert 'data-event-id="' in split


def test_records_rows_always_render_a_live_verb() -> None:
    """Records collapsed to one live row per contact, so there is no disabled verb.

    The old orange No patient badge and flag column are gone, and so is the inert
    disabled verb button and the actionable branch. Every surfaced row renders the
    live verb button, the superseded events live in the Details overridden history
    instead. See journal cnv-938/022.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The flag column, the No patient badge, and their builder are gone for good.
    assert "No patient</canvas-badge>" not in html
    assert "flag-col" not in html
    assert "const noPatientBadge" not in html

    # The disabled verb path is removed entirely.
    assert "const disabledVerbButton" not in html
    assert "row.actionable ? verbButton(row) : disabledVerbButton(row)" not in html

    # The split action renders the live verb button directly, no branch.
    start = html.index("const splitAction = (row) =>")
    cell = html[start:html.index("const pendingRow", start)]
    assert "+ verbButton(row)" in cell


def test_record_table_heads_carry_their_action_tails() -> None:
    """Each record head closes with header less trailing spans after Received.

    Both record tables are dash grids. The Needs action head closes with one
    header less span over the two part action, the Skipped head with two over
    the small event indicator and Reopen, and the caret column leads both heads
    with its own blank span. See journal cnv-938/018, cnv-941/012, and
    cnv-941/015.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    indent = "\n                    "
    one_span = "<span>Received</span>" + indent + "<span></span>"
    two_spans = one_span + indent + "<span></span>"

    pending_head = _records_head(html, "Needs action")
    assert one_span in pending_head
    assert two_spans not in pending_head

    skipped_head = _records_head(html, "Skipped")
    assert two_spans in skipped_head

    for head in (pending_head, skipped_head):
        assert ">Event<" not in head
        assert "flag-col" not in head
        # The caret column leads with a blank span ahead of First name.
        assert head.index("<span></span>") < head.index("<span>First name</span>")


def test_action_builders_place_one_action_region_per_cell() -> None:
    """Each trailing action rides its own dash cell in the summary row.

    The pending summary closes with one cell holding the split action, so the
    action pair classes left it. The skipped summary keeps its two cells, the
    event indicator then Reopen, pulled together like a dialog footer. See
    journal cnv-938/018, cnv-941/012, cnv-941/014, and cnv-941/015.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const pendingRow = (row) =>")
    block = html[start:html.index("const skippedRow", start)]
    assert block.count('<span class="dash-cell">') == 1
    assert "action-pair-lead" not in block
    assert "action-pair-tail" not in block
    assert "splitAction(row)" in block
    assert "disabledVerbButton" not in block

    start = html.index("const skippedRow = (row) =>")
    block = html[start:html.index("const CARET_ICON", start)]
    assert block.count('<span class="dash-cell action-pair-lead">') == 1
    assert block.count('<span class="dash-cell action-pair-tail">') == 1
    assert "eventBadge(row)" in block
    assert "data-reopen-id=" in block

    # The verb button sits alone in its group slot, wired by verb.
    assert '<canvas-button size="xs" data-modify-edit-id="' in html
    assert '<canvas-button size="xs" data-delete-id="' in html


def test_split_action_fills_its_records_cell() -> None:
    """The fluid split group fills its cell so the action column reads flush.

    The column sizes to the widest verb plus the caret, fluid stretches the
    verb of a narrower group to absorb the slack while the caret part stays
    content sized, and the caret segment takes the right outer radius through
    the inherited custom property, flush with no seam like the showcase same
    color group. The 0.0.84 bare verb width rule left with the pair cells.
    See journal cnv-941/012 and cnv-941/015.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert ".action-split { width: 100%; }" in html
    assert ".action-split canvas-menu-button {" in html
    assert (
        "--canvas-button-radius: 0 var(--radius, .28571429rem)"
        " var(--radius, .28571429rem) 0;"
    ) in html
    assert "margin-left: 1px;" not in html
    # The single action panel drops the 180px dropdown minimum and shrinks to
    # its content, a tooltip sized panel hugging the caret.
    assert "--canvas-menu-button-menu-min-width: 0;" in html
    assert (
        '.dash-records .dash-cell canvas-button:not([variant="ghost"])'
    ) not in html
    assert "canvas-table-cell[actions]" not in html


def test_pending_grid_carries_its_own_eight_track_template() -> None:
    """Needs action drops to eight tracks, Skipped keeps the shared nine.

    The two trailing action columns collapsed into one on Needs action, so it
    carries its own template under the dash-records-pending modifier while the
    shared dash-records template stays for Skipped. See journal cnv-941/015.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert (
        ".dash-records { grid-template-columns: 36px max-content max-content"
        " max-content max-content minmax(160px, 1fr) max-content max-content"
        " max-content; }"
    ) in html
    assert (
        ".dash-records-pending { grid-template-columns: 36px max-content"
        " max-content max-content max-content minmax(160px, 1fr) max-content"
        " max-content; }"
    ) in html
    assert (
        '<div class="dash-records dash-records-pending" role="table"'
        ' aria-label="Needs action">'
    ) in html
    assert '<div class="dash-records" role="table" aria-label="Skipped">' in html


def test_menu_select_delegation_opens_the_skip_modal() -> None:
    """Selecting Skip from the caret menu opens the existing Skip confirm.

    The component closes itself before select fires, so the delegated listener
    only resolves the host ids and opens the modal. The submit and refresh flow
    is the one the standalone Skip button used. See journal cnv-941/015.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'addEventListener("select", (e) => {' in html
    assert 'e.target.closest("canvas-menu-button[data-menu-skip-id]")' in html
    assert 'e.detail.value !== "skip"' in html
    assert (
        'openSkip(host.getAttribute("data-menu-skip-id"),'
        ' host.getAttribute("data-event-id"));'
    ) in html


def test_open_menu_holds_the_repaint_without_reserving_layout() -> None:
    """An open caret menu pauses the pending repaint and shifts nothing.

    The open and close delegation stamps data-menu-open on the host so the
    status poll skips the pending body repaint, undone on close. The menu now
    flips upward on its own when it would hit the scroll area bottom, so the
    page no longer pads the scroll area to fit it and the tables below never
    shift. See journal cnv-941/015 and cnv-941/025.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'addEventListener("open", (e) => {' in html
    assert 'host.setAttribute("data-menu-open", "");' in html
    assert 'addEventListener("close", (e) => {' in html
    assert 'host.removeAttribute("data-menu-open");' in html
    assert (
        '!pendingBody.querySelector("canvas-menu-button[data-menu-open]")'
    ) in html
    # The layout reserving padding hack is gone, no row may push the page.
    assert "menu-open-pad" not in html


def test_empty_state_has_zero_padding_and_left_alignment() -> None:
    """The empty state block collapses its padding and reads flush left."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert ".empty-state { padding: 0; text-align: left; }" in html
    # The old huge centered rule does not survive.
    assert ".empty-state { padding: var(--space-huge); text-align: center; }" not in html


def test_unpopulated_cells_are_blank_and_required_fields_badge_red() -> None:
    """Empty cells render blank now, the required record fields badge red when missing.

    The shared empty token is the empty string, so an unpopulated cell reads as a
    clean blank. The five required record fields route through reqCell, which shows
    the red Not specified badge when the value is blank. See journal cnv-928/009.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'const EMPTY = "";' in html
    assert 'const EMPTY = "/";' not in html
    # dash still routes empty values through the shared EMPTY token.
    assert "? EMPTY : esc(value)" in html
    # The Received cell still falls back to EMPTY when there is no event time.
    assert "(fmtDateTime(row.received_at) || EMPTY)" in html
    # The required record cells badge red rather than fall back to EMPTY.
    assert (
        'const NOT_SPECIFIED = \'<canvas-badge color="red" size="mini">Not specified</canvas-badge>\';'
        in html
    )
    assert "(inner ? inner : NOT_SPECIFIED)" in html


def _records_head(html: str, label: str) -> str:
    start = html.index(f'aria-label="{label}"')
    end = html.index('class="dash-body"', start)
    return html[start:end]


def test_needs_action_and_skipped_share_one_uniform_header() -> None:
    """Both record tables carry the same seven labeled columns in the same order.

    The demographics were reshaped into the five patient required fields, First name,
    Last name, Date of birth, Sex at birth, and Phone number, then Received. The
    Event column was dropped from both record heads, the event now reads off the
    verb on the Needs action button and a small indicator on a Skipped row. Email,
    Address, the bare Name header, and the DOB header all left the record heads.
    See journal cnv-928/009, cnv-928/043, and cnv-938/018.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    pending_head = _records_head(html, "Needs action")
    skipped_head = _records_head(html, "Skipped")

    for head in (pending_head, skipped_head):
        assert ">SF record<" not in head
        assert ">Actioned<" not in head
        # The dropped columns are gone from both heads.
        assert ">Email<" not in head
        assert ">Address<" not in head
        assert ">Name<" not in head
        assert ">DOB<" not in head
        assert ">Event<" not in head
        for column in (
            ">First name<",
            ">Last name<",
            ">Date of birth<",
            ">Sex at birth<",
            ">Phone number<",
            ">Received<",
        ):
            assert column in head, f"missing column {column}"
        # The five required fields lead, Received closes the labeled head.
        assert head.index(">First name<") < head.index(">Last name<")
        assert head.index(">Phone number<") < head.index(">Received<")


def test_record_lead_cells_render_the_five_required_fields_through_req_cell() -> None:
    """The shared lead cells emit the five required fields via reqCell, each badging red.

    recordLeadCells routes First name, Last name, Date of birth, Sex at birth, and Phone
    number through reqCell, which shows the value or the red Not specified badge when the
    value is blank, then closes with the Received time. See journal cnv-928/009.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const recordLeadCells = (row) =>")
    end = html.index("const recordSummary", start)
    block = html[start:end]

    assert "reqCell(esc(row.first_name), true)" in block
    assert "reqCell(esc(row.last_name), true)" in block
    assert "reqCell(fmtDate(row.mapped && row.mapped.date_of_birth), false)" in block
    assert "reqCell(esc(row.mapped && row.mapped.sex_at_birth), false)" in block
    assert "reqCell(fmtPhone(row.phone), false)" in block
    assert "(fmtDateTime(row.received_at) || EMPTY)" in block

    # The red badge is the missing field marker, both its colour and its text are pinned.
    assert 'const NOT_SPECIFIED = \'<canvas-badge color="red" size="mini">Not specified</canvas-badge>\';' in html
    assert 'color="red"' in html
    assert ">Not specified</canvas-badge>" in html


def test_phone_number_column_expands_and_the_rest_collapse() -> None:
    """Every record column collapses to its content except Phone number, which expands.

    The widths live on the dash-records grid template now. The caret leads in
    its fixed box, the four demographics and Received and the two action columns
    size to their content, and Phone number is the one flexible track, keeping
    the stretch it had in the canvas-table layout. See journal cnv-928/011 and
    cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert (
        ".dash-records { grid-template-columns: 36px max-content max-content "
        "max-content max-content minmax(160px, 1fr) max-content max-content "
        "max-content; }"
    ) in html
    # The expand flag is gone from reqCell, the grid template owns the widths.
    assert 'expand ? "" : \' class="col-fit"\'' not in html
    assert "reqCell(fmtPhone(row.phone), false, true)" not in html
    assert "reqCell(fmtPhone(row.phone), false)" in html


def test_fmt_date_time_normalizes_designator_free_values_to_utc() -> None:
    """fmtDateTime appends a UTC marker when the value carries no zone designator.

    The stored received_at and actioned_at values are UTC. Without a designator the
    browser would read them as local, so fmtDateTime appends a Z so the instant is
    parsed as UTC and rendered in the reviewer local time. See journal cnv-928/009.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const fmtDateTime = (value) => {")
    end = html.index("const fmtDate = (value) => {", start)
    block = html[start:end]

    assert "let s = String(value);" in block
    # The normalization regex and the append both ship. The Python source carries the
    # doubled backslash so the emitted JS regex reads a single backslash digit class.
    assert r'if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += "Z";' in block
    assert "const d = new Date(s);" in block
    # fmtDate is left alone, a calendar date must not shift across a zone, so the UTC
    # normalization never appears in its body.
    fmt_date_start = html.index("const fmtDate = (value) => {")
    fmt_date_end = html.index("const fullName", fmt_date_start)
    fmt_date_block = html[fmt_date_start:fmt_date_end]
    assert 's += "Z";' not in fmt_date_block


def test_skipped_row_renders_reopen_button() -> None:
    """The Skipped row builder offers a Reopen action keyed on external id.

    This is how the story two reopen backend path becomes operator reachable.
    See journal cnv-909/091.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'data-reopen-id="' in html
    assert ">Reopen</canvas-button>" in html


def test_skipped_row_orders_event_badge_before_reopen() -> None:
    """In the Skipped summary the event indicator sits before Reopen.

    The Details button left the row, the row itself expands. The event badge and
    Reopen keep their places as the two trailing cells. See journal cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    skipped_builder = html.index("const skippedRow")
    next_builder = html.index("const CARET_ICON")
    block = html[skipped_builder:next_builder]
    assert "detailsRowButton" not in html
    assert block.index("eventBadge(row)") < block.index("data-reopen-id")


def test_activity_panel_ledger_follows_the_synced_shape() -> None:
    """The Activity ledger reads like Synced, a person centred row with two links.

    The head reads When, Action, Event, Patient, then two header less link columns
    for the Salesforce record and the patient chart. The Decision column is renamed
    Action, and the SF record, By, Canvas patient, and Note columns are gone, that
    metadata now lives in Details and on the chart link. See journal cnv-928/030.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'id="panel-activity"' in html
    assert 'id="activity-section"' in html
    assert '<h4 class="section-title">Activity</h4>' in html
    assert 'id="activity-body"' in html

    start = html.index('aria-label="Activity ledger"')
    end = html.index("</canvas-table-head>", start)
    head = html[start:end]
    for column in (
        ">When<",
        ">Action<",
        ">Event<",
        ">Patient<",
    ):
        assert column in head, f"missing activity column {column}"
    assert head.index(">When<") < head.index(">Action<")
    assert head.index(">Action<") < head.index(">Event<")
    assert head.index(">Event<") < head.index(">Patient<")
    # The removed columns and the renamed one are gone from the head.
    for gone in (">SF record<", ">Decision<", ">By<", ">Canvas patient<", ">Note<"):
        assert gone not in head, f"stale activity column {gone}"
    assert ">Received<" not in head
    assert ">Applied<" not in head


def test_activity_load_more_wrap_starts_hidden() -> None:
    """The Load more wrapper ships hidden, it reveals only when a next page exists."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<div id="activity-load-more-wrap" class="load-more-wrap" hidden>' in html


def test_activity_is_fetched_lazily_on_tab_activation() -> None:
    """The script fetches the activity endpoint and tracks the active tab."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'const fetchActivity = async (cursor) => {' in html
    assert '/activity' in html
    assert 'activityActive = panel === "panel-activity"' in html


def test_activity_row_is_an_expandable_summary_with_who_and_caret() -> None:
    """The activity row builder emits an expandable summary plus a detail row.

    The summary carries the trail id and the per row activity key, the new Who acted
    column, and a trailing caret cell, then the shared detail row follows. The old
    inline Salesforce, chart, and Details cells are gone, that content moves into the
    expanded detail. See journal cnv-941/003.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    activity_builder = html.index("const activityRow")
    block = html[activity_builder:activity_builder + 1500]
    # The row is an expandable summary keyed for both the trail and the feed item.
    assert 'class="dash-row expandable-summary"' in block
    assert 'data-trail-id="' in block
    assert 'data-activity-key="' in block
    assert 'e.kind + ":" + e.id' in block
    # The Who acted column reads the staff name, a dash for an arrival or empty actor.
    assert 'dash(e.staff_name)' in block
    # A trailing caret cell and the shared detail block close the builder.
    assert 'class="dash-cell caret-cell"' in block
    assert "+ detailRow();" in block
    # The old inline links and Details button are gone from the row.
    assert "detailsButton(e)" not in html
    assert 'linkCell(e.salesforce_url' not in html


def test_clicking_an_expandable_row_toggles_its_detail() -> None:
    """A click or Enter or Space on a summary row toggles the paired detail row.

    The capture listener toggles a summary that is not a button, the link buttons
    run first and return so a Synced link click opens rather than expands, and a
    keydown handler gives the focusable row keyboard reach. The detail rows collapse
    to display none right after each render. See journal cnv-941/003.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const toggleRow = (summary) => {" in html
    assert 'const summary = target.closest(".expandable-summary");' in html
    # The caret menu host is excused alongside buttons, a menu item click
    # retargets to the canvas-menu-button host and must not toggle the row.
    assert 'if (summary && !target.closest("canvas-button, canvas-menu-button")) {' in html
    assert 'if (!summary || target.closest("canvas-button, canvas-menu-button")) return;' in html
    # The link branch returns before the toggle so a link click does not expand.
    assert 'window.open(extBtn.getAttribute("data-ext-url"), "_blank", "noopener,noreferrer");\n          return;' in html
    # Keyboard reach on Enter and Space, and Space is prevented from scrolling.
    assert 'if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;' in html
    assert "e.preventDefault();" in html
    # The detail rows are collapsed by an inline display sweep after render.
    assert "const collapseDetailRows = (container) => {" in html
    assert 'rows[i].style.display = "none";' in html


def test_inline_detail_carries_links_demographics_timeline_payload() -> None:
    """The expanded detail region holds everything the retired trail modal showed.

    The colspan detail cell carries a links wrap, a demographics wrap, a timeline
    list, and the raw payload accordion. populateRowDetail fills the links and, on
    the Activity path, the comparison synchronously, then the trail fetch fills the
    timeline, the payload, and, on the Synced path, the Canvas identity card. The
    trail modal is retired. See journal cnv-941/003.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The retired modal and its openers are gone.
    assert 'id="trail-modal"' not in html
    assert "const openTrail" not in html
    assert "const renderTrail =" not in html
    # The detail row skeleton carries the links, demographics, timeline, and the
    # hidden pre that stashes the raw payload for the modal.
    assert "const detailRow = () =>" in html
    assert 'class="row-detail-links"' in html
    assert 'class="row-detail-demographics"' in html
    assert "row-detail-trail" in html
    assert 'class="code-block row-detail-payload-json" hidden' in html
    # The populate path builds links, the comparison, the timeline, and the payload.
    assert "const populateRowDetail = async (detail, opts) => {" in html
    assert 'linkButton(opts.salesforceUrl, "Salesforce")' in html
    assert "buildCompareTable(opts.item)" in html
    assert "trail.map((t) => \"<li>\" + trailItemLine(t) + \"</li>\")" in html
    # The payload matcher receives the event id of whichever row expanded.
    assert "opts.item ? opts.item.event_id : (opts.record ? opts.record.event_id : null)" in html
    # The Synced path fills a Canvas identity card from the trail snapshot.
    assert "if (demo && !opts.item && !opts.record && hasAnyValue(data.canvas)) {" in html
    assert "buildCanvasIdentityTable(data.canvas)" in html


def test_raw_payload_opens_in_a_modal_from_the_links_bar() -> None:
    """The raw Salesforce payload rides a modal, opened from a button on the links bar.

    The inline accordion is gone. fillDetailPayload stashes the JSON on the hidden pre
    and grows the links bar with a Raw Salesforce payload button pushed to the far
    right. Clicking it prints the stashed JSON into the shared raw-payload-modal.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The dedicated modal carries the JSON sink inside a vertical scroll area.
    assert '<canvas-modal id="raw-payload-modal">' in html
    assert '<pre id="raw-payload-json" class="code-block"></pre>' in html
    # The button is added to the links bar and floated right by its own rule.
    assert 'class="row-detail-payload-btn"' in html
    assert ".row-detail-payload-btn { margin-left: auto; }" in html
    # The click handler reads the stashed JSON off the row and opens the modal.
    assert 'const payloadBtn = target.closest(".row-detail-payload-btn");' in html
    assert 'document.getElementById("raw-payload-modal").open();' in html


def test_compare_table_builder_has_three_view_types() -> None:
    """The Demographics comparison builder branches on what the row carries.

    The column shape follows what the row carries, not just whether anything applied.
    An applied modify is the only row with a Canvas before snapshot, so it reads as a
    four column before and after, Was in Canvas, What Salesforce sent, Written, the
    Written cell ambering on a real chart change and chipping on an operator override.
    An applied create or promote has no before, so it drops to three columns, What
    Salesforce sent and Written. Every other row reads as a two column What Salesforce
    sent list. The builder now feeds the inline detail rather than a modal. See
    journal cnv-928/037 and cnv-941/003.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The table builder branches on the two snapshots. A before plus applied is the
    # four column modify, applied alone is the three column create or promote, neither
    # is the two column arrival list.
    assert "const buildCompareTable = (item) => {" in html
    assert "if (applied && before) {" in html
    builder = html.index("const buildCompareTable")
    block = html[builder:builder + 2600]
    # The plain phrase headers read without a legend.
    assert 'headCell("Was in Canvas")' in block
    assert 'headCell("What Salesforce sent")' in block
    assert 'headCell("Written")' in block
    # Amber on Written where it differs from Was in Canvas, the chip where it differs
    # from What Salesforce sent.
    assert "const changed = wasVal !== writtenVal;" in block
    assert "const edited = sentVal !== writtenVal;" in block
    assert 'cell-changed' in block
    assert "EDITED_CHIP" in block
    # The chip is a blue mini badge, distinct from the amber cell and the red badge.
    assert (
        'const EDITED_CHIP = \' <canvas-badge color="blue" size="mini">Edited</canvas-badge>\';'
    ) in html
    # The old Received and Applied headers are gone from the builder.
    assert "Received</canvas-table-cell>" not in block
    assert "Applied</canvas-table-cell>" not in block
    # The fixed field order ships, and the row lookup map is filled.
    assert "const COMPARE_FIELDS = [" in html
    assert "let activityByKey = {};" in html
    for label in (
        '"Name"',
        '"Date of birth"',
        '"Sex at birth"',
        '"Email"',
        '"Phone"',
        '"Mobile"',
        '"Address"',
    ):
        assert label in html, f"missing comparison field {label}"


def test_synced_demographics_drops_to_one_canvas_column() -> None:
    """The Synced path shows a single Canvas identity card, not a comparison.

    A settled linked record offers no action, so the old Canvas against Salesforce
    comparison drove no decision and is dropped. The Synced trail render now paints a
    two column Field and Canvas card from the canvas snapshot alone, gated on the
    canvas snapshot carrying values. See journal cnv-928/037.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const buildCanvasIdentityTable = (canvas) => {" in html
    builder = html.index("const buildCanvasIdentityTable")
    block = html[builder:builder + 900]
    assert "Canvas</canvas-table-cell>" in block
    # The Salesforce column and the diff framing are gone from the Synced card.
    assert "Salesforce</canvas-table-cell>" not in block
    # The old comparison builder is gone entirely.
    assert "buildCanvasSalesforceTable" not in html
    # The inline detail gates on the canvas snapshot and paints the identity card on
    # the Synced path, which carries no feed item and no status row.
    assert "if (demo && !opts.item && !opts.record && hasAnyValue(data.canvas)) {" in html
    assert "buildCanvasIdentityTable(data.canvas)" in html


def test_promote_timeline_line_reads_as_one_self_contained_phrase() -> None:
    """A promote decision line names its modify origin in one phrase.

    The timeline used the shared Promoted to create label, leaving the from modify
    origin to the Event cell alone. The line now reads Promoted this modify to a
    create so the origin is plain in one place, while the Activity badge keeps the
    shorter shared label. See journal cnv-928/037.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const trailItemLine = (t) => {")
    end = html.index("const collapseDetailRows", start)
    block = html[start:end]
    assert 't.action_taken === "promoted_to_create"' in block
    assert '"Promoted this modify to a create"' in block
    # The shorter shared label still backs the Activity row badge.
    assert 'promoted_to_create: "Promoted to create"' in html


def test_render_activity_fills_the_row_lookup_map() -> None:
    """A reset read replaces the key map, a load more read extends it.

    The Details comparison reads the clicked row out of activityByKey, so the map
    must stay in sync with the rendered rows on both render paths. See journal
    cnv-928/023.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const renderActivity = (data, append) => {")
    end = html.index("const fetchActivity", start)
    body = html[start:end]
    assert "if (!append) activityByKey = {};" in body
    assert 'activityByKey[e.kind + ":" + e.id] = e;' in body


def test_action_rows_carry_the_event_id_for_per_event_targeting() -> None:
    """Story four threads the event id through the row action buttons.

    The per event queue can show more than one live event for a record, so the
    payload viewer and the resolution routes key on the event id, not the
    Salesforce id. The payload button is keyed by event id and the resolution
    POSTs append the event id query. See journal cnv-909/092 story four.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'data-event-id="' in html
    # The expandable records summary resolves its cached row by event id.
    assert 'data-record-key="\' + esc(row.event_id)' in html
    assert "rowByEventId[recordKey]" in html
    # The event id query helper threads it onto the resolution POSTs.
    assert "const eventQuery = (eventId) =>" in html
    assert '"?event_id=" + encodeURIComponent(eventId)' in html
    # The row map and the edit prefill map are keyed by event id.
    assert "rowByEventId[r.event_id]" in html
    assert "pendingByEventId[r.event_id]" in html


def test_patient_linked_delete_row_renders_a_delete_verb_button() -> None:
    """A linked delete row's verb is Delete, wired to the deactivation confirm.

    The per state delete builders collapsed into the one verb button. A delete
    event resolves to the Delete verb via data-delete-id, which opens the three
    radio deactivation confirm, and Skip stays on the row through the shared
    action cell. No Resolve menu survives. See journal cnv-938/018.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const verbButton = (row) => {")
    block = html[start:html.index("const eventBadge", start)]
    assert 'if (verb === "Delete")' in block
    assert "data-delete-id=" in block
    assert ">Delete</canvas-button>" in block
    assert "canvas-menu-button" not in block
    # Skip rides on every pending summary row, in the caret menu.
    assert "data-menu-skip-id=" in html


def test_delete_confirm_modal_renders_three_radio_methods() -> None:
    """Phase Two, journal cnv-909/107. The Delete confirmation modal holds three
    canvas radios, Tag deleted, Mark inactive, and Unlink only, in one group,
    plus a Cancel and a Delete button.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<canvas-modal id="delete-confirm-modal"' in html

    start = html.index('<canvas-modal id="delete-confirm-modal"')
    end = html.index("</canvas-modal>", start)
    modal_block = html[start:end]

    assert '<canvas-radio name="delete-method" label="Tag deleted" value="tag-deleted" checked>' in modal_block
    assert '<canvas-radio name="delete-method" label="Mark inactive" value="mark-inactive">' in modal_block
    assert '<canvas-radio name="delete-method" label="Unlink only" value="unlink-only">' in modal_block
    assert '<canvas-button id="delete-confirm-cancel"' in modal_block
    assert '<canvas-button id="delete-confirm-ok">Delete</canvas-button>' in modal_block
    # Canvas components only, no raw input or button primitives in the modal.
    assert "<input " not in modal_block
    assert "<button " not in modal_block
    assert "<select" not in modal_block


def test_delete_confirm_posts_to_the_route_for_each_radio_with_event_id() -> None:
    """Phase Two, journal cnv-909/107. Confirm reads the selected radio and posts
    to the matching deactivation route carrying the delete row event id through
    the shared event query helper. Tag deleted hits tag-deleted, Mark inactive
    hits mark-inactive, Unlink only hits unlink-only.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The Delete row button opens the confirmation, it does not post straight away.
    assert "openDeleteConfirm(deleteBtn.getAttribute" in html
    assert "const openDeleteConfirm = (id, eventId) => {" in html
    assert "const submitDeleteConfirm = async () => {" in html
    assert 'onBtnClick("delete-confirm-ok", submitDeleteConfirm);' in html
    assert 'onBtnClick("delete-confirm-cancel", cancelDeleteConfirm);' in html

    # Confirm dispatches to the poster matching the selected radio value.
    assert 'if (method === "mark-inactive") await markInactiveDirect(id, eventId);' in html
    assert 'else if (method === "unlink-only") await unlinkOnlyDirect(id, eventId);' in html
    assert "else await tagDeletedDirect(id, eventId);" in html

    # Each poster targets its own route and threads the event id query, so per
    # event targeting in _target_row acts on the exact delete row.
    assert '"/tag-deleted" + eventQuery(eventId)' in html
    assert '"/mark-inactive" + eventQuery(eventId)' in html
    assert '"/unlink-only" + eventQuery(eventId)' in html

    # Success is silent, the posters clear the banner and refresh rather than
    # raising a success banner or toast.
    assert "const markInactiveDirect = async (id, eventId) => {" in html


def test_delete_confirm_uses_capture_phase_click_wiring() -> None:
    """Phase Two, journal cnv-909/107. The confirmation buttons go through the
    shared onBtnClick capture phase wrapper, since canvas-button clicks do not
    bubble out of the shadow DOM, and the Delete row button rides the page
    content capture click delegation like the other row actions.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'onBtnClick("delete-confirm-ok", submitDeleteConfirm);' in html
    assert 'const deleteBtn = target.closest("canvas-button[data-delete-id]");' in html


def test_open_delete_confirm_clears_group_before_setting_default() -> None:
    """Journal cnv-909/111. Reopening the Delete dialog must show one selected
    radio. A programmatic check does not deselect siblings, so openDeleteConfirm
    unchecks every delete-method radio before checking the Tag deleted default,
    otherwise a prior selection stays checked alongside the default on reopen.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const openDeleteConfirm = (id, eventId) => {")
    end = html.index("const cancelDeleteConfirm", start)
    body = html[start:end]

    clear = body.index("radios[i].checked = false")
    set_default = body.index('canvas-radio[value="tag-deleted"]')
    # The group is cleared before the default is selected, not after.
    assert clear < set_default
    assert "for (let i = 0; i < radios.length; i++) radios[i].checked = false;" in body


def test_no_patient_delete_is_not_rendered_as_an_inert_row() -> None:
    """A delete with no Canvas patient drops off Records in the backend.

    There is no inert delete verb to render, the backend simply does not surface
    the row, so the operator never sees a dead Delete button. The collapsed
    builders and the Resolve menu stay gone, and no disabled verb path survives.
    See journal cnv-938/022.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The collapsed builders and the Resolve menu are gone for good. The only
    # menu button is the split action caret, never a Resolve list.
    assert "deleteNoPatientActionCell" not in html
    assert "deleteLinkedActionCell" not in html
    assert "deleteActionCell" not in html
    assert 'data-resolve-id="' not in html
    assert ">Resolve</canvas-button>" not in html

    # rowVerb still maps a delete event to the Delete verb, but there is no
    # disabled verb path anywhere.
    assert 'if (row.action === "delete") return "Delete";' in html
    assert "disabledVerbButton" not in html


def test_no_patient_delete_run_it_first_note_is_gone() -> None:
    """The delete run it first note is gone with the collapse.

    A delete with no Canvas patient drops off Records entirely, so there is no row
    to carry a run it first note. The note helper and the delete_blocked_by branch
    are removed. The unlinked modify promote note still rides in the Details
    context. See journal cnv-938/022.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The note helper and its wiring are gone.
    assert "const deleteBlockedText" not in html
    assert "blockedNoun" not in html
    assert "deleteBlockedText(row.delete_blocked_by)" not in html
    assert "row.delete_blocked_by" not in html

    # The pending summary still carries Skip plus the verb, through the split
    # action, the verb in the group and Skip in the caret menu.
    start = html.index("const splitAction = (row) =>")
    cell = html[start:html.index("const skippedRow", start)]
    assert "data-menu-skip-id=" in cell
    assert "verbButton(row)" in cell


def test_details_context_surfaces_the_unlinked_modify_note() -> None:
    """An unlinked modify shows its promote explanation in the Details context.

    The orange No patient chip and its flag column are gone, replaced by the
    disabled verb on the row. Only the longer sentence remains, in the Details
    modal top. See journal cnv-928/007 and cnv-938/018.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const buildDetailsContext = (row) => {" in html
    assert 'row.action === "modify" && !row.linked' in html
    assert "No Canvas patient is linked to this Salesforce record." in html
    # The chip is gone entirely under the unified inert model.
    assert ">No patient</canvas-badge>" not in html


def test_records_expand_fills_the_context_and_routes_demographics() -> None:
    """An expanded records row fills its context block and routes demographics.

    populateRowDetail paints the context banners, the hold reasons, the skip
    attribution, the promote note, and the overridden history, only when the
    expanded summary resolved a cached status row, then hands the demographics
    region to the records router. See journal cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'const ctx = root.querySelector(".row-detail-context");' in html
    assert (
        "ctx.innerHTML = buildDetailsContext(opts.record) + buildOverriddenBanner(opts.record);"
    ) in html
    assert "if (ctx && opts.record) {" in html
    assert "} else if (demo && opts.record) {" in html
    assert "fillRecordDemographics(demo, opts.record);" in html
    # The skeleton ships the context div ahead of the links bar.
    detail_row = html.index("const detailRow = () =>")
    block = html[detail_row:html.index("// The open in external glyph carrier", detail_row)]
    assert block.index('row-detail-context') < block.index('row-detail-links')


def test_records_expand_draws_canvas_now_versus_incoming_for_a_linked_modify() -> None:
    """A linked modify expand leads with the current chart against the incoming values.

    fillRecordDemographics fetches the live chart only for a linked modify and
    renders Canvas now against Incoming with the changed cue. Every other row
    shows the Received data list alone, so no empty Canvas column is ever drawn
    and the metadata fields stay visible. See journal cnv-928/037 and cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const fillRecordDemographics = async (demo, row) => {")
    block = html[start:html.index("// Fill an expanded detail block.", start)]
    assert 'if (row.action === "modify" && row.linked) {' in block
    assert "const data = await fetchCanvasCurrent(row.external_id);" in block
    assert '"Canvas now", "Incoming", canvas, rowIncomingSnapshot(row), true' in block
    # The fallback is the full received list with its title, metadata included.
    assert "Received data</h5>" in block
    assert "buildReceivedRows(row)" in block
    # The changed cue ambers a differing right cell.
    assert ".cell-changed" in html
    assert 'changed ? \' class="cell-changed"\' : ""' in html


def test_records_expand_carries_the_overridden_history_banner() -> None:
    """The expanded records detail shows the overridden chain for the newest row.

    The Details modal accordion item became an info banner in the context block,
    fed from the row's gap events, empty when the window is empty, reusing
    gapEventLine so the wording matches the apply step. See journal cnv-938/022
    and cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const buildOverriddenBanner = (row) => {")
    block = html[start:html.index("const fillRecordDemographics", start)]
    assert "row.gap && row.gap.events" in block
    assert 'if (!events.length) return "";' in block
    assert "row.gap.has_anchor" in block
    assert 'header="Overridden history"' in block
    assert "gapEventLine(e)" in block


def test_records_repaint_guards_and_mutation_close() -> None:
    """The records bodies skip the poll repaint while a detail row is open.

    render guards each records body on hasOpenDetail and collapses fresh detail
    rows after a repaint, the same idiom Synced and Activity use. A mutation
    closes any open records details first through refreshAfterAction, so the
    acted on row never lingers on screen under an open panel after it changed
    buckets. See journal cnv-941/004 and cnv-941/012.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert 'const pendingBody = document.getElementById("pending-body");' in html
    assert "if (!hasOpenDetail(pendingBody)" in html
    assert "collapseDetailRows(pendingBody);" in html
    assert 'const skippedBody = document.getElementById("skipped-body");' in html
    assert "if (!hasOpenDetail(skippedBody)" in html
    assert "collapseDetailRows(skippedBody);" in html

    assert "const closeRecordDetails = () => {" in html
    start = html.index("const refreshAfterAction = async () => {")
    block = html[start : html.index("};", start)]
    assert "closeRecordDetails();" in block


def test_verb_button_handles_create_modify_and_delete_in_one_builder() -> None:
    """The one verb button wires all three verbs, no per action builder.

    The separate create, modify, and delete builders collapsed into rowVerb plus
    verbButton, so the verb and its route are derived in one place from the live
    link, not branched per stored action or delete state. See journal cnv-938/018.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const createActionCell" not in html
    assert "const modifyActionCell" not in html
    assert "const deleteActionCell" not in html

    start = html.index("const verbButton = (row) => {")
    block = html[start:html.index("const eventBadge", start)]
    assert "data-create-id" in block
    assert "data-promote-id" in block
    assert "data-modify-edit-id" in block
    assert "data-delete-id" in block
    # The verb is derived from the live link, not the delete state.
    assert "delete_state" not in block


def test_linked_modify_offers_a_single_modify_verb_opening_the_edit_modal() -> None:
    """A linked modify row's verb is Modify, opening the editable audit modal.

    The verb for a linked sync is Modify, wired to the modify edit hook that
    opens the editable audit modal where the operator edits and commits. The old
    Apply and Review labels, the blind apply path, and the completeness gate are
    all gone. See journal cnv-928/040 041 and cnv-938/018.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The gate and its required field set are gone.
    assert "const APPLY_REQUIRED_FIELDS" not in html
    assert "const hasRequiredForApply" not in html
    assert "const applyButton" not in html

    start = html.index("const verbButton = (row) => {")
    block = html[start:html.index("const eventBadge", start)]
    # The Modify verb uses the modify edit hook.
    assert 'if (verb === "Modify")' in block
    assert "data-modify-edit-id=" in block
    assert ">Modify</canvas-button>" in block
    # The Review label and the blind apply button are both gone.
    assert ">Review</canvas-button>" not in html
    assert "data-apply-update-id=" not in html

    # The verb click opens the audit modal in modify mode, the edit and commit form.
    assert 'openAudit(editBtn.getAttribute("data-event-id"), "modify");' in html


def test_audit_modal_carries_the_one_history_banner_region() -> None:
    """The one history banner rides inside the audit modal.

    It shows on the create, modify, and promote forms. The separate stale warning
    banner folded into this one info banner, so there is a single history region
    rather than two stacked banners. See journal cnv-909/088 and cnv-938/022.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index('<canvas-modal id="audit-modal"')
    end = html.index("</canvas-modal>", start)
    modal_block = html[start:end]

    assert '<div id="gap-info" class="audit-gap" hidden>' in modal_block
    assert '<canvas-banner id="gap-banner" variant="info"' in modal_block
    assert 'id="gap-banner-body"' in modal_block
    # The separate stale banner is gone, its message folds into the gap banner.
    assert 'id="stale-info"' not in modal_block
    assert 'id="stale-banner"' not in modal_block


def test_gap_banner_detail_is_a_click_to_expand_disclosure() -> None:
    """The gap detail is a collapsed click to expand list, not a hover tooltip."""
    html = render_admin_page(plugin_name=PLUGIN)

    # A native button toggle, collapsed by default, controlling the event list.
    assert 'id="gap-banner-toggle"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="gap-banner-detail"' in html
    # The list is a real ul, hidden until the toggle opens it.
    assert 'id="gap-banner-detail" class="gap-event-list" hidden' in html
    # The retired hover mechanism is gone. The gap toggle itself is not a tooltip
    # trigger, it is a real button revealing the inline list. The Last name help
    # marker elsewhere on the page is a legitimate tooltip, so scope the check to
    # the gap toggle tag rather than the whole page.
    toggle_start = html.rindex("<", 0, html.index('id="gap-banner-toggle"'))
    toggle_tag = html[toggle_start : html.index(">", toggle_start) + 1]
    assert "data-canvas-tooltip" not in toggle_tag
    assert "Hover to see the events" not in html


def test_gap_banner_renderer_is_shipped_and_wired() -> None:
    """The one history renderer exists and the open paths call it.

    The gap banner reads on create, modify, and promote forms. The stale heads up
    folded into it, gated by an allowStale flag that is true only on a modify
    apply, a create has nothing to replay over. See journal cnv-909/089 question
    two and cnv-938/022.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const renderGapBanner = (gap, allowStale) => {" in html
    assert "const gapSummaryLine = (gap) => {" in html
    # The hover tooltip string builder retired, the list renders inline and the
    # toggle reveals it. See journal cnv-941/046.
    assert "const gapTooltipText" not in html
    assert "const gapEventListItems = (gap) => {" in html
    assert "const toggleGapDetail = () => {" in html
    assert 'onBtnClick("gap-banner-toggle", toggleGapDetail);' in html
    # The separate stale renderer is gone, it folded into renderGapBanner.
    assert "const renderStaleBanner" not in html
    # openAudit renders the gap for every mode, folding stale in only on modify.
    assert 'renderGapBanner(row.gap, mode === "modify");' in html
    # openPromote renders the gap from the pending row, with create events dropped
    # so it does not repeat the orange promote warning, and never the stale heads
    # up. See D1.
    assert "renderGapBanner(promoteRow && gapExcludingCreates(promoteRow.gap), false);" in html


def test_promote_gap_banner_excludes_create_events() -> None:
    """D1, journal cnv-909/098. On the promote form the orange warning owns the
    skipped or open create, so the gap banner filters create events out and hides
    when nothing else remains. The helper is shipped and wired into the promote
    open path.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert "const gapExcludingCreates = (gap) => {" in html
    assert 'filter((e) => e.action !== "create")' in html
    assert "renderGapBanner(promoteRow && gapExcludingCreates(promoteRow.gap), false);" in html


def test_blind_apply_confirmation_path_is_removed() -> None:
    """The blind apply confirmation modal and its wiring are gone.

    Collapsing the linked modify to a single Apply that opens the editable audit
    modal makes the old fast path unreachable, so its modal, state, renderers,
    handlers, and click branch are removed. The shared gap helpers stay, the audit
    modal gap banner still uses them. See journal cnv-928/040 and 041.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The confirmation modal and all its parts are gone.
    assert '<canvas-modal id="apply-confirm-modal"' not in html
    assert 'id="apply-confirm-accordion"' not in html
    assert 'id="apply-confirm-list"' not in html
    assert 'id="apply-confirm-stale"' not in html

    # The renderers, the open and submit handlers, and the blind apply fetch are gone.
    assert "renderApplyConfirmStale" not in html
    assert "renderApplyConfirmGap" not in html
    assert "openApplyConfirm" not in html
    assert "submitApplyConfirm" not in html
    assert "applyUpdateDirect" not in html
    assert 'onBtnClick("apply-confirm-ok"' not in html

    # The shared gap helpers survive for the audit modal gap banner.
    assert "const gapSummaryLine = (gap) => {" in html
    assert "const renderGapBanner = (gap, allowStale) => {" in html


def test_activity_has_a_left_aligned_load_more_button_not_a_truncated_note() -> None:
    """Journal cnv-928/005. The Activity tab pages with a Load more button that
    appends the next batch, replacing the old truncated note that dead ended the
    list at the cap.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    # The Load more button and its left aligned wrapper render, the old note is gone.
    assert 'id="activity-load-more"' in html
    assert ">Load 200 more</canvas-button>" in html
    assert 'id="activity-load-more-wrap"' in html
    assert "class=\"load-more-wrap\"" in html
    assert 'id="activity-truncated"' not in html
    assert ".load-more-wrap { margin-top:" in html

    # The button is wired through the capture phase click wrapper, not a bare listener.
    assert 'onBtnClick("activity-load-more", loadMoreActivity);' in html


def test_render_activity_appends_on_load_more_and_replaces_on_reset() -> None:
    """Journal cnv-928/005. A load more read appends to the table body, a reset
    read replaces it. The cursor and button follow has_more.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const renderActivity = (data, append) => {")
    end = html.index("const fetchActivity", start)
    body = html[start:end]

    # Append path adds rows, reset path replaces and re evaluates the empty state.
    assert 'insertAdjacentHTML("beforeend"' in body
    assert "toggleRegion(entries" in body
    # The cursor follows has_more and the button hides when there is no next page.
    assert "activityCursor = (data && data.has_more) ? data.next_cursor : null;" in body
    assert "wrap.hidden = !activityCursor;" in body

    # Load more sends the stored cursor, the first read sends none.
    fetch_start = html.index("const fetchActivity = async (cursor) => {")
    fetch_end = html.index("const loadMoreActivity", fetch_start)
    fetch_body = html[fetch_start:fetch_end]
    assert "before=" in fetch_body and "before_id=" in fetch_body
    assert "renderActivity(data, Boolean(cursor));" in fetch_body


def test_duplicate_check_skipped_in_modify_mode() -> None:
    """Journal cnv-932. A modify resolves its target through the Salesforce id
    link, so the duplicate matcher would find the linked patient itself and
    block Apply update behind the override. The check short circuits on modify,
    before the last name and birth date guard, and clears any matches so the
    submit gate stays open. Create and promote still run it.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    start = html.index("const runDuplicateCheck = async () => {")
    end = html.index("const scheduleDuplicateCheck", start)
    body = html[start:end]

    # The modify gate exists and short circuits with matches cleared.
    assert 'if (auditMode === "modify") {' in body
    gate = body.index('if (auditMode === "modify") {')
    later = body.index("if (!last ||")
    assert gate < later
    # Inside the gate the matches reset and the submit state refreshes before return.
    gate_body = body[gate:later]
    assert "duplicateMatches = [];" in gate_body
    assert "updateAuditSubmitState();" in gate_body
    assert "return;" in gate_body


def test_duplicate_checkbox_keeps_component_flex_layout() -> None:
    """Journal cnv-932. The canvas-checkbox host is inline-flex. A document rule
    that forced inline-block reflowed its shadow box and label as plain inline
    spans and collapsed the 17px box. The rule keeps only the spacing now.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    assert ".audit-duplicate canvas-checkbox { margin-top:" in html
    assert ".audit-duplicate canvas-checkbox { display: inline-block" not in html


def test_last_name_required_field_carries_a_help_tooltip() -> None:
    """The Last name requirement reads through a focusable help marker and tooltip.

    The hint line below the checkbox is gone. A small question mark marker sits
    after the label, carries the requirement text as a canvas-tooltip, and is
    focusable so the surface shows on keyboard focus as well as hover. The global
    canvas-tooltip host is placed once so the data attribute activates.
    """
    html = render_admin_page(plugin_name=PLUGIN)

    text = "Last name is always required to create a patient."
    assert "<canvas-tooltip></canvas-tooltip>" in html
    assert f'data-canvas-tooltip="{text}"' in html
    assert f'aria-label="{text}"' in html
    assert 'class="field-help" tabindex="0"' in html
    # The marker sits in the flex row beside the checkbox, not as a hint line.
    assert '<p class="settings-hint">' not in html


def test_settings_save_button_starts_disabled() -> None:
    """The Save settings button is disabled in the markup, dirty tracking enables it."""
    html = render_admin_page(plugin_name=PLUGIN)

    assert '<canvas-button id="settings-save" disabled>Save settings</canvas-button>' in html


def test_settings_form_wires_dirty_state_tracking() -> None:
    """Save enables when the form differs from the saved snapshot and disables when it matches."""
    html = render_admin_page(plugin_name=PLUGIN)

    # The snapshot helpers and the change wiring on the settings controls.
    assert "savedSettingsSnapshot" in html
    assert "const refreshSaveEnabled" in html
    assert "const markSettingsSaved" in html
    assert 'r.addEventListener("change", refreshSaveEnabled)' in html
    # A successful save re-snapshots so the button drops back to disabled.
    assert "markSettingsSaved();" in html
