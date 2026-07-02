"""Self-contained HTML for the admin application.

The page is rendered as a single HTML string. It loads the Canvas plugin design
system (``canvas-plugin-ui.css`` and ``canvas-plugin-ui.js``) plus the Lato font,
all served by ``SalesforceStatusAPI``, and builds the whole console out of
``<canvas-*>`` web components and Canvas design tokens so it reads as native next
to the Canvas home app. The page polls ``/status`` and exposes the copy-webhook
and view-payload affordances.
"""

from html import escape

# Stamped onto the design system asset URLs so every release forces the browser
# past any cached copy of the bundle. A stale bundle next to fresh page HTML is
# exactly the mix that broke the dashboard silently, the page referenced
# component features the cached bundle did not have. A test pins this constant
# to the manifest plugin_version so the two can never drift.
ASSET_VERSION = "0.0.103"

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Salesforce integration</title>
  <link href="https://fonts.googleapis.com/css?family=Lato:400,700,400italic,700italic&subset=latin" rel="stylesheet">
  <link rel="stylesheet" href="/plugin-io/api/__PLUGIN_NAME__/canvas-plugin-ui.css?v=__ASSET_VERSION__">
  <script src="/plugin-io/api/__PLUGIN_NAME__/canvas-plugin-ui.js?v=__ASSET_VERSION__"></script>
  <style>
    :root { --code-font: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
    [hidden] { display: none !important; }
    body { font-family: var(--font-family); padding: var(--space-huge); }
    .muted { color: var(--color-text-muted); }
    .col-fit { width: 1%; white-space: nowrap; }
    .card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: var(--space-medium);
      max-width: 960px;
    }
    .card-title { margin: 0 0 var(--space-small); }
    .section-title { margin: 0 0 var(--space-small); }
    .button-row { display: flex; gap: var(--space-mini); margin-top: var(--space-medium); flex-wrap: wrap; }
    .code-row { display: flex; align-items: center; gap: var(--space-tiny); margin: var(--space-tiny) 0; flex-wrap: wrap; }
    .hint { margin-top: var(--space-tiny); }
    .load-more-wrap { margin-top: var(--space-small); text-align: left; }
    .code-block {
      font-family: var(--code-font);
      font-size: 0.85714286rem;
      background: var(--color-bg);
      border: 1px solid var(--color-border);
      border-radius: var(--radius);
      padding: var(--space-tiny) var(--space-small);
      color: var(--color-text);
      overflow-wrap: anywhere;
    }
    .code-inline { font-family: var(--code-font); font-size: 0.92857143em; }
    .row-detail-context .skip-reason-label { margin: var(--space-small) 0 0; }
    .row-detail-context .skip-reason-text { margin: 0; }
    .details-kv-label { color: var(--color-text-muted); white-space: nowrap; }
    /* A value that differs from the baseline column to its left, the changed
       cue shared by every comparison surface. A soft amber wash, readable in
       both themes, falling back when the token is absent. See journal
       cnv-928/037. */
    .cell-changed { background: var(--color-warning-subtle, #fff4e5); }
    #page-content { margin-top: var(--space-large); }
    .settings-section { margin-top: var(--space-large); }
    .empty-state { padding: 0; text-align: left; }
    .empty-state h3 { margin: 0 0 var(--space-small); }
    .empty-state-inline { padding: var(--space-medium); }
    /* The two part action on Needs action, the verb plus the caret menu in
       one connected group. The group spans its cell and fluid stretches the
       verb to absorb the column slack, so the column reads flush while the
       caret stays content sized. The menu button child is outside the group's
       slotted radius rules, so it takes the right outer radius through the
       inherited custom property. The segments sit flush with no seam, the
       same continuous bar the showcase same color button group shows. See
       journal cnv-941/015. */
    .action-split { width: 100%; }
    /* The caret menu holds a single short action, so the panel drops the
       180px dropdown minimum and shrinks to its content, a tooltip sized
       panel hugging the caret. */
    .action-split canvas-menu-button {
      --canvas-button-radius: 0 var(--radius, .28571429rem) var(--radius, .28571429rem) 0;
      --canvas-menu-button-menu-min-width: 0;
    }
    /* The two trailing action cells on Skipped read as one pair, an 8px gap
       between the event badge and Reopen, the same gap the modal footer puts
       between its buttons, instead of the two full 0.7rem cell paddings that
       left them floating apart. */
    .dash-records .action-pair-lead { padding-right: 4px; }
    .dash-records .action-pair-tail { padding-left: 4px; }
    .audit-form { display: grid; gap: var(--space-small); }
    .audit-form .audit-row { display: grid; gap: var(--space-small); grid-template-columns: 1fr 1fr; }
    .audit-form canvas-input, .audit-form canvas-dropdown { max-width: 360px; }
    .audit-form .audit-row canvas-input, .audit-form .audit-row canvas-dropdown { max-width: 100%; }
    .audit-form .audit-field-full canvas-input, .audit-form .audit-field-full canvas-dropdown { max-width: 100%; }
    .audit-form .audit-label { display: block; font-weight: 700; margin-bottom: var(--space-mini); }
    .audit-form .audit-field { display: flex; flex-direction: column; }
    .audit-form .audit-metadata { margin-top: var(--space-tiny); }
    .audit-form .audit-metadata h5 { margin: 0 0 var(--space-mini); font-size: 0.92857143em; }
    .audit-form .audit-metadata dl { display: grid; grid-template-columns: max-content 1fr; gap: var(--space-mini) var(--space-small); margin: 0; }
    .audit-form .audit-metadata dt { color: var(--color-text-muted); }
    .audit-form .audit-metadata dd { margin: 0; }
    .audit-error { color: var(--color-error, #b00020); margin-top: var(--space-small); }
    .audit-error[hidden] { display: none !important; }
    label.audit-label.required::after {
      content: " *";
      color: #9f3a38;
      margin-left: 2px;
    }
    .audit-promote-warning { margin-bottom: var(--space-small); }
    .audit-promote-warning p { margin: 0 0 var(--space-mini); }
    .audit-promote-warning p:last-child { margin-bottom: 0; }
    .audit-gap { margin-bottom: var(--space-small); }
    .audit-gap p { margin: 0 0 var(--space-mini); }
    .audit-gap p:last-child { margin-bottom: 0; }
    /* The gap detail disclosure. A plain text trigger with a leading caret
       toggles an inline event list, collapsed by default, replacing the retired
       hover tooltip so the events are click and keyboard reachable. No button
       chrome, it reads as the accordion style expander the dashboard rows use.
       The caret flips a quarter turn on aria-expanded, which stays on this plain
       span so it is a direct style hook. See journal cnv-941/046. */
    .gap-detail-toggle { display: inline-flex; align-items: center; gap: var(--space-mini); margin-top: var(--space-tiny); cursor: pointer; color: rgba(0, 0, 0, 0.87); }
    .gap-detail-toggle:focus-visible { outline: 2px solid var(--color-primary, #2185d0); outline-offset: 2px; }
    .gap-detail-caret { flex: none; transition: transform 0.1s ease; transform: rotate(-90deg); }
    .gap-detail-toggle[aria-expanded="true"] .gap-detail-caret { transform: rotate(0deg); }
    .gap-event-list { margin: var(--space-mini) 0 0; padding-left: var(--space-medium); }
    .gap-event-list li { margin: 0 0 var(--space-mini); }
    .gap-event-list li:last-child { margin-bottom: 0; }
    .trail-list { margin: var(--space-small) 0 0; padding-left: var(--space-medium); }
    .trail-list li { margin-bottom: var(--space-small); }
    .trail-list .trail-detail { color: var(--color-text-muted); }
    .audit-duplicate ul { margin: var(--space-mini) 0; padding-left: 1.2em; }
    .audit-duplicate li a { color: var(--color-primary, #2185d0); }
    /* No display override here. The component host is inline-flex, and forcing
       inline-block reflows its shadow box and label as plain inline spans, which
       drops the 17px box to zero. Keep only the spacing. */
    .audit-duplicate canvas-checkbox { margin-top: var(--space-small); }
    .ext-link { color: var(--color-primary, #2185d0); text-decoration: none; }
    .ext-link:hover { text-decoration: underline; }
    .ext-btn-icon { margin-left: var(--space-mini, 4px); vertical-align: -1px; }
    /* The Sync automation card sits in its own section below the Connection and
       Webhook pair rather than inside their grid, so its taller control stack
       never stretches the two short cards through equalizeSettingsCards. Capped
       so the controls do not run edge to edge on a full width page. */
    #sync-automation-section { max-width: 520px; }
    .settings-form { display: grid; gap: var(--space-medium); }
    .settings-group { display: flex; flex-direction: column; gap: var(--space-mini); }
    .settings-group-title { font-weight: 700; margin: 0 0 var(--space-tiny); }
    /* Field mapping editor. The picker row keeps the dropdown and its active
       state badge on one line, the editor below caps its width like the sync
       card so the inputs never run edge to edge. A cleared Salesforce input dims
       its row and reveals the will not sync hint, so dropping a target from the
       map is visible before the operator saves rather than silent. */
    #field-mapping-section { max-width: 640px; }
    .mapping-profile-row { display: flex; align-items: center; gap: var(--space-small); flex-wrap: wrap; }
    /* canvas-dropdown sizes its menu to the trigger and the trigger to its label,
       so a short label like Default leaves the menu too narrow for the longer
       options and their badges, which then truncate. Widen the host so both the
       trigger and the menu have room for Custom plus its Customizable badge. */
    #mapping-profile { width: 248px; }
    .mapping-hint { margin: var(--space-tiny) 0 0; }
    .mapping-actions { align-items: center; }
    .mapping-actions-spacer { flex: 1 1 auto; }
    .mapping-top-actions { display: flex; gap: var(--space-mini); align-items: center; }
    .mapping-input { width: 100%; }
    .mapping-clear-hint { display: none; margin-top: var(--space-tiny); font-size: var(--font-size-small, 0.85rem); color: var(--color-text-secondary, rgba(0,0,0,0.6)); }
    .mapping-row-cleared .mapping-clear-hint { display: block; }
    .mapping-row-cleared { opacity: 0.55; }
    /* The Last name required field carries a small help marker after its label
       instead of a hint line below it. The checkbox host is inline-flex and hugs
       its content, so the row is a flex line that lands the marker just past the
       label with a small gap. The marker is focusable so the canvas-tooltip
       surfaces on keyboard focus as well as hover. */
    .required-field-row { display: flex; align-items: center; gap: var(--space-small); }
    .field-help {
      display: inline-flex; align-items: center; justify-content: center;
      width: 16px; height: 16px; border-radius: 50%;
      border: 1px solid var(--color-border, #d4d4d5);
      color: var(--text-secondary, #6b7280);
      font-size: 0.6875rem; font-weight: 700; line-height: 1;
      cursor: help; flex: none; user-select: none;
    }
    .field-help:focus-visible { outline: 2px solid var(--color-primary, #2185d0); outline-offset: 2px; }
    #delete-action-group[data-disabled] { opacity: 0.5; }
    .hold-reasons { margin: var(--space-mini) 0 0; padding-left: 1.2em; }
    /* The dashboard tables are div grids, not canvas-table, so an expanded detail
       can span the full width that a CSS table cell cannot. Each table is one grid
       and every row joins it through subgrid, so all rows share a single set of
       column tracks and the max-content columns size to the longest cell anywhere
       in the table, header included, exactly like a native table. The caret leads
       every table in its fixed box, and one column keeps a floor and takes the
       leftover width. Each grid sizes to its tracks, never below the visible
       width, so every row border and hover background spans the full scrollable
       width instead of stopping at the viewport edge when the table is scrolled
       sideways. See journal cnv-941/007, cnv-941/009, cnv-941/010, and
       cnv-941/012. */
    .dash-activity, .dash-synced, .dash-records { display: grid; width: max-content; min-width: 100%; }
    /* Activity, the caret, four content sized columns, Who acted expands. */
    .dash-activity { grid-template-columns: 36px max-content max-content max-content max-content minmax(160px, 1fr); }
    /* Synced, the caret, five content sized demographics, Last synced expands. The
       Salesforce and chart links live in the expanded detail links bar, not in
       summary columns. */
    .dash-synced { grid-template-columns: 36px max-content max-content max-content max-content max-content minmax(160px, 1fr); }
    /* Needs action and Skipped share the lead shape, the caret, four content
       sized demographics, then Phone number holding the stretch so it absorbs
       the row slack mid table, then Received. Skipped closes with two action
       columns, the event badge and Reopen. Needs action closes with a single
       action column holding the two part verb and caret button, so it carries
       its own eight track template. See journal cnv-941/015. */
    .dash-records { grid-template-columns: 36px max-content max-content max-content max-content minmax(160px, 1fr) max-content max-content max-content; }
    .dash-records-pending { grid-template-columns: 36px max-content max-content max-content max-content minmax(160px, 1fr) max-content max-content; }
    /* Rows span all columns and inherit the shared tracks. Cells never wrap, nowrap
       inherits to the header spans and the cells alike, and since the columns grow
       to fit their longest cell nothing ever bleeds. A panel narrower than the track
       total scrolls horizontally through the scroll area. */
    .dash-row { display: grid; grid-template-columns: subgrid; grid-column: 1 / -1; align-items: center; white-space: nowrap; }
    /* The body wrapper steps out of layout so summary rows and detail blocks are
       direct grid items. Its border selector still matches, display contents does
       not affect selector matching. */
    .dash-body { display: contents; }
    .dash-head { font-weight: 700; border-bottom: 2px solid var(--color-border); }
    .dash-head > span { padding: 0.5rem 0.7rem; }
    .dash-body .dash-row { border-bottom: 1px solid rgba(34, 36, 38, 0.1); }
    .dash-cell { padding: 0.35rem 0.7rem; min-width: 0; overflow-wrap: anywhere; }
    .caret-cell { display: flex; align-items: center; justify-content: center; color: #212121; }
    /* The summary row is the click to expand control, lit light gray on hover, with
       a rotating caret. The detail collapses through a JS inline display toggle. */
    /* Every summary row shares one floor so the four tables read as a single set.
       Needs action and Skipped carry an xs canvas-button in their trailing cell,
       29.83px tall, which lands the row near 42px once the 11.2px of shared cell
       padding is added. The text only Synced and Activity rows have no button and
       fall short, Synced to 31px and Activity to 36px, which is what made the
       dashboard read as two sets. The 41px floor is that button height plus the
       shared cell padding, so the text rows rise to the records height while the
       taller button rows stay put, their natural content already clears the floor.
       See journal cnv-941/027. */
    .dash-row.expandable-summary { min-height: 41px; }
    .expandable-summary { cursor: pointer; }
    .expandable-summary:hover { background: #f5f5f5; }
    .expandable-summary:focus-visible { outline: 2px solid var(--color-primary, #2185d0); outline-offset: -2px; }
    /* The exact chevron the canvas-accordion uses, a filled triangle in a centered
       10px box. Collapsed it points right at rotate(-90deg), expanded it rotates to
       point down, matching the accordion open state. */
    .caret-icon { display: inline-flex; align-items: center; justify-content: center; width: 10px; height: 10px; transition: transform 0.1s ease; transform: rotate(-90deg); }
    .expandable-summary.expanded .caret-icon { transform: rotate(0deg); }
    /* The detail block spans the full row width. It crosses the flexible track of
       its table, so its content is excluded from the intrinsic sizing of the
       max-content columns and a wide payload never widens the data columns. */
    .dash-detail { grid-column: 1 / -1; border-bottom: 1px solid rgba(34, 36, 38, 0.1); padding: 0 0.7rem; }
    .row-detail { padding: var(--space-small) 0 var(--space-medium); }
    /* The records only context block above the links bar, the hold reasons, skip
       attribution, promote note, and overridden history banners. Empty on the
       Activity and Synced paths, where it takes no space. */
    .row-detail-context:not(:empty) { display: grid; gap: var(--space-small); margin-bottom: var(--space-medium); white-space: normal; }
    .row-detail-links { display: flex; align-items: center; gap: var(--space-small); margin-bottom: var(--space-medium); }
    /* The raw payload trigger sits on the same line as the Salesforce and chart
       links but pushed to the far right, so the link pair stays left and the payload
       button anchors the opposite end. */
    .row-detail-payload-btn { margin-left: auto; }
    /* Demographics on the left, the record timeline on the right, collapsing to one
       column when the row is too narrow to hold both. */
    .row-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--space-large); align-items: start; }
    .row-detail-title { margin: 0 0 var(--space-small); font-size: 0.92857143em; }
    .row-detail .trail-list { margin: 0; }
    .row-detail-payload-json { white-space: pre-wrap; word-break: break-word; margin: 0; }
  </style>
</head>
<body>
  <h1>Salesforce integration</h1>

  <div id="error-region"></div>

  <canvas-tooltip></canvas-tooltip>

  <canvas-loader id="initial-loader" size="large" centered text="Loading"></canvas-loader>

  <div id="page-content" hidden>
    <canvas-tabs>
      <canvas-tab id="tab-records" for="panel-records" active>
        <canvas-tab-label>Records</canvas-tab-label>
      </canvas-tab>
      <canvas-tab id="tab-activity" for="panel-activity">
        <canvas-tab-label>Activity</canvas-tab-label>
      </canvas-tab>
      <canvas-tab id="tab-settings" for="panel-settings">
        <canvas-tab-label>Settings</canvas-tab-label>
      </canvas-tab>

      <canvas-tab-panel id="panel-records">
        <canvas-accordion aria-label="Inbound Salesforce records">
          <canvas-accordion-item id="pending-item" open>
            <canvas-accordion-title>
              <span>Needs action</span>
              <canvas-badge id="pending-count-badge" size="mini" basic>0</canvas-badge>
            </canvas-accordion-title>
            <canvas-accordion-content>
              <div id="pending-empty" class="empty-state" hidden>
                <h3>No records awaiting review</h3>
                <p class="muted">Inbound Salesforce records appear here once they are captured.</p>
              </div>
              <canvas-scroll-area id="pending-scroll" horizontal aria-label="Pending Salesforce records" style="max-width: 100%" hidden>
                <div class="dash-records dash-records-pending" role="table" aria-label="Needs action">
                  <div class="dash-head dash-row" role="row">
                    <span></span>
                    <span>First name</span>
                    <span>Last name</span>
                    <span>Date of birth</span>
                    <span>Sex at birth</span>
                    <span>Phone number</span>
                    <span>Received</span>
                    <span></span>
                  </div>
                  <div id="pending-body" class="dash-body"></div>
                </div>
              </canvas-scroll-area>
            </canvas-accordion-content>
          </canvas-accordion-item>

          <canvas-accordion-item id="skipped-item" open>
            <canvas-accordion-title>
              <span>Skipped</span>
              <canvas-badge id="skipped-count-badge" size="mini" basic>0</canvas-badge>
            </canvas-accordion-title>
            <canvas-accordion-content>
              <div id="skipped-empty" class="empty-state" hidden>
                <h3>Nothing skipped</h3>
                <p class="muted">Records you skip land here. Reopen one to return it to Needs action.</p>
              </div>
              <canvas-scroll-area id="skipped-scroll" horizontal aria-label="Skipped Salesforce records" style="max-width: 100%" hidden>
                <div class="dash-records" role="table" aria-label="Skipped">
                  <div class="dash-head dash-row" role="row">
                    <span></span>
                    <span>First name</span>
                    <span>Last name</span>
                    <span>Date of birth</span>
                    <span>Sex at birth</span>
                    <span>Phone number</span>
                    <span>Received</span>
                    <span></span>
                    <span></span>
                  </div>
                  <div id="skipped-body" class="dash-body"></div>
                </div>
              </canvas-scroll-area>
            </canvas-accordion-content>
          </canvas-accordion-item>

          <canvas-accordion-item id="synced-item">
            <canvas-accordion-title>
              <span>Synced</span>
              <canvas-badge id="synced-count-badge" size="mini" basic>0</canvas-badge>
            </canvas-accordion-title>
            <canvas-accordion-content>
              <p class="muted">Salesforce contacts linked to a Canvas patient, most recently synced first. Click a row to expand the Salesforce record link, the patient chart link, the Canvas identity, the record timeline, and the raw payload.</p>
              <div id="synced-empty" class="empty-state" hidden>
                <h3>No synced patients yet</h3>
                <p class="muted">A contact appears here once it is created or applied as a Canvas patient.</p>
              </div>
              <canvas-scroll-area id="synced-scroll" horizontal aria-label="Synced patients" style="max-width: 100%" hidden>
                <div class="dash-synced" role="table">
                  <div class="dash-head dash-row" role="row">
                    <span></span>
                    <span>First name</span>
                    <span>Last name</span>
                    <span>Date of birth</span>
                    <span>Sex at birth</span>
                    <span>Phone number</span>
                    <span>Last synced</span>
                  </div>
                  <div id="synced-body" class="dash-body"></div>
                </div>
              </canvas-scroll-area>
            </canvas-accordion-content>
          </canvas-accordion-item>
        </canvas-accordion>
      </canvas-tab-panel>

      <canvas-tab-panel id="panel-activity">
        <section class="settings-section" id="activity-section">
          <h4 class="section-title">Activity</h4>
          <p class="muted">Every arrival and decision, newest first. Click a row to expand the Salesforce record link, the patient chart link, who acted, the received versus applied comparison, the record timeline, and the raw Salesforce payload.</p>
          <div id="activity-empty" class="empty-state" hidden>
            <h3>No activity recorded yet</h3>
            <p class="muted">Accept, apply, skip, reopen, and delete resolutions all appear here once they happen.</p>
          </div>
          <canvas-scroll-area id="activity-scroll" horizontal aria-label="Activity ledger" style="max-width: 100%" hidden>
            <div class="dash-activity" role="table">
              <div class="dash-head dash-row" role="row">
                <span></span>
                <span>When</span>
                <span>Action</span>
                <span>Event</span>
                <span>Patient</span>
                <span>Who acted</span>
              </div>
              <div id="activity-body" class="dash-body"></div>
            </div>
          </canvas-scroll-area>
          <div id="activity-load-more-wrap" class="load-more-wrap" hidden>
            <canvas-button id="activity-load-more" variant="ghost">Load 200 more</canvas-button>
          </div>
        </section>
      </canvas-tab-panel>

      <canvas-tab-panel id="panel-settings">
        <div class="card-grid">
          <canvas-card>
            <canvas-card-body>
              <h4 class="card-title">Webhook</h4>
              <p class="muted">Configure this URL in your Salesforce Flow HTTP Callout.</p>
              <div class="code-row">
                <code id="webhook-url" class="code-block"></code>
                <canvas-button id="copy-webhook-btn" variant="ghost">Copy</canvas-button>
              </div>
              <p class="muted hint">Send it with the header <code class="code-inline">X-Signature: sha256=&lt;HMAC-SHA256 of the body keyed by SF_WEBHOOK_SECRET&gt;</code></p>
            </canvas-card-body>
          </canvas-card>
        </div>

        <section class="settings-section" id="sync-automation-section">
          <h4 class="section-title">Sync automation</h4>
          <p class="muted">Decide which inbound Salesforce events apply on their own. Anything that does not qualify holds on the Records tab for a human to review.</p>
          <div id="settings-error" class="audit-error" hidden></div>
          <canvas-card>
            <canvas-card-body>
              <div class="settings-form">
                <div class="settings-group">
                  <p class="settings-group-title">Apply automatically</p>
                  <canvas-checkbox id="set-auto-create" label="Create new patients"></canvas-checkbox>
                  <canvas-checkbox id="set-auto-modify" label="Update linked patients"></canvas-checkbox>
                  <canvas-checkbox id="set-auto-delete" label="Process deletes on linked patients"></canvas-checkbox>
                </div>
                <div class="settings-group" id="delete-action-group">
                  <p class="settings-group-title">When a delete applies</p>
                  <canvas-radio name="settings-delete-action" value="mark_inactive" label="Mark inactive"></canvas-radio>
                  <canvas-radio name="settings-delete-action" value="tag_deleted" label="Tag deleted"></canvas-radio>
                  <canvas-radio name="settings-delete-action" value="unlink" label="Unlink only"></canvas-radio>
                </div>
                <div class="settings-group">
                  <p class="settings-group-title">Require these fields before applying</p>
                  <canvas-checkbox data-required-field="first_name" label="First name"></canvas-checkbox>
                  <div class="required-field-row">
                    <canvas-checkbox data-required-field="last_name" label="Last name" checked disabled></canvas-checkbox>
                    <span class="field-help" tabindex="0" aria-label="Last name is always required to create a patient." data-canvas-tooltip="Last name is always required to create a patient.">?</span>
                  </div>
                  <canvas-checkbox data-required-field="date_of_birth" label="Date of birth"></canvas-checkbox>
                  <canvas-checkbox data-required-field="sex_at_birth" label="Sex at birth"></canvas-checkbox>
                  <canvas-checkbox data-required-field="email" label="Email"></canvas-checkbox>
                  <canvas-checkbox data-required-field="phone" label="Phone"></canvas-checkbox>
                </div>
                <div class="settings-group">
                  <p class="settings-group-title">Validation rules</p>
                  <canvas-checkbox id="set-address-group" label="Hold when the address is only partly filled in"></canvas-checkbox>
                  <canvas-checkbox id="set-validity" label="Hold when a value fails a basic format check"></canvas-checkbox>
                </div>
                <div class="button-row">
                  <canvas-button id="settings-save" disabled>Save settings</canvas-button>
                </div>
              </div>
            </canvas-card-body>
          </canvas-card>
        </section>

        <section class="settings-section" id="field-mapping-section">
          <h4 class="section-title">Field mapping</h4>
          <p class="muted">Choose which mapping the sync uses. Default and Secret are read only. Custom is editable on the Salesforce side.</p>
          <div id="mapping-error" class="audit-error" hidden></div>
          <canvas-card>
            <canvas-card-body>
              <div class="settings-group">
                <p class="settings-group-title">Active profile</p>
                <div class="mapping-profile-row">
                  <canvas-dropdown id="mapping-profile" name="mapping-profile" aria-label="Active field mapping profile">
                    <canvas-option value="default" label="Default">Default</canvas-option>
                    <canvas-option value="secret" label="Secret" __SECRET_OPTION_DISABLED__>Secret __SECRET_OPTION_BADGE__</canvas-option>
                    <canvas-option value="custom" label="Custom">Custom <canvas-badge color="blue" size="mini">Customizable</canvas-badge></canvas-option>
                  </canvas-dropdown>
                  <canvas-badge id="mapping-active-badge" size="mini" hidden></canvas-badge>
                  <span class="mapping-actions-spacer"></span>
                  <div class="mapping-top-actions">
                    <canvas-button id="mapping-edit" variant="ghost" size="sm" hidden>Edit</canvas-button>
                    <canvas-button id="mapping-copy-defaults" variant="ghost" size="sm" hidden>Copy in defaults</canvas-button>
                    <canvas-button id="mapping-copy-secret" variant="ghost" size="sm" hidden __COPY_SECRET_DISABLED__>Copy in secret</canvas-button>
                  </div>
                </div>
                <p id="mapping-profile-hint" class="mapping-hint muted"></p>
              </div>
              <div id="mapping-empty" class="empty-state-inline" hidden>
                <p class="muted">No field mapping configured.</p>
              </div>
              <canvas-table id="mapping-table" aria-label="Field mapping" hidden>
                <canvas-table-head>
                  <canvas-table-row>
                    <canvas-table-cell>Salesforce field</canvas-table-cell>
                    <canvas-table-cell>Canvas target</canvas-table-cell>
                  </canvas-table-row>
                </canvas-table-head>
                <canvas-table-body id="mapping-body"></canvas-table-body>
              </canvas-table>
              <div class="button-row mapping-actions" id="mapping-bottom-actions" hidden>
                <span class="mapping-actions-spacer"></span>
                <canvas-button id="mapping-cancel" variant="ghost">Cancel</canvas-button>
                <canvas-button id="mapping-save" disabled>Save mapping</canvas-button>
              </div>
            </canvas-card-body>
          </canvas-card>
        </section>
      </canvas-tab-panel>
    </canvas-tabs>
  </div>

  <canvas-modal id="raw-payload-modal">
    <canvas-modal-header dismissable>Raw Salesforce payload</canvas-modal-header>
    <canvas-modal-content>
      <canvas-scroll-area vertical aria-label="Raw Salesforce payload JSON" style="max-height: 60vh">
        <pre id="raw-payload-json" class="code-block"></pre>
      </canvas-scroll-area>
    </canvas-modal-content>
  </canvas-modal>

  <canvas-modal id="mark-inactive-modal" size="small" persistent>
    <canvas-modal-header>Mark patient inactive</canvas-modal-header>
    <canvas-modal-content>
      <p>This will mark the Canvas patient inactive. The patient stops appearing in default Canvas search, but the record stays in the database and can be reactivated.</p>
    </canvas-modal-content>
    <canvas-modal-footer>
      <canvas-button id="mark-inactive-cancel" variant="ghost">Cancel</canvas-button>
      <canvas-button id="mark-inactive-confirm">Mark inactive</canvas-button>
    </canvas-modal-footer>
  </canvas-modal>

  <canvas-modal id="audit-modal" persistent>
    <canvas-modal-header id="audit-modal-header" dismissable>Review and create patient</canvas-modal-header>
    <canvas-modal-content>
      <p id="audit-modal-intro" class="muted">Edit any field before creating the Canvas patient. The Salesforce record id is preserved on the new patient.</p>
      <div id="promote-warning" class="audit-promote-warning" hidden>
        <canvas-banner id="promote-banner" variant="warning" header="Heads up">
          <p id="promote-warning-body"></p>
          <p id="promote-warning-prefill" class="muted hint" hidden></p>
        </canvas-banner>
      </div>
      <div id="gap-info" class="audit-gap" hidden>
        <canvas-banner id="gap-banner" variant="info" header="Unresolved history">
          <p id="gap-banner-body"></p>
          <div class="hint" hidden id="gap-banner-detail-wrap">
            <span id="gap-banner-toggle" class="gap-detail-toggle" role="button" tabindex="0" aria-expanded="false" aria-controls="gap-banner-detail">
              <svg class="gap-detail-caret" width="10" height="6" viewBox="0 0 10 6" fill="currentColor" aria-hidden="true" focusable="false"><path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"></path></svg>
              <span id="gap-banner-toggle-label">The events in this gap</span>
            </span>
            <ul id="gap-banner-detail" class="gap-event-list" hidden></ul>
          </div>
        </canvas-banner>
      </div>
      <div class="audit-form">
        <div class="audit-row">
          <div class="audit-field">
            <label class="audit-label required" for="audit-first-name">First name</label>
            <canvas-input id="audit-first-name" name="first_name" required></canvas-input>
          </div>
          <div class="audit-field">
            <label class="audit-label required" for="audit-last-name">Last name</label>
            <canvas-input id="audit-last-name" name="last_name" required></canvas-input>
          </div>
        </div>
        <div class="audit-row">
          <div class="audit-field">
            <label class="audit-label required" for="audit-dob">Date of birth</label>
            <canvas-input id="audit-dob" name="date_of_birth" type="date"></canvas-input>
          </div>
          <div class="audit-field">
            <label class="audit-label required" for="audit-sex">Sex at birth</label>
            <canvas-dropdown id="audit-sex" name="sex_at_birth" placeholder="Select">
              <canvas-option value="">Select</canvas-option>
              <canvas-option value="female">Female</canvas-option>
              <canvas-option value="male">Male</canvas-option>
              <canvas-option value="other">Other</canvas-option>
              <canvas-option value="unknown">Unknown</canvas-option>
            </canvas-dropdown>
          </div>
        </div>
        <div class="audit-field audit-field-full">
          <label class="audit-label" for="audit-email">Email</label>
          <canvas-input id="audit-email" name="email" type="email"></canvas-input>
        </div>
        <div class="audit-row">
          <div class="audit-field">
            <label class="audit-label" for="audit-phone">Phone</label>
            <canvas-input id="audit-phone" name="phone" type="tel" format="phone" placeholder="(000) 000-0000"></canvas-input>
          </div>
          <div class="audit-field">
            <label class="audit-label" for="audit-mobile">Mobile phone</label>
            <canvas-input id="audit-mobile" name="telecom_mobile" type="tel" format="phone" placeholder="(000) 000-0000"></canvas-input>
          </div>
        </div>
        <div class="audit-row">
          <div class="audit-field">
            <label class="audit-label" for="audit-address-1">Address line 1</label>
            <canvas-input id="audit-address-1" name="address_line_1"></canvas-input>
          </div>
          <div class="audit-field">
            <label class="audit-label" for="audit-address-2">Address line 2</label>
            <canvas-input id="audit-address-2" name="address_line_2"></canvas-input>
          </div>
        </div>
        <div class="audit-row">
          <div class="audit-field">
            <label class="audit-label" for="audit-city">City</label>
            <canvas-input id="audit-city" name="city"></canvas-input>
          </div>
          <div class="audit-field">
            <label class="audit-label" for="audit-state">State</label>
            <canvas-input id="audit-state" name="state"></canvas-input>
          </div>
        </div>
        <div class="audit-row">
          <div class="audit-field">
            <label class="audit-label" for="audit-postal">Postal code</label>
            <canvas-input id="audit-postal" name="postal_code"></canvas-input>
          </div>
          <div class="audit-field">
            <label class="audit-label" for="audit-country">Country</label>
            <canvas-input id="audit-country" name="country"></canvas-input>
          </div>
        </div>
        <div id="audit-metadata-block" class="audit-metadata" hidden>
          <h5>Additional metadata that will be attached</h5>
          <dl id="audit-metadata-list"></dl>
        </div>
        <div id="duplicate-warning" class="audit-duplicate" hidden>
          <canvas-banner variant="warning" header="Potential duplicate patient">
            <p>It looks like this patient might already exist in Canvas. Check the records of the patients listed below and make sure it is not a duplicate.</p>
            <ul id="duplicate-warning-list"></ul>
            <canvas-checkbox id="duplicate-override" label="This is not a duplicate patient"></canvas-checkbox>
          </canvas-banner>
        </div>
        <p id="audit-error" class="audit-error" role="alert" hidden></p>
      </div>
    </canvas-modal-content>
    <canvas-modal-footer>
      <canvas-button id="audit-cancel" variant="ghost">Cancel</canvas-button>
      <canvas-button id="audit-confirm-open" variant="secondary">Add and open</canvas-button>
      <canvas-button id="audit-confirm">Add</canvas-button>
    </canvas-modal-footer>
  </canvas-modal>

  <canvas-modal id="skip-modal" size="small" persistent>
    <canvas-modal-header>Skip this record</canvas-modal-header>
    <canvas-modal-content>
      <p>This marks the record as Skipped. It moves to the Skipped list, where you can reopen it later. The Canvas patient is not created.</p>
      <canvas-textarea id="skip-reason" label="Reason for skipping (optional)" placeholder="Add a short reason so the next reviewer knows why this was skipped" rows="3"></canvas-textarea>
    </canvas-modal-content>
    <canvas-modal-footer>
      <canvas-button id="skip-cancel" variant="ghost">Cancel</canvas-button>
      <canvas-button id="skip-confirm">Skip</canvas-button>
    </canvas-modal-footer>
  </canvas-modal>

  <canvas-modal id="delete-confirm-modal" size="small" persistent>
    <canvas-modal-header>Delete this patient</canvas-modal-header>
    <canvas-modal-content>
      <p>This Salesforce contact is flagged Delete. Pick how to handle the linked Canvas patient. This is a permanent change.</p>
      <div class="delete-confirm-options" style="display: flex; flex-direction: column; gap: var(--space-mini); margin-top: var(--space-small)">
        <canvas-radio name="delete-method" label="Tag deleted" value="tag-deleted" checked></canvas-radio>
        <canvas-radio name="delete-method" label="Mark inactive" value="mark-inactive"></canvas-radio>
        <canvas-radio name="delete-method" label="Unlink only" value="unlink-only"></canvas-radio>
      </div>
    </canvas-modal-content>
    <canvas-modal-footer>
      <canvas-button id="delete-confirm-cancel" variant="ghost">Cancel</canvas-button>
      <canvas-button id="delete-confirm-ok">Delete</canvas-button>
    </canvas-modal-footer>
  </canvas-modal>


  <script>
    (function () {
      const pluginPrefix = "/plugin-io/api/__PLUGIN_NAME__";
      let firstLoaded = false;
      // Story four keys the payload viewer and the edit prefill by event id,
      // not Salesforce id, because the per event queue can show more than one
      // live event for a record at once, so the Salesforce id is no longer a
      // unique row key. See journal cnv-909/092 story four.
      let rowByEventId = {};
      let pendingByEventId = {};
      let pendingSkipExternalId = null;
      let pendingSkipEventId = null;
      let pendingAuditExternalId = null;
      let pendingAuditEventId = null;
      let pendingMarkInactiveExternalId = null;
      let pendingMarkInactiveEventId = null;
      let pendingDeleteExternalId = null;
      let pendingDeleteEventId = null;
      // Tracks which audit modal flow is active. "create" posts to /accept,
      // "modify" posts to /review-and-update.
      let auditMode = "create";
      let duplicateCheckSeq = 0;
      let duplicateMatches = [];
      let duplicateLoading = false;
      let submittingAudit = false;
      // The activity tab fetches lazily. Once the operator has opened it, the
      // poll keeps it fresh and every mutation refreshes it.
      let activityActive = false;
      // Load more state. activityCursor holds the next page cursor from the last
      // read, null when on the newest page or the ledger is exhausted.
      // activityLoading guards against a double fire while a page is in flight.
      let activityCursor = null;
      let activityLoading = false;
      // Feed items keyed by kind plus id, filled as Activity rows render, so an
      // expanded row can look up its feed item and build the received versus
      // applied comparison without another fetch. A reset read replaces the map,
      // a load more read extends it. See journal cnv-928/023.
      let activityByKey = {};
      // The synced registry now lives in the collapsed fold at the foot of Records,
      // so it loads at boot and stays fresh through the poll and after a mutation
      // while Records is the open surface. Starts true to match the default tab.
      let syncedActive = true;

      // Tab persistence. Remember the last open tab for this browser session so a
      // reload returns to where the operator was instead of snapping back to
      // Records. sessionStorage is per browser tab and clears when that tab or the
      // window closes, which is the closest the browser gives us to until they log
      // out with no server round trip. The stored value is only a panel id, nothing
      // sensitive, so a stale read after a re login in the same tab is harmless.
      const TAB_STORE_KEY = "sf-sync.active-tab";
      const KNOWN_PANELS = ["panel-records", "panel-activity", "panel-settings"];
      const readStoredTab = () => {
        try { return window.sessionStorage.getItem(TAB_STORE_KEY); }
        catch (e) { return null; }
      };
      const writeStoredTab = (panel) => {
        try { window.sessionStorage.setItem(TAB_STORE_KEY, panel); }
        catch (e) { /* a blocked store makes persistence a silent no op */ }
      };
      // Restore synchronously. The canvas-tabs component reads the active attribute
      // off its children inside a deferred connectedCallback, so moving the active
      // attribute here, before that zero delay timer fires, is all it takes. The
      // stored panel is validated against the known ids so a stale value from an
      // older build can never activate a tab that no longer exists.
      const restoreTab = () => {
        const stored = readStoredTab();
        if (!stored || KNOWN_PANELS.indexOf(stored) === -1) return;
        const target = document.querySelector('canvas-tab[for="' + stored + '"]');
        if (!target) return;
        const tabs = document.querySelectorAll("canvas-tabs > canvas-tab");
        for (let i = 0; i < tabs.length; i++) tabs[i].removeAttribute("active");
        target.setAttribute("active", "");
      };
      restoreTab();

      const EMPTY = "";

      // Marks a Written cell where the operator wrote a value different from what
      // Salesforce sent, a manual override. Sits beside the amber changed cue,
      // which marks a value different from what Canvas held. See journal cnv-928/037.
      const EDITED_CHIP = ' <canvas-badge color="blue" size="mini">Edited</canvas-badge>';

      // Append the event id so a resolution route acts on the exact event the
      // operator clicked rather than the newest of its action. See journal
      // cnv-909/092 story four.
      const eventQuery = (eventId) =>
        (eventId === null || eventId === undefined || eventId === "")
          ? ""
          : "?event_id=" + encodeURIComponent(eventId);

      const esc = (value) => {
        if (value === null || value === undefined) return "";
        const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
        return String(value).replace(/[&<>"']/g, (c) => map[c]);
      };

      const dash = (value) =>
        (value === null || value === undefined || value === "") ? EMPTY : esc(value);

      const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

      const fmtDateTime = (value) => {
        if (!value) return "";
        let s = String(value);
        // received_at and actioned_at are stored UTC. If the serialized value has no zone
        // designator, mark it UTC so the browser converts it to the reviewer local time.
        if (!/[zZ]|[+-]\\d{2}:?\\d{2}$/.test(s)) s += "Z";
        const d = new Date(s);
        if (isNaN(d.getTime())) return esc(value);
        let h = d.getHours();
        const ampm = h >= 12 ? "PM" : "AM";
        h = h % 12; if (h === 0) h = 12;
        const mm = String(d.getMinutes()).padStart(2, "0");
        return MONTHS[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear() + ", " + h + ":" + mm + " " + ampm;
      };

      const fmtDate = (value) => {
        if (!value) return "";
        const m = /^(\\d{4})-(\\d{2})-(\\d{2})$/.exec(String(value));
        if (m) return MONTHS[parseInt(m[2], 10) - 1] + " " + parseInt(m[3], 10) + ", " + m[1];
        const d = new Date(value);
        if (isNaN(d.getTime())) return esc(value);
        return MONTHS[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
      };

      const fullName = (row) =>
        [row.first_name, row.last_name].filter(Boolean).map(esc).join(" ");

      const fmtAddress = (m) => {
        if (!m) return "";
        const parts = [m.address_line_1, m.address_line_2, m.city, m.state, m.postal_code, m.country]
          .filter(Boolean).map(esc);
        return parts.join(", ");
      };

      // Format a raw phone value to the Canvas form mask, (000) 000-0000. Mirrors the
      // canvas-input format="phone" mask in the bundle so every read surface matches the
      // audit form. Strips a single leading 1 on 11 digit US numbers, formats partial
      // lengths the way the component does, and passes anything it cannot shape through
      // escaped and unchanged so nothing is silently blanked. See journal cnv-941/029.
      const fmtPhone = (value) => {
        if (value === null || value === undefined || value === "") return "";
        let digits = String(value).replace(/\\D/g, "");
        if (digits.length === 11 && digits.charAt(0) === "1") digits = digits.slice(1);
        if (digits.length < 4) return digits ? digits : esc(value);
        if (digits.length <= 6) return "(" + digits.slice(0, 3) + ") " + digits.slice(3);
        if (digits.length <= 10)
          return "(" + digits.slice(0, 3) + ") " + digits.slice(3, 6) + "-" + digits.slice(6);
        return esc(value);
      };

      // Decision log action_taken token to a human label plus a badge colour.
      // The skipped and reopened tokens read as their plain words, the Canvas
      // changing actions read green. See journal cnv-909/091.
      const DECISION_LABELS = {
        created: "Created",
        modify_applied: "Update applied",
        promoted_to_create: "Promoted to create",
        create_superseded: "Create superseded",
        tag_deleted: "Tagged deleted",
        mark_inactive: "Marked inactive",
        unlink: "Unlinked",
        skipped: "Skipped",
        reopened: "Reopened",
      };

      const decisionBadge = (actionTaken) => {
        const label = DECISION_LABELS[actionTaken] || dash(actionTaken);
        const green = actionTaken === "created"
          || actionTaken === "modify_applied"
          || actionTaken === "promoted_to_create"
          || actionTaken === "tag_deleted"
          || actionTaken === "mark_inactive"
          || actionTaken === "unlink";
        const colour = green ? ' color="green"' : ' basic';
        return '<canvas-badge size="mini"' + colour + '>' + label + '</canvas-badge>';
      };

      const clearBanner = () => { document.getElementById("error-region").innerHTML = ""; };
      const setBanner = (header, body) => {
        document.getElementById("error-region").innerHTML =
          '<canvas-banner variant="error" header="' + esc(header) + '">' +
          (body ? "<p>" + esc(body) + "</p>" : "") + "</canvas-banner>";
      };

      const setTabBadge = (id, count) => {
        const tab = document.getElementById(id);
        if (tab) tab.setAttribute("badge", String(count));
      };

      const setCountBadge = (id, count) => {
        const badge = document.getElementById(id);
        if (badge) badge.textContent = String(count);
      };

      // canvas-card renders its border inside a shadow DOM .card div that we
      // cannot reach from outside, so grid align-items: stretch makes the host
      // fill the row track but the visible card border ends at its content
      // height. To match heights visually, set min-height on the slotted
      // canvas-card-body, which is light DOM. The body grows, .card grows, the
      // host follows, and both cards land at the same bottom border.
      const equalizeSettingsCards = () => {
        const bodies = document.querySelectorAll("#panel-settings .card-grid canvas-card-body");
        if (bodies.length < 2) return;
        bodies.forEach((b) => { b.style.minHeight = ""; });
        let max = 0;
        bodies.forEach((b) => {
          const h = b.getBoundingClientRect().height;
          if (h > max) max = h;
        });
        if (max <= 0) return;
        bodies.forEach((b) => { b.style.minHeight = max + "px"; });
      };

      const scheduleEqualize = () => {
        requestAnimationFrame(() => requestAnimationFrame(equalizeSettingsCards));
      };

      const toggleRegion = (rows, emptyId, contentId) => {
        const empty = document.getElementById(emptyId);
        const content = document.getElementById(contentId);
        const has = rows.length > 0;
        empty.hidden = has;
        content.hidden = !has;
        return has;
      };

      // The verb says what acting on the row will do right now, derived from
      // the live link, Create when no Canvas patient exists, Modify when one
      // does, Delete for a delete event on a linked patient.
      // Records now collapses each contact to a single live row, the newest
      // pending event, so every surfaced row is actionable and there is no
      // disabled verb. The superseded events live in the Details overridden
      // history instead. See journal cnv-938/022.
      const rowVerb = (row) => {
        if (row.action === "delete") return "Delete";
        return row.linked ? "Modify" : "Create";
      };

      // The live verb button, wired to the route the verb implies. A Create on a
      // stored create posts to accept, a Create on a stored modify promotes it
      // into a create from the fresher snapshot, a Modify opens the editable
      // apply modal on the linked patient, a Delete opens the deactivation
      // confirm. See journal cnv-938/018.
      const verbButton = (row) => {
        const verb = rowVerb(row);
        const ext = esc(row.external_id);
        const ev = esc(row.event_id);
        if (verb === "Delete") {
          return '<canvas-button size="xs" data-delete-id="' + ext + '" data-event-id="' + ev + '">Delete</canvas-button>';
        }
        if (verb === "Modify") {
          return '<canvas-button size="xs" data-modify-edit-id="' + ext + '" data-event-id="' + ev + '">Modify</canvas-button>';
        }
        const attr = row.arrival_action === "modify" ? "data-promote-id" : "data-create-id";
        return '<canvas-button size="xs" ' + attr + '="' + ext + '" data-event-id="' + ev + '">Create</canvas-button>';
      };

      // The small read only Sync or Delete indicator a skipped row carries in
      // place of the dropped Event column, so a skipped row still says what it
      // was. See journal cnv-938/018.
      const eventBadge = (row) =>
        '<canvas-badge size="mini" basic>'
        + esc(row.event || (row.action === "delete" ? "Delete" : "Sync")) + "</canvas-badge>";

      // A red badge marks a missing patient required field so the reviewer sees the gap.
      const NOT_SPECIFIED = '<canvas-badge color="red" size="mini">Not specified</canvas-badge>';
      // Render a required field cell. Show the value when present, the red badge when it
      // is blank. inner is already escaped or a safe formatted string. Column widths
      // live on the dash-records grid template, Phone number keeps the stretch there.
      // See journal cnv-928/009 and cnv-941/012.
      const reqCell = (inner, bold) =>
        '<span class="dash-cell"' + (bold ? ' style="font-weight:700"' : "") + ">"
        + (inner ? inner : NOT_SPECIFIED) + "</span>";

      // Shared lead cells for both record tables, Needs action and Skipped. The five
      // patient required fields, First name, Last name, Date of birth, Sex at birth, and
      // Phone number, each badge red when missing, then the Salesforce event time.
      // Email and Address ride in the expanded detail. See journal cnv-928/009 and
      // cnv-941/012.
      const recordLeadCells = (row) =>
        reqCell(esc(row.first_name), true)
        + reqCell(esc(row.last_name), true)
        + reqCell(fmtDate(row.mapped && row.mapped.date_of_birth), false)
        + reqCell(esc(row.mapped && row.mapped.sex_at_birth), false)
        + reqCell(fmtPhone(row.phone), false)
        + '<span class="dash-cell">' + (fmtDateTime(row.received_at) || EMPTY) + "</span>";

      // One record entry as a summary plus detail pair, the same expandable row
      // design Synced and Activity use. The caret leads, then the shared lead
      // cells, then the trailing action cells each table keeps in the row, the
      // two part verb and caret button on Needs action, the event badge and
      // Reopen on Skipped.
      // The Details button is gone, the row itself expands. data-trail-id keys
      // the record timeline fetch and data-record-key resolves the cached status
      // row for the context banners, the comparison, the links, and the payload.
      // See journal cnv-941/012.
      const recordSummary = (row, trailing) =>
        '<div class="dash-row expandable-summary" tabindex="0" role="button"'
        + ' aria-expanded="false" data-trail-id="' + esc(row.external_id)
        + '" data-record-key="' + esc(row.event_id) + '">'
        + '<span class="dash-cell caret-cell">' + CARET_ICON + "</span>"
        + recordLeadCells(row)
        + trailing
        + "</div>"
        + detailRow();

      // The white chevron inside the caret part of the split button, the same
      // path as the row caret but sized to the xs button text.
      const MENU_CARET_ICON =
        '<svg width="10" height="6" viewBox="0 0 10 6" fill="currentColor"'
        + ' aria-hidden="true" focusable="false">'
        + '<path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"></path></svg>';

      // The two part action, the verb as the immediate main part and a caret
      // part opening a tooltip styled panel that holds Skip alone, the arrow
      // attribute gives the panel the canvas-tooltip treatment pointing at
      // the caret. Details rides the row expand, so the panel carries nothing
      // else. The group is fluid so the verb absorbs the column slack while
      // the caret stays content sized. data-menu-skip-id is distinct from
      // data-skip-id so the click delegation never half matches the host.
      // See journal cnv-941/015.
      const splitAction = (row) =>
        '<canvas-button-group fluid class="action-split">'
        + verbButton(row)
        + '<canvas-menu-button align="end" arrow data-menu-skip-id="' + esc(row.external_id) + '" data-event-id="' + esc(row.event_id) + '">'
        + '<canvas-button slot="trigger" size="xs" aria-label="More actions">' + MENU_CARET_ICON + "</canvas-button>"
        + '<canvas-option value="skip">Skip</canvas-option>'
        + "</canvas-menu-button>"
        + "</canvas-button-group>";

      const pendingRow = (row) =>
        recordSummary(
          row,
          '<span class="dash-cell">' + splitAction(row) + "</span>"
        );

      const skippedRow = (row) =>
        recordSummary(
          row,
          '<span class="dash-cell action-pair-lead">' + eventBadge(row) + "</span>"
          + '<span class="dash-cell action-pair-tail"><canvas-button variant="ghost" size="xs" data-reopen-id="' + esc(row.external_id) + '" data-event-id="' + esc(row.event_id) + '">Reopen</canvas-button></span>'
        );

      // The chevron in the trailing caret cell of an expandable row. It rotates a
      // quarter turn when the row opens, the only persistent cue that a row holds a
      // detail panel. Hidden from the accessibility tree, the row itself carries
      // aria-expanded.
      const CARET_ICON =
        '<span class="caret-icon" aria-hidden="true">'
        + '<svg width="10" height="6" viewBox="0 0 10 6" fill="currentColor"'
        + ' aria-hidden="true" focusable="false">'
        + '<path d="M1 0h8a1 1 0 01.7 1.7l-4 4a1 1 0 01-1.4 0l-4-4A1 1 0 011 0z"></path></svg>'
        + '</span>';

      // The detail block that follows every expandable summary row. A plain full
      // width div sibling, so it spans the whole list, which a CSS table cell could
      // not. A full width links bar, then a two column grid holding the demographics
      // and the record timeline. The raw Salesforce payload no longer rides inline,
      // it is stashed on a hidden pre and printed into a shared modal from the Raw
      // Salesforce payload button the links bar grows on the right. The regions are
      // addressed by class, not id, since many live on the page at once, and they
      // fill lazily on first expand. See journal cnv-941/003 and cnv-941/004.
      const detailRow = () =>
        '<div class="dash-detail expandable-detail">'
        + '<div class="row-detail">'
        + '<div class="row-detail-context"></div>'
        + '<div class="row-detail-links" hidden></div>'
        + '<div class="row-detail-grid">'
        + '<div class="row-detail-demographics"></div>'
        + '<div class="row-detail-timeline"><h5 class="row-detail-title">Record timeline</h5>'
        + '<ul class="trail-list row-detail-trail"><li>Loading history.</li></ul></div>'
        + '</div>'
        + '<pre class="code-block row-detail-payload-json" hidden></pre>'
        + '</div></div>';

      // The open in external glyph carrier, the small gray ghost button for the
      // link pair inside an expanded detail, both Activity and Synced. A missing
      // url renders nothing.
      const linkButton = (url, label) =>
        url
          ? '<canvas-button variant="ghost" size="xs" data-ext-url="' + esc(url)
            + '" aria-label="Open ' + esc(label) + '">' + esc(label) + EXT_ICON + "</canvas-button>"
          : EMPTY;

      // The arrived marker for the Action column on an arrival line. An arrival
      // carried no operator decision, so it reads arrived rather than a resolution
      // badge.
      const ARRIVED_BADGE = '<canvas-badge size="mini" basic>Arrived</canvas-badge>';

      // The person cell for an Activity row, first name last name with the birth
      // year in parentheses, like John Doe (1990). The name and birth date ride on
      // the received snapshot the feed item already carries. The year drops when no
      // birth date arrived, the whole cell falls to a dash when there is no name,
      // the cleared event log edge. See journal cnv-928/030.
      const nameWithYear = (e) => {
        const r = e.received || {};
        const name = [r.first_name, r.last_name].filter(Boolean).map(esc).join(" ");
        if (!name) return EMPTY;
        const m = /^(\\d{4})/.exec(String(r.date_of_birth || ""));
        return m ? name + " (" + m[1] + ")" : name;
      };

      // One Activity entry as a summary plus detail row pair. The summary carries
      // When, Action, Event, the person cell, the Who acted column, and the trailing
      // caret. Action is the resolution badge on a decision and an Arrived marker on
      // an arrival. Who acted reads the staff name the feed item already carries,
      // Automatic sync for the auto applied path, a dash for an arrival or an empty
      // actor. Clicking the row expands the detail row below, which holds the
      // Salesforce and chart links, the comparison, the timeline, and the payload
      // that the retired Details modal used to show. data-trail-id keys the record
      // timeline and data-activity-key keys the single feed item. See journal
      // cnv-941/003.
      const activityRow = (e) => {
        const action = e.kind === "received" ? ARRIVED_BADGE : decisionBadge(e.action_taken);
        const who = e.kind === "received" ? dash("") : dash(e.staff_name);
        return '<div class="dash-row expandable-summary" tabindex="0" role="button"'
          + ' aria-expanded="false" data-trail-id="' + esc(e.external_id)
          + '" data-activity-key="' + esc(e.kind + ":" + e.id) + '">'
          + '<span class="dash-cell caret-cell">' + CARET_ICON + "</span>"
          + '<span class="dash-cell">' + (fmtDateTime(e.ts) || EMPTY) + "</span>"
          + '<span class="dash-cell">' + action + "</span>"
          + '<span class="dash-cell">' + esc(e.event || (e.action === "delete" ? "Delete" : "Sync")) + "</span>"
          + '<span class="dash-cell">' + nameWithYear(e) + "</span>"
          + '<span class="dash-cell">' + who + "</span>"
          + "</div>"
          + detailRow();
      };

      // The open in external glyph that rides inside a link button, a Lucide style
      // box with an arrow leaving the top right corner. It inherits the gray button
      // text color through stroke currentColor, and is hidden from the accessibility
      // tree since the button label already names the destination.
      const EXT_ICON =
        '<svg class="ext-btn-icon" width="12" height="12" viewBox="0 0 24 24" fill="none"'
        + ' stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
        + ' aria-hidden="true"><path d="M15 3h6v6"></path><path d="M10 14 21 3"></path>'
        + '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path></svg>';

      const patientChartUrl = (row) =>
        row.patient_id ? window.location.origin + "/patient/" + encodeURIComponent(row.patient_id) : "";

      // A Synced entry as a summary plus detail block pair, the same row design
      // Activity uses. The caret leads, then the six demographic cells. The
      // Salesforce and chart links no longer ride as summary columns, they moved
      // into the expanded detail links bar, so the row carries both urls as data
      // attributes for readDetailOpts to resolve. Clicking the row expands the same
      // detail panel Activity uses, here the links bar, the Canvas identity card,
      // the timeline, and the payload. See journal cnv-941/010.
      const syncedRow = (row) =>
        '<div class="dash-row expandable-summary" tabindex="0" role="button"'
        + ' aria-expanded="false" data-trail-id="' + esc(row.external_id)
        + '" data-sf-url="' + esc(row.salesforce_url || "")
        + '" data-chart-url="' + esc(patientChartUrl(row)) + '">'
        + '<span class="dash-cell caret-cell">' + CARET_ICON + "</span>"
        + '<span class="dash-cell" style="font-weight:700">' + dash(row.first_name) + "</span>"
        + '<span class="dash-cell" style="font-weight:700">' + dash(row.last_name) + "</span>"
        + '<span class="dash-cell">' + (fmtDate(row.date_of_birth) || EMPTY) + "</span>"
        + '<span class="dash-cell">' + dash(row.sex_at_birth) + "</span>"
        + '<span class="dash-cell">' + (row.phone ? fmtPhone(row.phone) : EMPTY) + "</span>"
        + '<span class="dash-cell">' + (fmtDateTime(row.last_synced_at) || EMPTY) + "</span>"
        + "</div>"
        + detailRow();

      const render = (data) => {
        if (data.config_error) setBanner("Configuration error", data.config_error);
        else clearBanner();

        document.getElementById("webhook-url").textContent =
          window.location.origin + pluginPrefix + "/webhooks/patient/sync";

        const pending = data.pending || [];
        const skipped = data.skipped || [];
        setTabBadge("tab-records", pending.length);
        setCountBadge("pending-count-badge", pending.length);
        setCountBadge("skipped-count-badge", skipped.length);

        rowByEventId = {};
        pending.concat(skipped).forEach((r) => { rowByEventId[r.event_id] = r; });
        pendingByEventId = {};
        pending.forEach((r) => { pendingByEventId[r.event_id] = r; });

        // Skip a body's repaint while it holds an open detail row, the same
        // guard Synced and Activity use, so the periodic poll never collapses
        // what the operator is reading. The badges above still update, and a
        // mutation closes open details first through refreshAfterAction. The
        // pending body also skips while a caret menu is open, a repaint would
        // silently remove the menu under the operator's pointer. See journal
        // cnv-941/004, cnv-941/012, and cnv-941/015.
        const pendingBody = document.getElementById("pending-body");
        if (!hasOpenDetail(pendingBody)
            && !pendingBody.querySelector("canvas-menu-button[data-menu-open]")
            && toggleRegion(pending, "pending-empty", "pending-scroll")) {
          pendingBody.innerHTML = pending.map(pendingRow).join("");
          collapseDetailRows(pendingBody);
        }
        const skippedBody = document.getElementById("skipped-body");
        if (!hasOpenDetail(skippedBody)
            && toggleRegion(skipped, "skipped-empty", "skipped-scroll")) {
          skippedBody.innerHTML = skipped.map(skippedRow).join("");
          collapseDetailRows(skippedBody);
        }

        scheduleEqualize();
      };

      const fetchStatus = async () => {
        try {
          const resp = await fetch(pluginPrefix + "/status", { credentials: "include" });
          if (!resp.ok) throw new Error("status request failed");
          const data = await resp.json();
          revealContent();
          render(data);
        } catch (e) {
          if (window.console) console.error(e);
          revealContent();
          setBanner("Could not load status", "Try again in a moment.");
        }
      };

      // Render a page of activity. A reset read replaces the table body and
      // re evaluates the empty state, a load more read appends to whatever is
      // there. The cursor and the Load more button follow has_more.
      const renderActivity = (data, append) => {
        const entries = (data && Array.isArray(data.entries)) ? data.entries : [];
        const body = document.getElementById("activity-body");
        // A reset repaint would destroy an open detail row, so skip it while one is
        // open and leave both the rows and the key map as they are. A load more
        // append is additive and always proceeds. See journal cnv-941/004.
        if (!append && hasOpenDetail(body)) return;
        if (!append) activityByKey = {};
        entries.forEach((e) => { activityByKey[e.kind + ":" + e.id] = e; });
        if (append) {
          if (body) body.insertAdjacentHTML("beforeend", entries.map(activityRow).join(""));
        } else if (toggleRegion(entries, "activity-empty", "activity-scroll")) {
          if (body) body.innerHTML = entries.map(activityRow).join("");
        }
        if (body) collapseDetailRows(body);
        activityCursor = (data && data.has_more) ? data.next_cursor : null;
        const wrap = document.getElementById("activity-load-more-wrap");
        if (wrap) wrap.hidden = !activityCursor;
      };

      // Fetch one page of the ledger. With no cursor it serves the newest page
      // and resets the list, with the stored cursor it appends the next page.
      const fetchActivity = async (cursor) => {
        if (activityLoading) return;
        activityLoading = true;
        try {
          let url = pluginPrefix + "/activity";
          if (cursor && cursor.ts && cursor.id != null) {
            url += "?before=" + encodeURIComponent(cursor.ts)
              + "&before_kind=" + encodeURIComponent(cursor.kind)
              + "&before_id=" + encodeURIComponent(cursor.id);
          }
          const resp = await fetch(url, { credentials: "include" });
          if (!resp.ok) throw new Error("activity request failed");
          const data = await resp.json();
          renderActivity(data, Boolean(cursor));
        } catch (e) {
          if (window.console) console.error(e);
        } finally {
          activityLoading = false;
        }
      };

      const loadMoreActivity = () => {
        if (activityCursor) fetchActivity(activityCursor);
      };

      // Paint the Synced registry, one row per linked contact, already sorted by
      // Last synced on the server. Synced now lives as the collapsed accordion item
      // at the foot of Records, so its count rides the accordion title badge.
      const renderSynced = (data) => {
        const rows = (data && Array.isArray(data.synced)) ? data.synced : [];
        setCountBadge("synced-count-badge", rows.length);
        const body = document.getElementById("synced-body");
        // Skip the repaint while a detail row is open so the poll never collapses it.
        // The count badge above still updates. See journal cnv-941/004.
        if (hasOpenDetail(body)) return;
        if (toggleRegion(rows, "synced-empty", "synced-scroll")) {
          body.innerHTML = rows.map(syncedRow).join("");
          collapseDetailRows(body);
        }
      };

      const fetchSynced = async () => {
        try {
          const resp = await fetch(pluginPrefix + "/synced", { credentials: "include" });
          if (!resp.ok) throw new Error("synced request failed");
          const data = await resp.json();
          renderSynced(data);
        } catch (e) {
          if (window.console) console.error(e);
        }
      };

      // One trail line per event or decision in the record's timeline. A received
      // line names what arrived from Salesforce, a decision line names who acted
      // and what they did. Built as escaped text since it lands as innerHTML.
      const trailItemLine = (t) => {
        const when = fmtDateTime(t.ts) || "an unknown time";
        if (t.kind === "received") {
          const noun = GAP_NOUN[t.action] || t.action || "event";
          const demo = [esc(t.name), esc(t.email), fmtPhone(t.phone)].filter(Boolean).join(", ");
          let line = "Received " + esc(noun) + ", " + esc(when);
          if (demo) line += '<br><span class="trail-detail">' + demo + "</span>";
          return line;
        }
        // A promote reads as one self contained phrase so the from modify origin
        // is plain in the timeline without joining it to the Event cell. Every
        // other decision uses its shared label. See journal cnv-928/037.
        const label = t.action_taken === "promoted_to_create"
          ? "Promoted this modify to a create"
          : (DECISION_LABELS[t.action_taken] || esc(t.action_taken));
        let line = label + (t.staff_name ? " by " + esc(t.staff_name) : "") + ", " + esc(when);
        if (t.note) line += '<br><span class="trail-detail">' + esc(t.note) + "</span>";
        return line;
      };

      // Collapse every detail row in a freshly painted table body. The table
      // component forces display table-row inline in its connectedCallback, so the
      // hidden attribute and a stylesheet class cannot hide a detail row. The only
      // reliable lever is the inline display, set to none here, flipped back to
      // table-row by the toggle. Runs synchronously right after innerHTML so the
      // rows never flash open. See journal cnv-941/003.
      const collapseDetailRows = (container) => {
        const rows = container.querySelectorAll(".expandable-detail");
        for (let i = 0; i < rows.length; i++) {
          // Only initialize a detail row that has never been touched. A load more
          // append must not collapse rows the operator already opened, and a guarded
          // reset never reaches here with open rows present.
          if (rows[i].dataset.open === undefined) {
            rows[i].style.display = "none";
            rows[i].dataset.open = "0";
          }
        }
      };

      // True when a body holds an expanded detail row. A background refresh skips
      // the reset repaint while one is open so the periodic poll never collapses
      // what the operator is reading. See journal cnv-941/004.
      const hasOpenDetail = (body) =>
        Boolean(body && body.querySelector('.expandable-detail[data-open="1"]'));

      // Read the expand inputs off a summary row. The Salesforce external id keys
      // the trail fetch, the activity key looks up the cached feed item for the
      // synchronous comparison and the links, and the record key looks up the
      // cached status row a Needs action or Skipped summary rides on. The Synced
      // path carries neither key, so its urls ride directly on the row as data
      // attributes, one resolver serves every table. See journal cnv-941/003,
      // cnv-941/010, and cnv-941/012.
      const readDetailOpts = (summary) => {
        const externalId = summary.getAttribute("data-trail-id");
        const key = summary.getAttribute("data-activity-key");
        const item = key ? activityByKey[key] : null;
        const recordKey = summary.getAttribute("data-record-key");
        const record = recordKey ? (rowByEventId[recordKey] || null) : null;
        return {
          externalId: externalId,
          item: item,
          record: record,
          salesforceUrl: item ? item.salesforce_url
            : record ? (record.salesforce_url || "")
            : (summary.getAttribute("data-sf-url") || ""),
          chartUrl: item ? patientChartUrl(item)
            : record ? patientChartUrl(record)
            : (summary.getAttribute("data-chart-url") || ""),
        };
      };

      // Toggle one summary row open or closed. Flips the paired detail block inline
      // display, none when closed and empty so the stylesheet block shows it when
      // open, mirrors the state on the caret rotation class and aria-expanded, and
      // fills the detail once on first open, guarded by data-loaded. See journal
      // cnv-941/003 and cnv-941/004.
      const toggleRow = (summary) => {
        const detail = summary.nextElementSibling;
        if (!detail || !detail.classList.contains("expandable-detail")) return;
        const open = detail.dataset.open === "1";
        if (open) {
          detail.style.display = "none";
          detail.dataset.open = "0";
          summary.classList.remove("expanded");
          summary.setAttribute("aria-expanded", "false");
          return;
        }
        detail.style.display = "";
        detail.dataset.open = "1";
        summary.classList.add("expanded");
        summary.setAttribute("aria-expanded", "true");
        if (detail.dataset.loaded !== "1") {
          detail.dataset.loaded = "1";
          populateRowDetail(detail, readDetailOpts(summary));
        }
      };

      // The compact table wrapper every demographics region shares, a horizontal
      // scroll area around one canvas-table.
      const demoTable = (inner) =>
        '<canvas-scroll-area horizontal aria-label="Demographics" style="max-width: 100%">'
        + '<canvas-table compact aria-label="Demographics">' + inner + "</canvas-table>"
        + "</canvas-scroll-area>";

      // The overridden history for a records row, the arrivals between the last
      // applied change and this newest event that were never written. The retired
      // Details modal held these in a collapsed accordion, inline they read as
      // one info banner. Empty when the gap window is empty. Reuses gapEventLine
      // so the wording matches the apply step. See journal cnv-938/022 and
      // cnv-941/012.
      const buildOverriddenBanner = (row) => {
        const events = (row.gap && row.gap.events) || [];
        if (!events.length) return "";
        const intro = (row.gap && row.gap.has_anchor)
          ? "These events arrived after the last change applied to this patient and were never written. This newest event overrides them."
          : "These events arrived before this one and were never written. This newest event overrides them.";
        return '<canvas-banner variant="info" header="Overridden history"><p>'
          + esc(intro) + "</p>"
          + '<ul class="trail-list">'
          + events.map((e) => "<li>" + esc(gapEventLine(e)) + "</li>").join("")
          + "</ul></canvas-banner>";
      };

      // The demographics region for a records row follows the retired Details
      // modal logic. A linked modify is a live decision, apply or skip, so it
      // leads with the current chart against the incoming values, fetched from
      // canvas-current and ambered where the incoming value differs. Every other
      // row has no chart to compare against, so it shows the Received data list,
      // which keeps the metadata fields the payload mapping surfaces. See journal
      // cnv-928/037 and cnv-941/012.
      const fillRecordDemographics = async (demo, row) => {
        if (row.action === "modify" && row.linked) {
          const data = await fetchCanvasCurrent(row.external_id);
          const canvas = (data && data.canvas) || {};
          demo.innerHTML = demoTable(buildComparisonTable(
            "Canvas now", "Incoming", canvas, rowIncomingSnapshot(row), true
          ));
          return;
        }
        demo.innerHTML = '<h5 class="row-detail-title">Received data</h5>'
          + demoTable("<canvas-table-body>" + buildReceivedRows(row) + "</canvas-table-body>");
      };

      // Fill an expanded detail block. The links and, on the Activity path, the
      // comparison fill synchronously from the cached feed item. A records row
      // additionally fills the context block, the hold reasons, skip attribution,
      // promote note, and overridden history the retired Details modal showed,
      // and routes its demographics through the modal logic. The timeline, the
      // payload, and, on the Synced path, the Canvas identity card come from the
      // record trail fetch. See journal cnv-941/003 and cnv-941/012.
      const populateRowDetail = async (detail, opts) => {
        const root = detail.querySelector(".row-detail");
        if (!root) return;
        const ctx = root.querySelector(".row-detail-context");
        if (ctx && opts.record) {
          ctx.innerHTML = buildDetailsContext(opts.record) + buildOverriddenBanner(opts.record);
        }
        const linksWrap = root.querySelector(".row-detail-links");
        const demo = root.querySelector(".row-detail-demographics");
        const trailList = root.querySelector(".row-detail-trail");
        const links = linkButton(opts.salesforceUrl, "Salesforce") + linkButton(opts.chartUrl, "Patient chart");
        if (linksWrap) {
          linksWrap.innerHTML = links;
          linksWrap.hidden = !links;
        }
        if (demo && opts.item) {
          demo.innerHTML = demoTable(buildCompareTable(opts.item));
        } else if (demo && opts.record) {
          fillRecordDemographics(demo, opts.record);
        }
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(opts.externalId) + "/trail",
            { credentials: "include" }
          );
          if (!resp.ok) throw new Error("trail request failed");
          const data = await resp.json();
          const trail = (data && Array.isArray(data.trail)) ? data.trail : [];
          if (trailList) {
            trailList.innerHTML = trail.length
              ? trail.map((t) => "<li>" + trailItemLine(t) + "</li>").join("")
              : "<li>No activity recorded for this record yet.</li>";
          }
          // The Synced path has no feed item and no status row, so its comparison
          // rides on the trail response as a single Canvas identity card.
          if (demo && !opts.item && !opts.record && hasAnyValue(data.canvas)) {
            demo.innerHTML = demoTable(buildCanvasIdentityTable(data.canvas));
          }
          fillDetailPayload(
            root,
            trail,
            opts.item ? opts.item.event_id : (opts.record ? opts.record.event_id : null)
          );
        } catch (e) {
          if (window.console) console.error(e);
          if (trailList) trailList.innerHTML = "<li>Could not load the record history. Try again in a moment.</li>";
        }
      };

      // The fixed field order for the received versus applied comparison, the same
      // demographics the Records details modal shows, formatted by the same helpers
      // so the two surfaces read alike. Each entry pairs a label with a formatter
      // that reads one side's snapshot. See journal cnv-928/023.
      const COMPARE_FIELDS = [
        ["Name", (d) => fullName(d)],
        ["Date of birth", (d) => esc(fmtDate(d.date_of_birth))],
        ["Sex at birth", (d) => esc(d.sex_at_birth)],
        ["Email", (d) => esc(d.email)],
        ["Phone", (d) => fmtPhone(d.phone)],
        ["Mobile", (d) => fmtPhone(d.mobile)],
        ["Address", (d) => fmtAddress(d)],
      ];

      const compareLabelCell = (label) =>
        '<canvas-table-cell class="col-fit details-kv-label">' + esc(label) + "</canvas-table-cell>";

      const headCell = (label, fit) =>
        "<canvas-table-cell" + (fit ? ' class="col-fit"' : "") + ">" + esc(label) + "</canvas-table-cell>";

      // Build the Demographics table for one Activity feed item. The column shape
      // follows what the row actually carries, not just whether anything applied.
      //
      // An applied modify is the only row with a Canvas before snapshot, so it reads
      // as four columns, Was in Canvas, What Salesforce sent, Written, the full before
      // and after. The Written cell ambers where it differs from Was in Canvas, the
      // real chart change, and carries an Edited chip where it differs from What
      // Salesforce sent, the operator override. An applied create or promote wrote a
      // patient that had no before, so it drops Was in Canvas and reads as three
      // columns, What Salesforce sent and Written. Every other row, an arrival, a
      // skip, a delete, wrote no demographics, so it reads as two columns, the single
      // What Salesforce sent list. All shapes render every field row so the keys read
      // as a stable column. See journal cnv-928/037.
      const buildCompareTable = (item) => {
        const received = item.received || {};
        const applied = item.applied;
        const before = item.canvas_before;
        if (applied && before) {
          const head = "<canvas-table-row>"
            + headCell("Field", true)
            + headCell("Was in Canvas")
            + headCell("What Salesforce sent")
            + headCell("Written")
            + "</canvas-table-row>";
          const rows = COMPARE_FIELDS.map((f) => {
            const wasVal = f[1](before) || EMPTY;
            const sentVal = f[1](received) || EMPTY;
            const writtenVal = f[1](applied) || EMPTY;
            const changed = wasVal !== writtenVal;
            const edited = sentVal !== writtenVal;
            const writtenCell = "<canvas-table-cell"
              + (changed ? ' class="cell-changed"' : "") + ">"
              + writtenVal + (edited ? EDITED_CHIP : "") + "</canvas-table-cell>";
            return "<canvas-table-row>"
              + compareLabelCell(f[0])
              + "<canvas-table-cell>" + wasVal + "</canvas-table-cell>"
              + "<canvas-table-cell>" + sentVal + "</canvas-table-cell>"
              + writtenCell
              + "</canvas-table-row>";
          }).join("");
          return "<canvas-table-head>" + head + "</canvas-table-head>"
            + "<canvas-table-body>" + rows + "</canvas-table-body>";
        }
        if (applied) {
          const head = "<canvas-table-row>"
            + headCell("Field", true)
            + headCell("What Salesforce sent")
            + headCell("Written")
            + "</canvas-table-row>";
          const rows = COMPARE_FIELDS.map((f) => "<canvas-table-row>"
            + compareLabelCell(f[0])
            + "<canvas-table-cell>" + (f[1](received) || EMPTY) + "</canvas-table-cell>"
            + "<canvas-table-cell>" + (f[1](applied) || EMPTY) + "</canvas-table-cell>"
            + "</canvas-table-row>").join("");
          return "<canvas-table-head>" + head + "</canvas-table-head>"
            + "<canvas-table-body>" + rows + "</canvas-table-body>";
        }
        const head = "<canvas-table-row>"
          + headCell("Field", true)
          + headCell("What Salesforce sent")
          + "</canvas-table-row>";
        const rows = COMPARE_FIELDS.map((f) => "<canvas-table-row>"
          + compareLabelCell(f[0])
          + "<canvas-table-cell>" + (f[1](received) || EMPTY) + "</canvas-table-cell>"
          + "</canvas-table-row>").join("");
        return "<canvas-table-head>" + head + "</canvas-table-head>"
          + "<canvas-table-body>" + rows + "</canvas-table-body>";
      };

      // Build the Demographics table for the Synced path, a single Canvas column
      // identity card of the linked patient. A settled linked record offers no
      // action, so the old Canvas against Salesforce comparison drove no decision
      // and is dropped, leaving the chart identity alone. The row set and the
      // formatters match the other surfaces so they read alike. See journal
      // cnv-928/037.
      const buildCanvasIdentityTable = (canvas) => {
        const c = canvas || {};
        const head = "<canvas-table-row>"
          + '<canvas-table-cell class="col-fit">Field</canvas-table-cell>'
          + "<canvas-table-cell>Canvas</canvas-table-cell>"
          + "</canvas-table-row>";
        const rows = COMPARE_FIELDS.map((f) => "<canvas-table-row>"
          + compareLabelCell(f[0])
          + "<canvas-table-cell>" + (f[1](c) || EMPTY) + "</canvas-table-cell>"
          + "</canvas-table-row>").join("");
        return "<canvas-table-head>" + head + "</canvas-table-head>"
          + "<canvas-table-body>" + rows + "</canvas-table-body>";
      };

      // Pack a Records status row into the compare snapshot shape, the same keys
      // the Canvas snapshot carries, sourced the same way buildReceivedRows reads
      // them, the typed columns first then the mapped payload. Lets the Records
      // comparison run the incoming side through the shared COMPARE_FIELDS
      // formatters. See journal cnv-928/037.
      const rowIncomingSnapshot = (row) => {
        const m = row.mapped || {};
        const telecom = row.telecom || {};
        return {
          first_name: row.first_name || m.first_name || "",
          last_name: row.last_name || m.last_name || "",
          date_of_birth: m.date_of_birth || "",
          sex_at_birth: m.sex_at_birth || "",
          email: row.email || m.email || "",
          phone: row.phone || m.phone || "",
          mobile: telecom.mobile || "",
          address_line_1: m.address_line_1 || "",
          address_line_2: m.address_line_2 || "",
          city: m.city || "",
          state: m.state || "",
          postal_code: m.postal_code || "",
          country: m.country || "",
        };
      };

      // A Field plus two value column comparison over the fixed demographic set.
      // When markChanged is set the right cell ambers wherever its formatted value
      // differs from the left, the changed cue. Both sides run through the shared
      // formatters so the two columns read alike. See journal cnv-928/037.
      const buildComparisonTable = (leftLabel, rightLabel, left, right, markChanged) => {
        const head = "<canvas-table-row>"
          + '<canvas-table-cell class="col-fit">Field</canvas-table-cell>'
          + "<canvas-table-cell>" + esc(leftLabel) + "</canvas-table-cell>"
          + "<canvas-table-cell>" + esc(rightLabel) + "</canvas-table-cell>"
          + "</canvas-table-row>";
        const rows = COMPARE_FIELDS.map((f) => {
          const lv = f[1](left) || EMPTY;
          const rv = f[1](right) || EMPTY;
          const changed = markChanged && lv !== rv;
          const rightCell = "<canvas-table-cell"
            + (changed ? ' class="cell-changed"' : "") + ">" + (rv || EMPTY) + "</canvas-table-cell>";
          return "<canvas-table-row>"
            + compareLabelCell(f[0])
            + "<canvas-table-cell>" + (lv || EMPTY) + "</canvas-table-cell>"
            + rightCell
            + "</canvas-table-row>";
        }).join("");
        return "<canvas-table-head>" + head + "</canvas-table-head>"
          + "<canvas-table-body>" + rows + "</canvas-table-body>";
      };

      const hasAnyValue = (snapshot) =>
        snapshot && Object.keys(snapshot).some((k) => snapshot[k]);

      // Fetch the current Canvas patient demographics linked to a record, for the
      // now versus will be comparison an expanded records row draws on a linked
      // modify. Returns null on any failure so the caller falls back to the flat
      // received list. See journal cnv-928/037.
      const fetchCanvasCurrent = async (externalId) => {
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(externalId) + "/canvas-current",
            { credentials: "include" }
          );
          if (!resp.ok) return null;
          return await resp.json();
        } catch (e) {
          if (window.console) console.error(e);
          return null;
        }
      };

      // Fill the Raw Salesforce payload stash inside an expanded detail row. The
      // clicked Activity or records row names an event, so show that event's
      // payload, matched on the event id the trail received items carry. The
      // Synced path passes no event id, so fall back to the newest captured
      // event, the first received item since the trail is newest first. See
      // journal cnv-928/030, cnv-941/003, and cnv-941/012.
      // Stash the row's raw Salesforce payload on the hidden pre and, when a payload
      // exists, grow the links bar with the Raw Salesforce payload button on the far
      // right. The button prints the stored JSON into the shared raw-payload-modal, so
      // the payload no longer rides inline. A row with no payload leaves the bar as is.
      const fillDetailPayload = (root, trail, eventId) => {
        const pre = root.querySelector(".row-detail-payload-json");
        const linksWrap = root.querySelector(".row-detail-links");
        if (!pre) return;
        const received = trail.filter((t) => t.kind === "received");
        let match = null;
        if (eventId != null) {
          match = received.find((t) => t.event_id === eventId) || null;
        }
        if (!match) match = received.length ? received[0] : null;
        const payload = match ? match.raw_payload : null;
        if (payload && Object.keys(payload).length) {
          pre.textContent = JSON.stringify(payload, null, 2);
          if (linksWrap && !linksWrap.querySelector(".row-detail-payload-btn")) {
            linksWrap.insertAdjacentHTML(
              "beforeend",
              '<canvas-button variant="ghost" size="xs" class="row-detail-payload-btn"'
                + ' aria-label="Open raw Salesforce payload">Raw Salesforce payload</canvas-button>'
            );
            linksWrap.hidden = false;
          }
        } else {
          pre.textContent = "";
        }
      };

      // Collapse every open detail in the two records bodies so the refresh
      // repaint is never skipped by the open detail guard. A mutation moves its
      // row between buckets, and a stale row lingering under an open panel would
      // read as the action not having happened. See journal cnv-941/012.
      const closeRecordDetails = () => {
        ["pending-body", "skipped-body"].forEach((id) => {
          const body = document.getElementById(id);
          if (!body) return;
          body.querySelectorAll('.expandable-detail[data-open="1"]').forEach((d) => {
            d.style.display = "none";
            d.dataset.open = "0";
            const summary = d.previousElementSibling;
            if (summary && summary.classList.contains("expandable-summary")) {
              summary.classList.remove("expanded");
              summary.setAttribute("aria-expanded", "false");
            }
          });
        });
      };

      // Refresh both surfaces after a mutation, the activity ledger only when it
      // is the visible tab so a background fetch never runs for nothing.
      const refreshAfterAction = async () => {
        closeRecordDetails();
        await fetchStatus();
        if (activityActive) fetchActivity();
        if (syncedActive) fetchSynced();
      };

      const revealContent = () => {
        if (firstLoaded) return;
        firstLoaded = true;
        document.getElementById("initial-loader").hidden = true;
        document.getElementById("page-content").hidden = false;
      };

      const copyWebhook = async () => {
        const url = document.getElementById("webhook-url").textContent;
        const btn = document.getElementById("copy-webhook-btn");
        try {
          await navigator.clipboard.writeText(url);
          const prev = btn.textContent;
          btn.textContent = "Copied";
          setTimeout(() => { btn.textContent = prev; }, 1500);
        } catch (e) {
          if (window.console) console.error(e);
        }
      };

      const detailsKvRow = (label, valueHtml) =>
        "<canvas-table-row>"
        + '<canvas-table-cell class="col-fit details-kv-label">' + esc(label) + "</canvas-table-cell>"
        + "<canvas-table-cell>" + valueHtml + "</canvas-table-cell>"
        + "</canvas-table-row>";

      const humanizeKey = (k) =>
        String(k || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

      // Build the human readable received data rows for an expanded records detail.
      // The record identifiers always show, the demographic and metadata fields show
      // only when the event carried a value, so the table stays tight even on a sparse
      // contact. The name and address come pre escaped from their formatters. See
      // journal cnv-928/007 and cnv-941/012.
      const buildReceivedRows = (row) => {
        const m = row.mapped || {};
        const telecom = row.telecom || {};
        const metadata = row.metadata || {};
        const rows = [];
        rows.push(["Salesforce record", '<code class="code-inline">' + esc(row.external_id) + "</code>"]);
        if (row.source_object) rows.push(["Source object", esc(row.source_object)]);
        rows.push(["Action", esc(row.action || "")]);
        rows.push(["Received", esc(fmtDateTime(row.received_at) || EMPTY)]);
        const name = fullName(row);
        if (name) rows.push(["Name", name]);
        const dob = fmtDate(m.date_of_birth);
        if (dob) rows.push(["Date of birth", esc(dob)]);
        if (m.sex_at_birth) rows.push(["Sex at birth", esc(m.sex_at_birth)]);
        const email = row.email || m.email;
        if (email) rows.push(["Email", esc(email)]);
        const phone = row.phone || m.phone;
        if (phone) rows.push(["Phone", fmtPhone(phone)]);
        if (telecom.mobile) rows.push(["Mobile", fmtPhone(telecom.mobile)]);
        const address = fmtAddress(m);
        if (address) rows.push(["Address", address]);
        Object.keys(metadata).forEach((k) => {
          if (metadata[k]) rows.push([humanizeKey(k), esc(String(metadata[k]))]);
        });
        return rows.map((pair) => detailsKvRow(pair[0], pair[1])).join("");
      };

      // The state context banners at the top of an expanded records detail. A held row
      // lists its hold reasons, a skipped row names who skipped it and why, and an
      // unlinked modify shows the promote explanation. These read off the same row
      // fields the retired Details modal used. See journal cnv-928/007 and cnv-941/012.
      const buildDetailsContext = (row) => {
        const blocks = [];
        // A held row carries the reasons the deliberate sync evaluator kept it
        // out of auto apply, the short stable strings the webhook stored. The
        // amber banner lists them so the operator sees exactly what to fix
        // before acting. Empty on a row that auto applied or arrived before the
        // evaluator wired in. See journal cnv-938/038.
        const holds = Array.isArray(row.hold_reasons) ? row.hold_reasons : [];
        if (holds.length) {
          const items = holds.map((r) => "<li>" + esc(r) + "</li>").join("");
          blocks.push(
            '<canvas-banner variant="warning" header="Held for manual review">'
            + "<p>This record did not pass the sync filter, so it was not applied automatically.</p>"
            + '<ul class="hold-reasons">' + items + "</ul></canvas-banner>"
          );
        }
        // A skipped row carries who skipped it, when, and the latest reason. The
        // yellow banner names the operator and time in its header, with a labeled
        // reason beneath when one was given. An empty skip shows the attribution
        // alone. Gated on the skip time so it rides only on skipped rows, never on
        // a pending one. See journal cnv-928/013.
        if (row.skipped_at) {
          const who = row.skipped_by ? "Skipped by " + esc(row.skipped_by) : "Skipped";
          const when = fmtDateTime(row.skipped_at);
          const headerText = who + (when ? ", " + when : "");
          const reason = row.skip_reason
            ? '<p class="skip-reason-label"><strong>Reason for skipping</strong></p>'
              + '<p class="skip-reason-text">' + esc(row.skip_reason) + "</p>"
            : "";
          blocks.push(
            '<canvas-banner variant="warning" header="' + esc(headerText) + '">'
            + reason + "</canvas-banner>"
          );
        }
        const banners = [];
        if (row.action === "modify" && !row.linked) {
          banners.push("No Canvas patient is linked to this Salesforce record. Promote this modify to create the patient from this data.");
        }
        banners.forEach((text) => {
          blocks.push(
            '<canvas-banner variant="info" header="Heads up"><p>' + esc(text) + "</p></canvas-banner>"
          );
        });
        return blocks.join("");
      };

      const AUDIT_INPUT_IDS = {
        first_name: "audit-first-name",
        last_name: "audit-last-name",
        date_of_birth: "audit-dob",
        sex_at_birth: "audit-sex",
        email: "audit-email",
        phone: "audit-phone",
        telecom_mobile: "audit-mobile",
        address_line_1: "audit-address-1",
        address_line_2: "audit-address-2",
        city: "audit-city",
        state: "audit-state",
        postal_code: "audit-postal",
        country: "audit-country",
      };

      // Human labels for the gap fill note in the promote warning, keyed by the
      // canvas field name the prefill endpoint returns in gap_filled.
      const FIELD_LABELS = {
        first_name: "First name",
        last_name: "Last name",
        date_of_birth: "Date of birth",
        sex_at_birth: "Sex at birth",
        email: "Email",
        phone: "Phone",
        address_line_1: "Address line 1",
        address_line_2: "Address line 2",
        city: "City",
        state: "State",
        postal_code: "Postal code",
        country: "Country",
      };

      // Story six, the gap banner. The pending row carries a gap object from
      // /status, count, has_anchor, older_than_last_applied, and the ordered
      // events list. The summary line groups the gap events by skipped versus
      // still pending and by action, the tooltip lists each one with its type,
      // date, and the operator who last touched it. See journal cnv-909/088 The
      // Gap Banner and 092 story six.
      const GAP_NOUN = { create: "creation", modify: "modification", delete: "deletion" };
      const NUM_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
      const numWord = (n) => (n >= 0 && n < NUM_WORDS.length) ? NUM_WORDS[n] : String(n);
      const gapNoun = (action, n) => {
        const base = GAP_NOUN[action] || action;
        return n === 1 ? base : base + "s";
      };

      const gapSummaryLine = (gap) => {
        const ORDER = ["create", "modify", "delete"];
        const skippedByAction = {};
        const pendingByAction = {};
        (gap.events || []).forEach((e) => {
          const target = e.status === "dismissed" ? skippedByAction : pendingByAction;
          target[e.action] = (target[e.action] || 0) + 1;
        });
        const phrases = [];
        ORDER.forEach((action) => {
          const n = skippedByAction[action];
          if (n) phrases.push(numWord(n) + " skipped " + gapNoun(action, n));
        });
        ORDER.forEach((action) => {
          const n = pendingByAction[action];
          if (n) phrases.push(numWord(n) + " unresolved " + gapNoun(action, n));
        });
        let line = phrases.join(" and ");
        if (line) line = line.charAt(0).toUpperCase() + line.slice(1);
        line += gap.has_anchor
          ? " since the last applied change."
          : " since this record was first received.";
        return line;
      };

      const gapEventLine = (e) => {
        const noun = GAP_NOUN[e.action] || e.action;
        const when = fmtDate(e.received_at) || "an unknown date";
        if (e.status === "dismissed") {
          return "Skipped " + noun + ", " + when + (e.who ? ", by " + e.who : "");
        }
        return "Pending " + noun + ", received " + when;
      };

      // One li per event for the inline disclosure list. Replaces the retired
      // newline joined tooltip string, the events now render as a real list the
      // toggle reveals. Each line is escaped, it carries operator names. See
      // journal cnv-941/046.
      const gapEventListItems = (gap) => {
        return (gap.events || []).map((e) => "<li>" + esc(gapEventLine(e)) + "</li>").join("");
      };

      // On the promote form the orange warning already names the skipped or open
      // create, so the gap banner drops create events to avoid repeating that one
      // event and hides when nothing else remains. The modify apply forms keep the
      // full gap since they carry no orange warning. See journal cnv-909/098 D1.
      const gapExcludingCreates = (gap) => {
        if (!gap) return gap;
        const events = (gap.events || []).filter((e) => e.action !== "create");
        return Object.assign({}, gap, { events: events, count: events.length });
      };

      // The one history banner in the apply step. It summarizes the overridden
      // events the same Details chain lists, and when ``allowStale`` is set and
      // this event is older than the last applied change it folds the warn but
      // allow heads up into the same banner rather than stacking a second one.
      // ``allowStale`` is true only on modify apply, a create has nothing to
      // replay over. Hidden when there is neither a gap nor a stale signal, so a
      // record resolved in step shows nothing. See journal cnv-909/089 question
      // two and cnv-938/022.
      const STALE_LINE = "A newer change has already been applied to this record. Applying this writes its older values over the newer ones.";
      // The toggle label describes the content, not the action, so it reads The
      // two events in this gap and stays constant whether open or closed. The
      // caret carries the expand or collapse cue. See journal cnv-941/048.
      const gapToggleLabel = (n) => {
        const noun = n === 1 ? "event" : "events";
        return "The " + numWord(n) + " " + noun + " in this gap";
      };

      // Flip the inline gap event list open or closed. Reachable by click through
      // the capture phase onBtnClick binding and by Enter or Space through the
      // keydown binding, the trigger is a plain role button span. aria-expanded
      // lives on the span and drives both the screen reader and the caret
      // rotation in CSS. See journal cnv-941/048.
      const toggleGapDetail = () => {
        const detail = document.getElementById("gap-banner-detail");
        const toggle = document.getElementById("gap-banner-toggle");
        if (!detail || !toggle) return;
        const open = toggle.getAttribute("aria-expanded") === "true";
        toggle.setAttribute("aria-expanded", open ? "false" : "true");
        detail.hidden = open;
      };

      const renderGapBanner = (gap, allowStale) => {
        const wrap = document.getElementById("gap-info");
        const body = document.getElementById("gap-banner-body");
        const detailWrap = document.getElementById("gap-banner-detail-wrap");
        const detail = document.getElementById("gap-banner-detail");
        const toggle = document.getElementById("gap-banner-toggle");
        const label = document.getElementById("gap-banner-toggle-label");
        if (!wrap || !body) return;
        const hasGap = !!(gap && gap.count);
        const stale = !!(allowStale && gap && gap.older_than_last_applied);
        // Reset the disclosure to collapsed on every render so a reopened modal
        // never shows a stale expanded list from a previous record.
        if (detail) { detail.hidden = true; detail.innerHTML = ""; }
        if (toggle) toggle.setAttribute("aria-expanded", "false");
        if (!hasGap && !stale) {
          wrap.hidden = true;
          if (detailWrap) detailWrap.hidden = true;
          return;
        }
        let line = hasGap ? gapSummaryLine(gap) : "";
        if (stale) line = line ? line + " " + STALE_LINE : STALE_LINE;
        body.textContent = line;
        if (detailWrap) {
          if (hasGap) {
            const events = gap.events || [];
            if (detail) detail.innerHTML = gapEventListItems(gap);
            if (label) label.textContent = gapToggleLabel(events.length);
            detailWrap.hidden = false;
          } else {
            detailWrap.hidden = true;
          }
        }
        wrap.hidden = false;
      };

      const clearAuditError = () => {
        const el = document.getElementById("audit-error");
        el.textContent = "";
        el.hidden = true;
      };

      const showAuditError = (msg) => {
        const el = document.getElementById("audit-error");
        el.textContent = msg;
        el.hidden = false;
      };

      const REQUIRED_FIELD_IDS = [
        "audit-first-name",
        "audit-last-name",
        "audit-dob",
        "audit-sex",
      ];

      const setAuditFieldError = (id, message) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (message) el.setAttribute("error", message);
        else el.removeAttribute("error");
      };

      const clearAuditFieldErrors = () => {
        REQUIRED_FIELD_IDS.forEach((id) => setAuditFieldError(id, ""));
        setAuditFieldError("audit-phone", "");
      };

      const validateAuditForm = () => {
        clearAuditFieldErrors();
        let firstInvalid = null;
        const flag = (id, msg) => {
          setAuditFieldError(id, msg);
          if (!firstInvalid) firstInvalid = id;
        };

        if (!readAuditInput("audit-first-name").trim()) flag("audit-first-name", "Required");
        if (!readAuditInput("audit-last-name").trim()) flag("audit-last-name", "Required");

        const dob = readAuditInput("audit-dob").trim();
        if (!dob) {
          flag("audit-dob", "Required");
        } else {
          const m = /^(\\d{4})-(\\d{2})-(\\d{2})$/.exec(dob);
          if (!m) {
            flag("audit-dob", "Must be a valid date");
          } else {
            const y = parseInt(m[1], 10);
            const mo = parseInt(m[2], 10);
            const d = parseInt(m[3], 10);
            const parsed = new Date(y, mo - 1, d);
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const sane =
              parsed.getFullYear() === y
              && parsed.getMonth() === mo - 1
              && parsed.getDate() === d
              && y >= 1000;
            if (!sane) flag("audit-dob", "Must be a valid date");
            else if (parsed > today) flag("audit-dob", "Must be a valid date");
          }
        }

        if (!readAuditInput("audit-sex").trim()) flag("audit-sex", "Required");

        const phone = readAuditInput("audit-phone").trim();
        if (phone) {
          const digits = phone.replace(/\\D/g, "");
          if (!/^\\d{10}$/.test(digits)) flag("audit-phone", "Must be a valid phone number");
        }

        return { valid: !firstInvalid, firstInvalid: firstInvalid };
      };

      const updateAuditSubmitState = () => {
        const btn = document.getElementById("audit-confirm");
        const openBtn = document.getElementById("audit-confirm-open");
        const override = document.getElementById("duplicate-override");
        const overrideChecked = !!(override && override.checked);
        const blocked =
          submittingAudit
          || duplicateLoading
          || (duplicateMatches.length > 0 && !overrideChecked);
        [btn, openBtn].forEach((b) => {
          if (!b) return;
          if (blocked) b.setAttribute("disabled", "");
          else b.removeAttribute("disabled");
        });
      };

      const runDuplicateCheck = async () => {
        const last = readAuditInput(AUDIT_INPUT_IDS.last_name).trim();
        const dob = readAuditInput(AUDIT_INPUT_IDS.date_of_birth).trim();
        const warning = document.getElementById("duplicate-warning");
        const override = document.getElementById("duplicate-override");
        const list = document.getElementById("duplicate-warning-list");
        // A modify resolves its target through the Salesforce id link, so there
        // is nothing to deduplicate. The matcher would find the linked patient
        // itself and block Apply update behind the override. Skip the check on
        // modify, keep the banner hidden, and leave the submit gate clear.
        // Create and promote still run the check because they make a new patient.
        if (auditMode === "modify") {
          duplicateCheckSeq++;
          duplicateMatches = [];
          duplicateLoading = false;
          if (warning) warning.hidden = true;
          if (override) override.checked = false;
          if (list) list.innerHTML = "";
          updateAuditSubmitState();
          return;
        }
        if (!last || !/^\\d{4}-\\d{2}-\\d{2}$/.test(dob)) {
          duplicateCheckSeq++;
          duplicateMatches = [];
          duplicateLoading = false;
          if (warning) warning.hidden = true;
          if (override) override.checked = false;
          if (list) list.innerHTML = "";
          updateAuditSubmitState();
          return;
        }
        const seq = ++duplicateCheckSeq;
        duplicateLoading = true;
        updateAuditSubmitState();
        try {
          const url = pluginPrefix
            + "/records/duplicate-check?last_name="
            + encodeURIComponent(last)
            + "&birth_date=" + encodeURIComponent(dob);
          const resp = await fetch(url, { credentials: "include" });
          if (seq !== duplicateCheckSeq) return;
          if (!resp.ok) {
            duplicateMatches = [];
            if (warning) warning.hidden = true;
            if (list) list.innerHTML = "";
            return;
          }
          const data = await resp.json();
          if (seq !== duplicateCheckSeq) return;
          duplicateMatches = (data && Array.isArray(data.matches)) ? data.matches : [];
          if (duplicateMatches.length) {
            if (override) override.checked = false;
            if (list) {
              list.innerHTML = duplicateMatches.map((p) =>
                '<li><a href="/patient/' + encodeURIComponent(String(p.id || ""))
                + '" target="_blank" rel="noopener">'
                + esc((p.first_name || "") + " " + (p.last_name || "")).trim()
                + ' <canvas-badge size="mini">' + esc(p.birth_date || "") + '</canvas-badge>'
                + '</a></li>'
              ).join("");
            }
            if (warning) warning.hidden = false;
          } else {
            if (warning) warning.hidden = true;
            if (list) list.innerHTML = "";
          }
        } catch (e) {
          if (window.console) console.error(e);
          if (seq === duplicateCheckSeq) {
            duplicateMatches = [];
            if (warning) warning.hidden = true;
            if (list) list.innerHTML = "";
          }
        } finally {
          if (seq === duplicateCheckSeq) {
            duplicateLoading = false;
            updateAuditSubmitState();
          }
        }
      };

      const scheduleDuplicateCheck = (() => {
        let timer = null;
        return () => {
          if (timer) clearTimeout(timer);
          timer = setTimeout(() => {
            timer = null;
            runDuplicateCheck();
          }, 300);
        };
      })();

      const writeAuditInput = (id, value) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.value = value == null ? "" : String(value);
      };

      const readAuditInput = (id) => {
        const el = document.getElementById(id);
        if (!el) return "";
        const v = el.value;
        return v == null ? "" : String(v);
      };

      const renderAuditMetadata = (metadata) => {
        const block = document.getElementById("audit-metadata-block");
        const list = document.getElementById("audit-metadata-list");
        const entries = metadata ? Object.entries(metadata) : [];
        if (!entries.length) {
          block.hidden = true;
          list.innerHTML = "";
          return;
        }
        block.hidden = false;
        list.innerHTML = entries
          .map(([k, v]) => "<dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd>")
          .join("");
      };

      const setAuditMode = (mode) => {
        auditMode = mode;
        const header = document.getElementById("audit-modal-header");
        const intro = document.getElementById("audit-modal-intro");
        const confirm = document.getElementById("audit-confirm");
        // Add and open lands a patient then opens its chart. It only makes sense
        // on the two paths that create a patient, create and promote. On modify
        // the patient already exists, so the button is hidden. The host display
        // is flex, so toggle style.display rather than the hidden attribute.
        const confirmOpen = document.getElementById("audit-confirm-open");
        if (confirmOpen) confirmOpen.style.display = (mode === "modify") ? "none" : "";
        // The promote warning belongs to promote mode only. openPromote shows it
        // once the prefill is in. Hide it for every other mode. The gap banner is
        // re rendered per open, hide it here so a fast reopen never flashes the
        // prior row's history.
        const promoteWarning = document.getElementById("promote-warning");
        if (promoteWarning) promoteWarning.hidden = true;
        const gapInfo = document.getElementById("gap-info");
        if (gapInfo) gapInfo.hidden = true;
        if (mode === "modify") {
          if (header) header.textContent = "Review and update patient";
          if (intro) intro.textContent = "Edit any field before applying the update to the linked Canvas patient. Blank fields are left as is, only the values you set will be pushed.";
          if (confirm) confirm.textContent = "Apply update";
        } else if (mode === "promote") {
          if (header) header.textContent = "Promote to create";
          if (intro) intro.textContent = "This modify has no linked Canvas patient. Review the fields below and create the patient from this Salesforce data. The Salesforce record id is preserved on the new patient.";
          if (confirm) confirm.textContent = "Add";
        } else {
          if (header) header.textContent = "Review and create patient";
          if (intro) intro.textContent = "Edit any field before creating the Canvas patient. The Salesforce record id is preserved on the new patient.";
          if (confirm) confirm.textContent = "Add";
        }
      };

      const openAudit = (eventId, mode) => {
        const row = pendingByEventId[eventId];
        if (!row) return;
        pendingAuditExternalId = row.external_id;
        pendingAuditEventId = eventId;
        setAuditMode(mode || "create");
        clearAuditError();
        clearAuditFieldErrors();
        duplicateCheckSeq++;
        duplicateMatches = [];
        duplicateLoading = false;
        submittingAudit = false;
        const warning = document.getElementById("duplicate-warning");
        if (warning) warning.hidden = true;
        const overrideCb = document.getElementById("duplicate-override");
        if (overrideCb) overrideCb.checked = false;
        const list = document.getElementById("duplicate-warning-list");
        if (list) list.innerHTML = "";
        const mapped = row.mapped || {};
        const telecom = row.telecom || {};
        writeAuditInput(AUDIT_INPUT_IDS.first_name, mapped.first_name || row.first_name || "");
        writeAuditInput(AUDIT_INPUT_IDS.last_name, mapped.last_name || row.last_name || "");
        writeAuditInput(AUDIT_INPUT_IDS.date_of_birth, mapped.date_of_birth || "");
        writeAuditInput(AUDIT_INPUT_IDS.sex_at_birth, mapped.sex_at_birth || "");
        writeAuditInput(AUDIT_INPUT_IDS.email, mapped.email || row.email || "");
        writeAuditInput(AUDIT_INPUT_IDS.phone, mapped.phone || row.phone || "");
        writeAuditInput(AUDIT_INPUT_IDS.telecom_mobile, telecom.mobile || "");
        writeAuditInput(AUDIT_INPUT_IDS.address_line_1, mapped.address_line_1 || "");
        writeAuditInput(AUDIT_INPUT_IDS.address_line_2, mapped.address_line_2 || "");
        writeAuditInput(AUDIT_INPUT_IDS.city, mapped.city || "");
        writeAuditInput(AUDIT_INPUT_IDS.state, mapped.state || "");
        writeAuditInput(AUDIT_INPUT_IDS.postal_code, mapped.postal_code || "");
        writeAuditInput(AUDIT_INPUT_IDS.country, mapped.country || "");
        renderAuditMetadata(row.metadata || {});
        // The gap banner reads the same on a create or a modify resolve form.
        // The older than last applied heads up only makes sense when applying a
        // modify, a create has nothing to replay over, so stale folds in only on
        // modify.
        renderGapBanner(row.gap, mode === "modify");
        document.getElementById("audit-modal").open();
        requestAnimationFrame(() => {
          const fn = document.getElementById("audit-first-name");
          if (fn && typeof fn.focus === "function") fn.focus();
        });
        updateAuditSubmitState();
        scheduleDuplicateCheck();
      };

      const seedAuditFromMapped = (mapped, telecom, row) => {
        mapped = mapped || {};
        telecom = telecom || {};
        row = row || {};
        writeAuditInput(AUDIT_INPUT_IDS.first_name, mapped.first_name || row.first_name || "");
        writeAuditInput(AUDIT_INPUT_IDS.last_name, mapped.last_name || row.last_name || "");
        writeAuditInput(AUDIT_INPUT_IDS.date_of_birth, mapped.date_of_birth || "");
        writeAuditInput(AUDIT_INPUT_IDS.sex_at_birth, mapped.sex_at_birth || "");
        writeAuditInput(AUDIT_INPUT_IDS.email, mapped.email || row.email || "");
        writeAuditInput(AUDIT_INPUT_IDS.phone, mapped.phone || row.phone || "");
        writeAuditInput(AUDIT_INPUT_IDS.telecom_mobile, telecom.mobile || "");
        writeAuditInput(AUDIT_INPUT_IDS.address_line_1, mapped.address_line_1 || "");
        writeAuditInput(AUDIT_INPUT_IDS.address_line_2, mapped.address_line_2 || "");
        writeAuditInput(AUDIT_INPUT_IDS.city, mapped.city || "");
        writeAuditInput(AUDIT_INPUT_IDS.state, mapped.state || "");
        writeAuditInput(AUDIT_INPUT_IDS.postal_code, mapped.postal_code || "");
        writeAuditInput(AUDIT_INPUT_IDS.country, mapped.country || "");
      };

      // Render the promote warning. A create that was skipped or is still open
      // for this record gets a warning banner, because promoting will create the
      // patient and close that create. The gap fill note names the only fields
      // sourced from the earlier event, the incoming modify wins everywhere else.
      const showPromoteWarning = (data) => {
        const wrap = document.getElementById("promote-warning");
        const banner = document.getElementById("promote-banner");
        const bodyEl = document.getElementById("promote-warning-body");
        const prefillEl = document.getElementById("promote-warning-prefill");
        if (!wrap || !banner || !bodyEl || !prefillEl) return;
        const ctc = (data && data.create_to_close) || {};
        let show = false;
        if (ctc.exists) {
          const skipped = ctc.status === "dismissed";
          banner.setAttribute("variant", "warning");
          banner.setAttribute("header", skipped
            ? "A create for this record was skipped"
            : "A create for this record is still open");
          let msg = skipped
            ? "A create for this record was skipped"
            : "A create for this record is still awaiting review";
          if (ctc.who) msg += " by " + ctc.who;
          if (ctc.when) msg += " on " + fmtDateTime(ctc.when);
          msg += ". Creating the patient from this modify will use the data below and close that create.";
          bodyEl.textContent = msg;
          show = true;
        } else {
          bodyEl.textContent = "";
        }
        const gf = (data && Array.isArray(data.gap_filled)) ? data.gap_filled : [];
        if (gf.length) {
          if (!show) {
            banner.setAttribute("variant", "info");
            banner.setAttribute("header", "Some fields filled from earlier Salesforce data");
          }
          const labels = gf.map((k) => FIELD_LABELS[k] || k).join(", ");
          prefillEl.textContent = "Filled from the earlier event where this modify was blank, "
            + labels + ". The incoming values win everywhere else.";
          prefillEl.hidden = false;
          show = true;
        } else {
          prefillEl.textContent = "";
          prefillEl.hidden = true;
        }
        wrap.hidden = !show;
      };

      const openPromote = async (externalId, eventId) => {
        pendingAuditExternalId = externalId;
        pendingAuditEventId = eventId;
        setAuditMode("promote");
        clearAuditError();
        clearAuditFieldErrors();
        duplicateCheckSeq++;
        duplicateMatches = [];
        duplicateLoading = false;
        submittingAudit = false;
        const dupWarning = document.getElementById("duplicate-warning");
        if (dupWarning) dupWarning.hidden = true;
        const overrideCb = document.getElementById("duplicate-override");
        if (overrideCb) overrideCb.checked = false;
        const dupList = document.getElementById("duplicate-warning-list");
        if (dupList) dupList.innerHTML = "";
        // Clear every field first so a failed prefill fetch never leaves stale
        // values from a prior open.
        Object.keys(AUDIT_INPUT_IDS).forEach((k) => writeAuditInput(AUDIT_INPUT_IDS[k], ""));
        renderAuditMetadata({});
        document.getElementById("audit-modal").open();
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(externalId) + "/promote-prefill" + eventQuery(eventId),
            { credentials: "include" }
          );
          if (!resp.ok) throw new Error("promote prefill failed");
          const data = await resp.json();
          seedAuditFromMapped(data.mapped, data.telecom, {});
          renderAuditMetadata(data.metadata || {});
          showPromoteWarning(data);
        } catch (e) {
          if (window.console) console.error(e);
          // Fall back to the pending row's own mapped data so promote still works
          // even if the prefill fetch failed. No gap fill or warning in that case.
          const row = pendingByEventId[eventId];
          if (row) {
            seedAuditFromMapped(row.mapped, row.telecom, row);
            renderAuditMetadata(row.metadata || {});
          }
        }
        // The gap banner rides on the pending row from /status, independent of
        // the prefill fetch, so it renders whether or not the prefill succeeded.
        // On promote the orange warning owns the create story, so the gap banner
        // drops create events and hides if nothing else remains, see D1. No older
        // than last applied heads up on promote, a still open create for the
        // record would already 409 the promote.
        const promoteRow = pendingByEventId[eventId];
        renderGapBanner(promoteRow && gapExcludingCreates(promoteRow.gap), false);
        requestAnimationFrame(() => {
          const fn = document.getElementById("audit-first-name");
          if (fn && typeof fn.focus === "function") fn.focus();
        });
        updateAuditSubmitState();
        scheduleDuplicateCheck();
      };

      // Paint a holding message into the Add and open tab while the create
      // effect lands. The tab is opened blank inside the click gesture so the
      // popup blocker lets it through, then this fills it so it is not a blank
      // window staring back at the operator.
      const writeTabMessage = (tab, title, body) => {
        if (!tab) return;
        try {
          tab.document.open();
          tab.document.write(
            '<!doctype html><html><head><meta charset="utf-8"><title>'
            + esc(title)
            + '</title></head><body style="font-family:system-ui,-apple-system,sans-serif;padding:2rem;color:#1a1a1a;line-height:1.5">'
            + esc(body)
            + "</body></html>"
          );
          tab.document.close();
        } catch (_) { /* cross origin or closed tab, ignore */ }
      };

      // After a create or promote lands, the Canvas patient id is not known
      // until the async effect is processed, so poll the link lookup until the
      // Salesforce identifier resolves to a patient, then point the tab at the
      // chart. Give up after a bounded wait and leave a note rather than spin.
      const openChartWhenLinked = (externalId, tab) => {
        if (!tab) return;
        const chartBase = window.location.origin + "/patient/";
        let tries = 0;
        const maxTries = 20;
        const poll = async () => {
          tries++;
          try {
            const resp = await fetch(
              pluginPrefix + "/records/" + encodeURIComponent(externalId) + "/linked-patient",
              { credentials: "include" }
            );
            if (resp.ok) {
              const data = await resp.json();
              if (data && data.patient_id) {
                try { tab.location = chartBase + encodeURIComponent(data.patient_id); } catch (_) {}
                return;
              }
            }
          } catch (_) { /* transient, keep polling */ }
          if (tries >= maxTries) {
            writeTabMessage(
              tab,
              "Patient is being created",
              "The patient is still being created in Canvas. You can close this tab and open the chart from the Synced tab in a moment."
            );
            return;
          }
          setTimeout(poll, 800);
        };
        setTimeout(poll, 800);
      };

      const submitAudit = async (openAfter) => {
        if (!pendingAuditExternalId) return;
        const validation = validateAuditForm();
        if (!validation.valid) {
          if (validation.firstInvalid) {
            const el = document.getElementById(validation.firstInvalid);
            if (el && typeof el.scrollIntoView === "function") {
              el.scrollIntoView({ block: "center", behavior: "smooth" });
            }
            if (el && typeof el.focus === "function") el.focus();
          }
          return;
        }
        clearAuditError();
        const body = {};
        Object.keys(AUDIT_INPUT_IDS).forEach((key) => {
          body[key] = readAuditInput(AUDIT_INPUT_IDS[key]);
        });
        if ((auditMode === "create" || auditMode === "promote") && (!body.last_name || !body.last_name.trim())) {
          showAuditError("Last name is required.");
          return;
        }
        clearAuditError();
        const externalId = pendingAuditExternalId;
        const endpoint = auditMode === "modify"
          ? "/review-and-update"
          : auditMode === "promote"
          ? "/promote"
          : "/accept";
        const failureMsg = auditMode === "modify"
          ? "Could not apply the update."
          : "Could not create the patient.";
        // Open and hold the chart tab now, synchronously inside the click, so
        // the popup blocker allows it. Only create and promote land a patient.
        const willOpen = !!openAfter && (auditMode === "create" || auditMode === "promote");
        let chartTab = null;
        if (willOpen) {
          chartTab = window.open("", "_blank");
          writeTabMessage(
            chartTab,
            "Creating patient",
            "Creating the patient in Canvas. This tab will open the chart automatically once it is ready."
          );
        }
        submittingAudit = true;
        updateAuditSubmitState();
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(externalId) + endpoint + eventQuery(pendingAuditEventId),
            {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            }
          );
          if (!resp.ok) {
            let msg = failureMsg;
            try {
              const data = await resp.json();
              if (data && data.error) msg = String(data.error);
            } catch (_) { /* ignore parse failure */ }
            showAuditError(msg);
            if (chartTab) chartTab.close();
            return;
          }
          document.getElementById("audit-modal").dismiss();
          pendingAuditExternalId = null;
          pendingAuditEventId = null;
          await refreshAfterAction();
          if (willOpen) openChartWhenLinked(externalId, chartTab);
        } catch (e) {
          if (window.console) console.error(e);
          showAuditError("Could not reach the plugin. Try again in a moment.");
          if (chartTab) chartTab.close();
        } finally {
          submittingAudit = false;
          updateAuditSubmitState();
        }
      };

      const reopenDirect = async (id, eventId) => {
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(id) + "/reopen" + eventQuery(eventId),
            { method: "POST", credentials: "include" }
          );
          if (!resp.ok) {
            let msg = "Could not reopen the record.";
            try {
              const data = await resp.json();
              if (data && data.error) msg = String(data.error);
            } catch (_) { /* ignore parse failure */ }
            setBanner("Reopen failed", msg);
            return;
          }
          clearBanner();
          await refreshAfterAction();
        } catch (e) {
          if (window.console) console.error(e);
          setBanner("Reopen failed", "Could not reach the plugin. Try again in a moment.");
        }
      };

      const tagDeletedDirect = async (id, eventId) => {
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(id) + "/tag-deleted" + eventQuery(eventId),
            { method: "POST", credentials: "include" }
          );
          if (!resp.ok) {
            let msg = "Could not tag the patient as deleted.";
            try {
              const data = await resp.json();
              if (data && data.error) msg = String(data.error);
            } catch (_) { /* ignore parse failure */ }
            setBanner("Tag deleted failed", msg);
            return;
          }
          clearBanner();
          await refreshAfterAction();
        } catch (e) {
          if (window.console) console.error(e);
          setBanner("Tag deleted failed", "Could not reach the plugin. Try again in a moment.");
        }
      };

      const markInactiveDirect = async (id, eventId) => {
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(id) + "/mark-inactive" + eventQuery(eventId),
            { method: "POST", credentials: "include" }
          );
          if (!resp.ok) {
            let msg = "Could not mark the patient inactive.";
            try {
              const data = await resp.json();
              if (data && data.error) msg = String(data.error);
            } catch (_) { /* ignore parse failure */ }
            setBanner("Mark inactive failed", msg);
            return;
          }
          clearBanner();
          await refreshAfterAction();
        } catch (e) {
          if (window.console) console.error(e);
          setBanner("Mark inactive failed", "Could not reach the plugin. Try again in a moment.");
        }
      };

      const unlinkOnlyDirect = async (id, eventId) => {
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(id) + "/unlink-only" + eventQuery(eventId),
            { method: "POST", credentials: "include" }
          );
          if (!resp.ok) {
            let msg = "Could not unlink the patient from Salesforce.";
            try {
              const data = await resp.json();
              if (data && data.error) msg = String(data.error);
            } catch (_) { /* ignore parse failure */ }
            setBanner("Unlink only failed", msg);
            return;
          }
          clearBanner();
          await refreshAfterAction();
        } catch (e) {
          if (window.console) console.error(e);
          setBanner("Unlink only failed", "Could not reach the plugin. Try again in a moment.");
        }
      };

      const cancelAudit = () => {
        pendingAuditExternalId = null;
        pendingAuditEventId = null;
        clearAuditError();
        document.getElementById("audit-modal").dismiss();
      };

      // The reason textarea is optional, so it is wiped on every open and on
      // cancel. A prior reason must never carry over into the next skip.
      const clearSkipReason = () => {
        const reason = document.getElementById("skip-reason");
        if (reason) reason.value = "";
      };

      const openSkip = (id, eventId) => {
        pendingSkipExternalId = id;
        pendingSkipEventId = eventId === undefined ? null : eventId;
        clearSkipReason();
        document.getElementById("skip-modal").open();
      };

      const cancelSkip = () => {
        pendingSkipExternalId = null;
        pendingSkipEventId = null;
        clearSkipReason();
        document.getElementById("skip-modal").dismiss();
      };

      const submitSkip = async () => {
        if (!pendingSkipExternalId) return;
        const id = pendingSkipExternalId;
        const eventId = pendingSkipEventId;
        const reasonEl = document.getElementById("skip-reason");
        // The reason is optional, an empty value posts an empty note.
        const note = reasonEl ? String(reasonEl.value || "").trim() : "";
        const modal = document.getElementById("skip-modal");
        const btn = document.getElementById("skip-confirm");
        btn.setAttribute("disabled", "");
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(id) + "/skip" + eventQuery(eventId),
            {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ note: note }),
            }
          );
          modal.dismiss();
          pendingSkipExternalId = null;
          pendingSkipEventId = null;
          if (!resp.ok) {
            setBanner("Could not skip the record", "Try again in a moment.");
            return;
          }
          await refreshAfterAction();
        } catch (e) {
          if (window.console) console.error(e);
          modal.dismiss();
          pendingSkipExternalId = null;
          pendingSkipEventId = null;
          setBanner("Could not skip the record", "Try again in a moment.");
        } finally {
          btn.removeAttribute("disabled");
        }
      };

      const markInactiveConfirm = (id, eventId) => {
        pendingMarkInactiveExternalId = id;
        pendingMarkInactiveEventId = eventId === undefined ? null : eventId;
        document.getElementById("mark-inactive-modal").open();
      };

      const cancelMarkInactive = () => {
        pendingMarkInactiveExternalId = null;
        pendingMarkInactiveEventId = null;
        document.getElementById("mark-inactive-modal").dismiss();
      };

      const submitMarkInactive = async () => {
        if (!pendingMarkInactiveExternalId) return;
        const id = pendingMarkInactiveExternalId;
        const eventId = pendingMarkInactiveEventId;
        const modal = document.getElementById("mark-inactive-modal");
        const btn = document.getElementById("mark-inactive-confirm");
        btn.setAttribute("disabled", "");
        try {
          const resp = await fetch(
            pluginPrefix + "/records/" + encodeURIComponent(id) + "/mark-inactive" + eventQuery(eventId),
            { method: "POST", credentials: "include" }
          );
          modal.dismiss();
          pendingMarkInactiveExternalId = null;
          pendingMarkInactiveEventId = null;
          if (!resp.ok) {
            let msg = "Could not mark the patient inactive.";
            try {
              const data = await resp.json();
              if (data && data.error) msg = String(data.error);
            } catch (_) { /* ignore parse failure */ }
            setBanner("Mark inactive failed", msg);
            return;
          }
          clearBanner();
          await refreshAfterAction();
        } catch (e) {
          if (window.console) console.error(e);
          modal.dismiss();
          pendingMarkInactiveExternalId = null;
          pendingMarkInactiveEventId = null;
          setBanner("Mark inactive failed", "Could not reach the plugin. Try again in a moment.");
        } finally {
          btn.removeAttribute("disabled");
        }
      };

      // The Delete confirmation for a patient_linked delete row. It opens the
      // three radio dialog, the operator picks one deactivation method, and
      // confirm posts to the route matching that radio carrying the delete row
      // event id. The three direct posters already clear the banner on success
      // and surface the route error on failure, so confirm reuses them. See
      // journal cnv-909/107 Phase Two.
      const openDeleteConfirm = (id, eventId) => {
        pendingDeleteExternalId = id;
        pendingDeleteEventId =
          (eventId === undefined || eventId === null || eventId === "") ? null : eventId;
        // A programmatic check does not deselect siblings the way a user click does,
        // so clear the whole group before setting the default or a prior selection
        // stays checked when the dialog reopens. See journal cnv-909/111.
        const radios = document.querySelectorAll('#delete-confirm-modal canvas-radio');
        for (let i = 0; i < radios.length; i++) radios[i].checked = false;
        const tag = document.querySelector('#delete-confirm-modal canvas-radio[value="tag-deleted"]');
        if (tag) tag.checked = true;
        document.getElementById("delete-confirm-modal").open();
      };

      const cancelDeleteConfirm = () => {
        pendingDeleteExternalId = null;
        pendingDeleteEventId = null;
        document.getElementById("delete-confirm-modal").dismiss();
      };

      const selectedDeleteMethod = () => {
        const radios = document.querySelectorAll('#delete-confirm-modal canvas-radio');
        for (let i = 0; i < radios.length; i++) {
          if (radios[i].checked) return radios[i].getAttribute("value");
        }
        return "tag-deleted";
      };

      const submitDeleteConfirm = async () => {
        if (!pendingDeleteExternalId) return;
        const id = pendingDeleteExternalId;
        const eventId = pendingDeleteEventId;
        const method = selectedDeleteMethod();
        pendingDeleteExternalId = null;
        pendingDeleteEventId = null;
        document.getElementById("delete-confirm-modal").dismiss();
        if (method === "mark-inactive") await markInactiveDirect(id, eventId);
        else if (method === "unlink-only") await unlinkOnlyDirect(id, eventId);
        else await tagDeletedDirect(id, eventId);
      };

      // ---- Settings tab, the sync automation form ------------------------
      // Loads from GET /settings on tab activation and saves through PUT
      // /settings. Banner only on failure, a successful save is silent and
      // clears any stale error, the plugin page convention. See journal
      // cnv-938/038.
      let savingSettings = false;

      const requiredFieldBoxes = () =>
        document.querySelectorAll('#sync-automation-section canvas-checkbox[data-required-field]');

      const clearSettingsError = () => {
        const el = document.getElementById("settings-error");
        if (el) { el.hidden = true; el.textContent = ""; }
      };

      const setSettingsError = (msg) => {
        const el = document.getElementById("settings-error");
        if (el) { el.textContent = msg; el.hidden = false; }
      };

      // The delete action only matters when auto delete is on, so the radio
      // group is disabled and dimmed while the toggle is off. A programmatic
      // attribute drive, not a click, so it mirrors the checkbox state on load
      // and on every change.
      const syncDeleteActionEnabled = () => {
        const cb = document.getElementById("set-auto-delete");
        const on = !!(cb && cb.checked);
        const group = document.getElementById("delete-action-group");
        if (group) {
          if (on) group.removeAttribute("data-disabled");
          else group.setAttribute("data-disabled", "");
        }
        const radios = document.querySelectorAll('#delete-action-group canvas-radio');
        for (let i = 0; i < radios.length; i++) {
          if (on) radios[i].removeAttribute("disabled");
          else radios[i].setAttribute("disabled", "");
        }
      };

      const applySettings = (s) => {
        s = s || {};
        const setChecked = (id, val) => {
          const el = document.getElementById(id);
          if (el) el.checked = !!val;
        };
        setChecked("set-auto-create", s.auto_create);
        setChecked("set-auto-modify", s.auto_modify);
        setChecked("set-auto-delete", s.auto_delete);
        setChecked("set-address-group", s.address_group_integrity);
        setChecked("set-validity", s.validity_checks);
        const da = s.delete_action || "mark_inactive";
        const radios = document.querySelectorAll('#delete-action-group canvas-radio');
        for (let i = 0; i < radios.length; i++) {
          radios[i].checked = radios[i].getAttribute("value") === da;
        }
        // Every field is a regular toggle, the box reflects the stored set.
        const req = Array.isArray(s.required_fields) ? s.required_fields : [];
        requiredFieldBoxes().forEach((b) => {
          const f = b.getAttribute("data-required-field");
          // Last name is the create floor, it stays checked regardless of the
          // stored set so the operator cannot turn it off. The evaluator floors
          // it for creates either way, this keeps the form honest about that.
          b.checked = f === "last_name" ? true : req.indexOf(f) !== -1;
        });
        syncDeleteActionEnabled();
      };

      const fetchSettings = async () => {
        try {
          const resp = await fetch(pluginPrefix + "/settings", { credentials: "include" });
          if (!resp.ok) throw new Error("settings request failed");
          const data = await resp.json();
          applySettings(data && data.settings);
          markSettingsSaved();
          clearSettingsError();
        } catch (e) {
          if (window.console) console.error(e);
          setSettingsError("Could not load settings. Try again in a moment.");
        }
      };

      const selectedDeleteAction = () => {
        const radios = document.querySelectorAll('#delete-action-group canvas-radio');
        for (let i = 0; i < radios.length; i++) {
          if (radios[i].checked) return radios[i].getAttribute("value");
        }
        return "mark_inactive";
      };

      const collectSettings = () => {
        const required = [];
        requiredFieldBoxes().forEach((b) => {
          if (b.checked) required.push(b.getAttribute("data-required-field"));
        });
        const checked = (id) => {
          const el = document.getElementById(id);
          return !!(el && el.checked);
        };
        return {
          auto_create: checked("set-auto-create"),
          auto_modify: checked("set-auto-modify"),
          auto_delete: checked("set-auto-delete"),
          delete_action: selectedDeleteAction(),
          required_fields: required,
          address_group_integrity: checked("set-address-group"),
          validity_checks: checked("set-validity"),
        };
      };

      // Dirty tracking, the Save button is disabled until the form differs from
      // the last loaded or saved state. collectSettings reads the boxes in DOM
      // order, so the snapshot is stable regardless of the stored field order.
      let savedSettingsSnapshot = null;
      const settingsSnapshot = () => JSON.stringify(collectSettings());
      const refreshSaveEnabled = () => {
        if (savingSettings) return;
        const btn = document.getElementById("settings-save");
        if (!btn) return;
        const dirty =
          savedSettingsSnapshot === null || settingsSnapshot() !== savedSettingsSnapshot;
        if (dirty) btn.removeAttribute("disabled");
        else btn.setAttribute("disabled", "");
      };
      const markSettingsSaved = () => {
        savedSettingsSnapshot = settingsSnapshot();
        refreshSaveEnabled();
      };

      const saveSettings = async () => {
        if (savingSettings) return;
        savingSettings = true;
        const btn = document.getElementById("settings-save");
        if (btn) btn.setAttribute("disabled", "");
        try {
          const resp = await fetch(pluginPrefix + "/settings", {
            method: "PUT",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(collectSettings()),
          });
          let data = {};
          try { data = await resp.json(); } catch (e) { data = {}; }
          if (!resp.ok) {
            setSettingsError((data && data.error) || "Could not save settings.");
            return;
          }
          applySettings(data && data.settings);
          markSettingsSaved();
          clearSettingsError();
        } catch (e) {
          if (window.console) console.error(e);
          setSettingsError("Could not save settings. Try again in a moment.");
        } finally {
          savingSettings = false;
          refreshSaveEnabled();
        }
      };

      const onBtnClick = (id, handler) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener("click", () => {
          if (el.hasAttribute("disabled")) return;
          handler();
        }, true);
      };

      onBtnClick("activity-load-more", loadMoreActivity);
      onBtnClick("copy-webhook-btn", copyWebhook);
      onBtnClick("audit-cancel", cancelAudit);
      onBtnClick("gap-banner-toggle", toggleGapDetail);
      // Keyboard reach for the gap disclosure. The trigger is a plain role button
      // span, so Enter and Space toggle it the same as a click, and Space does not
      // scroll the page. See journal cnv-941/048.
      const gapToggleEl = document.getElementById("gap-banner-toggle");
      if (gapToggleEl) {
        gapToggleEl.addEventListener("keydown", (e) => {
          if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
          e.preventDefault();
          toggleGapDetail();
        });
      }
      onBtnClick("audit-confirm", () => submitAudit(false));
      onBtnClick("audit-confirm-open", () => submitAudit(true));
      onBtnClick("skip-cancel", cancelSkip);
      onBtnClick("skip-confirm", submitSkip);
      onBtnClick("mark-inactive-cancel", cancelMarkInactive);
      onBtnClick("mark-inactive-confirm", submitMarkInactive);
      onBtnClick("delete-confirm-cancel", cancelDeleteConfirm);
      onBtnClick("delete-confirm-ok", submitDeleteConfirm);
      onBtnClick("settings-save", saveSettings);

      const autoDeleteEl = document.getElementById("set-auto-delete");
      if (autoDeleteEl) autoDeleteEl.addEventListener("change", syncDeleteActionEnabled);

      // Every settings control re-evaluates the Save button on change, so the
      // button enables the moment the form differs from the saved state and
      // disables again when it matches. Programmatic applySettings does not fire
      // change, so only real operator edits flip the button.
      ["set-auto-create", "set-auto-modify", "set-auto-delete", "set-address-group", "set-validity"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", refreshSaveEnabled);
      });
      document.querySelectorAll('#delete-action-group canvas-radio').forEach((r) => {
        r.addEventListener("change", refreshSaveEnabled);
      });
      requiredFieldBoxes().forEach((b) => {
        b.addEventListener("change", refreshSaveEnabled);
      });

      // ---- Settings tab, the field mapping profile editor -----------------
      // Loads from GET /field-mapping on tab activation. Default and Secret are
      // read only mirrors of their source, Custom is the one editable profile.
      // Switching the dropdown to a read only profile saves the active pointer at
      // once, editing Custom saves through the dirty gated Save. A cleared
      // Salesforce input dims its row and shows a will not sync hint, so dropping
      // a target from the map is visible before saving rather than silent. The
      // Secret option's grayed state is baked at server render time because the
      // dropdown reads its options at connect. See journal cnv-941/049 and 050.
      let mappingData = null;
      let savingMapping = false;
      let applyingMapping = false;
      let savedMappingSnapshot = null;
      // Custom has two display states, a read only view with an Edit button and an
      // edit mode with inputs, the Copy buttons up top, and Save plus Cancel at the
      // bottom. The read only profiles never enter edit mode.
      let editingCustom = false;

      const clearMappingError = () => {
        const el = document.getElementById("mapping-error");
        if (el) { el.hidden = true; el.textContent = ""; }
      };
      const setMappingError = (msg) => {
        const el = document.getElementById("mapping-error");
        if (el) { el.textContent = msg; el.hidden = false; }
      };

      const mappingInputs = () =>
        document.querySelectorAll("#mapping-body .mapping-input");

      // A read only profile row, both cells plain code. An empty Salesforce field
      // reads as a muted Not set rather than a blank cell.
      const mappingReadRow = (row) => {
        const sf = row.salesforce_field
          ? '<code class="code-inline">' + esc(row.salesforce_field) + "</code>"
          : '<span class="muted">Not set</span>';
        return "<canvas-table-row><canvas-table-cell>" + sf
          + '</canvas-table-cell><canvas-table-cell><code class="code-inline">'
          + esc(row.canvas_target) + "</code></canvas-table-cell></canvas-table-row>";
      };

      // A Custom profile row, the Salesforce cell an input keyed by its Canvas
      // target, the target itself read only. A blank input marks the row cleared.
      const mappingEditRow = (row) => {
        const cleared = row.salesforce_field ? "" : " mapping-row-cleared";
        return '<canvas-table-row class="mapping-row' + cleared
          + '" data-target="' + esc(row.canvas_target) + '">'
          + "<canvas-table-cell>"
          + '<canvas-input class="mapping-input" data-target="' + esc(row.canvas_target)
          + '" value="' + esc(row.salesforce_field)
          + '" aria-label="Salesforce field for ' + esc(row.canvas_target) + '"></canvas-input>'
          + '<span class="mapping-clear-hint">Cleared, this field will not sync</span>'
          + "</canvas-table-cell>"
          + '<canvas-table-cell><code class="code-inline">' + esc(row.canvas_target)
          + "</code></canvas-table-cell></canvas-table-row>";
      };

      // The editor rows as {salesforce_field, canvas_target} in table order, read
      // straight from the inputs so it reflects live edits.
      const mappingRowsFromInputs = () => {
        const rows = [];
        mappingInputs().forEach((inp) => {
          rows.push({
            salesforce_field: (inp.value || "").trim(),
            canvas_target: inp.getAttribute("data-target") || "",
          });
        });
        return rows;
      };

      const mappingSnapshot = () => JSON.stringify(mappingRowsFromInputs());
      const refreshMappingSave = () => {
        if (savingMapping) return;
        const btn = document.getElementById("mapping-save");
        if (!btn) return;
        const dirty = savedMappingSnapshot === null
          || mappingSnapshot() !== savedMappingSnapshot;
        if (dirty) btn.removeAttribute("disabled");
        else btn.setAttribute("disabled", "");
      };

      // Dim a row and reveal its hint the moment its input goes empty, so a
      // cleared mapping reads as deliberate before the operator saves.
      const reflectClearedRow = (inp) => {
        const row = inp.closest(".mapping-row");
        if (!row) return;
        if ((inp.value || "").trim()) row.classList.remove("mapping-row-cleared");
        else row.classList.add("mapping-row-cleared");
      };

      const bindMappingInputs = () => {
        mappingInputs().forEach((inp) => {
          const onEdit = () => { reflectClearedRow(inp); refreshMappingSave(); };
          inp.addEventListener("input", onEdit);
          inp.addEventListener("change", onEdit);
        });
      };

      const showMappingButton = (id, on) => {
        const el = document.getElementById(id);
        if (el) el.hidden = !on;
      };

      // Paint the table for a profile in the right state. Custom in edit mode
      // renders inputs, the Copy buttons, the bottom Save and Cancel, and resets
      // the dirty baseline. Custom in view mode and the read only profiles render
      // plain cells, view mode keeps the Edit button so the operator can switch in.
      const renderMappingProfile = (profile) => {
        const profiles = (mappingData && mappingData.profiles) || {};
        const rows = profiles[profile] || [];
        const body = document.getElementById("mapping-body");
        const custom = profile === "custom";
        const editing = custom && editingCustom;
        if (body && toggleRegion(rows, "mapping-empty", "mapping-table")) {
          body.innerHTML = rows.map(editing ? mappingEditRow : mappingReadRow).join("");
        }
        if (editing) {
          bindMappingInputs();
          savedMappingSnapshot = mappingSnapshot();
          refreshMappingSave();
        }
        // Edit shows only in Custom view mode, the Copy buttons and the bottom row
        // only in edit mode, the read only profiles show none of them.
        showMappingButton("mapping-edit", custom && !editing);
        showMappingButton("mapping-copy-defaults", editing);
        showMappingButton("mapping-copy-secret", editing);
        const bottom = document.getElementById("mapping-bottom-actions");
        if (bottom) bottom.hidden = !editing;
        const badge = document.getElementById("mapping-active-badge");
        if (badge) {
          badge.textContent = custom ? "Customizable" : "Read only";
          if (custom) badge.setAttribute("color", "blue");
          else badge.removeAttribute("color");
          badge.hidden = false;
        }
        const hint = document.getElementById("mapping-profile-hint");
        if (hint) {
          hint.textContent = editing
            ? "Edit the Salesforce field for each Canvas target. Clear a field to stop syncing it. Copy in defaults to start from the full set."
            : custom
              ? "Your editable mapping. Click Edit to change the Salesforce field for each Canvas target."
              : (profile === "secret"
                ? "The mapping from the SF_FIELD_MAPPING_JSON secret. Read only."
                : "The built in mapping. Read only.");
        }
        scheduleEqualize();
      };

      // Edit click, swap Custom into edit mode in place.
      const enterCustomEdit = () => { editingCustom = true; renderMappingProfile("custom"); };

      const applyMapping = (data) => {
        if (!data) return;
        mappingData = data;
        const dd = document.getElementById("mapping-profile");
        if (dd) { applyingMapping = true; dd.value = data.active; applyingMapping = false; }
        renderMappingProfile(data.active);
      };

      const fetchFieldMapping = async () => {
        try {
          const resp = await fetch(pluginPrefix + "/field-mapping", { credentials: "include" });
          if (!resp.ok) throw new Error("field mapping request failed");
          const data = await resp.json();
          applyMapping(data);
          clearMappingError();
        } catch (e) {
          if (window.console) console.error(e);
          setMappingError("Could not load field mapping. Try again in a moment.");
        }
      };

      // PUT the active profile and, for Custom, the edited rows. A read only
      // profile sends no custom key so the stored rows are preserved.
      const putFieldMapping = async (profile, custom) => {
        const payload = { active: profile };
        if (custom) payload.custom = custom;
        const resp = await fetch(pluginPrefix + "/field-mapping", {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        let data = {};
        try { data = await resp.json(); } catch (e) { data = {}; }
        if (!resp.ok) throw new Error((data && data.error) || "Could not save the profile.");
        return data;
      };

      const onMappingProfileChange = async () => {
        if (applyingMapping) return;
        const dd = document.getElementById("mapping-profile");
        const profile = dd ? dd.value : "default";
        // A profile switch always lands in read only view, Custom included, the
        // Edit button takes it into edit mode. Render first so the chosen profile
        // shows at once, then persist. Custom sends its stored rows so selecting
        // it materializes the seed, a read only profile leaves them untouched.
        editingCustom = false;
        renderMappingProfile(profile);
        try {
          const custom = profile === "custom"
            ? (((mappingData && mappingData.profiles) || {}).custom || [])
            : null;
          applyMapping(await putFieldMapping(profile, custom));
          clearMappingError();
        } catch (e) {
          setMappingError(e.message);
          fetchFieldMapping();
        }
      };

      const saveMapping = async () => {
        if (savingMapping) return;
        savingMapping = true;
        const btn = document.getElementById("mapping-save");
        if (btn) btn.setAttribute("disabled", "");
        try {
          const rows = mappingRowsFromInputs();
          const data = await putFieldMapping("custom", rows);
          // Only drop back to view mode once the save lands, a failure keeps the
          // inputs so the operator can fix and retry.
          editingCustom = false;
          applyMapping(data);
          clearMappingError();
        } catch (e) {
          if (window.console) console.error(e);
          setMappingError("Could not save the mapping. Try again in a moment.");
        } finally {
          savingMapping = false;
          refreshMappingSave();
        }
      };

      // Cancel, drop edits and return Custom to its read only view.
      const cancelMapping = () => {
        editingCustom = false;
        renderMappingProfile("custom");
        clearMappingError();
      };

      // Seed the Custom inputs from another profile's rows, matched by Canvas
      // target, without saving. The operator reviews then saves. A target the
      // source does not carry is left blank, which the cleared styling marks.
      const seedCustomFrom = (sourceRows) => {
        const byTarget = {};
        (sourceRows || []).forEach((r) => { byTarget[r.canvas_target] = r.salesforce_field || ""; });
        mappingInputs().forEach((inp) => {
          inp.value = byTarget[inp.getAttribute("data-target") || ""] || "";
          reflectClearedRow(inp);
        });
        refreshMappingSave();
      };
      const copyMappingDefaults = () =>
        seedCustomFrom(((mappingData && mappingData.profiles) || {}).default || []);
      const copyMappingSecret = () =>
        seedCustomFrom(((mappingData && mappingData.profiles) || {}).secret || []);

      const mappingProfileDropdown = document.getElementById("mapping-profile");
      if (mappingProfileDropdown) mappingProfileDropdown.addEventListener("change", onMappingProfileChange);
      onBtnClick("mapping-edit", enterCustomEdit);
      onBtnClick("mapping-save", saveMapping);
      onBtnClick("mapping-cancel", cancelMapping);
      onBtnClick("mapping-copy-defaults", copyMappingDefaults);
      onBtnClick("mapping-copy-secret", copyMappingSecret);

      const onDuplicateInput = () => scheduleDuplicateCheck();
      const lastNameEl = document.getElementById(AUDIT_INPUT_IDS.last_name);
      if (lastNameEl) {
        lastNameEl.addEventListener("input", onDuplicateInput);
        lastNameEl.addEventListener("change", onDuplicateInput);
      }
      const dobEl = document.getElementById(AUDIT_INPUT_IDS.date_of_birth);
      if (dobEl) {
        dobEl.addEventListener("input", onDuplicateInput);
        dobEl.addEventListener("change", onDuplicateInput);
      }
      const overrideEl = document.getElementById("duplicate-override");
      if (overrideEl) {
        overrideEl.addEventListener("change", updateAuditSubmitState);
      }

      document.getElementById("page-content").addEventListener("click", (e) => {
        const target = e.target;
        if (!target || !target.closest) return;
        const createBtn = target.closest("canvas-button[data-create-id]");
        if (createBtn && !createBtn.hasAttribute("disabled")) {
          openAudit(createBtn.getAttribute("data-event-id"), "create");
          return;
        }
        const promoteBtn = target.closest("canvas-button[data-promote-id]");
        if (promoteBtn && !promoteBtn.hasAttribute("disabled")) {
          openPromote(promoteBtn.getAttribute("data-promote-id"), promoteBtn.getAttribute("data-event-id"));
          return;
        }
        const editBtn = target.closest("canvas-button[data-modify-edit-id]");
        if (editBtn && !editBtn.hasAttribute("disabled")) {
          openAudit(editBtn.getAttribute("data-event-id"), "modify");
          return;
        }
        const deleteBtn = target.closest("canvas-button[data-delete-id]");
        if (deleteBtn && !deleteBtn.hasAttribute("disabled")) {
          openDeleteConfirm(deleteBtn.getAttribute("data-delete-id"), deleteBtn.getAttribute("data-event-id"));
          return;
        }
        const skipBtn = target.closest("canvas-button[data-skip-id]");
        if (skipBtn && !skipBtn.hasAttribute("disabled")) {
          openSkip(skipBtn.getAttribute("data-skip-id"), skipBtn.getAttribute("data-event-id"));
          return;
        }
        const reopenBtn = target.closest("canvas-button[data-reopen-id]");
        if (reopenBtn && !reopenBtn.hasAttribute("disabled")) {
          reopenDirect(reopenBtn.getAttribute("data-reopen-id"), reopenBtn.getAttribute("data-event-id"));
          return;
        }
        // The Salesforce and patient chart link buttons open their destination in a
        // new tab. A canvas-button does not navigate on its own the way an anchor
        // did, so the open runs here inside the user click. This runs ahead of the
        // row toggle so a Synced link click opens the link rather than expanding.
        const extBtn = target.closest("canvas-button[data-ext-url]");
        if (extBtn && !extBtn.hasAttribute("disabled")) {
          window.open(extBtn.getAttribute("data-ext-url"), "_blank", "noopener,noreferrer");
          return;
        }
        // The raw payload button prints the row's stashed Salesforce JSON into the
        // shared modal. The JSON sits on the hidden pre the detail filled on expand,
        // so the modal reads it straight off the row rather than refetching.
        const payloadBtn = target.closest(".row-detail-payload-btn");
        if (payloadBtn && !payloadBtn.hasAttribute("disabled")) {
          const detailRoot = payloadBtn.closest(".row-detail");
          const stash = detailRoot ? detailRoot.querySelector(".row-detail-payload-json") : null;
          const modalPre = document.getElementById("raw-payload-json");
          if (modalPre) modalPre.textContent = stash ? stash.textContent : "";
          document.getElementById("raw-payload-modal").open();
          return;
        }
        // A click anywhere on an expandable summary row, outside any button, toggles
        // its detail row. Buttons inside the row returned above, so only the row body
        // and the caret reach here. A click on a caret menu item retargets to the
        // canvas-menu-button host, which is not a canvas-button, so the menu host is
        // excused explicitly or selecting Skip would also toggle the row. See journal
        // cnv-941/003 and cnv-941/015.
        const summary = target.closest(".expandable-summary");
        if (summary && !target.closest("canvas-button, canvas-menu-button")) {
          toggleRow(summary);
        }
      }, true);

      // Skip from the caret menu of the two part action. The component closes
      // itself and returns focus to the trigger before this fires, so only the
      // modal open runs here. See journal cnv-941/015.
      document.getElementById("page-content").addEventListener("select", (e) => {
        const host = e.target && e.target.closest
          ? e.target.closest("canvas-menu-button[data-menu-skip-id]") : null;
        if (!host || !e.detail || e.detail.value !== "skip") return;
        openSkip(host.getAttribute("data-menu-skip-id"), host.getAttribute("data-event-id"));
      });

      // While a caret menu is open, stamp the host so the status poll skips the
      // repaint that would destroy it, cleared on close. The menu flips upward
      // on its own when it would hit the scroll area bottom, so the page no
      // longer reserves space for it and the tables below never shift. See
      // journal cnv-941/015 and cnv-941/025.
      document.getElementById("page-content").addEventListener("open", (e) => {
        const host = e.target;
        if (!host || !host.tagName || host.tagName.toLowerCase() !== "canvas-menu-button") return;
        host.setAttribute("data-menu-open", "");
      });
      document.getElementById("page-content").addEventListener("close", (e) => {
        const host = e.target;
        if (!host || !host.tagName || host.tagName.toLowerCase() !== "canvas-menu-button") return;
        host.removeAttribute("data-menu-open");
      });

      // Keyboard reach for the expandable rows. The summary row is focusable and
      // exposes role button, so Enter and Space toggle it the same as a click, and
      // Space does not scroll the page. Enter and Space inside an open caret menu
      // retarget to the canvas-menu-button host, excused the same as in the click
      // handler. See journal cnv-941/003 and cnv-941/015.
      document.getElementById("page-content").addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
        const target = e.target;
        if (!target || !target.closest) return;
        const summary = target.closest(".expandable-summary");
        if (!summary || target.closest("canvas-button, canvas-menu-button")) return;
        e.preventDefault();
        toggleRow(summary);
      });

      document.addEventListener("tab-change", (e) => {
        const panel = e && e.detail && e.detail.panel;
        if (panel) writeStoredTab(panel);
        if (panel === "panel-settings") { scheduleEqualize(); fetchSettings(); fetchFieldMapping(); }
        activityActive = panel === "panel-activity";
        if (activityActive) fetchActivity();
        syncedActive = panel === "panel-records";
        if (syncedActive) fetchSynced();
      });
      window.addEventListener("resize", scheduleEqualize);

      fetchStatus();
      fetchSynced();
      setInterval(() => {
        fetchStatus();
        if (activityActive) fetchActivity();
        if (syncedActive) fetchSynced();
      }, 15000);
    })();
  </script>
