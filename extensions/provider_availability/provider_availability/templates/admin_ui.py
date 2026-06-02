"""Renders the admin UI HTML for provider availability management."""

import json
from datetime import datetime, timezone

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

ADMIN_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Provider Availability</title>
<link rel="stylesheet" href="/plugin-io/api/provider_availability/api/tokens.css?v={{cache_bust}}">
<link rel="stylesheet" href="/plugin-io/api/provider_availability/api/typography.css?v={{cache_bust}}">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Serif+Display&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/plugin-io/api/provider_availability/api/admin.css?v={{cache_bust}}">
<script src="/plugin-io/api/provider_availability/api/canvas-components.js?v={{cache_bust}}"></script>
</head>
<body>

<main class="main">

  <div class="page-header">
    <div class="page-title-block">
      <h1>Provider Availability</h1>
      <span class="title-accent"></span>
      <p>Manage open hours and blocked time across all providers.</p>
    </div>
  </div>

  <div id="status-msg"></div>

  <canvas-tabs id="main-tabs">
    <canvas-tab for="panel-availability" active><canvas-tab-label>Availability</canvas-tab-label></canvas-tab>
    <canvas-tab for="panel-editor"><canvas-tab-label>Add / Edit</canvas-tab-label></canvas-tab>
    <canvas-tab for="panel-settings"><canvas-tab-label>Settings</canvas-tab-label></canvas-tab>

  <!-- Availability Panel -->
  <canvas-tab-panel id="panel-availability">
    <div class="filter-bar">
      <div id="ms-filter-provider" class="multi-select" style="flex:1;max-width:400px;"></div>
      <button class="btn btn-expand-collapse" onclick="toggleAllCards()">Expand All</button>
    </div>
    <div id="legend-bar-container" class="legend-bar"></div>
    <div class="provider-list" id="accordion-container">
      <div class="empty-state">Loading...</div>
    </div>
  </canvas-tab-panel>

  <!-- Editor Panel -->
  <canvas-tab-panel id="panel-editor">
    <div class="panel">
      <div class="panel-header">
        <div class="panel-header-left">
          <div class="panel-title" id="editor-title">Add New Rule</div>
          <div class="panel-subtitle">Fields marked <span style="color:var(--cyan)">*</span> are required</div>
        </div>
        <div class="panel-header-right">
        </div>
      </div>

      <div class="panel-body">
        <!-- Hidden fields -->
        <input type="hidden" id="editing_rule_id" value="">
        <input type="hidden" id="editing_block_id" value="">
        <input type="hidden" id="editing_recurring_block_id" value="">
        <input type="hidden" id="editing_group_id" value="">
        <input type="hidden" id="editing_type" value="available">

        <div id="group-banner" class="group-banner" style="display:none;">
          <canvas-checkbox id="apply_to_group" checked></canvas-checkbox>
          <span id="group-banner-text">This was created for N providers. Apply changes to all?</span>
        </div>

        <!-- Type selector -->
        <div id="type-selector-section">
          <div class="section-label">Rule Type <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
          <div class="type-selector">
            <div class="type-card selected-avail" id="type-available" onclick="selectType('available')">
              <div class="type-icon icon-avail">
                <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              </div>
              <div>
                <h3 style="color:var(--avail)">Available</h3>
                <p>Bookable hours for patient appointments</p>
              </div>
            </div>
            <div class="type-card" id="type-blocked" onclick="selectType('blocked')">
              <div class="type-icon icon-block">
                <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"/></svg>
              </div>
              <div>
                <h3 style="color:var(--block)">Blocked</h3>
                <p>Block time from patient scheduling during a provider's available hours</p>
              </div>
            </div>
            <div class="type-card" id="type-hold" onclick="selectType('hold')">
              <div class="type-icon icon-hold">
                <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M9 4v16m6-16v16"/></svg>
              </div>
              <div>
                <h3 style="color:var(--hold)">Hold</h3>
                <p>Reserve slots for same-day or next-day booking</p>
              </div>
            </div>
          </div>
        </div>

        <!-- AVAILABLE form -->
        <div id="form-available">
          <div>
            <div class="section-label">Who</div>
            <div class="form-row" style="grid-template-columns:1fr 1fr;">
              <div class="field">
                <label>Provider(s) <span class="req">*</span></label>
                <div id="ms-provider" class="multi-select"></div>
              </div>
              <div class="field">
                <label>Location(s)</label>
                <div id="ms-location" class="multi-select"></div>
              </div>
            </div>
            <div class="form-row" style="grid-template-columns:1fr 1fr;margin-top:14px;">
              <div class="field">
                <label>Reason</label>
                <canvas-input type="text" id="rule_reason" placeholder="e.g. Office hours, Telehealth, Walk-ins..."></canvas-input>
              </div>
              <div class="field">
                <label>Visit Type(s)</label>
                <div id="ms-visit-type" class="multi-select"></div>
              </div>
            </div>
          </div>

          <!-- Schedule Mode Toggle -->
          <div>
            <div class="section-label">Schedule</div>
            <div class="schedule-mode-toggle">
              <button type="button" class="mode-btn active" id="mode-single" onclick="setScheduleMode('single')">Single Event</button>
              <button type="button" class="mode-btn" id="mode-recurring" onclick="setScheduleMode('recurring')">Recurring</button>
            </div>
          </div>

          <!-- Single Event fields (default visible) -->
          <div id="single-event-fields">
            <div class="section-label">Date &amp; Time <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
            <p id="single-event-tz-hint" class="tz-convert-hint" style="margin-bottom:8px;"></p>
            <div class="form-row" style="grid-template-columns:1fr 1fr 1fr;">
              <div class="field" style="position:relative;">
                <label>Date <span class="req">*</span></label>
                <input class="input date-facade" type="text" id="single_date_display" readonly placeholder="Select date..." onclick="document.getElementById('single_date').showPicker()">
                <input type="date" id="single_date" class="date-hidden" onchange="syncDateFacade('single_date')" tabindex="-1">
              </div>
              <div class="field">
                <label>Start Time <span class="req">*</span></label>
                <canvas-input type="time" id="single_start_time"></canvas-input>
              </div>
              <div class="field">
                <label>End Time <span class="req">*</span></label>
                <canvas-input type="time" id="single_end_time"></canvas-input>
              </div>
            </div>
          </div>

          <!-- Recurring schedule fields (hidden in single mode) -->
          <div id="weekly-schedule-fields" style="display:none;">
            <div id="repeats-section">
              <div class="section-label">Repeats</div>
              <div class="form-row" style="grid-template-columns:120px 200px;align-items:end;">
                <div class="field">
                  <label>Every</label>
                  <input class="input" type="number" id="recurrence_interval" min="1" value="1" placeholder="1">
                </div>
                <div class="field">
                  <label>Frequency</label>
                  <select id="recurrence_frequency" class="input" onchange="onRecurrenceFrequencyChange()">
                    <option value="weekly" selected>Week(s)</option>
                    <option value="daily">Day(s)</option>
                  </select>
                </div>
              </div>
              <p style="font-size:12.5px;color:var(--text-muted);margin:6px 0 0;">
                e.g. <em>2 weeks</em> = bi-weekly &middot; <em>17 days</em> = every 17 days
              </p>
              <p id="daily-mode-hint" style="display:none;"></p>
            </div>
            <div>
              <div class="section-label">Effective Date Range</div>
              <div class="form-row">
                <div class="field" style="position:relative;">
                  <label>Start Date</label>
                  <input class="input date-facade" type="text" id="effective_start_display" readonly placeholder="Select date..." onclick="document.getElementById('effective_start').showPicker()">
                  <input type="date" id="effective_start" class="date-hidden" onchange="syncDateFacade('effective_start')" tabindex="-1">
                </div>
                <div class="field" style="position:relative;">
                  <label>End Date</label>
                  <input class="input date-facade" type="text" id="effective_end_display" readonly placeholder="Select date..." onclick="document.getElementById('effective_end').showPicker()">
                  <input type="date" id="effective_end" class="date-hidden" onchange="syncDateFacade('effective_end')" tabindex="-1">
                  <div class="no-end-row">
                    <canvas-checkbox id="no_end_date" label="No end date" checked onchange="toggleNoEndDate('effective_end', this.checked)"></canvas-checkbox>
                  </div>
                </div>
              </div>
            </div>

            <div id="weekly-grid-wrap">
              <div class="section-label" id="schedule-editor-label">Weekly Schedule <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
              <div class="tz-apply-row">
                <p id="weekly-avail-tz-hint" class="tz-convert-hint"></p>
                <div class="apply-btns">
                  <button type="button" onclick="applyToMF('schedule-editor')">Apply to M-F</button>
                  <button type="button" onclick="applyToAll('schedule-editor')">Apply to all days</button>
                </div>
              </div>
              <div id="schedule-editor" class="days-grid"></div>
            </div>
            <div id="time-windows-wrap" style="display:none;">
              <div class="section-label">Time Windows <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
              <p style="font-size:12.5px;color:var(--text-muted);margin:0 0 8px;">These hours apply on every recurring date.</p>
              <div id="time-windows-rows"></div>
              <button type="button" class="add-time-btn" onclick="addDailyTimeWindow('time-windows-rows')">
                <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M12 4v16m8-8H4"/></svg>
                Add hours
              </button>
            </div>
          </div>

          <div id="date-overrides-section" style="display:none;">
            <div class="section-label">Date Overrides</div>
            <p style="font-size:12.5px;color:var(--text-muted);margin-bottom:8px;">Override the weekly schedule for specific dates without creating a new rule.</p>
            <div id="overrides-list"></div>
            <div id="override-form" style="display:none;margin-top:12px;padding:14px;border:1px solid var(--border);border-radius:8px;">
              <input type="hidden" id="editing_override_date" value="">
              <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px;position:relative;">
                <label style="font-size:13px;font-weight:600;">Date</label>
                <input class="time-input date-facade" type="text" id="override_date_display" readonly placeholder="Select date..." style="flex:0 0 auto;min-width:180px;" onclick="document.getElementById('override_date').showPicker()">
                <input type="date" id="override_date" class="date-hidden" onchange="syncDateFacade('override_date')" tabindex="-1">
              </div>
              <div style="font-size:13px;font-weight:600;margin-bottom:4px;">Hours</div>
              <div id="override-windows">
                <button type="button" class="add-time-btn" onclick="addOverrideWindow()">
                  <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M12 4v16m8-8H4"/></svg>
                  Add hours
                </button>
              </div>
              <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px;margin-top:10px;">
                <label style="font-size:13px;font-weight:600;">Reason</label>
                <canvas-input type="text" id="override_reason" placeholder="e.g. Holiday, Special hours..." style="flex:1;min-width:180px;"></canvas-input>
              </div>
              <div style="display:flex;gap:8px;margin-top:12px;">
                <canvas-button size="sm" onclick="saveOverride()">Save Override</canvas-button>
                <canvas-button variant="ghost" size="sm" onclick="hideOverrideForm()">Cancel</canvas-button>
              </div>
            </div>
            <button type="button" class="add-time-btn" id="add-override-btn" onclick="showOverrideForm()" style="margin-top:8px;">
              <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M12 4v16m8-8H4"/></svg>
              Add Override
            </button>
          </div>

          <div id="settings-section">
            <div class="section-label">Scheduling Settings</div>
            <div class="settings-grid">
              <div class="setting-item">
                <span class="setting-label">Pre-appointment Buffer</span>
                <span class="setting-desc">Blocked time before each appointment</span>
                <div style="display:flex;align-items:center;gap:6px;">
                  <input type="number" id="buffer_pre" value="0" min="0" placeholder="0" style="flex:1;">
                  <span class="unit-label">minutes</span>
                </div>
              </div>
              <div class="setting-item">
                <span class="setting-label">Post-appointment Buffer</span>
                <span class="setting-desc">Blocked time after each appointment</span>
                <div style="display:flex;align-items:center;gap:6px;">
                  <input type="number" id="buffer_post" value="0" min="0" placeholder="0" style="flex:1;">
                  <span class="unit-label">minutes</span>
                </div>
              </div>
              <div class="setting-item">
                <span class="setting-label">Minimum Lead Time</span>
                <span class="setting-desc">How far in advance patients must book</span>
                <div style="display:flex;align-items:center;gap:6px;">
                  <input type="number" id="min_lead_hours" value="0" min="0" placeholder="0" style="flex:1;">
                  <span class="unit-label">hours</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- BLOCKED form -->
        <div id="form-blocked" style="display:none;">
          <div>
            <div class="section-label">Who</div>
            <div class="form-row" style="grid-template-columns:1fr 1fr;">
              <div class="field">
                <label>Provider(s) <span class="req">*</span></label>
                <div id="ms-block-provider" class="multi-select"></div>
              </div>
              <div class="field">
                <label>Location(s)</label>
                <div id="ms-block-location" class="multi-select"></div>
              </div>
            </div>
            <div class="form-row" style="grid-template-columns:1fr 1fr;margin-top:14px;">
              <div class="field">
                <label>Reason</label>
                <canvas-input type="text" id="block_reason" placeholder="e.g. PTO, Lunch break, Admin time..."></canvas-input>
              </div>
            </div>
          </div>

          <!-- Block Schedule Mode Toggle -->
          <div id="block-type-selector">
            <div class="section-label">Block Type</div>
            <div class="schedule-mode-toggle">
              <button type="button" class="mode-btn active" id="block-mode-single" onclick="setBlockMode('single')">Single Event</button>
              <button type="button" class="mode-btn" id="block-mode-recurring" onclick="setBlockMode('recurring')">Recurring</button>
            </div>
          </div>

          <div id="oneoff-block-fields">
            <div class="section-label">Date &amp; Time <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
            <p id="block-event-tz-hint" class="tz-convert-hint" style="margin-bottom:8px;"></p>
            <div class="form-row" style="grid-template-columns:auto auto;align-items:center;margin-bottom:6px;">
              <canvas-checkbox id="block_all_day" label="All day" onchange="onBlockAllDayToggle(this.checked)"></canvas-checkbox>
              <div style="font-size:12.5px;color:var(--text-muted);">Tip: add multiple dates below to block them all in one save (e.g. holiday list).</div>
            </div>
            <div class="form-row" id="block-time-row" style="grid-template-columns:1fr 1fr 1fr;">
              <div class="field" style="position:relative;">
                <label>Date <span class="req">*</span></label>
                <input class="input date-facade" type="text" id="block_date_display" readonly placeholder="Select date..." onclick="document.getElementById('block_date').showPicker()">
                <input type="date" id="block_date" class="date-hidden" onchange="syncDateFacade('block_date')" tabindex="-1">
              </div>
              <div class="field" id="block-start-time-field">
                <label>Start Time <span class="req">*</span></label>
                <canvas-input type="time" id="block_start_time"></canvas-input>
              </div>
              <div class="field" id="block-end-time-field">
                <label>End Time <span class="req">*</span></label>
                <canvas-input type="time" id="block_end_time"></canvas-input>
              </div>
            </div>
            <div class="form-row" style="grid-template-columns:1fr auto;align-items:end;margin-top:6px;">
              <div class="field" style="font-size:12.5px;color:var(--text-muted);">Add the date above and click <strong>Add date</strong> to queue more days. The block will be saved for each.</div>
              <button type="button" class="add-time-btn" onclick="addBlockDateChip()">+ Add date</button>
            </div>
            <div id="block-date-chips" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;"></div>
          </div>

          <div id="block-weekly-fields" style="display:none;">
          <div id="rb-repeats-section">
            <div class="section-label">Repeats</div>
            <div class="form-row" style="grid-template-columns:120px 200px;align-items:end;">
              <div class="field">
                <label>Every</label>
                <input class="input" type="number" id="rb_recurrence_interval" min="1" value="1" placeholder="1">
              </div>
              <div class="field">
                <label>Frequency</label>
                <select id="rb_recurrence_frequency" class="input" onchange="onRecurringBlockFrequencyChange()">
                  <option value="weekly" selected>Week(s)</option>
                  <option value="daily">Day(s)</option>
                </select>
              </div>
            </div>
            <p style="font-size:12.5px;color:var(--text-muted);margin:6px 0 0;">
              e.g. <em>2 weeks</em> = bi-weekly &middot; <em>17 days</em> = every 17 days
            </p>
            <p id="rb-daily-mode-hint" style="display:none;"></p>
          </div>
          <div id="blocked-effective-dates">
            <div class="section-label">Effective Date Range</div>
            <div class="form-row">
              <div class="field" style="position:relative;">
                <label>Start Date</label>
                <input class="input date-facade" type="text" id="rb_effective_start_display" readonly placeholder="Select date..." onclick="document.getElementById('rb_effective_start').showPicker()">
                <input type="date" id="rb_effective_start" class="date-hidden" onchange="syncDateFacade('rb_effective_start')" tabindex="-1">
              </div>
              <div class="field" style="position:relative;">
                <label>End Date</label>
                <input class="input date-facade" type="text" id="rb_effective_end_display" readonly placeholder="Select date..." onclick="document.getElementById('rb_effective_end').showPicker()">
                <input type="date" id="rb_effective_end" class="date-hidden" onchange="syncDateFacade('rb_effective_end')" tabindex="-1">
                <div class="no-end-row">
                  <canvas-checkbox id="rb_no_end_date" label="No end date" checked onchange="toggleNoEndDate('rb_effective_end', this.checked)"></canvas-checkbox>
                </div>
              </div>
            </div>
          </div>

          <div id="blocked-weekly-schedule">
            <div class="section-label" id="rb-schedule-editor-label">Weekly Block Schedule <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
            <div class="tz-apply-row">
              <p id="weekly-block-tz-hint" class="tz-convert-hint"></p>
              <div class="apply-btns">
                <button type="button" onclick="applyToMF('recurring-block-schedule-editor')">Apply to M-F</button>
                <button type="button" onclick="applyToAll('recurring-block-schedule-editor')">Apply to all days</button>
              </div>
            </div>
            <div id="recurring-block-schedule-editor" class="days-grid"></div>
          </div>
          <div id="rb-time-windows-wrap" style="display:none;">
            <div class="section-label">Block Time Windows <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
            <p style="font-size:12.5px;color:var(--text-muted);margin:0 0 8px;">These hours block availability on every recurring date.</p>
            <div id="rb-time-windows-rows"></div>
            <button type="button" class="add-time-btn" onclick="addDailyTimeWindow('rb-time-windows-rows')">
              <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M12 4v16m8-8H4"/></svg>
              Add hours
            </button>
          </div>
          </div><!-- /block-weekly-fields -->
        </div>

        <!-- HOLD form -->
        <div id="form-hold" style="display:none;">
          <input type="hidden" id="editing_hold_id" value="">
          <input type="hidden" id="editing_hold_group_id" value="">
          <div>
            <div class="section-label">Who</div>
            <div class="form-row" style="grid-template-columns:1fr 1fr;">
              <div class="field">
                <label>Provider(s) <span class="req">*</span></label>
                <div id="ms-hold-provider" class="multi-select"></div>
              </div>
              <div class="field">
                <label>Location(s)</label>
                <div id="ms-hold-location" class="multi-select"></div>
              </div>
            </div>
            <div class="form-row" style="grid-template-columns:1fr 1fr;margin-top:14px;">
              <div class="field">
                <label>Reason</label>
                <canvas-input type="text" id="hold_reason" placeholder="e.g. Same-day slots, Walk-in reserve..."></canvas-input>
              </div>
              <div class="field">
                <label>Hold Type <span class="req">*</span></label>
                <canvas-dropdown id="hold_type_select">
                  <canvas-option value="same_day" selected>Same-Day Hold (releases day-of)</canvas-option>
                  <canvas-option value="next_day">Next-Day Hold (releases day before)</canvas-option>
                </canvas-dropdown>
              </div>
            </div>
          </div>
          <div>
            <div class="section-label">Effective Date Range</div>
            <div class="form-row">
              <div class="field" style="position:relative;">
                <label>Start Date</label>
                <input class="input date-facade" type="text" id="hold_effective_start_display" readonly placeholder="Select date..." onclick="document.getElementById('hold_effective_start').showPicker()">
                <input type="date" id="hold_effective_start" class="date-hidden" onchange="syncDateFacade('hold_effective_start')" tabindex="-1">
              </div>
              <div class="field" style="position:relative;">
                <label>End Date</label>
                <input class="input date-facade" type="text" id="hold_effective_end_display" readonly placeholder="Select date..." onclick="document.getElementById('hold_effective_end').showPicker()">
                <input type="date" id="hold_effective_end" class="date-hidden" onchange="syncDateFacade('hold_effective_end')" tabindex="-1">
                <div class="no-end-row">
                  <canvas-checkbox id="hold_no_end_date" label="No end date" checked onchange="toggleNoEndDate('hold_effective_end', this.checked)"></canvas-checkbox>
                </div>
              </div>
            </div>
          </div>
          <div>
            <div class="section-label">Weekly Hold Schedule <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span></div>
            <div class="tz-apply-row">
              <p id="weekly-hold-tz-hint" class="tz-convert-hint"></p>
              <div class="apply-btns">
                <button type="button" onclick="applyToMF('hold-schedule-editor')">Apply to M-F</button>
                <button type="button" onclick="applyToAll('hold-schedule-editor')">Apply to all days</button>
              </div>
            </div>
            <div id="hold-schedule-editor" class="days-grid"></div>
          </div>
        </div>

      </div>

      <div class="panel-footer">
        <canvas-button variant="ghost" onclick="showTab('availability')">Cancel</canvas-button>
        <canvas-button onclick="saveCurrentForm()">Save Rule</canvas-button>
      </div>
    </div>
  </canvas-tab-panel>

  <!-- Settings Panel -->
  <canvas-tab-panel id="panel-settings">
    <div class="panel">
      <div class="panel-header">
        <div class="panel-header-left">
          <div class="panel-title">Settings</div>
          <div class="panel-subtitle">Configure access control and provider timezones.</div>
        </div>
      </div>
      <div class="panel-body">

        <!-- Access control -->
        <div>
          <div class="section-label">Access Control</div>
          <p style="font-size:13px;color:var(--text-dim);line-height:1.5;">
            Access is controlled by the <strong>allowed-staff-keys</strong> plugin secret.
            Configure it under <strong>Settings &gt; Plugins &gt; provider_availability</strong> in your Canvas instance.
            List the staff UUIDs (dashed or undashed) who should have access, separated by commas.
            Leave it empty to allow any logged-in Canvas staff member.
          </p>
        </div>

        
        <!-- Bulk assignment -->
        <div>
          <div class="section-label">Set All Providers</div>
          <p style="font-size:13px;color:var(--text-muted);margin-bottom:10px;">Assign the same timezone to every provider at once.</p>
          <div class="form-row" style="grid-template-columns:1fr auto;align-items:end;gap:12px;">
            <div class="field">
              <label>Timezone</label>
              <select class="input" id="bulk-tz-select"></select>
            </div>
            <canvas-button onclick="applyBulkTimezone()" style="white-space:nowrap;">Apply to All</canvas-button>
          </div>
        </div>

        
        <!-- Per-provider list -->
        <div>
          <div class="section-label">Per-Provider Timezones</div>
          <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px;">Configure timezone individually for each provider.</p>
          <div id="provider-tz-list" class="provider-tz-list">
            <div class="empty-state">Loading providers...</div>
          </div>
        </div>


      </div>
    </div>
  </canvas-tab-panel>

  </canvas-tabs>