</body>
</html>"""


def render_admin_page(
    *, plugin_name: str, secret_field_mapping_available: bool = True
) -> str:
    """Render the admin HTML with the given plugin slug substituted in URLs.

    ``secret_field_mapping_available`` bakes the Secret field mapping profile's
    grayed state and Not specified badge at render time, so they are set when the
    dropdown reads its options at connect rather than mutated afterward, which the
    dropdown does not observe. See journal cnv-941/049 and
    [[canvas_plugin_ui_combobox_sync]].
    """
    secret_disabled = "" if secret_field_mapping_available else "disabled"
    secret_badge = (
        ""
        if secret_field_mapping_available
        else '<canvas-badge size="mini">Not specified</canvas-badge>'
    )
    copy_secret_disabled = "" if secret_field_mapping_available else "disabled"
    return (
        _TEMPLATE.replace("__PLUGIN_NAME__", plugin_name)
        .replace("__ASSET_VERSION__", ASSET_VERSION)
        .replace("__SECRET_OPTION_DISABLED__", secret_disabled)
        .replace("__SECRET_OPTION_BADGE__", secret_badge)
        .replace("__COPY_SECRET_DISABLED__", copy_secret_disabled)
    )


# A Lucide lock glyph, inlined so the no access page needs no asset fetch. The
# console's web component bundle is gated to admins, so this page cannot rely on
# it. See the no access template below.
_LOCK_ICON = (
    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>'
    '<path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>'
)


# Self contained page shown to a logged in staff member who is not on the admin
# allowlist. It carries its own tokens and font link so it renders without the
# admin gated design system bundle, and it names the staff id so an
# administrator can drop it straight into SF_ADMIN_STAFF_IDS.
_NO_ACCESS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Salesforce integration</title>
  <link href="https://fonts.googleapis.com/css?family=Lato:400,700&subset=latin" rel="stylesheet">
  <style>
    :root {
      --font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --code-font: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      --color-text: rgba(0, 0, 0, 0.87);
      --color-text-muted: #767676;
      --color-border: rgba(34, 36, 38, 0.15);
      --color-surface: #FFFFFF;
      --color-bg: #F5F5F5;
      --radius: .28571429rem;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      font-family: var(--font-family);
      color: var(--color-text);
      background: var(--color-surface);
    }
    .gate {
      max-width: 520px;
      width: 100%;
      border: 1px solid var(--color-border);
      border-radius: var(--radius);
      padding: 24px;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
    }
    .gate-icon { color: var(--color-text-muted); margin-bottom: 12px; line-height: 0; }
    .gate h1 { font-size: 1.42857143rem; font-weight: 700; margin: 0 0 8px; }
    .gate p { margin: 0 0 16px; line-height: 1.5; }
    .id-label { font-size: 0.85714286rem; color: var(--color-text-muted); margin: 0 0 4px; }
    .id-box {
      font-family: var(--code-font);
      font-size: 0.92857143rem;
      background: var(--color-bg);
      border: 1px solid var(--color-border);
      border-radius: var(--radius);
      padding: 8px 12px;
      overflow-wrap: anywhere;
      user-select: all;
    }
    .muted { color: var(--color-text-muted); }
  </style>
</head>
<body>
  <main class="gate" role="alert">
    <div class="gate-icon">__LOCK_ICON__</div>
    <h1>You do not have access</h1>
    <p>The Salesforce integration console is limited to approved staff. Ask an administrator to add your staff id to the access list, then reload this page.</p>
    __STAFF_ID_BLOCK__
  </main>
</body>
</html>"""


def render_no_access_page(*, staff_id: str) -> str:
    """Render the page a logged in staff sees when not on the admin allowlist.

    Self contained so it renders without the admin gated design system bundle.
    It names the staff id so an administrator can add it to SF_ADMIN_STAFF_IDS.
    The id is escaped because it arrives on a request header.
    """
    safe_id = escape(staff_id or "")
    if safe_id:
        block = (
            '<p class="id-label">Your staff id</p>\n'
            '    <div class="id-box">' + safe_id + "</div>"
        )
    else:
        block = (
            '<p class="muted">Your staff session did not carry a staff id. '
            "Sign in to Canvas as a staff member, then reload.</p>"
        )
    return _NO_ACCESS_TEMPLATE.replace("__LOCK_ICON__", _LOCK_ICON).replace(
        "__STAFF_ID_BLOCK__", block
    )


_SETTINGS_ICON = (
    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="3"></circle>'
    '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06'
    "-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09"
    "A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83"
    "l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h"
    ".09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83"
    "-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 "
    "4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 "
    "2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 "
    '0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>'
)


# Self contained page shown when the plugin secrets are missing or malformed,
# so load_config raises before the admin allowlist is ever checked. It carries
# its own tokens and font link so it renders without the admin gated design
# system bundle. It deliberately names neither the missing secret nor the staff
# id, it only tells the viewer the integration is not configured and to contact
# an administrator.
_NOT_CONFIGURED_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Salesforce integration</title>
  <link href="https://fonts.googleapis.com/css?family=Lato:400,700&subset=latin" rel="stylesheet">
  <style>
    :root {
      --font-family: lato, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --color-text: rgba(0, 0, 0, 0.87);
      --color-text-muted: #767676;
      --color-border: rgba(34, 36, 38, 0.15);
      --color-surface: #FFFFFF;
      --radius: .28571429rem;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      font-family: var(--font-family);
      color: var(--color-text);
      background: var(--color-surface);
    }
    .gate {
      max-width: 520px;
      width: 100%;
      border: 1px solid var(--color-border);
      border-radius: var(--radius);
      padding: 24px;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
    }
    .gate-icon { color: var(--color-text-muted); margin-bottom: 12px; line-height: 0; }
    .gate h1 { font-size: 1.42857143rem; font-weight: 700; margin: 0 0 8px; }
    .gate p { margin: 0; line-height: 1.5; }
  </style>
</head>
<body>
  <main class="gate" role="alert">
    <div class="gate-icon">__SETTINGS_ICON__</div>
    <h1>Salesforce integration is not configured</h1>
    <p>The Salesforce integration has not been configured properly. Contact an administrator to finish setting it up, then reload this page.</p>
  </main>
</body>
</html>"""


def render_not_configured_page() -> str:
    """Render the page shown when the plugin secrets are missing or malformed.

    Self contained so it renders without the admin gated design system bundle.
    It carries no detail about which secret is missing and no staff id, by
    design. It only tells the viewer the integration is not configured and to
    contact an administrator.
    """
    return _NOT_CONFIGURED_TEMPLATE.replace("__SETTINGS_ICON__", _SETTINGS_ICON)


__all__ = (
    "render_admin_page",
    "render_no_access_page",
    "render_not_configured_page",
)