</main>

<div id="status-msg-bottom"></div>

<canvas-modal id="confirm-modal" size="small">
  <canvas-modal-header dismissable>Confirm</canvas-modal-header>
  <canvas-modal-content>
    <p id="confirm-message"></p>
  </canvas-modal-content>
  <canvas-modal-footer>
    <canvas-button variant="ghost" id="confirm-cancel-btn">Cancel</canvas-button>
    <canvas-button variant="danger" id="confirm-ok-btn">Delete</canvas-button>
  </canvas-modal-footer>
</canvas-modal>

{{PRELOADED_SCRIPT}}
<script src="/plugin-io/api/provider_availability/api/admin.js?v={{cache_bust}}"></script>
</body>
</html>"""


def render_admin_page(preloaded: dict | None = None) -> str:
    """Return the admin UI HTML with optional pre-rendered data."""
    if preloaded:
        # Escape </script> in JSON to prevent injection
        raw = json.dumps(preloaded, default=str)
        safe_json = raw.replace("</", "<\\/")
        script_tag = f"<script>window.__PRELOADED__={safe_json};</script>"
    else:
        script_tag = ""
    html = ADMIN_HTML_TEMPLATE.replace("{{PRELOADED_SCRIPT}}", script_tag)
    return html.replace("{{cache_bust}}", _CACHE_BUST)
