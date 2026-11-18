const API_BASE = '/plugin-io/api/provider_availability/api';
const DAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday'];
const DAY_ABBR = {monday:'Mon',tuesday:'Tue',wednesday:'Wed',thursday:'Thu',friday:'Fri',saturday:'Sat',sunday:'Sun'};
const DAY_FULL = {monday:'Monday',tuesday:'Tuesday',wednesday:'Wednesday',thursday:'Thursday',friday:'Friday',saturday:'Saturday',sunday:'Sunday'};
const USER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const AVATAR_CLASSES = ['avatar-a','avatar-b','avatar-c'];

const SVG_CHECK = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path d="M5 13l4 4L19 7"/></svg>';
const SVG_X = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path d="M6 18L18 6M6 6l12 12"/></svg>';
const SVG_PAUSE = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M9 4v16m6-16v16"/></svg>';
const SVG_OVERRIDE = '<svg fill="currentColor" viewBox="0 0 24 24" stroke="none"><path d="M12 3l9.5 16.5H2.5L12 3z"/></svg>';
const SVG_PLUS = '<svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M12 4v16m8-8H4"/></svg>';
const SVG_X_SM = '<svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M6 18L18 6M6 6l12 12"/></svg>';

const SVG_CHEVRON_RIGHT = '<svg class="row-chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M9 5l7 7-7 7"/></svg>';

const SVG_ROUND = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6"/></svg>';

// Rule types in the order the card counts and rows use.
const RULE_TYPES = [
  { key: 'avail', label: 'Available', one: 'available', many: 'available', chip: 'chip-avail', svg: SVG_CHECK },
  { key: 'over', label: 'Override', one: 'override', many: 'overrides', chip: 'chip-override', svg: SVG_OVERRIDE },
  { key: 'round', label: 'Facility round', one: 'facility round', many: 'facility rounds', chip: 'chip-round', svg: SVG_ROUND },
  { key: 'fblock', label: 'Facility block', one: 'facility block', many: 'facility blocks', chip: 'chip-fblock', svg: SVG_ROUND },
  { key: 'block', label: 'Blocked', one: 'blocked', many: 'blocked', chip: 'chip-block', svg: SVG_X },
  { key: 'hold', label: 'Hold', one: 'hold', many: 'holds', chip: 'chip-hold', svg: SVG_PAUSE },
];
const RULE_TYPE = {};
RULE_TYPES.forEach(function(t) { RULE_TYPE[t.key] = t; });
// Rows sort by type, then date.
const RULE_ORDER = { avail: 1, round: 2, over: 3, fblock: 4, block: 5, hold: 6 };

// Fixed column widths, so opening a row never moves the columns.
const RULE_TABLE_HEAD = '<colgroup><col style="width:170px"><col style="width:180px"><col style="width:158px"><col>' +
  '<col style="width:190px"><col style="width:114px"></colgroup>' +
  '<thead><tr><th>Type</th><th>When</th><th>Hours</th><th>Details</th><th>Effective</th><th></th></tr></thead>';

const DAY_PLURAL = { monday: 'Mondays', tuesday: 'Tuesdays', wednesday: 'Wednesdays', thursday: 'Thursdays', friday: 'Fridays', saturday: 'Saturdays', sunday: 'Sundays' };

// "Wed, Nov 11, 2026"
function fmtWeekdayDate(isoDate) {
  if (!isoDate) return '';
  var parts = isoDate.split('-');
  var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}

// When a recurring rule runs: "Tuesdays", "Mon, Wed, Fri", "Every 2 weeks, Thursday",
// "Daily", or the date for a one-day rule.
function whenLabel(r, days) {
  if (r.effective_start && r.effective_start === r.effective_end) return fmtWeekdayDate(r.effective_start);
  if (r.recurrence_frequency === 'daily') return dailyDayLabel(r);
  var iv = r.recurrence_interval || 1;
  if (iv === 1) return days.length === 1 ? DAY_PLURAL[days[0]] : formatDayRange(days);
  return 'Every ' + iv + ' weeks, ' + (days.length === 1 ? DAY_FULL[days[0]] : formatDayRange(days));
}

// The Effective column: one date, or a range on one line. Expired rows say when they ended.
function effectiveHtml(start, end, expired) {
  if (!start) return '<span class="col-empty">No start date</span>';
  if (expired && end) return '<span class="eff-ended">Ended ' + fmtDate(end) + '</span>';
  if (!end || end === start) return fmtDate(start);
  var sameYear = start.slice(0, 4) === end.slice(0, 4);
  var from = sameYear
    ? new Date(start + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : fmtDate(start);
  return from + ' – ' + fmtDate(end);
}

// "15 min before, 10 min after, 2 hr lead time"
function bufferText(r) {
  var buf = r.buffer_minutes || {};
  var lead = (r.booking_interval || {}).min_lead_hours || 0;
  var parts = [];
  if (buf.pre > 0 && paFeatureOn('buffers')) parts.push(buf.pre + ' min before');
  if (buf.post > 0 && paFeatureOn('buffers')) parts.push(buf.post + ' min after');
  if (lead > 0 && paFeatureOn('lead_time')) parts.push(lead + ' hr lead time');
  return parts.join(', ');
}

// A facility block's details: not bookable, and how many patients the facility has.
// The counts load once, the first time a facility block is drawn, then the list redraws.
var _facilityPatientCounts = null;
var _facilityPatientCountsLoading = false;

async function loadFacilityPatientCounts() {
  if (_facilityPatientCounts || _facilityPatientCountsLoading) return;
  _facilityPatientCountsLoading = true;
  var data = await apiCall('/facility-patient-counts');
  _facilityPatientCountsLoading = false;
  // A failed load leaves the Patients line out rather than retrying on every draw.
  _facilityPatientCounts = (data && !data.error && data.counts) || {};
  if (data && !data.error) renderAccordion();
}

function facilityBlockItems(b) {
  var items = [['Booking', 'Not bookable']];
  if (!_facilityPatientCounts) { loadFacilityPatientCounts(); return items; }
  var n = _facilityPatientCounts[String(b.facility_id)];
  if (typeof n === 'number') items.push(['Patients', n + ' at ' + (b.facility_name || facilityName(b.facility_id))]);
  return items;
}

// The place, in full: the facility, one location, the first location and a count, or all locations.
function placeHtml(names) {
  if (!names.length) return '<span class="place"><span class="rule-where">All locations</span></span>';
  var more = names.length > 1 ? '<span class="more"> + ' + (names.length - 1) + ' more</span>' : '';
  return '<span class="place"><span class="rule-where">' + _escHtml(names[0]) + '</span>' + more + '</span>';
}

// One row: type, when, hours, place and reason, effective, actions. When it has
// details, a row below it lists them and the row opens to show it.
function ruleRowHtml(o) {
  var t = RULE_TYPE[o.type];
  var expandable = o.items.length > 0;
  var reason = o.reason ? '<span class="why"><span class="dot">·</span>' + _escHtml(o.reason) + '</span>' : '';
  var h = '<tr class="t-' + o.type + (expandable ? ' data-row' : '') + '"' + (expandable ? ' onclick="toggleRowDetail(this, event)"' : '') + '>';
  h += '<td>' + (expandable ? SVG_CHEVRON_RIGHT : '<span class="chev-space"></span>') +
    '<span class="type-chip ' + t.chip + '">' + t.svg + '</span>' + _escHtml(t.label) + '</td>';
  h += '<td>' + _escHtml(o.when) + '</td>';
  h += '<td>' + o.hours + '</td>';
  h += '<td class="dcell"><div class="dline">' + o.place + reason + '</div></td>';
  h += '<td class="eff">' + o.effective + '</td>';
  h += '<td><div class="rule-acts"><button type="button" class="lnk-sm" onclick=\'' + o.edit + '\'>Edit</button>' +
    '<button type="button" class="lnk-sm danger" onclick=\'' + o.del + '\'>Delete</button></div></td>';
  h += '</tr>';
  if (expandable) {
    h += '<tr class="t-' + o.type + ' detail-row"><td colspan="3"></td><td colspan="3" class="x3"><dl>' +
      o.items.map(function(it) { return '<dt>' + _escHtml(it[0]) + '</dt><dd>' + _escHtml(it[1]) + '</dd>'; }).join('') +
      '</dl></td></tr>';
  }
  return h;
}

// A reason cut short by the column shows in full on hover and in the row's details.
// A row whose only detail is that reason becomes expandable for it.
function fitReasons() {
  document.querySelectorAll('.provider-card:not(.collapsed) .rule-table tbody tr:not(.detail-row)').forEach(function(row) {
    var why = row.querySelector('.why');
    if (!why) return;
    why.style.display = 'block';
    var cut = why.scrollWidth > why.clientWidth + 1;
    why.style.display = '';
    var full = why.textContent.replace(/^·/, '');
    why.classList.toggle('is-cut', cut);
    why.title = cut ? full : '';
    var det = row.nextElementSibling;
    if (!det || !det.classList.contains('detail-row')) {
      if (!cut) return;
      row.insertAdjacentHTML('afterend', '<tr class="' + row.className + ' detail-row"><td colspan="3"></td><td colspan="3" class="x3"><dl></dl></td></tr>');
      det = row.nextElementSibling;
      row.classList.add('data-row');
      row.setAttribute('onclick', 'toggleRowDetail(this, event)');
      var space = row.querySelector('.chev-space');
      if (space) space.outerHTML = SVG_CHEVRON_RIGHT;
    }
    var dl = det.querySelector('dl');
    var have = dl.querySelector('[data-reason]');
    if (cut && !have) dl.insertAdjacentHTML('afterbegin', '<dt data-reason>Reason</dt><dd data-reason>' + _escHtml(full) + '</dd>');
    if (!cut && have) dl.querySelectorAll('[data-reason]').forEach(function(x) { x.remove(); });
  });
}
window.addEventListener('resize', fitReasons);


let _providers = [];
let _locations = [];
let _visitTypes = [];
let _overviewData = [];
let _savedView = [];  // the viewer's saved default view, as loaded from the server
let _showExpired = false;  // expired rows are hidden until asked for
let _providerTzMap = {};  // {provider_id: {timezone, explicit}} — authoritative TZ state
let _tzOptions = [];
var _viewTz = null;  // null = practice TZ (default)
const COMMON_TZS = ['US/Eastern','US/Central','US/Mountain','America/Phoenix','US/Pacific','US/Alaska','US/Hawaii','UTC'];

/* ---------- Formatting helpers ---------- */

function fmtTime(isoStr) {
  if (!isoStr) return '';
  // Naive ISO strings (no Z or offset) are in the provider's timezone.
  // Extract HH:MM directly to avoid browser local-timezone reinterpretation.
  if (!isoStr.includes('Z') && !isoStr.includes('+') && !/T\d{2}:\d{2}:\d{2}-/.test(isoStr)) {
    return fmtHHMM(isoStr.slice(11, 16));
  }
  const d = new Date(isoStr);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: _practiceTz });
}

function fmtDateTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: USER_TZ }) + ' ' +
         d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short', timeZone: USER_TZ });
}

function fmtHHMM(hhmm) {
  if (!hhmm) return '';
  const [h, m] = hhmm.split(':').map(Number);
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  return h12 + ':' + String(m).padStart(2, '0') + ' ' + ampm;
}

function fmtDate(isoDate) {
  if (!isoDate) return '';
  const parts = isoDate.split('-');
  const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
function fmtDateRange(startIso, endIso) {
  if (!startIso || !endIso) return '';
  if (startIso === endIso) return fmtDate(startIso);
  return 'Start: ' + fmtDate(startIso) + '<br>End: ' + fmtDate(endIso);
}

function convertHHMM(hhmm, fromTz, toTz) {
  if (!hhmm || fromTz === toTz) return hhmm;
  var parts = hhmm.split(':').map(Number);
  // Use a reference date (a Wednesday to avoid DST transition edges)
  var refDate = new Date(2026, 0, 7, parts[0], parts[1], 0);
  // Get the "wall clock" hour/minute in fromTz
  var fromStr = refDate.toLocaleString('en-US', { timeZone: fromTz, hour12: false, hour: '2-digit', minute: '2-digit', day: 'numeric' });
  var toStr = refDate.toLocaleString('en-US', { timeZone: toTz, hour12: false, hour: '2-digit', minute: '2-digit', day: 'numeric' });
  // Parse to get the offset difference
  var fromParts = fromStr.split(',')[0].trim();
  var toParts = toStr.split(',')[0].trim();
  // Use Intl to get numeric values
  var fromFmt = new Intl.DateTimeFormat('en-US', { timeZone: fromTz, hour: 'numeric', minute: 'numeric', hour12: false, day: 'numeric' });
  var toFmt = new Intl.DateTimeFormat('en-US', { timeZone: toTz, hour: 'numeric', minute: 'numeric', hour12: false, day: 'numeric' });
  var fromResolved = fromFmt.formatToParts(refDate);
  var toResolved = toFmt.formatToParts(refDate);
  var getVal = function(resolved, type) {
    var p = resolved.find(function(x) { return x.type === type; });
    return p ? parseInt(p.value, 10) : 0;
  };
  var fromDay = getVal(fromResolved, 'day');
  var fromH = getVal(fromResolved, 'hour');
  var fromM = getVal(fromResolved, 'minute');
  var toDay = getVal(toResolved, 'day');
  var toH = getVal(toResolved, 'hour');
  var toM = getVal(toResolved, 'minute');
  // Compute the offset in minutes between the two TZs
  var offsetMin = ((toDay - fromDay) * 1440) + ((toH - fromH) * 60) + (toM - fromM);
  // Apply offset to original time
  var totalMin = parts[0] * 60 + parts[1] + offsetMin;
  var dayShift = 0;
  if (totalMin < 0) { totalMin += 1440; dayShift = -1; }
  else if (totalMin >= 1440) { totalMin -= 1440; dayShift = 1; }
  var h = Math.floor(totalMin / 60);
  var m = totalMin % 60;
  var result = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  if (dayShift !== 0) result += (dayShift > 0 ? ' +1d' : ' -1d');
  return result;
}

function fmtHHMMConverted(hhmm, fromTz) {
  var sourceTz = fromTz || _practiceTz;
  var targetTz = _viewTz || sourceTz;
  var converted = convertHHMM(hhmm, sourceTz, targetTz);
  if (!converted) return '';
  // Check for day shift suffix
  var dayTag = '';
  if (converted.indexOf(' +1d') !== -1) { dayTag = '<sup>+1d</sup>'; converted = converted.replace(' +1d', ''); }
  else if (converted.indexOf(' -1d') !== -1) { dayTag = '<sup>-1d</sup>'; converted = converted.replace(' -1d', ''); }
  return fmtHHMM(converted) + dayTag;
}

function providerTz(pid) {
  var entry = _providerTzMap[pid];
  if (entry && entry.explicit) return entry.timezone;
  var p = _overviewData.find(function(x) { return x.provider_id === pid; });
  return (p && p.provider_timezone) || _practiceTz;
}

/** Merge overview data into _providerTzMap (non-destructive — keeps entries not in overview). */
function _syncProviderTzMapFromOverview() {
  _overviewData.forEach(function(p) {
    if (p.provider_timezone_explicit) {
      _providerTzMap[p.provider_id] = { timezone: p.provider_timezone, explicit: true };
    }
  });
}

function convertIsoTime(isoStr, fromTz, toTz) {
  if (!isoStr) return '';
  // For naive ISO strings, extract HH:MM and use the same conversion as weekly rules.
  if (!isoStr.includes('Z') && !isoStr.includes('+') && !/T\d{2}:\d{2}:\d{2}-/.test(isoStr)) {
    var hhmm = isoStr.slice(11, 16);
    if (fromTz === toTz) return fmtHHMM(hhmm);
    return fmtHHMMConverted(hhmm, fromTz);
  }
  if (fromTz === toTz) return fmtTime(isoStr);
  var d = new Date(isoStr);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: toTz });
}

function changeViewTz(tz) {
  _viewTz = (tz === 'provider') ? null : tz;
  renderAccordion();
}

// Delegated handler for TZ dropdown (inline onchange may be blocked by CSP)
document.addEventListener('change', function(e) {
  if (e.target && e.target.id === 'view-tz-select') {
    changeViewTz(e.target.value);
  }
  if (e.target && e.target.classList.contains('tz-inline-select')) {
    updateEditorTzConversionHint(e.target);
  }
});

function syncDateFacade(hiddenId) {
  var hidden = document.getElementById(hiddenId);
  var display = document.getElementById(hiddenId + '_display');
  var clear = document.getElementById(hiddenId + '_clear');
  if (clear) clear.style.display = hidden.value ? '' : 'none';
  if (!display || !hidden.value) { if (display) display.value = ''; return; }
  var parts = hidden.value.split('-');
  var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  var weekday = d.toLocaleDateString('en-US', { weekday: 'short' });
  var rest = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  display.value = weekday + ' ' + rest;
}

var _scheduleMode = 'single';
var _blockMode = 'single';

function setScheduleMode(mode) {
  _scheduleMode = mode;
  var isSingle = mode === 'single';
  var isRecurring = mode === 'recurring';
  document.getElementById('single-event-fields').style.display = isSingle ? '' : 'none';
  document.getElementById('weekly-schedule-fields').style.display = isRecurring ? '' : 'none';
  document.getElementById('mode-single').classList.toggle('active', isSingle);
  document.getElementById('mode-recurring').classList.toggle('active', isRecurring);
  _updateScheduleEditorLabel();
  // Show/hide overrides section based on mode and editing state
  var ovr = document.getElementById('date-overrides-section');
  if (ovr) {
    if (isSingle) {
      ovr.style.display = 'none';
    } else {
      ovr.style.display = '';
      renderOverridesList();
    }
  }
  updateEditorTzLabels();
}

function _updateScheduleEditorLabel() {
  var lbl = document.getElementById('schedule-editor-label');
  if (!lbl) return;
  var asterisk = ' <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span>';
  var fq = document.getElementById('recurrence_frequency');
  var freq = fq ? fq.value : 'weekly';
  lbl.innerHTML = (freq === 'daily' ? 'Time windows' : 'Weekly schedule') + asterisk;
}

function setBlockMode(mode) {
  _blockMode = mode;
  var isSingle = mode === 'single';
  var isRecurring = mode === 'recurring';
  document.getElementById('oneoff-block-fields').style.display = isSingle ? '' : 'none';
  document.getElementById('block-weekly-fields').style.display = isRecurring ? '' : 'none';
  document.getElementById('block-mode-single').classList.toggle('active', isSingle);
  document.getElementById('block-mode-recurring').classList.toggle('active', isRecurring);
  _updateBlockScheduleEditorLabel();
  updateEditorTzLabels();
}

function onRecurrenceFrequencyChange() {
  var sel = document.getElementById('recurrence_frequency');
  var isDaily = !!(sel && sel.value === 'daily');
  var weeklyWrap = document.getElementById('weekly-grid-wrap');
  var dailyWrap = document.getElementById('time-windows-wrap');
  if (weeklyWrap) weeklyWrap.style.display = isDaily ? 'none' : '';
  if (dailyWrap) dailyWrap.style.display = isDaily ? '' : 'none';
  // Seed one empty row when switching to daily for the first time
  if (isDaily) {
    var rows = document.getElementById('time-windows-rows');
    if (rows && !rows.querySelector('.day-time-inputs')) {
      addDailyTimeWindow('time-windows-rows');
    }
  }
  _updateScheduleEditorLabel();
}

function onRecurringBlockFrequencyChange() {
  var sel = document.getElementById('rb_recurrence_frequency');
  var isDaily = !!(sel && sel.value === 'daily');
  var weeklyWrap = document.getElementById('blocked-weekly-schedule');
  var dailyWrap = document.getElementById('rb-time-windows-wrap');
  if (weeklyWrap) weeklyWrap.style.display = isDaily ? 'none' : '';
  if (dailyWrap) dailyWrap.style.display = isDaily ? '' : 'none';
  if (isDaily) {
    var rows = document.getElementById('rb-time-windows-rows');
    if (rows && !rows.querySelector('.day-time-inputs')) {
      addDailyTimeWindow('rb-time-windows-rows');
    }
  }
  _updateBlockScheduleEditorLabel();
}

function _updateBlockScheduleEditorLabel() {
  var lbl = document.getElementById('rb-schedule-editor-label');
  if (!lbl) return;
  var asterisk = ' <span style="color:var(--block);font-size:13px;margin-left:2px;">*</span>';
  var fq = document.getElementById('rb_recurrence_frequency');
  var freq = fq ? fq.value : 'weekly';
  lbl.innerHTML = (freq === 'daily' ? 'Block time windows' : 'Weekly block schedule') + asterisk;
}

function _readRecurrenceFields(intervalId, frequencyId) {
  var ivEl = document.getElementById(intervalId);
  var fqEl = document.getElementById(frequencyId);
  var iv = ivEl ? parseInt(ivEl.value, 10) : 1;
  if (!iv || iv < 1) iv = 1;
  var fq = fqEl ? fqEl.value : 'weekly';
  if (fq !== 'daily' && fq !== 'weekly') fq = 'weekly';
  return { interval: iv, frequency: fq };
}

function _firstWindowFromSchedule(schedule) {
  // For daily mode, take the time windows from the first weekday that has any.
  var keys = Object.keys(schedule || {});
  for (var i = 0; i < keys.length; i++) {
    if ((schedule[keys[i]] || []).length > 0) return schedule[keys[i]];
  }
  return [];
}

/* ---------- Time field (typed, e.g. "9:07 AM") ---------- */

function _pad2(n) { n = String(n); return n.length < 2 ? '0' + n : n; }

function _fmt12(v) {
  var p = String(v).split(':');
  if (p.length < 2) return v;
  var h = parseInt(p[0], 10);
  var min = p[1];
  var ap = h < 12 ? 'AM' : 'PM';
  var h12 = h % 12;
  if (h12 === 0) h12 = 12;
  return h12 + ':' + min + ' ' + ap;
}

// Parse "9:07 AM", "9 am", "21:07", "9:07" -> canonical "HH:MM" (or "" if invalid).
function parseTimeTo24(str) {
  if (!str) return '';
  var m = String(str).trim().toLowerCase().match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
  if (!m) return '';
  var h = parseInt(m[1], 10);
  var min = m[2] ? parseInt(m[2], 10) : 0;
  var ap = m[3];
  if (min > 59) return '';
  if (ap) {
    if (h < 1 || h > 12) return '';
    if (ap === 'pm' && h !== 12) h += 12;
    if (ap === 'am' && h === 12) h = 0;
  } else if (h > 23) {
    return '';
  }
  return _pad2(h) + ':' + _pad2(min);
}

// 15-minute suggestions for the time fields. Options carry the same 12-hour
// display text the visible input uses, so picking one flows through the
// existing parse-on-input handler with no special casing. A datalist only
// suggests, so typing an off-grid time such as "9:07 AM" still works exactly
// as before. Order is plain chronological from 12:00 AM: a datalist cannot be
// told where to scroll, so reordering it would only move the oddity around.
var TIME_OPTIONS_ID = 'pa-time-options';

function buildTimeOptions() {
  if (document.getElementById(TIME_OPTIONS_ID)) return;
  var dl = document.createElement('datalist');
  dl.id = TIME_OPTIONS_ID;
  var html = '';
  for (var mins = 0; mins < 24 * 60; mins += 15) {
    var canon = _pad2(Math.floor(mins / 60)) + ':' + _pad2(mins % 60);
    html += '<option value="' + _fmt12(canon) + '"></option>';
  }
  dl.innerHTML = html;
  document.body.appendChild(dl);
}

// A plain typed time field. The user types any time (e.g. "9:07 AM"); it is
// parsed and normalized on blur. The canonical HH:MM value lives on the hidden
// `.time-input` so existing read sites keep working unchanged.
function timeFieldHtml(val, id) {
  val = val || '';
  var idAttr = id ? ' id="' + id + '"' : '';
  var display = val ? _fmt12(val) : '';
  return '<span class="time-combo">' +
    '<input type="text" class="time-combo-input" autocomplete="off" list="' + TIME_OPTIONS_ID + '" placeholder="Enter time" value="' + display + '">' +
    '<input type="hidden" class="time-input"' + idAttr + ' value="' + val + '">' +
    '</span>';
}

// Render a time field into a container span (used for the template-defined
// Single Event / Blocked start & end fields). The hidden input keeps `id` so
// existing `getElementById(id).value` reads keep working.
function initTimeField(wrapId, fieldId) {
  var wrap = document.getElementById(wrapId);
  if (wrap) wrap.innerHTML = timeFieldHtml('', fieldId);
}

// Set a time field's value programmatically, syncing the visible input.
function setTimeField(fieldId, val) {
  var hidden = document.getElementById(fieldId);
  if (!hidden) return;
  var span = hidden.closest('.time-combo');
  val = val || '';
  hidden.value = val;
  if (span) span.querySelector('.time-combo-input').value = val ? _fmt12(val) : '';
}

/* ----- typed-field behavior via event delegation (covers dynamic rows) ----- */

// Keep the hidden canonical value in sync as the user types.
document.addEventListener('input', function (e) {
  var input = e.target.closest && e.target.closest('.time-combo-input');
  if (!input) return;
  input.closest('.time-combo').querySelector('.time-input').value = parseTimeTo24(input.value) || '';
});

// Normalize the typed text to a clean value when the field loses focus.
document.addEventListener('focusout', function (e) {
  var input = e.target.closest && e.target.closest('.time-combo-input');
  if (!input) return;
  var span = input.closest('.time-combo');
  var canon = parseTimeTo24(input.value);
  span.querySelector('.time-input').value = canon || '';
  input.value = canon ? _fmt12(canon) : '';
});

/* ---------- Saved default view ---------- */

// A row is expired once its end date has passed. One definition, used by both
// the filtering below and the Expired badge, so the badge can never disagree
// with what got hidden.
function isExpiredRow(row) {
  return !!(row.effective_end && new Date(row.effective_end + 'T23:59:59') < new Date());
}
// A one-off block is expired once its end time has passed.
function isExpiredBlock(b) {
  return !!(b.end && new Date(b.end) < new Date());
}
// A date override is expired once its day has ended.
function isExpiredOverride(ovr) {
  return !!(ovr.date && new Date(ovr.date + 'T23:59:59') < new Date());
}

// Expired rules, recurring blocks and holds, one-off blocks, and date overrides
// are hidden by default: a provider's list is dominated by finished items otherwise. Not persisted, so a reload
// returns to hiding them.
// Banner offering to review items that ended over 30 days ago, for providers the
// viewer can edit. Review opens a list to pick from; "Ask again in 30 days"
// snoozes the items listed now, so anything that ends later still shows.
var _expiredSummary = { count: 0, items: [] };
var _expiredSel = {};
var _EXPIRED_TYPES = {
  available: ['chip-avail', SVG_CHECK, 'Available'],
  blocked: ['chip-block', SVG_X, 'Blocked'],
  hold: ['chip-hold', SVG_PAUSE, 'Hold'],
  override: ['chip-override', SVG_OVERRIDE, 'Override'],
};

// Safe in element text and in attribute values, including inline handlers:
// the browser decodes the entities back before running the handler.
// A value as a script string inside an onclick attribute. Escaping alone isn't enough
// there: the browser decodes the attribute before running it, so the value is first
// encoded as a JS string, then escaped for the attribute.
function _jsArg(value) {
  return _escHtml(JSON.stringify(value == null ? '' : value));
}

function _escHtml(text) {
  return (text == null ? '' : String(text))
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _expiredProviderName(pid) {
  var p = (_providers || []).find(function(x) { return String(x.id) === String(pid); });
  if (p) return p.name;
  var o = (_overviewData || []).find(function(x) { return String(x.provider_id) === String(pid); });
  return o ? o.provider_name : pid;
}

function renderExpiredBanner() {
  var el = document.getElementById('expired-banner');
  if (!el) return;
  var n = _expiredSummary.count || 0;
  if (!n) { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.innerHTML = '<span class="expired-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></span>' +
    '<span class="expired-text"><b>' + n + (n === 1 ? ' event' : ' events') + ' expired more than 30 days ago.</b> Remove ' + (n === 1 ? 'it' : 'them') + ' from the availability list?' +
    '<span class="expired-note">This only removes ' + (n === 1 ? 'it' : 'them') + ' from this dashboard and does not change anything else in Canvas.</span></span>' +
    '<span class="expired-actions"><button class="btn" onclick="snoozeExpired()">Ask again in 30 days</button>' +
    '<button class="btn btn-primary" onclick="openExpiredPanel()">Review</button></span>';
  el.style.display = '';
}

async function loadExpiredBanner() {
  var data = await apiCall('/expired-summary');
  if (data && typeof data.count === 'number') { _expiredSummary = data; renderExpiredBanner(); }
}

function openExpiredPanel() {
  _expiredSel = {};
  renderExpiredPanel();
  document.getElementById('expired-panel').classList.add('open');
}

function closeExpiredPanel() {
  document.getElementById('expired-panel').classList.remove('open');
}

function renderExpiredPanel() {
  var items = _expiredSummary.items || [];
  var last = null;
  document.getElementById('ep-rows').innerHTML = items.map(function(it, i) {
    var t = _EXPIRED_TYPES[it.kind] || _EXPIRED_TYPES.blocked;
    var next = last !== null && it.provider_id !== last;
    last = it.provider_id;
    return '<tr data-i="' + i + '" class="' + (_expiredSel[it.key] ? 'ep-sel ' : '') + (next ? 'ep-next-provider' : '') + '">' +
      '<td><input type="checkbox"' + (_expiredSel[it.key] ? ' checked' : '') + '></td>' +
      '<td>' + _escHtml(_expiredProviderName(it.provider_id)) + '</td>' +
      '<td><span class="type-chip ' + t[0] + '">' + t[1] + '</span>' + t[2] + '</td>' +
      '<td>' + _escHtml(it.when) + '</td>' +
      '<td><div class="ep-reason" title="' + _escHtml(it.reason) + '">' + (it.reason ? _escHtml(it.reason) : '<span class="col-empty">—</span>') + '</div></td>' +
      '<td>' + fmtDate(it.ended) + '</td></tr>';
  }).join('');
  document.querySelectorAll('#ep-rows tr').forEach(function(tr) {
    tr.addEventListener('click', function() {
      var key = items[+tr.dataset.i].key;
      _expiredSel[key] = !_expiredSel[key];
      renderExpiredPanel();
    });
  });
  var picked = items.filter(function(it) { return _expiredSel[it.key]; }).length;
  document.getElementById('ep-count').textContent = picked ? picked + ' of ' + items.length + ' selected' : items.length + (items.length === 1 ? ' item' : ' items');
  var all = document.getElementById('ep-all');
  all.checked = picked > 0 && picked === items.length;
  all.indeterminate = picked > 0 && picked < items.length;
  var rm = document.getElementById('ep-remove');
  rm.disabled = !picked;
  rm.textContent = picked ? 'Remove ' + picked + ' selected' : 'Remove selected';
  var sn = document.getElementById('ep-snooze');
  sn.disabled = !picked;
  sn.textContent = picked ? 'Ask again in 30 days (' + picked + ')' : 'Ask again in 30 days';
}

function toggleExpiredAll() {
  var items = _expiredSummary.items || [];
  var on = !items.every(function(it) { return _expiredSel[it.key]; });
  items.forEach(function(it) { _expiredSel[it.key] = on; });
  renderExpiredPanel();
}

async function removeExpired() {
  var keys = (_expiredSummary.items || []).filter(function(it) { return _expiredSel[it.key]; }).map(function(it) { return it.key; });
  if (!keys.length) return;
  if (!confirm('Remove ' + keys.length + (keys.length === 1 ? ' item' : ' items') + ' from this list? Their past calendar entries stay in Canvas.')) return;
  var data = await apiCall('/expired/remove', { method: 'POST', body: JSON.stringify({ keys: keys }) });
  if (data.error) { showMsg(data.error, 'error'); return; }
  showMsg(data.message || 'Removed', 'success');
  var gone = {}; keys.forEach(function(k) { gone[k] = true; });
  _expiredSummary.items = (_expiredSummary.items || []).filter(function(it) { return !gone[it.key]; });
  _expiredSummary.count = _expiredSummary.items.length;
  _expiredSel = {};
  if (_expiredSummary.count) renderExpiredPanel(); else closeExpiredPanel();
  renderExpiredBanner();
  await loadOverview();
}

// From the banner, snoozes everything it counts. From the review panel,
// snoozes only the items ticked there; the rest stay listed.
async function snoozeExpired(selectedOnly) {
  var items = _expiredSummary.items || [];
  if (selectedOnly) items = items.filter(function(it) { return _expiredSel[it.key]; });
  var keys = items.map(function(it) { return it.key; });
  if (!keys.length) return;
  var data = await apiCall('/expired/snooze', { method: 'POST', body: JSON.stringify({ keys: keys }) });
  if (data.error) { showMsg(data.error, 'error'); return; }
  var gone = {}; keys.forEach(function(k) { gone[k] = true; });
  _expiredSummary.items = (_expiredSummary.items || []).filter(function(it) { return !gone[it.key]; });
  _expiredSummary.count = _expiredSummary.items.length;
  _expiredSel = {};
  if (_expiredSummary.count && selectedOnly) renderExpiredPanel(); else closeExpiredPanel();
  renderExpiredBanner();
  if (data.until) showMsg('Hidden until ' + fmtDate(data.until) + '. Anything else that ends meanwhile still brings the banner back.', 'success');
}

// Escape closes the review panel.
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') { var p = document.getElementById('expired-panel'); if (p && p.classList.contains('open')) closeExpiredPanel(); }
});

function toggleExpired() {
  _showExpired = !_showExpired;
  var btn = document.getElementById('toggle-expired');
  if (btn) btn.textContent = _showExpired ? 'Hide expired' : 'Show expired';
  renderAccordion();
}


// The provider filter and saved views cover other providers only. The viewer's
// own row always shows in its own section, so offering them in the filter
// would be a choice that does nothing.
function filterItems(providers, items) {
  var viewer = {};
  providers.forEach(function(p) { if (p.is_you) viewer[String(p.id)] = true; });
  return items.filter(function(it) { return !viewer[String(it.id)]; });
}


// Store whichever providers are selected in the filter as this user's default
// view. Saved per staff member on the server, so two people managing different
// providers do not overwrite each other. An empty selection clears the saved
// view, which means "show everyone" rather than "show nobody".
async function saveMyView() {
  var ids = msFilterProvider ? msFilterProvider.getValue() : [];
  if (msFilterProvider && msFilterProvider.isAll()) ids = [];
  var data = await apiCall('/my-view', { method: 'PUT', body: JSON.stringify({ provider_ids: ids }) });
  if (data && data.error) { showMsg(data.error, 'error'); return; }
  _savedView = ids.map(String);
  renderAccordion();
  if (ids.length) {
    showMsg('Saved ' + ids.length + ' provider' + (ids.length === 1 ? '' : 's') + ' as my default view', 'success');
  } else {
    showMsg('Default view cleared. You will see every provider.', 'success');
  }
}

// Clear the filter so every provider shows. Deliberately not persisted: the
// next page load returns to the saved view.
/* ---------- Daily mode flat time-windows editor ---------- */

function addDailyTimeWindow(containerId, startVal, endVal) {
  var container = document.getElementById(containerId);
  if (!container) return;
  var row = document.createElement('div');
  row.className = 'day-time-inputs';
  row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;';
  row.innerHTML =
    timeFieldHtml(startVal) +
    '<span class="time-sep">\u2013</span>' +
    timeFieldHtml(endVal);
  var rmv = document.createElement('button');
  rmv.type = 'button';
  rmv.className = 'remove-time';
  rmv.innerHTML = SVG_X_SM;
  rmv.onclick = function() { row.remove(); };
  row.appendChild(rmv);
  container.appendChild(row);
}

function _readDailyTimeWindows(containerId) {
  var out = [];
  var container = document.getElementById(containerId);
  if (!container) return out;
  var rows = container.querySelectorAll('.day-time-inputs');
  rows.forEach(function(r) {
    var inputs = r.querySelectorAll('.time-input');
    if (inputs.length >= 2 && inputs[0].value && inputs[1].value) {
      out.push({ start: inputs[0].value, end: inputs[1].value });
    }
  });
  return out;
}

function _clearDailyTimeWindows(containerId) {
  var container = document.getElementById(containerId);
  if (container) container.innerHTML = '';
}

/* ---------- Block all-day + multi-date chips ---------- */

// Blocks queued with "+ Add to list": [{date, allDay, start, end}], each with its own times.
var _blockEntries = [];
// When set, the form is editing a multi-date block group (one provider, many
// dates) — saving will replace the entire group instead of updating one block.
var _editingBlockGroup = null;

// Hold type toggle: Same-day or Next-day, kept in a hidden input the save reads.
function setHoldType(value) {
  var v = value === 'next_day' ? 'next_day' : 'same_day';
  document.getElementById('hold_type_select').value = v;
  ['same_day', 'next_day'].forEach(function(k) {
    var b = document.getElementById('hold-type-' + k);
    if (b) { b.classList.toggle('active', k === v); b.setAttribute('aria-pressed', k === v ? 'true' : 'false'); }
  });
  var hint = document.getElementById('hold-type-hint');
  if (hint) hint.textContent = v === 'next_day' ? 'Availability blocked until the day before.' : 'Availability blocked until the day of.';
}

function onBlockAllDayToggle(checked) {
  // The time boxes keep their place (grayed out) so the row does not jump around.
  ['block_start_time', 'block_end_time'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.disabled = checked;
  });
  ['block-start-time-field', 'block-end-time-field'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.classList.toggle('is-off', checked);
  });
}

function _blockTzShort(isoDate) {
  var pids = msBlockProvider ? msBlockProvider.getValue() : [];
  var tz = pids.length === 1 ? providerTz(pids[0]) : _practiceTz;
  try {
    var parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' }).formatToParts(new Date(isoDate + 'T12:00:00Z'));
    var zone = parts.find(function(x) { return x.type === 'timeZoneName'; });
    return zone ? zone.value : '';
  } catch (e) { return ''; }
}

function _blockEntryKey(e) { return e.date + '|' + (e.allDay ? 'all' : e.start + '-' + e.end); }

function _renderBlockEntries() {
  var box = document.getElementById('block-entries');
  if (!box) return;
  _blockEntries.sort(function(a, b) { return _blockEntryKey(a) < _blockEntryKey(b) ? -1 : 1; });
  box.style.display = _blockEntries.length ? '' : 'none';
  // What each block is: the facility for a facility block, otherwise the reason.
  var what = _blockWhat === 'facility'
    ? facilityName((fpBlockFacility && fpBlockFacility.getValue()[0]) || '') || (_editingBlockFacility ? _editingBlockFacility.name : '')
    : document.getElementById('block_reason').value;
  box.innerHTML = '<div class="block-entries-h">Blocks to save (' + _blockEntries.length + ')</div>' +
    _blockEntries.map(function(e, i) {
      var when = e.allDay ? 'All day' : fmtHHMM(e.start) + ' \u2013 ' + fmtHHMM(e.end) + ' ' + _blockTzShort(e.date);
      var day = new Date(e.date + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
      return '<div class="block-entry"><span class="be-date">' + day + '</span><span class="be-when">' + when + '</span>' +
        '<span class="be-what">' + _escHtml(what) + '</span>' +
        '<button type="button" class="lnk-sm danger be-x" aria-label="Remove ' + day + '" data-i="' + i + '">Remove</button></div>';
    }).join('');
  box.querySelectorAll('.be-x').forEach(function(x) {
    x.onclick = function() { _blockEntries.splice(+x.dataset.i, 1); _renderBlockEntries(); };
  });
}

// The date and times typed in the row above, or an error message.
function _readBlockEntryInputs() {
  var date = document.getElementById('block_date').value;
  var allDayEl = document.getElementById('block_all_day');
  var allDay = !!(allDayEl && allDayEl.checked);
  var start = document.getElementById('block_start_time').value;
  var end = document.getElementById('block_end_time').value;
  if (!date) return { error: 'Select a date first' };
  if (!allDay && (!start || !end)) return { error: 'Start and end time are required (or check All day)' };
  if (!allDay && start >= end) return { error: 'Start time must be before end time' };
  return { date: date, allDay: allDay, start: allDay ? '' : start, end: allDay ? '' : end };
}

function addBlockEntry() {
  var e = _readBlockEntryInputs();
  if (e.error) { showMsg(e.error, 'error'); return; }
  if (!_blockEntries.some(function(x) { return _blockEntryKey(x) === _blockEntryKey(e); })) _blockEntries.push(e);
  _renderBlockEntries();
  // Clear the date so the next pick starts fresh; the times stay for the next date.
  document.getElementById('block_date').value = '';
  syncDateFacade('block_date');
}

function _resetBlockEntries() {
  _blockEntries = [];
  _renderBlockEntries();
}

// One request saves every date, with its own times, for every provider listed, so
// either all of it saves or none does. replace: { blocks: [{provider_id, id}],
// recurringBlockId } for saved blocks this save replaces; the server removes them
// only once its checks pass.
async function _postBlockEntries(providerIds, entries, reason, locationIds, groupId, facilityId, replace) {
  replace = replace || {};
  const body = {
    provider_id: providerIds[0], provider_ids: providerIds.slice(),
    reason: reason, location_ids: locationIds, group_id: groupId, facility_id: facilityId || '',
    replace_blocks: (replace.blocks || []).slice(),
    entries: entries.map(function(e) {
      return { date: e.date, all_day: !!e.allDay, start: e.allDay ? '' : e.start + ':00', end: e.allDay ? '' : e.end + ':00' };
    }),
  };
  if (replace.recurringBlockId) body.replace_recurring_block_id = replace.recurringBlockId;
  const data = await apiCall('/blocks', { method: 'POST', body: JSON.stringify(body) });
  if (data.error) return { error: data.error, status: data._status, created: 0 };
  return { created: data.blocks ? data.blocks.length : entries.length * providerIds.length };
}

function getInitials(name) {
  if (!name) return '??';
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function summarizeDays(schedule) {
  const active = DAYS.filter(d => (schedule[d] || []).length > 0);
  if (active.length === 0) return 'None';
  const abbrs = active.map(d => DAY_ABBR[d]);
  if (active.length === 5 && active[0] === 'monday' && active[4] === 'friday') return 'Mon\u2013Fri';
  if (active.length === 7) return 'Every day';
  return abbrs.join(', ');
}

function summarizeWindows(schedule) {
  const active = DAYS.filter(d => (schedule[d] || []).length > 0);
  if (active.length === 0) return '';
  const fmtWins = ws => ws.map(w => fmtHHMM(w.start) + ' \u2013 ' + fmtHHMM(w.end)).join(', ');
  const firstKey = JSON.stringify(schedule[active[0]]);
  const allSame = active.every(d => JSON.stringify(schedule[d]) === firstKey);
  if (allSame) {
    return fmtWins(schedule[active[0]]);
  }
  return active.map(d => '<b>' + DAY_ABBR[d] + '</b> ' + fmtWins(schedule[d])).join('<br>');
}

function dailyDayLabel(r) {
  var iv = (r && r.recurrence_interval) || 1;
  return iv === 1 ? 'Daily' : 'Every ' + iv + ' days';
}

function frequencyLabel(r) {
  // Human label for the detail panel — always present, regardless of interval.
  var iv = (r && r.recurrence_interval) || 1;
  var fq = (r && r.recurrence_frequency) || 'weekly';
  if (fq === 'daily') return iv === 1 ? 'Daily' : 'Every ' + iv + ' days';
  if (iv === 1) return 'Weekly';
  if (iv === 2) return 'Bi-weekly';
  return 'Every ' + iv + ' weeks';
}

function formatDayRange(dayNames) {
  // Given an array of DAYS entries (e.g. ['monday','tuesday','wednesday']),
  // produce a compact label: consecutive runs as ranges, others as comma-sep.
  if (dayNames.length === 0) return '';
  if (dayNames.length === 7) return 'Every day';
  const indices = dayNames.map(d => DAYS.indexOf(d)).sort((a, b) => a - b);
  const runs = [];
  let start = indices[0], end = indices[0];
  for (let i = 1; i < indices.length; i++) {
    if (indices[i] === end + 1) { end = indices[i]; }
    else { runs.push([start, end]); start = indices[i]; end = indices[i]; }
  }
  runs.push([start, end]);
  return runs.map(([s, e]) => {
    if (s === e) return DAY_ABBR[DAYS[s]];
    if (e - s === 1) return DAY_ABBR[DAYS[s]] + ', ' + DAY_ABBR[DAYS[e]];
    return DAY_ABBR[DAYS[s]] + ' \u2013 ' + DAY_ABBR[DAYS[e]];
  }).join(', ');
}

function groupDaysByWindows(schedule) {
  // Group active days by identical time windows. Returns array of {days:[], windows:[]}.
  const active = DAYS.filter(d => (schedule[d] || []).length > 0);
  const groups = [];
  const seen = new Map();
  active.forEach(d => {
    const key = JSON.stringify(schedule[d]);
    if (seen.has(key)) { seen.get(key).days.push(d); }
    else { const g = { days: [d], windows: schedule[d] }; seen.set(key, g); groups.push(g); }
  });
  return groups;
}

function detailTagClass(type) {
  if (type === 'available') return 'tag-avail';
  if (type === 'blocked') return 'tag-block';
  return 'tag-neutral';
}

function toggleDetailPopover(el) {
  const existing = el.querySelector('.detail-popover');
  if (existing) { existing.remove(); return; }
  // Close any other open popovers
  document.querySelectorAll('.detail-popover').forEach(p => p.remove());
  const pop = document.createElement('div');
  pop.className = 'detail-popover';
  pop.textContent = el.getAttribute('title');
  el.appendChild(pop);
}

document.addEventListener('click', function(e) {
  if (!e.target.closest('.detail-tag[title]')) {
    document.querySelectorAll('.detail-popover').forEach(p => p.remove());
  }
});

/* ---------- MultiSelect component ---------- */

class MultiSelect {
  constructor(containerId, options) {
    this.container = document.getElementById(containerId);
    this.placeholder = options.placeholder || 'Search...';
    this.displayKey = options.displayKey || 'name';
    this.valueKey = options.valueKey || 'id';
    this.extraDisplayKey = options.extraDisplayKey || null;
    // Gray text after a name: hintKey in the list, chipHintKey on the picked chip.
    this.hintKey = options.hintKey || null;
    this.chipHintKey = options.chipHintKey || null;
    // summaryNoun: once more than 3 items are picked, the field shows one summary
    // chip ("All providers", "12 of 15 providers") instead of a chip per item.
    // startAll: with nothing picked yet, every item starts checked.
    this.summaryNoun = options.summaryNoun || null;
    this.startAll = !!options.startAll;
    this.items = [];
    this.selected = [];
    this.filterText = '';
    this.isOpen = false;
    this.render();
  }

  render() {
    this.container.innerHTML = '';
    this.control = document.createElement('div');
    this.control.className = 'ms-control';
    this.control.addEventListener('click', () => this.input.focus());

    this.chipsArea = document.createElement('span');
    this.chipsArea.className = 'ms-chips';
    this.control.appendChild(this.chipsArea);

    this.input = document.createElement('input');
    this.input.type = 'text';
    this.input.className = 'ms-input';
    this.input.placeholder = this.placeholder;
    this.input.addEventListener('input', () => { this.filterText = this.input.value; this.renderDropdown(); });
    this.input.addEventListener('focus', () => this.open());
    this.control.appendChild(this.input);

    this.container.appendChild(this.control);

    this.dropdown = document.createElement('div');
    this.dropdown.className = 'ms-dropdown';
    this.container.appendChild(this.dropdown);

    document.addEventListener('click', (e) => {
      if (!this.container.contains(e.target)) this.close();
    });
  }

  setItems(items) {
    const wasAll = this.items.length > 0 && this.isAll();
    this.items = items;
    if (this.startAll && (wasAll || this.selected.length === 0)) {
      this.selected = items.map(i => String(i[this.valueKey]));
      this.updateChips();
    }
    this.renderDropdown();
  }

  // True when every item is picked.
  isAll() {
    return this.items.length > 0 && this.items.every(i => this.selected.includes(String(i[this.valueKey])));
  }

  open() { this.isOpen = true; this.dropdown.classList.add('open'); this.renderDropdown(); }
  close() { this.isOpen = false; this.dropdown.classList.remove('open'); this.filterText = ''; this.input.value = ''; }

  renderDropdown() {
    if (!this.isOpen) return;
    const filter = this.filterText.toLowerCase();
    const filtered = this.items.filter(item => {
      const label = String(item[this.displayKey] || '').toLowerCase();
      const extra = this.extraDisplayKey ? String(item[this.extraDisplayKey] || '').toLowerCase() : '';
      const hint = this.hintKey ? String(item[this.hintKey] || '').toLowerCase() : '';
      return label.includes(filter) || extra.includes(filter) || hint.includes(filter);
    });
    this.dropdown.innerHTML = '';
    if (filtered.length === 0) { this.dropdown.innerHTML = '<div class="ms-empty">No matches</div>'; return; }

    // Select All option. While searching it reads "Select all matches (N)" and
    // checks or unchecks only the names showing, so a search plus one click picks a group.
    // When everyone is already checked (a filter that starts with all), that click
    // narrows the selection to just the matches instead of unchecking them.
    if (filtered.length > 1 || filter) {
      const allVals = filtered.map(i => String(i[this.valueKey]));
      const narrowing = !!filter && filtered.length < this.items.length && this.isAll();
      const allSelected = !narrowing && allVals.every(v => this.selected.includes(v));
      const selAll = document.createElement('div');
      selAll.className = 'ms-option' + (allSelected ? ' selected' : '');
      selAll.style.fontWeight = '600';
      selAll.style.borderBottom = '1px solid var(--border)';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = allSelected;
      selAll.appendChild(cb);
      const span = document.createElement('span');
      span.textContent = filter ? 'Select all matches (' + filtered.length + ')' : 'Select All';
      selAll.appendChild(span);
      selAll.addEventListener('click', (e) => {
        e.stopPropagation();
        if (narrowing) { this.selected = allVals.slice(); }
        else if (allSelected) { allVals.forEach(v => { const idx = this.selected.indexOf(v); if (idx >= 0) this.selected.splice(idx, 1); }); }
        else { allVals.forEach(v => { if (!this.selected.includes(v)) this.selected.push(v); }); }
        this.updateChips();
        this.renderDropdown();
      });
      this.dropdown.appendChild(selAll);
    }

    filtered.forEach(item => {
      const val = String(item[this.valueKey]);
      const isSelected = this.selected.includes(val);
      const opt = document.createElement('div');
      opt.className = 'ms-option' + (isSelected ? ' selected' : '');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = isSelected;
      opt.appendChild(cb);
      const span = document.createElement('span');
      span.textContent = item[this.displayKey] || val;
      opt.appendChild(span);
      const hintText = (this.hintKey && item[this.hintKey]) || (this.extraDisplayKey && item[this.extraDisplayKey]);
      if (hintText) {
        const hint = document.createElement('span');
        hint.className = 'ms-hint';
        hint.textContent = hintText;
        opt.appendChild(hint);
      }
      opt.addEventListener('click', (e) => { e.stopPropagation(); this.toggle(val); });
      this.dropdown.appendChild(opt);
    });
  }

  toggle(value) {
    const idx = this.selected.indexOf(value);
    if (idx >= 0) this.selected.splice(idx, 1);
    else this.selected.push(value);
    this.updateChips();
    this.renderDropdown();
  }

  updateChips() {
    this.chipsArea.innerHTML = '';
    if (this.summaryNoun && this.selected.length > 3) {
      const chip = document.createElement('span');
      chip.className = 'ms-chip';
      chip.textContent = this.isAll()
        ? 'All ' + this.summaryNoun
        : this.selected.length + ' of ' + this.items.length + ' ' + this.summaryNoun;
      this.chipsArea.appendChild(chip);
      this.input.placeholder = '';
      return;
    }
    this.selected.forEach(val => {
      const item = this.items.find(i => String(i[this.valueKey]) === val);
      const label = item ? (item[this.displayKey] || val) : val;
      const chip = document.createElement('span');
      chip.className = 'ms-chip';
      const chipHint = item && this.chipHintKey && item[this.chipHintKey] ? ' <span class="ms-chip-hint">' + _escHtml(item[this.chipHintKey]) + '</span>' : '';
      chip.innerHTML = _escHtml(label) + chipHint + ' <span class="ms-chip-remove">&times;</span>';
      chip.querySelector('.ms-chip-remove').addEventListener('click', (e) => { e.stopPropagation(); this.toggle(val); });
      this.chipsArea.appendChild(chip);
    });
    this.input.placeholder = this.selected.length > 0 ? '' : this.placeholder;
  }

  getValue() { return this.selected.slice(); }
  setValue(values) { this.selected = (values || []).map(String); this.updateChips(); }
  clear() { this.selected = []; this.updateChips(); }
}

let msProvider, msLocation, msVisitType, msBlockProvider, msBlockLocation, msFilterProvider, msHoldProvider, msHoldLocation, msSchedulableRoles;

/* ---------- Tab management ---------- */

let _formDirty = false;
let _settingsDirty = false;
let _skipDirtyCheck = false;

// The browser shows its own "Reload site?" box; pages cannot change its text
// or buttons.
window.addEventListener('beforeunload', function(e) {
  if (_formDirty || _settingsDirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});

// Changes made by clicking rather than typing: picker options and chips,
// adding or removing time windows, block date chips, overrides, and the rule
// type cards. Listened for in the capture phase because several of these
// controls stop the click from bubbling.
var _DIRTY_CLICK_SELECTOR = '.ms-option, .ms-chip-remove, .remove-time, .date-chip-remove, .type-card, ' +
  '[onclick^="add"], [onclick^="saveOverride"], [onclick^="deleteOverride"]';
document.addEventListener('click', function(e) {
  if (!e.isTrusted) return;
  var hit = e.target && e.target.closest ? e.target.closest(_DIRTY_CLICK_SELECTOR) : null;
  if (!hit) return;
  var editor = document.getElementById('panel-editor');
  if (editor && editor.contains(hit)) _formDirty = true;
  var roles = document.getElementById('ms-schedulable-roles');
  if (roles && roles.contains(hit)) _settingsDirty = true;
}, true);

// While the page itself fills the editor (opening it blank, or loading a rule,
// block or hold), the controls it sets announce changes that are not the
// user's. Every editor loader fills the form in the same task that switches
// tabs, so ignoring changes until that task ends covers them all. Origin
// cannot be judged from the event: the page's checkbox and dropdown controls
// re-send even a user's change as a page-generated event.
var _pageIsFilling = false;
function _fillingForm() {
  _pageIsFilling = true;
  setTimeout(function() { _pageIsFilling = false; }, 0);
}

// Dropdowns, checkboxes and date pickers report "change" rather than "input".
document.addEventListener('change', function(e) {
  if (_pageIsFilling) return;
  var editor = document.getElementById('panel-editor');
  if (editor && editor.contains(e.target)) _formDirty = true;
});

// Remember the open tab for this browser tab, so a refresh reopens it. The
// address hash alone is lost, because Canvas rebuilds the app's frame from
// its launch address on a refresh.
var _LAST_TAB_KEY = 'provider_availability:last-tab';
function _rememberTab(name) {
  _activeTab = name;
  syncHeaderTabs(name);
  try { history.replaceState(null, '', '#' + name); } catch (e) {}
  try { sessionStorage.setItem(_LAST_TAB_KEY, name); } catch (e) {}
}

var _tabIndexMap = { 'availability': 0, 'editor': 1, 'settings': 2 };
var _tabPanelMap = { 'panel-availability': 'availability', 'panel-editor': 'editor', 'panel-settings': 'settings' };

// Which tab is showing, kept by _rememberTab.
var _activeTab = 'availability';

// Ask before leaving a tab that has unsaved changes. Returns false to stay.
function _confirmLeave(toName) {
  if (_skipDirtyCheck || toName === _activeTab) return true;
  var unsaved = (_activeTab === 'editor' && _formDirty) || (_activeTab === 'settings' && _settingsDirty);
  if (!unsaved) return true;
  if (!confirm('You have unsaved changes. Leave without saving?')) return false;
  if (_activeTab === 'settings') _settingsDirty = false;
  return true;
}

function showTab(name) {
  if (!_confirmLeave(name)) return;
  _fillingForm();
  _formDirty = false;

  showTab._inProgress = true;
  // Let canvas-tabs handle panel visibility (this dispatches tab-change synchronously)
  var tabsEl = document.getElementById('main-tabs');
  var idx = _tabIndexMap[name] || 0;
  if (tabsEl && tabsEl._activate) {
    tabsEl._activate(idx);
  }
  showTab._inProgress = false;

  // Side effects: if the tab-change listener already ran them (set _fromEvent),
  // skip our own block and just clear the flag. Otherwise run them now.
  if (!showTab._fromEvent) {
    if (name === 'editor') {
      if (!_skipDirtyCheck) resetForm();
    } else if (name === 'settings') {
      renderSettingsPanel();
      bulkReset();
      if (window.paSettings) window.paSettings.open();
    } else {
      if (!_skipDirtyCheck) loadOverview();
    }
    _skipDirtyCheck = false;
  } else {
    showTab._fromEvent = false;
  }
  _rememberTab(name);
}
showTab._fromEvent = false;

function showMsg(msg, type) {
  const dismissBtn = '<button class="alert-dismiss" onclick="dismissMsg()">&times;</button>';
  // Messages carry server and form-path text, so they are always shown as text.
  const alertHtml = '<div class="alert alert-' + type + '"><span>' + _escHtml(msg) + '</span>' + dismissBtn + '</div>';
  const elTop = document.getElementById('status-msg');
  const elBot = document.getElementById('status-msg-bottom');
  if (elTop) elTop.innerHTML = alertHtml;
  if (elBot) elBot.innerHTML = alertHtml;
  const timeout = type === 'error' ? 10000 : 4000;
  clearTimeout(showMsg._timer);
  showMsg._timer = setTimeout(dismissMsg, timeout);
}
showMsg._timer = null;
function dismissMsg() {
  clearTimeout(showMsg._timer);
  const elTop = document.getElementById('status-msg');
  const elBot = document.getElementById('status-msg-bottom');
  if (elTop) elTop.innerHTML = '';
  if (elBot) elBot.innerHTML = '';
}

/* ---------- Bulk CSV Import ---------- */
const CSV_BASE = '/plugin-io/api/provider_availability/csv';
var _bulkFile = null;
var _bulkRecords = null;

function _bulkShowFileName() {
  var label = document.getElementById('bulk-file-name');
  if (label) label.textContent = _bulkFile ? _bulkFile.name : 'No file chosen';
}

function bulkFileSelect(event) {
  _bulkFile = (event.target.files && event.target.files[0]) || null;
  _bulkShowFileName();
  var btn = document.getElementById('bulk-validate-btn');
  if (btn) btn.disabled = !_bulkFile;
  var err = document.getElementById('bulk-upload-error');
  if (err) err.style.display = 'none';
}

function bulkShowStep(step) {
  ['upload', 'preview', 'results'].forEach(function(s) {
    var el = document.getElementById('bulk-step-' + s);
    if (el) el.style.display = (s === step) ? 'block' : 'none';
  });
}

function bulkReset() {
  _bulkFile = null;
  _bulkRecords = null;
  var input = document.getElementById('bulk-file');
  if (input) input.value = '';
  _bulkShowFileName();
  var btn = document.getElementById('bulk-validate-btn');
  if (btn) btn.disabled = true;
  var err = document.getElementById('bulk-upload-error');
  if (err) err.style.display = 'none';
  bulkShowStep('upload');
}

function bulkDownloadTemplate() {
  var csv = (window.__PRELOADED__ && window.__PRELOADED__.csv_template) || '';
  if (!csv) { showMsg('Template unavailable', 'error'); return; }
  var blob = new Blob([csv], { type: 'text/csv' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = 'availability_template.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function bulkShowError(msg) {
  var el = document.getElementById('bulk-upload-error');
  if (el) { el.textContent = msg; el.style.display = 'block'; }
}

async function bulkUploadValidate() {
  if (!_bulkFile) return;
  var btn = document.getElementById('bulk-validate-btn');
  if (btn) btn.disabled = true;
  try {
    var fd = new FormData();
    fd.append('file', _bulkFile);
    var resp = await fetch(CSV_BASE + '/validate', { method: 'POST', body: fd, credentials: 'same-origin' });
    if (!resp.ok) {
      var e = await resp.json().catch(function() { return { error: 'Upload failed' }; });
      bulkShowError(e.error || 'Upload failed');
      if (btn) btn.disabled = false;
      return;
    }
    var result = await resp.json();
    _bulkRecords = result.records || [];
    bulkRenderPreview(result);
    bulkShowStep('preview');
  } catch (err) {
    bulkShowError('Upload failed: ' + err.message);
    if (btn) btn.disabled = false;
  }
}

function _bulkStat(num, label, color) {
  return '<div style="text-align:center;"><div style="font-size:26px;font-weight:700;color:' + color +
    ';">' + num + '</div><div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;">' +
    label + '</div></div>';
}

function bulkRenderPreview(result) {
  var summary = document.getElementById('bulk-summary');
  if (summary) {
    summary.innerHTML =
      _bulkStat(result.total_rows, 'Rows', 'var(--text)') +
      _bulkStat(result.record_count, 'Records', '#2e7d32') +
      // Rounds are rules too; they are counted on their own when the file has any.
      _bulkStat((result.rule_count || 0) - (result.round_count || 0), 'Rules', 'var(--text)') +
      (result.round_count ? _bulkStat(result.round_count, 'Rounds', 'var(--text)') : '') +
      _bulkStat(result.block_count, 'Blocks', 'var(--text)') +
      _bulkStat(result.rblock_count, 'Recurring', 'var(--text)') +
      _bulkStat(result.error_count, 'Errors', '#c62828');
  }
  var errSec = document.getElementById('bulk-error-section');
  var body = document.getElementById('bulk-error-body');
  if (body) body.innerHTML = '';
  if (body && result.errors && result.errors.length > 0) {
    if (errSec) errSec.style.display = 'block';
    result.errors.forEach(function(row) {
      var tr = document.createElement('tr');
      var td1 = document.createElement('td');
      td1.style.padding = '8px 12px';
      td1.style.borderBottom = '1px solid var(--border)';
      td1.textContent = row.row_number;
      var td2 = document.createElement('td');
      td2.style.padding = '8px 12px';
      td2.style.borderBottom = '1px solid var(--border)';
      td2.style.color = '#c62828';
      td2.textContent = (row.errors || []).join('; ');
      tr.appendChild(td1);
      tr.appendChild(td2);
      body.appendChild(tr);
    });
  } else if (errSec) {
    errSec.style.display = 'none';
  }
  var commitBtn = document.getElementById('bulk-commit-btn');
  if (commitBtn) commitBtn.disabled = result.record_count === 0;
}

async function bulkConfirmCommit() {
  if (!_bulkRecords || _bulkRecords.length === 0) return;
  var btn = document.getElementById('bulk-commit-btn');
  if (btn) btn.disabled = true;
  try {
    var resp = await fetch(CSV_BASE + '/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ records: _bulkRecords }),
      credentials: 'same-origin',
    });
    if (!resp.ok) {
      var e = await resp.json().catch(function() { return { error: 'Load failed' }; });
      showMsg(e.error || 'Load failed', 'error');
      if (btn) btn.disabled = false;
      return;
    }
    var result = await resp.json();
    var rules = result.created_rules || 0;
    var blocks = result.created_blocks || 0;
    var rblocks = result.created_recurring_blocks || 0;
    var total = rules + blocks + rblocks;
    var msg = document.getElementById('bulk-results-msg');
    if (msg) {
      msg.textContent = total + ' record(s) loaded: ' + rules + ' rule(s), ' + blocks +
        ' block(s), ' + rblocks + ' recurring block(s). Calendar events are syncing.';
    }
    bulkShowStep('results');
    showMsg('Imported ' + total + ' record(s)', 'success');
  } catch (err) {
    showMsg('Load failed: ' + err.message, 'error');
    if (btn) btn.disabled = false;
  }
}


async function apiCall(path, opts = {}) {
  try {
    const resp = await fetch(API_BASE + path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...opts.headers },
      ...opts,
    });
    if (!resp.ok) {
      const text = await resp.text();
      console.error('API error', resp.status, path, text);
      if (text && text.toLowerCase().includes('credentials are invalid')) {
        return { error: 'Your session has expired. Please log back in to Canvas in a new tab, then return here to continue. Your unsaved changes are still on screen.' };
      }
      // The status rides along on error bodies, so callers can tell a refusal (403) from other errors.
      try { var body = JSON.parse(text); if (body && typeof body === 'object') body._status = resp.status; return body; }
      catch (e) { return { error: text || ('HTTP ' + resp.status), _status: resp.status }; }
    }
    return resp.json();
  } catch (fetchErr) {
    // fetch() blocked by Canvas sandbox CSP — fall back to hidden-iframe form submission
    return _formApiCall(path, opts);
  }
}

function _formApiCall(path, opts) {
  // For writes (POST/PUT/DELETE): submit a hidden form that redirects back.
  // The server's form-action endpoint processes the write and redirects to the admin page
  // with fresh pre-rendered data.
  var method = (opts.method || 'GET').toUpperCase();
  if (method === 'GET') {
    // Can't do GET data fetches via form fallback; return empty to trigger preloaded path
    return Promise.resolve({});
  }

  var form = document.createElement('form');
  form.method = 'POST';
  form.action = API_BASE + '/form-action';
  form.style.display = 'none';

  function addField(name, value) {
    var input = document.createElement('input');
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }

  addField('_method', method);
  addField('_path', path);
  if (opts.body) addField('_body', opts.body);

  // The reload that follows is the save itself, not leaving with unsaved
  // work, and it should land where a normal save would: Settings for Settings
  // saves, Availability for everything else.
  _formDirty = false;
  _settingsDirty = false;
  var p = String(path).replace(/^\//, '');
  var landing = /^(roles|timezone|provider-timezone)/.test(p) ? 'settings' : 'availability';
  try { sessionStorage.setItem(_LAST_TAB_KEY, landing); } catch (e) {}

  document.body.appendChild(form);
  form.submit();

  // The form submission triggers a full page redirect; this promise never resolves
  // (the page navigates away)
  return new Promise(function() {});
}

/* ---------- Confirmation dialog (canvas-modal) ---------- */

var _confirmCallback = null;

function showConfirm(message, onConfirm) {
  _confirmCallback = onConfirm;
  var msgEl = document.getElementById('confirm-message');
  if (msgEl) msgEl.textContent = message;
  var modal = document.getElementById('confirm-modal');
  if (modal && modal.open) {
    modal.open();
  } else {
    // Fallback: use native confirm if modal not ready
    if (confirm(message)) { onConfirm(); }
  }
}

function _dismissConfirmModal() {
  var modal = document.getElementById('confirm-modal');
  if (modal && modal.dismiss) modal.dismiss();
  _confirmCallback = null;
}

// Wire up modal buttons — use a small delay to ensure custom elements are registered
setTimeout(function() {
  var cancelBtn = document.getElementById('confirm-cancel-btn');
  var okBtn = document.getElementById('confirm-ok-btn');
  if (cancelBtn) cancelBtn.addEventListener('click', _dismissConfirmModal);
  if (okBtn) okBtn.addEventListener('click', function() {
    var cb = _confirmCallback;
    _dismissConfirmModal();
    if (cb) cb();
  });
}, 100);

/* ---------- Type selector ---------- */

function selectType(type) {
  document.getElementById('editing_type').value = type;
  document.querySelectorAll('.type-card').forEach(c => c.classList.remove('selected-avail', 'selected-block', 'selected-hold'));
  const cardEl = document.getElementById('type-' + type);
  if (cardEl) cardEl.classList.add(type === 'available' ? 'selected-avail' : type === 'hold' ? 'selected-hold' : 'selected-block');
  document.getElementById('form-available').style.display = type === 'available' ? '' : 'none';
  document.getElementById('form-blocked').style.display = type === 'blocked' ? '' : 'none';
  document.getElementById('form-hold').style.display = type === 'hold' ? '' : 'none';
}

function saveCurrentForm() {
  const type = document.getElementById('editing_type').value;
  if (type === 'available') {
    saveRule();
  } else if (type === 'hold') {
    saveHold();
  } else if (_blockMode === 'single') {
    saveOneoffBlock();
  } else {
    saveRecurringBlock();
  }
}

/* ---------- Dropdown data loaders ---------- */

async function loadProviders() {
  try { const data = await apiCall('/providers/list'); _providers = data.providers || []; } catch (e) { _providers = []; }
  const items = _providers.map(p => ({ id: p.id, name: p.name, npi: p.npi_number || '' }));
  var editable = editableProviderItems(_providers, items);
  if (msProvider) msProvider.setItems(editable);
  if (msBlockProvider) msBlockProvider.setItems(editable);
  if (msHoldProvider) msHoldProvider.setItems(editable);
  if (msFilterProvider) msFilterProvider.setItems(filterItems(_providers, items));
}

async function loadLocations() {
  try { const data = await apiCall('/locations'); _locations = data.locations || []; } catch (e) { _locations = []; }
  if (msLocation) {
    msLocation.setItems(_locations);
    // Default all selected on fresh form
    msLocation.setValue(_locations.map(l => String(l.id)));
  }
  if (msBlockLocation) {
    msBlockLocation.setItems(_locations);
    msBlockLocation.setValue(_locations.map(l => String(l.id)));
  }
  if (msHoldLocation) {
    msHoldLocation.setItems(_locations);
    msHoldLocation.setValue(_locations.map(l => String(l.id)));
  }
}

async function loadVisitTypes() {
  try { const data = await apiCall('/visit-types'); _visitTypes = data.visit_types || []; } catch (e) { _visitTypes = []; }
  if (msVisitType) {
    msVisitType.setItems(_visitTypes);
    // Default all selected on fresh form
    msVisitType.setValue(_visitTypes.map(v => String(v.id)));
  }
}

/* ---------- Overview / Accordion ---------- */

async function loadOverview() {
  var container = document.getElementById('accordion-container');
  if (container) container.style.opacity = '0.5';
  try {
    const data = await apiCall('/overview');
    if (data.error) {
      showMsg(data.error, 'error');
    } else {
      _overviewData = data.providers || [];
      _syncProviderTzMapFromOverview();
    }
  } catch (e) {
    showMsg('Failed to load data', 'error');
  }
  renderAccordion();
  if (container) requestAnimationFrame(function() { container.style.opacity = '1'; });
}

function resolveLocationNames(locationIds) {
  if (!locationIds || locationIds.length === 0) return [];
  return locationIds.map(function(lid) {
    var loc = _locations.find(function(l) { return String(l.id) === String(lid); });
    return loc ? loc.name : String(lid);
  });
}


function toggleRowDetail(dataRow, event) {
  // Ignore clicks on action chips
  if (event && event.target.closest('button, .action-chip')) return;
  var detailRow = dataRow.nextElementSibling;
  if (!detailRow || !detailRow.classList.contains('detail-row')) return;

  // Toggle just this row — leave any other expanded rows alone so the user
  // can compare multiple rules side-by-side.
  var isOpen = detailRow.classList.contains('open');
  detailRow.classList.toggle('open', !isOpen);
  dataRow.classList.toggle('expanded', !isOpen);
}

function renderAccordion() {
  const container = document.getElementById('accordion-container');
  // Save expanded card state before re-render
  var expandedProviders = [];
  container.querySelectorAll('.provider-card:not(.collapsed)').forEach(function(card) {
    if (card.dataset.providerId) expandedProviders.push(card.dataset.providerId);
  });
  var savedScroll = window.scrollY;
  // Build TZ hint HTML for embedding in the legend bar
  // Update legend bar in filter bar
  // "View times in" sits in the toolbar; the legend sits on the first section heading.
  var tzWrap = document.getElementById('view-tz-wrap');
  if (tzWrap) {
    var tzList = COMMON_TZS.slice();
    if (tzList.indexOf(_practiceTz) === -1) tzList.unshift(_practiceTz);
    var activeTz = _viewTz || 'provider';
    tzWrap.innerHTML = 'View times in <select class="input" id="view-tz-select" onchange="changeViewTz(this.value)">' +
      '<option value="provider"' + (activeTz === 'provider' ? ' selected' : '') + '>Provider\'s timezone</option>' +
      tzList.map(function(tz) { return '<option value="' + tz + '"' + (tz === activeTz ? ' selected' : '') + '>' + tz + '</option>'; }).join('') +
      '</select>';
  }
  var legendHtml = '<span class="av-legend">' +
    '<span class="legend-item"><span class="type-chip chip-avail">' + SVG_CHECK + '</span> Available</span>' +
    (paFeatureOn('facility_rounds') ? '<span class="legend-item"><span class="type-chip chip-round">' + SVG_ROUND + '</span> Facility round</span>' : '') +
    (paFeatureOn('facility_blocks') ? '<span class="legend-item"><span class="type-chip chip-fblock">' + SVG_ROUND + '</span> Facility block</span>' : '') +
    '<span class="legend-item"><span class="type-chip chip-block">' + SVG_X + '</span> Blocked</span>' +
    '<span class="legend-item"><span class="type-chip chip-override">' + SVG_OVERRIDE + '</span> Override</span>' +
    '<span class="legend-item"><span class="type-chip chip-hold">' + SVG_PAUSE + '</span> Hold</span>' +
    '</span>';
  var legendShown = false;
  function sectionHeading(title) {
    var row = '<div class="av-sec-row"><h3 class="overview-section-title">' + title + '</h3>' + (legendShown ? '' : legendHtml) + '</div>';
    legendShown = true;
    return row;
  }

  const selectedIds = msFilterProvider ? msFilterProvider.getValue() : [];

  // The viewer's own row lives in its own section and ignores the filter and
  // saved view. Those narrow only the other providers.
  const yours = _overviewData.filter(p => p.is_you);
  let others = _overviewData.filter(p => !p.is_you);
  if (selectedIds.length > 0) {
    others = others.filter(p => selectedIds.includes(p.provider_id));
  }
  others = others.slice().sort(function(a, b) {
    var aLast = (a.provider_name || '').split(' ').slice(-1)[0].toLowerCase();
    var bLast = (b.provider_name || '').split(' ').slice(-1)[0].toLowerCase();
    return aLast.localeCompare(bLast);
  });

  let othersEmpty = '';
  if (others.length === 0) {
    if (selectedIds.length > 0) {
      othersEmpty = '<div class="empty-state">No availability configured for the selected provider(s).<br><span style="font-size:13px;margin-top:6px;display:inline-block;">Use <strong>Add / Edit</strong> to set up rules.</span></div>';
    } else if (yours.length) {
      othersEmpty = '<div class="empty-state">No other providers have availability or blocks configured yet</div>';
    } else {
      othersEmpty = '<div class="empty-state">No availability or blocks configured yet</div>';
    }
  }

  const providers = yours.concat(others);

  let html = '';
  if (yours.length) html += sectionHeading('My availability');
  providers.forEach((p, idx) => {
    if (idx === yours.length) {
      html += sectionHeading(yours.length ? 'Other providers' : 'Providers');
    }
    const pid = p.provider_id;
    const name = p.provider_name || pid.slice(0, 8) + '...';
    const initials = getInitials(name);
    const avatarClass = AVATAR_CLASSES[idx % 3];
    // Hide expired rows unless asked for, and count only what is shown: a
    // count taken before filtering would read "3 available" above one row.
    const visibleRules = (p.rules || []).filter(r => _showExpired || !isExpiredRow(r));
    const visibleRecurring = (p.recurring_blocks || []).filter(
      rb => _showExpired || !isExpiredRow(rb)
    );
    const visibleBlocks = (p.blocks || []).filter(b => _showExpired || !isExpiredBlock(b));
    const visibleOverrides = r => (r.date_overrides || []).filter(ovr => _showExpired || !isExpiredOverride(ovr));

    // One count per rule, so a "Mon-Fri" rule and an "Every 2 days" rule both count as 1.
    const counts = { avail: 0, over: 0, round: 0, fblock: 0, block: 0, hold: 0 };
    visibleRules.forEach(r => {
      if (r.facility_id) counts.round++; else counts.avail++;
      counts.over += visibleOverrides(r).length;
    });
    visibleRecurring.forEach(rb => {
      if (rb.hold_type && rb.hold_type !== 'none') counts.hold++;
      else if (rb.facility_id) counts.fblock++;
      else counts.block++;
    });
    visibleBlocks.forEach(b => { if (b.facility_id) counts.fblock++; else counts.block++; });
    const hasData = counts.avail + counts.round + counts.fblock + counts.block + counts.hold > 0;

    var readOnly = p.can_edit === false;
    html += '<div class="provider-card' + (readOnly ? ' read-only' : '') + '" data-provider-id="' + _escHtml(pid) + '">';

    // Header
    html += '<div class="provider-card-header" onclick="toggleCard(this)">';
    html += '<div class="provider-info">';
    html += '<div class="provider-avatar ' + avatarClass + '">' + _escHtml(initials) + '</div>';
    var pTz = p.provider_timezone || _practiceTz;
    var pTzExplicit = p.provider_timezone_explicit;
    html += '<div class="provider-name-col">';
    html += '<span class="provider-name">' + _escHtml(name) + '</span>';
    if (!_viewTz) {
      html += '<div class="provider-tz-subtitle">' + pTz + (pTzExplicit ? '' : ' · practice default') + '</div>';
    }
    html += '</div></div>';
    html += '<div class="provider-header-right">';
    // Counts sit by the buttons: a type icon and a number per type.
    var countHtml = '';
    RULE_TYPES.forEach(function(t) {
      var n = counts[t.key];
      if (!n) return;
      countHtml += '<span class="card-count" title="' + n + ' ' + (n === 1 ? t.one : t.many) + '"><span class="type-chip ' + t.chip + '">' + t.svg + '</span><b>' + n + '</b></span>';
    });
    if (countHtml) html += '<span class="rule-counts">' + countHtml + '</span>';
    if (readOnly) html += '<span class="read-only-note">View only</span>';
    html += '<button class="btn btn-avail" onclick="event.stopPropagation();addForProvider(' + _jsArg(pid) + ',\'available\')">+ Available</button>';
    html += '<button class="btn btn-block-add" onclick="event.stopPropagation();addForProvider(' + _jsArg(pid) + ',\'blocked\')">+ Blocked</button>';
    html += '<svg class="chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M19 9l-7 7-7-7"/></svg>';
    html += '</div></div>';

    if (!hasData) {
      html += '<div style="padding:32px 24px;text-align:center;color:var(--text-muted);font-size:14px;">No availability or blocks configured';
      html += '<br><button class="btn btn-primary btn-sm" style="margin-top:12px;" onclick="addForProvider(' + _jsArg(pid) + ',\'available\')">+ Add Availability</button>';
      html += '</div>';
    } else {
      html += '<table class="rule-table">' + RULE_TABLE_HEAD + '<tbody>';
      var rows = [];
      function hoursText(windows) {
        return windows.map(w => fmtHHMMConverted(w.start, pTz) + ' – ' + fmtHHMMConverted(w.end, pTz)).join(', ');
      }

      // Available rules and facility rounds: one row per set of days with the same hours.
      visibleRules.forEach(r => {
        const isRound = !!r.facility_id;
        const type = isRound ? 'round' : 'avail';
        const ruleJson = _escHtml(JSON.stringify(JSON.stringify(r)));
        const items = [];
        if (isRound && r.max_visits) items.push(['Visits per round', 'Up to ' + r.max_visits]);
        if (!isRound) {
          var locNames = resolveLocationNames(r.location_ids);
          if (locNames.length > 1) items.push(['Locations', locNames.join(', ')]);
        }
        if ((r.visit_type_names || []).length) items.push(['Visit types', r.visit_type_names.join(', ')]);
        var buffers = bufferText(r);
        if (buffers) items.push(['Buffers', buffers]);
        if (r.effective_end && r.effective_end !== r.effective_start) {
          items.push(['Effective', fmtDate(r.effective_start) + ' to ' + fmtDate(r.effective_end)]);
        }
        const place = isRound ? placeHtml([r.facility_name || facilityName(r.facility_id)]) : placeHtml(resolveLocationNames(r.location_ids));

        var groups = r.recurrence_frequency === 'daily'
          ? ((r.time_windows || []).length ? [{ days: [], windows: r.time_windows }] : [])
          : groupDaysByWindows(r.weekly_schedule || {});
        var rowHtml = '';
        groups.forEach(group => {
          rowHtml += ruleRowHtml({
            type: type, when: whenLabel(r, group.days), hours: hoursText(group.windows), place: place, reason: r.reason,
            effective: effectiveHtml(r.effective_start, r.effective_end, isExpiredRow(r)), items: items,
            edit: 'editRule(' + ruleJson + ')',
            del: 'deleteRuleDays(' + _jsArg(r.provider_id) + ',' + _jsArg(r.id) + ',' + _jsArg(group.days) + ',' + ruleJson + ')',
          });
        });
        if (groups.length === 0) {
          rowHtml += ruleRowHtml({
            type: type, when: 'No days', hours: '—', place: place, reason: r.reason,
            effective: effectiveHtml(r.effective_start, r.effective_end, isExpiredRow(r)), items: items,
            edit: 'editRule(' + ruleJson + ')',
            del: 'confirmDeleteRule(' + _jsArg(r.provider_id) + ',' + _jsArg(r.id) + ')',
          });
        }
        rows.push({ order: RULE_ORDER[type], sortKey: r.effective_start || '0000-00-00', html: rowHtml });

        // Overrides change one date of the rule above.
        visibleOverrides(r).forEach(function(ovr) {
          var ovrDay = DAYS[(new Date(ovr.date + 'T12:00:00').getDay() + 6) % 7];
          var usual = r.recurrence_frequency === 'daily' ? (r.time_windows || []) : ((r.weekly_schedule || {})[ovrDay] || []);
          var ovrItems = [['Changes', (r.reason || (isRound ? 'Facility round' : 'Availability')) + (usual.length ? ', usually ' + hoursText(usual) : '')]];
          var ovrJson = _escHtml(JSON.stringify(JSON.stringify(ovr)));
          rows.push({ order: RULE_ORDER.over, sortKey: ovr.date, html: ruleRowHtml({
            type: 'over', when: fmtWeekdayDate(ovr.date), hours: ovr.is_closed ? 'Closed' : hoursText(ovr.time_windows || []),
            place: place, reason: ovr.reason, effective: effectiveHtml(ovr.date, ovr.date, isExpiredOverride(ovr)), items: ovrItems,
            edit: 'editOverrideFromAccordion(' + _jsArg(r.provider_id) + ',' + _jsArg(r.id) + ',' + ovrJson + ')',
            del: 'deleteOverrideFromAccordion(' + _jsArg(r.provider_id) + ',' + _jsArg(r.id) + ',' + _jsArg(ovr.date) + ')',
          }) });
        });
      });

      // One-off blocks
      visibleBlocks.forEach(b => {
        const day = (b.start || '').slice(0, 10);
        const viewTz = _viewTz || pTz;
        const blockJson = _escHtml(JSON.stringify(JSON.stringify(b)));
        var locNames = resolveLocationNames(b.location_ids);
        var fb = !!b.facility_id;
        rows.push({ order: RULE_ORDER[fb ? 'fblock' : 'block'], sortKey: day, html: ruleRowHtml({
          type: fb ? 'fblock' : 'block', when: fmtWeekdayDate(day),
          hours: b.all_day ? 'All day' : convertIsoTime(b.start, pTz, viewTz) + ' – ' + convertIsoTime(b.end, pTz, viewTz),
          place: fb ? placeHtml([b.facility_name || facilityName(b.facility_id)]) : placeHtml(locNames),
          reason: fb ? '' : b.reason, effective: effectiveHtml(day, day, isExpiredBlock(b)),
          items: fb ? facilityBlockItems(b) : (locNames.length > 1 ? [['Locations', locNames.join(', ')]] : []),
          edit: 'editBlock(' + blockJson + ')',
          del: 'confirmDeleteBlock(' + _jsArg(b.provider_id) + ',' + _jsArg(b.id) + ')',
        }) });
      });

      // Recurring blocks and holds
      visibleRecurring.forEach(rb => {
        const isHold = rb.hold_type && rb.hold_type !== 'none';
        const fb = !isHold && !!rb.facility_id;
        const type = isHold ? 'hold' : (fb ? 'fblock' : 'block');
        const holdLabel = { same_day: 'Same-day hold', next_day: 'Next-day hold' }[rb.hold_type] || '';
        // Escaped where it is shown (ruleRowHtml).
        const reason = isHold ? [holdLabel, rb.reason].filter(Boolean).join(': ') : (fb ? '' : rb.reason);
        const rbJson = _escHtml(JSON.stringify(JSON.stringify(rb)));
        var locNames = resolveLocationNames(rb.location_ids);
        var place = fb ? placeHtml([rb.facility_name || facilityName(rb.facility_id)]) : placeHtml(locNames);
        var items = fb ? facilityBlockItems(rb) : (locNames.length > 1 ? [['Locations', locNames.join(', ')]] : []);
        if (rb.effective_end && rb.effective_end !== rb.effective_start) {
          items.push(['Effective', fmtDate(rb.effective_start) + ' to ' + fmtDate(rb.effective_end)]);
        }
        var groups = rb.recurrence_frequency === 'daily'
          ? ((rb.time_windows || []).length ? [{ days: [], windows: rb.time_windows }] : [])
          : groupDaysByWindows(rb.weekly_schedule || {});
        var rowHtml = '';
        groups.forEach(group => {
          rowHtml += ruleRowHtml({
            type: type, when: whenLabel(rb, group.days), hours: hoursText(group.windows), place: place,
            reason: reason, effective: effectiveHtml(rb.effective_start, rb.effective_end, isExpiredRow(rb)), items: items,
            edit: (isHold ? 'editHold(' : 'editRecurringBlock(') + rbJson + ')',
            del: isHold
              ? 'deleteHold(' + _jsArg(rb.provider_id) + ',' + _jsArg(rb.id) + ')'
              : 'deleteRecurringBlockDays(' + _jsArg(rb.provider_id) + ',' + _jsArg(rb.id) + ',' + _jsArg(group.days) + ',' + rbJson + ')',
          });
        });
        rows.push({ order: RULE_ORDER[type], sortKey: rb.effective_start || '0000-00-00', html: rowHtml });
      });

      // By type, then by date.
      rows.sort(function(a, b) {
        if (a.order !== b.order) return a.order - b.order;
        return a.sortKey.localeCompare(b.sortKey);
      });
      rows.forEach(function(r) { html += r.html; });

      html += '</tbody></table>';
    }

    html += '</div>';
  });
  if (others.length === 0) {
    if (yours.length) html += sectionHeading('Other providers');
    html += othersEmpty;
  }
  container.innerHTML = html;
  // Restore expanded card state — collapse cards that weren't open before
  container.querySelectorAll('.provider-card[data-provider-id]').forEach(function(card) {
    if (expandedProviders.indexOf(card.dataset.providerId) === -1) card.classList.add('collapsed');
  });
  // Sync expand/collapse button label
  var ecBtn = document.querySelector('.btn-expand-collapse');
  if (ecBtn) {
    var anyCollapsed = container.querySelector('.provider-card.collapsed');
    ecBtn.textContent = anyCollapsed ? 'Expand all' : 'Collapse all';
  }
  fitReasons();
  window.scrollTo(0, savedScroll);
}

function toggleCard(header) {
  header.closest('.provider-card').classList.toggle('collapsed');
  fitReasons();
}

function toggleAllCards() {
  var cards = document.querySelectorAll('.provider-card');
  var btn = document.querySelector('.btn-expand-collapse');
  var allExpanded = true;
  cards.forEach(function(c) { if (c.classList.contains('collapsed')) allExpanded = false; });
  cards.forEach(function(c) {
    if (allExpanded) c.classList.add('collapsed');
    else c.classList.remove('collapsed');
  });
  if (btn) btn.textContent = allExpanded ? 'Expand all' : 'Collapse all';
  fitReasons();
}

function onFilterProviderChange() { renderAccordion(); }

function addForProvider(providerId, type) {
  resetForm();
  selectType(type);
  _skipDirtyCheck = true;
  showTab('editor');
  if (type === 'available') {
    msProvider.setValue([providerId]);
  } else if (type === 'blocked') {
    msBlockProvider.setValue([providerId]);
  }
}

/* ---------- Schedule editors ---------- */

function initScheduleEditor() {
  let html = '';
  DAYS.forEach(day => {
    html += '<div id="day-wrap-' + day + '">';
    html += '<div class="day-header collapsed" onclick="toggleDayCollapse(this)">';
    html += '<span class="day-label">' + DAY_FULL[day] + '</span>';
    html += '<span class="day-summary" id="day-summary-' + day + '">No hours</span>';
    html += '<svg class="day-chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M19 9l-7 7-7-7"/></svg>';
    html += '</div>';
    html += '<div class="day-body hidden" id="day-' + day + '">';
    html += '<button type="button" class="add-time-btn" onclick="addWindow(\'' + day + '\')">';
    html += SVG_PLUS + 'Add hours</button>';
    html += '</div>';
    html += '</div>';
  });
  document.getElementById('schedule-editor').innerHTML = html;
}

function toggleDayCollapse(header) {
  header.classList.toggle('collapsed');
  const body = header.nextElementSibling;
  body.classList.toggle('hidden');
}

function updateDaySummary(day, prefix) {
  const pfx = prefix || '';
  const sumEl = document.getElementById(pfx + 'day-summary-' + day);
  if (!sumEl) return;
  const wraps = document.querySelectorAll('#' + pfx + 'day-' + day + ' .day-time-inputs');
  if (wraps.length === 0) {
    sumEl.textContent = 'No hours';
    return;
  }
  const parts = [];
  wraps.forEach(w => {
    const inputs = w.querySelectorAll('.time-input');
    if (inputs[0].value && inputs[1].value) {
      parts.push(fmtHHMM(inputs[0].value) + ' \u2013 ' + fmtHHMM(inputs[1].value));
    }
  });
  sumEl.textContent = parts.length > 0 ? parts.length + ' block' + (parts.length > 1 ? 's' : '') : 'No hours';
}

function addWindow(day, startVal, endVal) {
  const row = document.getElementById('day-' + day);
  const btn = row.querySelector('.add-time-btn');
  const group = document.createElement('div');
  group.style.display = 'flex';
  group.style.alignItems = 'center';
  group.style.gap = '8px';
  group.style.flex = '1';
  const wrap = document.createElement('div');
  wrap.className = 'day-time-inputs';
  wrap.innerHTML = timeFieldHtml(startVal) +
    '<span class="time-sep">\u2013</span>' +
    timeFieldHtml(endVal);
  const rmv = document.createElement('button');
  rmv.type = 'button';
  rmv.className = 'remove-time';
  rmv.innerHTML = SVG_X_SM;
  rmv.onclick = () => {
    group.remove();
    const header = document.getElementById('day-wrap-' + day);
    if (header) {
      const h = header.querySelector('.day-header');
      if (!row.querySelector('.day-time-inputs') && h) h.classList.remove('has-time');
    }
    updateDaySummary(day);
  };
  group.appendChild(wrap);
  group.appendChild(rmv);
  row.insertBefore(group, btn);
  // Style the header and auto-expand
  const wrapEl = document.getElementById('day-wrap-' + day);
  if (wrapEl) {
    const h = wrapEl.querySelector('.day-header');
    if (h) { h.classList.add('has-time'); h.classList.remove('collapsed'); }
  }
  row.classList.remove('hidden');
  updateDaySummary(day);
}

function initRecurringBlockScheduleEditor() {
  let html = '';
  DAYS.forEach(day => {
    html += '<div id="rb-day-wrap-' + day + '">';
    html += '<div class="day-header collapsed" onclick="toggleDayCollapse(this)">';
    html += '<span class="day-label">' + DAY_FULL[day] + '</span>';
    html += '<span class="day-summary" id="rb-day-summary-' + day + '">No hours</span>';
    html += '<svg class="day-chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M19 9l-7 7-7-7"/></svg>';
    html += '</div>';
    html += '<div class="day-body hidden" id="rb-day-' + day + '">';
    html += '<button type="button" class="add-time-btn" onclick="addRecurringBlockWindow(\'' + day + '\')">';
    html += SVG_PLUS + 'Add hours</button>';
    html += '</div>';
    html += '</div>';
  });
  document.getElementById('recurring-block-schedule-editor').innerHTML = html;
}

function addRecurringBlockWindow(day, startVal, endVal) {
  const row = document.getElementById('rb-day-' + day);
  const btn = row.querySelector('.add-time-btn');
  const group = document.createElement('div');
  group.style.display = 'flex';
  group.style.alignItems = 'center';
  group.style.gap = '8px';
  group.style.flex = '1';
  const wrap = document.createElement('div');
  wrap.className = 'day-time-inputs';
  wrap.innerHTML = timeFieldHtml(startVal) +
    '<span class="time-sep">\u2013</span>' +
    timeFieldHtml(endVal);
  const rmv = document.createElement('button');
  rmv.type = 'button';
  rmv.className = 'remove-time';
  rmv.innerHTML = SVG_X_SM;
  rmv.onclick = () => {
    group.remove();
    const header = document.getElementById('rb-day-wrap-' + day);
    if (header) {
      const h = header.querySelector('.day-header');
      if (!row.querySelector('.day-time-inputs') && h) h.classList.remove('has-block');
    }
    updateDaySummary(day, 'rb-');
  };
  group.appendChild(wrap);
  group.appendChild(rmv);
  row.insertBefore(group, btn);
  // Style the header and auto-expand
  const wrapEl = document.getElementById('rb-day-wrap-' + day);
  if (wrapEl) {
    const h = wrapEl.querySelector('.day-header');
    if (h) { h.classList.add('has-block'); h.classList.remove('collapsed'); }
  }
  row.classList.remove('hidden');
  updateDaySummary(day, 'rb-');
}

/* ---------- Date Overrides ---------- */

// Overrides added while creating a rule. They are sent through the override
// endpoint right after the rule saves, so they get the same checks as any other.
var _pendingOverrides = [];
// The override date whose Remove is waiting for a confirm, or null.
var _removingOverride = null;

function askRemoveOverride(dateStr) {
  _removingOverride = dateStr;
  renderOverridesList();
}

function renderOverridesList() {
  const ruleId = document.getElementById('editing_rule_id').value;
  const providerId = msProvider.getValue()[0];
  let overrides = _pendingOverrides;
  if (ruleId) {
    if (!providerId) return;
    const rule = _findCurrentRule(providerId, ruleId);
    overrides = (rule && rule.date_overrides) || [];
  }
  const container = document.getElementById('overrides-list');
  if (overrides.length === 0) {
    container.innerHTML = '<p style="font-size:13px;color:var(--text-muted);">No date overrides.</p>';
    return;
  }
  let html = '<div class="ovr-list">';
  overrides.sort((a, b) => a.date.localeCompare(b.date));
  overrides.forEach(o => {
    const dateStr = o.date;
    const dateObj = new Date(dateStr + 'T12:00:00');
    const dayAbbr = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][dateObj.getDay()];
    const detail = (o.time_windows || []).map(w => fmtHHMM(w.start) + ' \u2013 ' + fmtHHMM(w.end)).join(', ') || 'Closed';
    const label = dayAbbr + ', ' + fmtDate(dateStr);
    html += '<div class="ovr-row">';
    html += '<span class="ovr-date">' + _escHtml(label) + '</span>';
    html += '<span class="ovr-when">' + detail + '</span>';
    html += '<span class="ovr-reason">' + _escHtml(o.reason || '') + '</span>';
    html += '<span class="ovr-acts"><button type="button" class="lnk-sm" onclick=\'editOverrideInPlace(' + _escHtml(JSON.stringify(JSON.stringify(o))) + ')\'>Edit</button>';
    html += '<button type="button" class="lnk-sm danger" onclick="askRemoveOverride(' + _jsArg(dateStr) + ')">Remove</button></span>';
    html += '</div>';
    if (_removingOverride === dateStr) {
      html += '<div class="ax-confirm ovr-confirm"><div><div class="ax-cf-title">Remove the override for ' + _escHtml(label) + '?</div>' +
        '<p>That date goes back to the weekly schedule.</p></div>' +
        '<button type="button" class="btn" onclick="askRemoveOverride(null)">Cancel</button>' +
        '<button type="button" class="btn btn-danger" onclick="deleteOverride(' + _jsArg(dateStr) + ')">Remove</button></div>';
    }
  });
  html += '</div>';
  container.innerHTML = html;
}

function _findCurrentRule(providerId, ruleId) {
  if (!_overviewData) return null;
  for (const p of _overviewData) {
    if (p.provider_id === providerId) {
      for (const r of (p.rules || [])) {
        if (r.id === ruleId) return r;
      }
    }
  }
  return null;
}

function showOverrideForm() {
  document.getElementById('override-form').style.display = '';
  document.getElementById('add-override-btn').style.display = 'none';
  document.getElementById('editing_override_date').value = '';
  document.getElementById('override_date').value = '';
  syncDateFacade('override_date');
  var ovrReasonEl = document.getElementById('override_reason');
  if (ovrReasonEl) ovrReasonEl.value = '';
  // Clear existing time window rows (keep the add-time-btn)
  const container = document.getElementById('override-windows');
  container.querySelectorAll('.override-window-row').forEach(el => el.remove());
}

function hideOverrideForm() {
  document.getElementById('override-form').style.display = 'none';
  document.getElementById('add-override-btn').style.display = '';
}

function addOverrideWindow(startVal, endVal) {
  const container = document.getElementById('override-windows');
  const btn = container.querySelector('.add-time-btn');
  const group = document.createElement('div');
  group.className = 'override-window-row';
  group.style.display = 'flex';
  group.style.alignItems = 'center';
  group.style.gap = '8px';
  group.style.marginBottom = '4px';
  const wrap = document.createElement('div');
  wrap.className = 'day-time-inputs';
  wrap.innerHTML = timeFieldHtml(startVal) +
    '<span class="time-sep">\u2013</span>' +
    timeFieldHtml(endVal);
  const rmv = document.createElement('button');
  rmv.type = 'button';
  rmv.className = 'remove-time';
  rmv.innerHTML = SVG_X_SM;
  rmv.onclick = () => group.remove();
  group.appendChild(wrap);
  group.appendChild(rmv);
  container.insertBefore(group, btn);
}

async function saveOverride() {
  const ruleId = document.getElementById('editing_rule_id').value;
  const providerId = msProvider.getValue()[0];
  const dateVal = document.getElementById('override_date').value;
  if (!dateVal) { showMsg('Please select a date', 'error'); return; }
  const timeWindows = [];
  const wraps = document.getElementById('override-windows').querySelectorAll('.day-time-inputs');
  for (const wrap of wraps) {
    const inputs = wrap.querySelectorAll('.time-input');
    if (inputs[0].value && inputs[1].value) {
      if (inputs[0].value >= inputs[1].value) {
        showMsg('Override: start time must be before end time', 'error');
        return;
      }
      timeWindows.push({ start: inputs[0].value, end: inputs[1].value });
    }
  }
  if (timeWindows.length === 0) { showMsg('Please add at least one time window', 'error'); return; }
  var editingDate = document.getElementById('editing_override_date') ? document.getElementById('editing_override_date').value : '';
  if (!ruleId) {
    // New rule: keep it on the page; it saves right after the rule does.
    var reasonNew = document.getElementById('override_reason') ? document.getElementById('override_reason').value : '';
    _pendingOverrides = _pendingOverrides.filter(function(o) { return o.date !== dateVal && o.date !== editingDate; });
    _pendingOverrides.push({ date: dateVal, is_closed: false, time_windows: timeWindows, reason: reasonNew });
    document.getElementById('editing_override_date').value = '';
    hideOverrideForm();
    renderOverridesList();
    return;
  }
  // If editing an existing override and the date changed, delete the old one first
  if (editingDate && editingDate !== dateVal) {
    const moved = await apiCall('/rules/' + providerId + '/' + ruleId + '/overrides/' + editingDate, { method: 'DELETE' });
    if (moved.error) { showMsg(moved.error, 'error'); return; }
  }
  var ovrReason = document.getElementById('override_reason') ? document.getElementById('override_reason').value : '';
  const data = await apiCall('/rules/' + providerId + '/' + ruleId + '/overrides', {
    method: 'POST',
    body: JSON.stringify({ date: dateVal, is_closed: false, time_windows: timeWindows, reason: ovrReason }),
  });
  if (data.error) { showMsg(data.error, 'error'); return; }
  showMsg('Override saved', 'success');
  if (document.getElementById('editing_override_date')) document.getElementById('editing_override_date').value = '';
  hideOverrideForm();
  // Refresh overview data so the list re-renders
  await refreshOverviewAndOverrides(providerId, ruleId);
}

async function deleteOverride(dateStr) {
  _removingOverride = null;
  const ruleId = document.getElementById('editing_rule_id').value;
  if (!ruleId) {
    _pendingOverrides = _pendingOverrides.filter(function(o) { return o.date !== dateStr; });
    renderOverridesList();
    return;
  }
  const providerId = msProvider.getValue()[0];
  const data = await apiCall('/rules/' + providerId + '/' + ruleId + '/overrides/' + dateStr, {
    method: 'DELETE',
  });
  if (data.error) { showMsg(data.error, 'error'); return; }
  showMsg('Override removed', 'success');
  await refreshOverviewAndOverrides(providerId, ruleId);
}

async function deleteOverrideFromAccordion(providerId, ruleId, dateStr) {
  showConfirm('Delete this override for ' + fmtDate(dateStr) + '?', async function() {
    const data = await apiCall('/rules/' + providerId + '/' + ruleId + '/overrides/' + dateStr, {
      method: 'DELETE',
    });
    if (data.error) { showMsg(data.error, 'error'); return; }
    showMsg('Override removed', 'success');
    await loadOverview();
  });
}

function editOverrideFromAccordion(providerId, ruleId, ovrJson) {
  var ovr = (typeof ovrJson === 'string') ? JSON.parse(ovrJson) : ovrJson;
  // Find the parent rule and open it in the editor
  var rule = _findCurrentRule(providerId, ruleId);
  if (!rule) { showMsg('Rule not found', 'error'); return; }
  editRule(JSON.stringify(rule));
  // Now open the override form and pre-fill
  showOverrideForm();
  document.getElementById('editing_override_date').value = ovr.date;
  document.getElementById('override_date').value = ovr.date;
  syncDateFacade('override_date');
  var ovrReasonEl = document.getElementById('override_reason');
  if (ovrReasonEl) ovrReasonEl.value = ovr.reason || '';
  // Pre-fill time windows
  if (ovr.time_windows && ovr.time_windows.length > 0) {
    ovr.time_windows.forEach(function(w) { addOverrideWindow(w.start, w.end); });
  }
  // Scroll the override form into view after tab switch + render
  setTimeout(function() {
    var ovrForm = document.getElementById('override-form');
    if (ovrForm) ovrForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 100);
}

function editOverrideInPlace(ovrJsonStr) {
  var ovr = (typeof ovrJsonStr === 'string') ? JSON.parse(ovrJsonStr) : ovrJsonStr;
  showOverrideForm();
  document.getElementById('editing_override_date').value = ovr.date;
  document.getElementById('override_date').value = ovr.date;
  syncDateFacade('override_date');
  var ovrReasonEl = document.getElementById('override_reason');
  if (ovrReasonEl) ovrReasonEl.value = ovr.reason || '';
  if (ovr.time_windows && ovr.time_windows.length > 0) {
    ovr.time_windows.forEach(function(w) { addOverrideWindow(w.start, w.end); });
  }
  setTimeout(function() {
    var ovrForm = document.getElementById('override-form');
    if (ovrForm) ovrForm.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 100);
}

async function refreshOverviewAndOverrides(providerId, ruleId) {
  // Re-fetch overrides to update the local cache and re-render
  const resp = await apiCall('/rules/' + providerId + '/' + ruleId + '/overrides');
  if (resp && resp.overrides) {
    // Update the _overviewData cache
    const rule = _findCurrentRule(providerId, ruleId);
    if (rule) rule.date_overrides = resp.overrides;
  }
  renderOverridesList();
}

/* ---------- Form management ---------- */

function resetForm() {
  const today = new Date().toISOString().slice(0, 10);
  document.getElementById('editor-title').textContent = 'Add new rule';
  document.getElementById('editing_rule_id').value = '';
  _pendingOverrides = [];
  document.getElementById('editing_block_id').value = '';
  document.getElementById('editing_recurring_block_id').value = '';
  document.getElementById('editing_group_id').value = '';
  document.getElementById('editing_type').value = 'available';
  document.getElementById('group-banner').style.display = 'none';
  // The banner's checkbox keeps DOM state across edits; reset it so a prior
  // edit's "Apply to all" choice never silently carries into the next one.
  var applyToGroupEl = document.getElementById('apply_to_group');
  if (applyToGroupEl) applyToGroupEl.checked = false;
  document.getElementById('type-selector-section').style.display = '';
  document.getElementById('date-overrides-section').style.display = 'none';

  msProvider.clear();
  // Default locations and visit types to all selected
  msLocation.setValue(_locations.map(l => String(l.id)));
  msVisitType.setValue(_visitTypes.map(v => String(v.id)));
  msBlockProvider.clear();
  msBlockLocation.setValue(_locations.map(l => String(l.id)));

  // New rules start from the defaults saved in Settings (settings.js keeps these current).
  var _defaults = (window.__PRELOADED__ && window.__PRELOADED__.rule_defaults) || {};
  document.getElementById('buffer_pre').value = String(_defaults.buffer_pre || 0);
  document.getElementById('buffer_post').value = String(_defaults.buffer_post || 0);
  document.getElementById('min_lead_hours').value = String(_defaults.min_lead_hours || 0);
  applyFeatureVisibility();
  document.getElementById('effective_start').value = today;
  document.getElementById('effective_end').value = '';
  clearEndDate('effective_end');
  syncDateFacade('effective_start');
  syncDateFacade('effective_end');
  document.getElementById('rule_reason').value = '';
  document.getElementById('block_reason').value = '';
  document.getElementById('rb_effective_start').value = today;
  document.getElementById('rb_effective_end').value = '';
  clearEndDate('rb_effective_end');
  syncDateFacade('rb_effective_start');
  syncDateFacade('rb_effective_end');
  document.getElementById('block_date').value = '';
  setTimeField('block_start_time', '');
  setTimeField('block_end_time', '');
  syncDateFacade('block_date');

  // Reset single event fields
  document.getElementById('single_date').value = '';
  setTimeField('single_start_time', '');
  setTimeField('single_end_time', '');
  syncDateFacade('single_date');

  // Reset the All-day checkbox and the multi-date chip queue
  // (block_date/start/end are already cleared above).
  var allDayEl = document.getElementById('block_all_day');
  if (allDayEl) {
    allDayEl.checked = false;
    onBlockAllDayToggle(false);
  }
  _resetBlockEntries();
  _editingBlockGroup = null;

  // Reset recurrence controls and clear daily-mode editors
  var ivEl = document.getElementById('recurrence_interval');
  var fqEl = document.getElementById('recurrence_frequency');
  if (ivEl) ivEl.value = '1';
  if (fqEl) fqEl.value = 'weekly';
  var rbIvEl = document.getElementById('rb_recurrence_interval');
  var rbFqEl = document.getElementById('rb_recurrence_frequency');
  if (rbIvEl) rbIvEl.value = '1';
  if (rbFqEl) rbFqEl.value = 'weekly';
  _clearDailyTimeWindows('time-windows-rows');
  _clearDailyTimeWindows('rb-time-windows-rows');

  setScheduleMode('single');
  resetRoundFields();
  resetBlockWhat();

  // Reset block mode to single
  setBlockMode('single');

  // Reset hold form
  document.getElementById('editing_hold_id').value = '';
  document.getElementById('editing_hold_group_id').value = '';
  document.getElementById('hold_reason').value = '';
  setHoldType('same_day');
  document.getElementById('hold_effective_start').value = today;
  document.getElementById('hold_effective_end').value = '';
  clearEndDate('hold_effective_end');
  syncDateFacade('hold_effective_start');
  syncDateFacade('hold_effective_end');
  if (msHoldProvider) msHoldProvider.clear();
  if (msHoldLocation) msHoldLocation.setValue(_locations.map(l => String(l.id)));

  selectType('available');
  initScheduleEditor();
  initRecurringBlockScheduleEditor();
  initHoldScheduleEditor();
  _formDirty = false;
}

// An empty end date means no end. The × in the box clears a picked date.
function clearEndDate(inputId) {
  var el = document.getElementById(inputId);
  if (!el) return;
  el.value = '';
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function editRule(ruleJson) {
  const r = JSON.parse(ruleJson);
  resetForm();
  selectType('available');
  document.getElementById('type-selector-section').style.display = 'none';
  _skipDirtyCheck = true;
  showTab('editor');
  document.getElementById('editor-title').textContent = 'Edit availability';
  document.getElementById('editing_rule_id').value = r.id || '';
  document.getElementById('editing_group_id').value = r.group_id || '';
  msProvider.setValue([r.provider_id]);
  msLocation.setValue(r.location_ids || []);
  msVisitType.setValue(r.visit_types || []);
  fillRoundFields(r);

  document.getElementById('rule_reason').value = r.reason || '';
  document.getElementById('buffer_pre').value = (r.buffer_minutes || {}).pre || 0;
  document.getElementById('buffer_post').value = (r.buffer_minutes || {}).post || 0;
  document.getElementById('min_lead_hours').value = (r.booking_interval || {}).min_lead_hours || 0;

  // Detect single event: effective_start === effective_end, schedule has exactly 1 day with 1 window
  const hasEnd = !!r.effective_end;
  var isSingleDay = hasEnd && r.effective_start === r.effective_end;
  var schedule = r.weekly_schedule || {};
  var activeDays = DAYS.filter(function(d) { return (schedule[d] || []).length > 0; });
  var isSingleEvent = isSingleDay && activeDays.length === 1 && schedule[activeDays[0]].length === 1;

  if (isSingleEvent) {
    setScheduleMode('single');
    document.getElementById('single_date').value = r.effective_start;
    syncDateFacade('single_date');
    var win = schedule[activeDays[0]][0];
    setTimeField('single_start_time', win.start);
    setTimeField('single_end_time', win.end);
  } else {
    setScheduleMode('recurring');
    document.getElementById('effective_start').value = r.effective_start || '';
    document.getElementById('effective_end').value = r.effective_end || '';
    syncDateFacade('effective_start');
    syncDateFacade('effective_end');
    // Restore stored recurrence on the form
    var ivEl = document.getElementById('recurrence_interval');
    var fqEl = document.getElementById('recurrence_frequency');
    if (ivEl) ivEl.value = String(r.recurrence_interval || 1);
    if (fqEl) fqEl.value = (r.recurrence_frequency === 'daily') ? 'daily' : 'weekly';
    onRecurrenceFrequencyChange();
  }

  if (r.group_id) {
    let groupCount = 0;
    _overviewData.forEach(p => {
      p.rules.forEach(pr => { if (pr.group_id === r.group_id) groupCount++; });
    });
    if (groupCount > 1) {
      document.getElementById('group-banner').style.display = '';
      document.getElementById('group-banner-text').textContent = 'This was created for ' + groupCount + ' providers. Apply changes to all?';
    }
  }

  if (_scheduleMode === 'recurring') {
    initScheduleEditor();
    DAYS.forEach(day => {
      ((r.weekly_schedule || {})[day] || []).forEach(w => addWindow(day, w.start, w.end));
    });
    // For daily-frequency rules, the time windows live on r.time_windows
    // and are edited in the flat editor — populate it.
    if (r.recurrence_frequency === 'daily') {
      _clearDailyTimeWindows('time-windows-rows');
      (r.time_windows || []).forEach(w => addDailyTimeWindow('time-windows-rows', w.start, w.end));
    }
  }

  // Show date overrides section when editing in recurring mode
  if (_scheduleMode === 'recurring') {
    document.getElementById('date-overrides-section').style.display = '';
    renderOverridesList();
  }
}

function editRecurringBlock(blockJson) {
  const b = JSON.parse(blockJson);
  resetForm();
  selectType('blocked');
  setBlockMode('recurring');
  document.getElementById('type-selector-section').style.display = 'none';
  _skipDirtyCheck = true;
  showTab('editor');
  document.getElementById('editor-title').textContent = 'Edit block';
  document.getElementById('editing_recurring_block_id').value = b.id || '';
  document.getElementById('editing_group_id').value = b.group_id || '';
  msBlockProvider.setValue([b.provider_id]);
  msBlockLocation.setValue(b.location_ids || []);
  fillBlockWhat(b);

  document.getElementById('block_reason').value = b.facility_id ? '' : (b.reason || '');
  document.getElementById('rb_effective_start').value = b.effective_start || '';
  document.getElementById('rb_effective_end').value = b.effective_end || '';

  syncDateFacade('rb_effective_start');
  syncDateFacade('rb_effective_end');

  // Restore stored recurrence on the form
  var rbIvEl = document.getElementById('rb_recurrence_interval');
  var rbFqEl = document.getElementById('rb_recurrence_frequency');
  if (rbIvEl) rbIvEl.value = String(b.recurrence_interval || 1);
  if (rbFqEl) rbFqEl.value = (b.recurrence_frequency === 'daily') ? 'daily' : 'weekly';
  onRecurringBlockFrequencyChange();

  if (b.group_id) {
    let groupCount = 0;
    _overviewData.forEach(p => {
      p.recurring_blocks.forEach(prb => { if (prb.group_id === b.group_id) groupCount++; });
    });
    if (groupCount > 1) {
      document.getElementById('group-banner').style.display = '';
      document.getElementById('group-banner-text').textContent = 'This was created for ' + groupCount + ' providers. Apply changes to all?';
    }
  }

  initRecurringBlockScheduleEditor();
  DAYS.forEach(day => {
    ((b.weekly_schedule || {})[day] || []).forEach(w => addRecurringBlockWindow(day, w.start, w.end));
  });
  // Daily-frequency blocks live on b.time_windows in the flat editor.
  if (b.recurrence_frequency === 'daily') {
    _clearDailyTimeWindows('rb-time-windows-rows');
    (b.time_windows || []).forEach(w => addDailyTimeWindow('rb-time-windows-rows', w.start, w.end));
  }
}

function editBlock(blockJson) {
  const b = JSON.parse(blockJson);
  resetForm();
  selectType('blocked');
  setBlockMode('single');
  document.getElementById('type-selector-section').style.display = 'none';
  _skipDirtyCheck = true;
  showTab('editor');
  document.getElementById('editor-title').textContent = 'Edit block';
  document.getElementById('editing_block_id').value = b.id || '';
  document.getElementById('editing_group_id').value = b.group_id || '';
  msBlockProvider.setValue([b.provider_id]);
  msBlockLocation.setValue(b.location_ids || []);
  fillBlockWhat(b);

  document.getElementById('block_reason').value = b.facility_id ? '' : (b.reason || '');

  // Populate date/time from block start/end ISO strings
  document.getElementById('block_date').value = (b.start || '').slice(0, 10);
  setTimeField('block_start_time', (b.start || '').slice(11, 16));
  setTimeField('block_end_time', (b.end || '').slice(11, 16));
  syncDateFacade('block_date');

  // Restore the all-day checkbox from the saved block
  var allDayEl = document.getElementById('block_all_day');
  if (allDayEl) {
    allDayEl.checked = !!b.all_day;
    onBlockAllDayToggle(!!b.all_day);
  }

  // Multi-date group: list every block in the group with its own date and
  // times, and clear the row above so it is free for adding more. Saving
  // replaces the whole group.
  _editingBlockGroup = null;
  if (b.group_id) {
    var siblings = [];
    _overviewData.forEach(function(p) {
      if (p.provider_id !== b.provider_id) return;
      (p.blocks || []).forEach(function(pb) { if (pb.group_id === b.group_id) siblings.push(pb); });
    });
    var sameDate = (b.start || '').slice(0, 10);
    if (siblings.some(function(pb) { return (pb.start || '').slice(0, 10) !== sameDate; })) {
      _editingBlockGroup = b.group_id;
      _resetBlockEntries();
      siblings.forEach(function(pb) {
        var e = { date: (pb.start || '').slice(0, 10), allDay: !!pb.all_day,
                  start: pb.all_day ? '' : (pb.start || '').slice(11, 16), end: pb.all_day ? '' : (pb.end || '').slice(11, 16) };
        if (!_blockEntries.some(function(x) { return _blockEntryKey(x) === _blockEntryKey(e); })) _blockEntries.push(e);
      });
      _renderBlockEntries();
      document.getElementById('block_date').value = '';
      syncDateFacade('block_date');
    }
  }

  // Show the apply-to-group banner whenever the group spans multiple
  // providers. Multi-DATE groups also surface the banner so the user can
  // explicitly opt into propagating edits across providers — without it,
  // an "edit time" save would silently leak to siblings via stale checkbox
  // state, or not propagate at all when the user wanted it to.
  if (b.group_id) {
    var providerCount = 0;
    _overviewData.forEach(function(p) {
      var hit = (p.blocks || []).some(function(pb) { return pb.group_id === b.group_id; });
      if (hit) providerCount++;
    });
    if (providerCount > 1) {
      document.getElementById('group-banner').style.display = '';
      document.getElementById('group-banner-text').textContent = 'This was created for ' + providerCount + ' providers. Apply changes to all?';
    }
  }
}

/* ---------- Save functions ---------- */

// An override typed into the open override box is saved only by its own
// Save Override button, so Save Rule would otherwise drop it without a word.
function _hasUnsavedOverride() {
  var form = document.getElementById('override-form');
  if (!form || form.style.display === 'none') return false;
  var dateEl = document.getElementById('override_date');
  return !!(dateEl && dateEl.value) || form.querySelectorAll('.override-window-row').length > 0;
}

async function saveRule() {
  if (_hasUnsavedOverride()) {
    showMsg('You have an unsaved date override. Click Save Override or Cancel first.', 'error');
    return;
  }
  const providerIds = msProvider.getValue();
  if (providerIds.length === 0) { showMsg('Please select at least one provider', 'error'); return; }

  var filledSchedule;
  var effectiveStart, effectiveEnd;

  if (_scheduleMode === 'single') {
    // Single event mode: derive schedule from date + times
    var sDate = document.getElementById('single_date').value;
    var sStart = document.getElementById('single_start_time').value;
    var sEnd = document.getElementById('single_end_time').value;
    if (!sDate || !sStart || !sEnd) { showMsg('Date, start time, and end time are required', 'error'); return; }
    if (sStart >= sEnd) { showMsg('Start time must be before end time', 'error'); return; }
    // Derive day-of-week from date
    var dateParts = sDate.split('-');
    var dateObj = new Date(Number(dateParts[0]), Number(dateParts[1]) - 1, Number(dateParts[2]));
    var dayNames = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];
    var dayOfWeek = dayNames[dateObj.getDay()];
    filledSchedule = {};
    filledSchedule[dayOfWeek] = [{ start: sStart, end: sEnd }];
    effectiveStart = sDate;
    effectiveEnd = sDate;
  } else {
    // Weekly schedule mode
    const schedule = {};
    let hasValidationError = false;
    DAYS.forEach(day => {
      const wraps = document.querySelectorAll('#day-' + day + ' .day-time-inputs');
      if (wraps.length > 0) {
        schedule[day] = [];
        wraps.forEach(wrap => {
          const inputs = wrap.querySelectorAll('.time-input');
          if (inputs[0].value && inputs[1].value) {
            if (inputs[0].value >= inputs[1].value) {
              showMsg('Start time must be before end time (' + DAY_ABBR[day] + ': ' + inputs[0].value + ' >= ' + inputs[1].value + ')', 'error');
              hasValidationError = true;
              return;
            }
            schedule[day].push({ start: inputs[0].value, end: inputs[1].value });
          }
        });
      }
    });
    if (hasValidationError) return;

    // Filter out days with empty window arrays
    filledSchedule = {};
    Object.entries(schedule).forEach(([day, windows]) => {
      if (windows.length > 0) filledSchedule[day] = windows;
    });
    effectiveStart = document.getElementById('effective_start').value || null;
    effectiveEnd = document.getElementById('effective_end').value || null;
    if (!effectiveStart) { showMsg('Start date is required', 'error'); return; }
  }

  const round = readRoundFields();
  if (round.error) { showMsg(round.error, 'error'); return; }

  const editingId = document.getElementById('editing_rule_id').value;
  const groupId = document.getElementById('editing_group_id').value;
  const applyToGroup = document.getElementById('apply_to_group').checked && groupId;

  // Recurrence: read controls when in recurring mode; single events use defaults.
  var recurrence = _scheduleMode === 'recurring'
    ? _readRecurrenceFields('recurrence_interval', 'recurrence_frequency')
    : { interval: 1, frequency: 'weekly' };

  // Daily mode: read time windows from the flat editor; weekly grid is hidden.
  var timeWindows = recurrence.frequency === 'daily'
    ? _readDailyTimeWindows('time-windows-rows')
    : [];

  if (_scheduleMode !== 'single') {
    if (recurrence.frequency === 'daily') {
      if (timeWindows.length === 0) {
        showMsg('Add at least one time window', 'error');
        return;
      }
      // Daily mode ignores the weekly grid; clear it from the payload.
      filledSchedule = {};
    } else if (Object.keys(filledSchedule).length === 0) {
      showMsg('Please add at least one time window', 'error');
      return;
    }
  }

  const ruleBase = {
    location_ids: msLocation.getValue(),
    visit_types: msVisitType.getValue(),
    reason: document.getElementById('rule_reason').value,
    weekly_schedule: filledSchedule,
    buffer_minutes: {
      pre: parseInt(document.getElementById('buffer_pre').value) || 0,
      post: parseInt(document.getElementById('buffer_post').value) || 0,
    },
    booking_interval: {
      min_lead_hours: parseInt(document.getElementById('min_lead_hours').value) || 0,
    },
    is_active: true,
    effective_start: effectiveStart,
    effective_end: effectiveEnd,
    timezone: getEditorTimezone(),
    recurrence_frequency: recurrence.frequency,
    recurrence_interval: recurrence.interval,
    time_windows: timeWindows,
  };
  Object.assign(ruleBase, round.fields);

  if (editingId && providerIds.length === 1) {
    const rule = Object.assign({}, ruleBase, {
      provider_id: providerIds[0],
      id: editingId,
      group_id: groupId || null,
      apply_to_group: !!applyToGroup,
    });
    const data = await apiCall('/rules', { method: 'PUT', body: JSON.stringify(rule) });
    if (data.error) { showMsg(data.error, 'error'); return; }
    showMsg(data.message || 'Rule updated', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  const newGroupId = providerIds.length > 1 ? crypto.randomUUID() : null;
  let errors = [];
  let saved = 0;

  const overridesToAdd = _scheduleMode === 'recurring' ? _pendingOverrides.slice() : [];
  for (const pid of providerIds) {
    const rule = Object.assign({}, ruleBase, { provider_id: pid, group_id: newGroupId });
    const data = await apiCall('/rules', { method: 'POST', body: JSON.stringify(rule) });
    if (data.error) { errors.push(data.error); continue; }
    saved++;
    const newRuleId = data.rule && data.rule.id;
    for (const o of overridesToAdd) {
      if (!newRuleId) break;
      const res = await apiCall('/rules/' + pid + '/' + newRuleId + '/overrides', { method: 'POST', body: JSON.stringify(o) });
      if (res && res.error) errors.push('Override ' + fmtDate(o.date) + ': ' + res.error);
    }
  }
  _pendingOverrides = [];

  if (errors.length > 0) showMsg(errors.join('; '), 'error');
  else showMsg(saved === 1 ? 'Availability saved' : saved + ' availability rules created', 'success');
  // Once any rule is saved, leave the form so a second Save can't create it twice.
  if (saved > 0) {
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
  }
}

async function saveRecurringBlock() {
  const providerIds = msBlockProvider.getValue();
  if (providerIds.length === 0) { showMsg('Please select at least one provider', 'error'); return; }
  const what = readBlockWhat();
  if (what.error) { showMsg(what.error, 'error'); return; }

  let schedule = {};
  let hasValidationError = false;
  DAYS.forEach(day => {
    const wraps = document.querySelectorAll('#rb-day-' + day + ' .day-time-inputs');
    if (wraps.length > 0) {
      schedule[day] = [];
      wraps.forEach(wrap => {
        const inputs = wrap.querySelectorAll('.time-input');
        if (inputs[0].value && inputs[1].value) {
          if (inputs[0].value >= inputs[1].value) {
            showMsg('Start time must be before end time (' + DAY_ABBR[day] + ': ' + inputs[0].value + ' >= ' + inputs[1].value + ')', 'error');
            hasValidationError = true;
            return;
          }
          schedule[day].push({ start: inputs[0].value, end: inputs[1].value });
        }
      });
    }
  });
  if (hasValidationError) return;

  // Recurrence: read controls when in recurring mode (always, since we collapsed to one tab).
  var rbRecurrence = _readRecurrenceFields('rb_recurrence_interval', 'rb_recurrence_frequency');
  var rbTimeWindows = rbRecurrence.frequency === 'daily'
    ? _readDailyTimeWindows('rb-time-windows-rows')
    : [];

  if (rbRecurrence.frequency === 'daily') {
    if (rbTimeWindows.length === 0) {
      showMsg('Add at least one time window', 'error');
      return;
    }
    schedule = {};  // daily mode ignores the weekly grid
  } else if (Object.keys(schedule).length === 0) {
    showMsg('Please add at least one time window', 'error');
    return;
  }

  const editingId = document.getElementById('editing_recurring_block_id').value;
  const groupId = document.getElementById('editing_group_id').value;
  const applyToGroup = document.getElementById('apply_to_group').checked && groupId;
  const holdType = 'none';
  if (!document.getElementById('rb_effective_start').value) { showMsg('Start date is required', 'error'); return; }

  const locationIds = what.locationIds;
  const reason = what.facilityId ? '' : document.getElementById('block_reason').value;

  if (editingId && providerIds.length === 1) {
    const body = {
      id: editingId,
      provider_id: providerIds[0],
      weekly_schedule: schedule,
      reason: reason,
      location_ids: locationIds,
      facility_id: what.facilityId,
      effective_start: document.getElementById('rb_effective_start').value || null,
      effective_end: document.getElementById('rb_effective_end').value || null,
      is_active: true,
      hold_type: holdType,
      timezone: getEditorTimezone(),
      group_id: groupId || null,
      apply_to_group: !!applyToGroup,
      recurrence_frequency: rbRecurrence.frequency,
      recurrence_interval: rbRecurrence.interval,
      time_windows: rbTimeWindows,
    };
    const data = await apiCall('/recurring-blocks', { method: 'PUT', body: JSON.stringify(body) });
    if (data.error) { showMsg(data.error, 'error'); return; }
    showMsg(data.message || 'Block updated', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  // Converting from single block → recurring block (atomic: create + delete in one call)
  const singleBlockId = document.getElementById('editing_block_id').value;
  if (singleBlockId && providerIds.length === 1) {
    const createBody = {
      provider_id: providerIds[0],
      weekly_schedule: schedule,
      reason: reason,
      location_ids: locationIds,
      facility_id: what.facilityId,
      effective_start: document.getElementById('rb_effective_start').value || null,
      effective_end: document.getElementById('rb_effective_end').value || null,
      is_active: true,
      hold_type: holdType,
      timezone: getEditorTimezone(),
      group_id: groupId || null,
      replace_block_id: singleBlockId,
      recurrence_frequency: rbRecurrence.frequency,
      recurrence_interval: rbRecurrence.interval,
      time_windows: rbTimeWindows,
    };
    const createData = await apiCall('/recurring-blocks', { method: 'POST', body: JSON.stringify(createBody) });
    if (createData.error) { showMsg(createData.error, 'error'); return; }
    showMsg('Block converted to weekly schedule', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  const newGroupId = providerIds.length > 1 ? crypto.randomUUID() : null;
  let errors = [];
  let saved = 0;

  for (const pid of providerIds) {
    const body = {
      provider_id: pid,
      weekly_schedule: schedule,
      reason: reason,
      location_ids: locationIds,
      facility_id: what.facilityId,
      effective_start: document.getElementById('rb_effective_start').value || null,
      effective_end: document.getElementById('rb_effective_end').value || null,
      is_active: true,
      hold_type: holdType,
      timezone: getEditorTimezone(),
      group_id: newGroupId,
      recurrence_frequency: rbRecurrence.frequency,
      recurrence_interval: rbRecurrence.interval,
      time_windows: rbTimeWindows,
    };
    const data = await apiCall('/recurring-blocks', { method: 'POST', body: JSON.stringify(body) });
    if (data.error) errors.push(data.error);
    else saved++;
  }

  if (errors.length > 0) {
    showMsg(errors.join('; '), 'error');
  } else {
    showMsg(saved === 1 ? 'Block created' : saved + ' blocks created', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
  }
}

async function saveOneoffBlock() {
  const blockId = document.getElementById('editing_block_id').value;
  const providerIds = msBlockProvider.getValue();
  if (providerIds.length === 0) { showMsg('Please select at least one provider', 'error'); return; }
  const what = readBlockWhat();
  if (what.error) { showMsg(what.error, 'error'); return; }

  // Every block to save: the list, plus the row above when a date is filled in.
  const entries = _blockEntries.slice();
  if (document.getElementById('block_date').value) {
    const live = _readBlockEntryInputs();
    if (live.error) { showMsg(live.error, 'error'); return; }
    if (!entries.some(function(x) { return _blockEntryKey(x) === _blockEntryKey(live); })) entries.push(live);
  }
  const allDates = entries.map(function(e) { return e.date; }).sort();
  const allDay = entries.length > 0 && entries[0].allDay;
  const startTime = entries.length > 0 ? entries[0].start : '';
  const endTime = entries.length > 0 ? entries[0].end : '';
  const reason = what.facilityId ? '' : document.getElementById('block_reason').value;
  const groupId = document.getElementById('editing_group_id').value;
  const applyToGroup = document.getElementById('apply_to_group').checked && groupId;
  const locationIds = what.locationIds;

  if (entries.length === 0) {
    showMsg('Select at least one date', 'error'); return;
  }

  // Multi-date edit path. Enters when either:
  //   (a) editing an existing multi-date group, or
  //   (b) editing a single-date block AND the user added more dates as chips.
  if (providerIds.length === 1 && blockId && (_editingBlockGroup || entries.length > 1)) {
    // Build the list of providers to operate on. By default, only the
    // editing provider. If the user checked "Apply to all" on a
    // multi-provider group, also include the sibling providers.
    var groupProviderIds = [providerIds[0]];
    if (applyToGroup && groupId) {
      _overviewData.forEach(function(p) {
        if (p.provider_id === providerIds[0]) return;
        var inGroup = (p.blocks || []).some(function(pb) { return pb.group_id === groupId; });
        if (inGroup) groupProviderIds.push(p.provider_id);
      });
    }
    // The block ids the fresh batch replaces, for every affected provider. One request
    // saves them all: the server checks every provider first and removes the old blocks
    // only once its checks pass, so a refused save leaves the group as it was.
    var replaceBlocks = [];
    for (const pid of groupProviderIds) {
      var blockIdsToDelete = [];
      if (groupId) {
        _overviewData.forEach(function(p) {
          if (p.provider_id !== pid) return;
          (p.blocks || []).forEach(function(pb) {
            if (pb.group_id === groupId) blockIdsToDelete.push(pb.id);
          });
        });
      } else if (pid === providerIds[0]) {
        blockIdsToDelete.push(blockId);
      }
      blockIdsToDelete.forEach(function(id) { replaceBlocks.push({ provider_id: pid, id: id }); });
    }
    const batchGroupId = _editingBlockGroup
      || groupId
      || (entries.length > 1 || groupProviderIds.length > 1 ? crypto.randomUUID() : null);
    const res = await _postBlockEntries(groupProviderIds, entries, reason, locationIds, batchGroupId, what.facilityId, { blocks: replaceBlocks });
    if (res.error) {
      // When this provider can be edited but another in the group can't, the fix is the
      // checkbox that leaves the others out; any other refusal shows the server's message.
      var editable = function(pid) {
        var row = _overviewData.find(function(p) { return String(p.provider_id) === String(pid); });
        return !row || row.can_edit !== false;
      };
      var siblingLocked = res.status === 403 && editable(groupProviderIds[0]) &&
        groupProviderIds.slice(1).some(function(pid) { return !editable(pid); });
      showMsg(siblingLocked ? 'You can’t edit every provider in this group. Clear the checkbox at the top to change only this provider.' : res.error, 'error');
      return;
    }
    showMsg(res.created + ' block(s) saved', 'success');
    _editingBlockGroup = null;
    _resetBlockEntries();
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  // Multi-date or all-day batch path: use new dates[] payload to fan out server-side.
  const isBatch = entries.length > 1 || allDay;
  if (isBatch && !blockId) {
    // One request for every provider and date, sharing one group id so the blocks
    // edit together later. Converting a recurring block replaces it in the same request.
    const newGroupId = providerIds.length > 1 || entries.length > 1 ? crypto.randomUUID() : null;
    const fromRecurring = document.getElementById('editing_recurring_block_id').value;
    if (fromRecurring && providerIds.length > 1) {
      showMsg('A recurring block can be changed to single events for one provider at a time', 'error');
      return;
    }
    const res = await _postBlockEntries(providerIds, entries, reason, locationIds, newGroupId, what.facilityId,
      { recurringBlockId: fromRecurring });
    if (res.error) { showMsg(res.error, 'error'); return; }
    _resetBlockEntries();
    showMsg(fromRecurring ? 'Block converted to single events' : res.created + ' block(s) created', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  // Single-date / single-provider edit path (unchanged behavior).
  // All-day end stays inside the same day (23:59:59) so the calendar event
  // doesn't span midnight, which Canvas renders awkwardly.
  const blockDate = allDates[0];
  const start = allDay
    ? blockDate + 'T00:00:00'
    : blockDate + 'T' + startTime + ':00';
  const end = allDay
    ? blockDate + 'T23:59:59'
    : blockDate + 'T' + endTime + ':00';

  if (blockId && providerIds.length === 1) {
    const body = {
      id: blockId,
      provider_id: providerIds[0],
      start: start,
      end: end,
      reason: reason,
      location_ids: locationIds,
      facility_id: what.facilityId,
      group_id: groupId || null,
      apply_to_group: !!applyToGroup,
      all_day: allDay,
    };
    const data = await apiCall('/blocks', { method: 'PUT', body: JSON.stringify(body) });
    if (data.error) { showMsg(data.error, 'error'); return; }
    showMsg(data.message || 'Block updated', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  // Converting from recurring block → single block (atomic: create + delete in one call)
  const recurringBlockId = document.getElementById('editing_recurring_block_id').value;
  if (recurringBlockId && providerIds.length === 1) {
    const createBody = {
      provider_id: providerIds[0],
      start: start,
      end: end,
      reason: reason,
      location_ids: locationIds,
      facility_id: what.facilityId,
      group_id: groupId || null,
      replace_recurring_block_id: recurringBlockId,
      all_day: allDay,
    };
    const createData = await apiCall('/blocks', { method: 'POST', body: JSON.stringify(createBody) });
    if (createData.error) { showMsg(createData.error, 'error'); return; }
    showMsg('Block converted to single event', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  const newGroupId = providerIds.length > 1 ? crypto.randomUUID() : null;
  let errors = [];
  let saved = 0;
  for (const pid of providerIds) {
    const body = {
      provider_id: pid,
      start: start,
      end: end,
      reason: reason,
      location_ids: locationIds,
      facility_id: what.facilityId,
      group_id: newGroupId,
      all_day: allDay,
    };
    const data = await apiCall('/blocks', { method: 'POST', body: JSON.stringify(body) });
    if (data.error) errors.push(data.error);
    else saved++;
  }
  if (errors.length > 0) showMsg(errors.join('; '), 'error');
  else {
    showMsg(saved === 1 ? 'Block created' : saved + ' blocks created', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
  }
}

/* ---------- Delete functions ---------- */

function confirmDeleteRule(providerId, ruleId) {
  showConfirm('Delete this availability rule?', () => doDeleteRule(providerId, ruleId));
}
async function doDeleteRule(providerId, ruleId) {
  const data = await apiCall('/rules/' + providerId + '/' + ruleId, { method: 'DELETE' });
  if (data.error) { showMsg(data.error, 'error'); return; }
  showMsg('Rule deleted', 'success');
  loadOverview();
}

function confirmDeleteBlock(providerId, blockId) {
  showConfirm('Delete this block?', () => doDeleteBlock(providerId, blockId));
}
async function doDeleteBlock(providerId, blockId) {
  const data = await apiCall('/blocks/' + providerId + '/' + blockId, { method: 'DELETE' });
  if (data.error) { showMsg(data.error, 'error'); return; }
  showMsg('Block deleted', 'success');
  loadOverview();
}

function confirmDeleteRecurringBlock(providerId, blockId) {
  showConfirm('Delete this recurring block?', () => doDeleteRecurringBlock(providerId, blockId));
}
async function doDeleteRecurringBlock(providerId, blockId) {
  const data = await apiCall('/recurring-blocks/' + providerId + '/' + blockId, { method: 'DELETE' });
  if (data.error) { showMsg(data.error, 'error'); return; }
  showMsg('Recurring block deleted', 'success');
  loadOverview();
}

function deleteRuleDays(providerId, ruleId, daysToRemove, ruleJsonStr) {
  var rule = JSON.parse(ruleJsonStr);
  var schedule = rule.weekly_schedule || {};
  var activeDays = Object.keys(schedule).filter(function(d) {
    return schedule[d] && schedule[d].length > 0;
  });

  var hasEnd = !!rule.effective_end;
  var isSingleDay = hasEnd && rule.effective_start === rule.effective_end;
  var isSingleEvent = isSingleDay && activeDays.length === 1 && schedule[activeDays[0]].length === 1;

  var msg = isSingleEvent
    ? 'Delete this availability event?'
    : 'This will delete the entire weekly schedule. To remove individual days, use Edit instead.';
  showConfirm(msg, function() { doDeleteRule(providerId, ruleId); });
}

function deleteRecurringBlockDays(providerId, blockId, daysToRemove, rbJsonStr) {
  var rb = JSON.parse(rbJsonStr);
  var schedule = rb.weekly_schedule || {};
  var activeDays = Object.keys(schedule).filter(function(d) {
    return schedule[d] && schedule[d].length > 0;
  });

  var hasEnd = !!rb.effective_end;
  var isSingleDay = hasEnd && rb.effective_start === rb.effective_end;
  var isSingleEvent = isSingleDay && activeDays.length === 1 && schedule[activeDays[0]].length === 1;

  var msg = isSingleEvent
    ? 'Delete this block?'
    : 'This will delete the entire weekly block. To remove individual days, use Edit instead.';
  showConfirm(msg, function() { doDeleteRecurringBlock(providerId, blockId); });
}

/* ---------- Apply to M-F / all days ---------- */

function _getScheduleData(editorId) {
  const isHold = editorId.startsWith('hold');
  const isRb = editorId.startsWith('recurring');
  const prefix = isHold ? 'hold-day-' : isRb ? 'rb-day-' : 'day-';
  let firstDayData = null;
  for (const day of DAYS) {
    const wraps = document.querySelectorAll('#' + prefix + day + ' .day-time-inputs');
    if (wraps.length > 0) {
      firstDayData = [];
      wraps.forEach(wrap => {
        const inputs = wrap.querySelectorAll('.time-input');
        if (inputs[0].value && inputs[1].value) {
          firstDayData.push({ start: inputs[0].value, end: inputs[1].value });
        }
      });
      break;
    }
  }
  return { firstDayData, isRb, prefix };
}

function applyToMF(editorId) {
  const { firstDayData, isRb, prefix } = _getScheduleData(editorId);
  if (!firstDayData || firstDayData.length === 0) { showMsg('Add hours to at least one day first', 'error'); return; }
  const mfDays = ['monday','tuesday','wednesday','thursday','friday'];
  if (prefix === 'hold-day-') {
    initHoldScheduleEditor();
    mfDays.forEach(day => { firstDayData.forEach(w => addHoldWindow(day, w.start, w.end)); });
  } else if (isRb) {
    initRecurringBlockScheduleEditor();
    mfDays.forEach(day => { firstDayData.forEach(w => addRecurringBlockWindow(day, w.start, w.end)); });
  } else {
    initScheduleEditor();
    mfDays.forEach(day => { firstDayData.forEach(w => addWindow(day, w.start, w.end)); });
  }
  _formDirty = true;
}

function applyToAll(editorId) {
  const { firstDayData, isRb, prefix } = _getScheduleData(editorId);
  if (!firstDayData || firstDayData.length === 0) { showMsg('Add hours to at least one day first', 'error'); return; }
  if (prefix === 'hold-day-') {
    initHoldScheduleEditor();
    DAYS.forEach(day => { firstDayData.forEach(w => addHoldWindow(day, w.start, w.end)); });
  } else if (isRb) {
    initRecurringBlockScheduleEditor();
    DAYS.forEach(day => { firstDayData.forEach(w => addRecurringBlockWindow(day, w.start, w.end)); });
  } else {
    initScheduleEditor();
    DAYS.forEach(day => { firstDayData.forEach(w => addWindow(day, w.start, w.end)); });
  }
  _formDirty = true;
}

/* ---------- Timezone ---------- */

let _practiceTz = 'UTC';

function updateTzHints() {
  ['schedule-tz-hint', 'block-schedule-tz-hint'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

function updateEditorTzConversionHint() {
  // No-op: timezone selector removed; always use provider's timezone
}

async function loadTimezone() {
  // A failed or empty response (expired session, form fallback mode) keeps the
  // last known values, so the page never quietly switches the practice to UTC.
  try {
    const data = await apiCall('/timezone');
    if (data && data.timezone) _practiceTz = data.timezone;
    if (data && data.available && data.available.length) _tzOptions = data.available;
  } catch (e) {}

  updateTzHints();
  updateEditorTzLabels();
}

function updateEditorTzLabels() {
  var icon = '<svg style="width:13px;height:13px;vertical-align:-2px;margin-right:3px;" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
  var selectedPids = (msProvider ? msProvider.getValue() : []).concat(msBlockProvider ? msBlockProvider.getValue() : []).concat(msHoldProvider ? msHoldProvider.getValue() : []);
  var editorProvTz = selectedPids.length === 1 ? providerTz(selectedPids[0]) : _practiceTz;
  var hint = icon + 'Times are in the provider\u2019s timezone, <strong>' + editorProvTz + '</strong>.';
  ['single-event-tz-hint', 'block-event-tz-hint', 'weekly-avail-tz-hint', 'weekly-block-tz-hint', 'weekly-hold-tz-hint'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = hint;
  });
}

function getEditorTimezone() {
  return null;  // Always use provider's timezone
}


/* ---------- Schedulable roles ---------- */

function _roleItems(available) {
  return (available || []).map(function(r) {
    var hint = [r.name ? r.code : '', r.staff_count ? r.staff_count + ' staff' : ''].filter(Boolean).join(' \u00b7 ');
    return { code: r.code, name: r.name || r.code, hint: hint, chipHint: r.name ? r.code : '' };
  });
}

async function loadSchedulableRoles() {
  if (!msSchedulableRoles) return;
  var data = await apiCall('/roles');
  if (!data || data.error) {
    showMsg((data && data.error) || 'Could not load roles', 'error');
    return;
  }
  var configured = (data.schedulable_roles || []).map(function(c) { return String(c).toUpperCase(); });
  var items = _roleItems(data.available);
  // Keep any configured code no active staff currently hold, so it isn't dropped.
  configured.forEach(function(code) {
    if (!items.some(function(i) { return String(i.code).toUpperCase() === code; })) {
      items.push({ code: code, name: code, hint: 'No active staff', chipHint: '' });
    }
  });
  msSchedulableRoles.setItems(items);
  msSchedulableRoles.setValue(configured);
  _showRolesFallbackNote(data.fallback_active);
}

function _showRolesFallbackNote(active) {
  var note = document.getElementById('roles-fallback-note');
  if (note) note.style.display = active ? 'block' : 'none';
}

// After a save the picker already shows what was saved, so only the note needs
// refreshing. The picker is left alone: a reload landing after the user's next
// pick would silently undo it. A failed refresh says nothing, because the save
// itself succeeded.
async function _refreshRolesFallbackNote() {
  try {
    var data = await apiCall('/roles');
    if (data && !data.error) _showRolesFallbackNote(data.fallback_active);
  } catch (e) {}
}

async function saveSchedulableRoles() {
  if (!msSchedulableRoles) return;
  var codes = msSchedulableRoles.getValue();
  var data = await apiCall('/roles', { method: 'PUT', body: JSON.stringify({ schedulable_roles: codes }) });
  if (data && data.error) { showMsg(data.error, 'error'); return; }
  _settingsDirty = false;
  showMsg('Schedulable roles saved', 'success');
  // Re-check so the "no active staff hold these roles" note matches what was saved.
  _refreshRolesFallbackNote();
  // Reflect the change immediately — refresh the provider pickers without a page reload.
  await loadProviders();
}


/* ---------- Settings panel ---------- */

async function renderSettingsPanel() {
  // Load the schedulable-role checklist, unless the user has picks they have
  // not saved yet (a timezone save also re-renders this panel).
  if (!_settingsDirty) loadSchedulableRoles();

  // Refresh the practice timezone so the bulk selector reflects the saved value.
  await loadTimezone();

  // Populate bulk TZ dropdown
  var bulkSel = document.getElementById('bulk-tz-select');
  if (bulkSel && bulkSel.options.length === 0) {
    COMMON_TZS.forEach(function(tz) {
      var opt = document.createElement('option');
      opt.value = tz;
      opt.textContent = tz;
      bulkSel.appendChild(opt);
    });
  }
  // Reflect the current practice timezone (defaults to UTC), not the first option.
  if (bulkSel) bulkSel.value = _practiceTz;

  // Ensure we have provider data
  if (_providers.length === 0) {
    try {
      var data = await apiCall('/providers/list');
      _providers = data.providers || [];
    } catch (e) { _providers = []; }
  }
  // Fetch authoritative TZ data from backend
  try {
    var tzData = await apiCall('/provider-timezones/all');
    var serverTzs = tzData.timezones || {};
    // The server's list is the whole truth: anyone missing from it uses the practice timezone.
    Object.keys(_providerTzMap).forEach(function(pid) {
      if (!serverTzs[pid]) _providerTzMap[pid] = { timezone: _practiceTz, explicit: false };
    });
    Object.keys(serverTzs).forEach(function(pid) {
      _providerTzMap[pid] = { timezone: serverTzs[pid], explicit: true };
    });
  } catch (e) {}

  var body = document.getElementById('pv-rows');
  if (!body) return;

  if (_providers.length === 0) {
    body.innerHTML = '<tr class="pv-none"><td colspan="3">No providers found</td></tr>';
    filterProviderRows();
    return;
  }

  var sortedProviders = _providers.slice().sort(function(a, b) {
    var aLast = (a.name || '').split(' ').slice(-1)[0].toLowerCase();
    var bLast = (b.name || '').split(' ').slice(-1)[0].toLowerCase();
    return aLast.localeCompare(bLast);
  });

  // One row per provider: timezone and facilities. A provider on the practice timezone reads gray.
  var html = '';
  sortedProviders.forEach(function(p) {
    var entry = _providerTzMap[p.id];
    var isExplicit = entry && entry.explicit;
    var currentTz = isExplicit ? entry.timezone : '';
    html += '<tr data-name="' + _escHtml((p.name || '').toLowerCase()) + '">';
    html += '<td>' + _escHtml(p.name || p.id) + '</td>';
    html += '<td class="tz-col"><select class="input provider-tz-dropdown' + (currentTz ? '' : ' tz-follows') + '" data-provider-id="' + _escHtml(p.id) + '" onchange="saveProviderTz(this)">';
    html += '<option value=""' + (!currentTz ? ' selected' : '') + '>Practice timezone</option>';
    COMMON_TZS.forEach(function(tz) {
      html += '<option value="' + tz + '"' + (tz === currentTz ? ' selected' : '') + '>' + tz + '</option>';
    });
    html += '</select></td>';
    html += '<td class="pf-col round-only"><div id="pf-pick-' + _escHtml(p.id) + '"></div></td>';
    html += '</tr>';
  });
  // The provider facility pickers save open picks before their rows are replaced (settings.js).
  if (window.paFlushProviderPickers) window.paFlushProviderPickers();
  body.innerHTML = html + '<tr class="pv-none" style="display:none"><td colspan="3">No providers match.</td></tr>';
  if (window.paDrawProviderFacilities) window.paDrawProviderFacilities();
  filterProviderRows();
}

// Settings › Providers search: narrows the rows and keeps the count current.
function filterProviderRows() {
  var body = document.getElementById('pv-rows');
  var input = document.getElementById('pv-search');
  var count = document.getElementById('pv-count');
  if (!body || !input || !count) return;
  var q = input.value.trim().toLowerCase();
  var rows = body.querySelectorAll('tr[data-name]');
  var shown = 0;
  rows.forEach(function(r) { var on = !q || r.dataset.name.indexOf(q) >= 0; r.style.display = on ? '' : 'none'; if (on) shown++; });
  var none = body.querySelector('tr.pv-none');
  if (none && rows.length) none.style.display = shown ? 'none' : '';
  count.textContent = rows.length ? (q ? shown + ' of ' + rows.length + ' providers' : rows.length + ' providers') : '';
}

async function saveProviderTz(selectEl) {
  var pid = selectEl.getAttribute('data-provider-id');
  var tz = selectEl.value;
  var data;
  if (!tz) {
    // "Practice default" selected — clear the explicit override.
    data = await apiCall('/provider-timezone/' + pid, { method: 'DELETE' });
  } else {
    data = await apiCall('/provider-timezone', {
      method: 'PUT',
      body: JSON.stringify({ provider_id: pid, timezone: tz }),
    });
  }
  if (data.error) {
    showMsg(data.error, 'error');
  } else {
    showMsg(data.message || 'Timezone updated', 'success');
    // Update local TZ map directly — no overview dependency
    if (tz) {
      _providerTzMap[pid] = { timezone: tz, explicit: true };
    } else {
      delete _providerTzMap[pid];
    }
    // Also refresh overview for accordion display
    try {
      var ovData = await apiCall('/overview');
      _overviewData = ovData.providers || [];
      _syncProviderTzMapFromOverview();
    } catch (e) {}
    renderSettingsPanel();
  }
}

// The practice timezone dropdown saves on change. Providers who use the practice
// timezone move with it; providers with their own timezone keep theirs.
async function savePracticeTimezone() {
  var sel = document.getElementById('bulk-tz-select');
  if (!sel || !sel.value || sel.value === _practiceTz) return;
  if (!confirm('Set the practice timezone to ' + sel.value + '? Providers who use the practice timezone move with it.')) {
    sel.value = _practiceTz;
    return;
  }
  await _putPracticeTimezone(sel.value, false);
}

// Apply to all: every provider uses the practice timezone, and their own timezones are cleared.
async function applyBulkTimezone() {
  var sel = document.getElementById('bulk-tz-select');
  if (!sel || !sel.value) return;
  if (!confirm('Use ' + sel.value + ' for all providers? Each provider\'s own timezone is cleared.')) return;
  await _putPracticeTimezone(sel.value, true);
}

async function _putPracticeTimezone(tz, applyToAll) {
  var data = await apiCall('/timezone', {
    method: 'PUT',
    body: JSON.stringify({ timezone: tz, apply_to_all: applyToAll }),
  });
  var sel = document.getElementById('bulk-tz-select');
  if (!data || data.error) {
    showMsg((data && data.error) || 'The timezone was not saved.', 'error');
    if (sel) sel.value = _practiceTz;
    return;
  }
  showMsg(data.message || 'Timezone updated', 'success');
  _practiceTz = data.timezone;
  if (applyToAll) _providerTzMap = {};
  try {
    var ovData = await apiCall('/overview');
    _overviewData = ovData.providers || [];
    _syncProviderTzMapFromOverview();
  } catch (e) {}
  renderSettingsPanel();
}

/* ---------- Holds ---------- */

function editHold(holdJson) {
  var h = JSON.parse(holdJson);
  resetForm();
  selectType('hold');
  document.getElementById('type-selector-section').style.display = 'none';
  _skipDirtyCheck = true;
  showTab('editor');
  document.getElementById('editor-title').textContent = 'Edit hold';
  document.getElementById('editing_hold_id').value = h.id || '';
  document.getElementById('editing_hold_group_id').value = h.group_id || '';
  document.getElementById('hold_reason').value = h.reason || '';
  setHoldType(h.hold_type || 'same_day');
  document.getElementById('hold_effective_start').value = h.effective_start || '';
  document.getElementById('hold_effective_end').value = h.effective_end || '';
  syncDateFacade('hold_effective_start');
  syncDateFacade('hold_effective_end');
  msHoldProvider.setValue([h.provider_id]);
  msHoldLocation.setValue(h.location_ids || []);
  initHoldScheduleEditor();
  DAYS.forEach(function(day) {
    ((h.weekly_schedule || {})[day] || []).forEach(function(w) { addHoldWindow(day, w.start, w.end); });
  });
}

async function saveHold() {
  var providerIds = msHoldProvider.getValue();
  if (providerIds.length === 0) { showMsg('Please select at least one provider', 'error'); return; }

  var holdType = document.getElementById('hold_type_select').value;
  var reason = document.getElementById('hold_reason').value;
  var effectiveStart = document.getElementById('hold_effective_start').value || null;
  var effectiveEnd = document.getElementById('hold_effective_end').value || null;
  if (!effectiveStart) { showMsg('Start date is required', 'error'); return; }
  var locationIds = msHoldLocation.getValue();

  // Gather schedule from hold-day-* inputs
  var schedule = {};
  var hasValidationError = false;
  DAYS.forEach(function(day) {
    var wraps = document.querySelectorAll('#hold-day-' + day + ' .day-time-inputs');
    if (wraps.length > 0) {
      schedule[day] = [];
      wraps.forEach(function(wrap) {
        var inputs = wrap.querySelectorAll('.time-input');
        if (inputs[0].value && inputs[1].value) {
          if (inputs[0].value >= inputs[1].value) {
            showMsg('Start time must be before end time (' + DAY_ABBR[day] + ': ' + inputs[0].value + ' >= ' + inputs[1].value + ')', 'error');
            hasValidationError = true;
            return;
          }
          schedule[day].push({ start: inputs[0].value, end: inputs[1].value });
        }
      });
    }
  });
  if (hasValidationError) return;
  if (Object.keys(schedule).length === 0) { showMsg('Please add at least one time window', 'error'); return; }

  var editingId = document.getElementById('editing_hold_id').value;
  var groupId = document.getElementById('editing_hold_group_id').value;

  if (editingId && providerIds.length === 1) {
    var body = {
      id: editingId,
      provider_id: providerIds[0],
      weekly_schedule: schedule,
      reason: reason,
      location_ids: locationIds,
      effective_start: effectiveStart,
      effective_end: effectiveEnd,
      is_active: true,
      hold_type: holdType,
      timezone: getEditorTimezone(),
      group_id: groupId || null,
      apply_to_group: false,
    };
    var data = await apiCall('/recurring-blocks', { method: 'PUT', body: JSON.stringify(body) });
    if (data.error) { showMsg(data.error, 'error'); return; }
    showMsg(data.message || 'Hold updated', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  var newGroupId = providerIds.length > 1 ? crypto.randomUUID() : null;
  var errors = [];
  var saved = 0;
  for (var i = 0; i < providerIds.length; i++) {
    var pid = providerIds[i];
    var body = {
      provider_id: pid,
      weekly_schedule: schedule,
      reason: reason,
      location_ids: locationIds,
      effective_start: effectiveStart,
      effective_end: effectiveEnd,
      is_active: true,
      hold_type: holdType,
      timezone: getEditorTimezone(),
      group_id: newGroupId,
    };
    var data = await apiCall('/recurring-blocks', { method: 'POST', body: JSON.stringify(body) });
    if (data.error) errors.push(data.error);
    else saved++;
  }

  if (errors.length > 0) {
    showMsg(errors.join('; '), 'error');
  } else {
    showMsg(saved === 1 ? 'Hold created' : saved + ' holds created', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
  }
}

function deleteHold(providerId, holdId) {
  showConfirm('Delete this hold?', function() {
    doDeleteRecurringBlock(providerId, holdId).then(function() {
      loadOverview();
    });
  });
}

function initHoldScheduleEditor() {
  var html = '';
  DAYS.forEach(function(day) {
    html += '<div id="hold-day-wrap-' + day + '">';
    html += '<div class="day-header collapsed" onclick="toggleDayCollapse(this)">';
    html += '<span class="day-label">' + DAY_FULL[day] + '</span>';
    html += '<span class="day-summary" id="hold-day-summary-' + day + '">No hours</span>';
    html += '<svg class="day-chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M19 9l-7 7-7-7"/></svg>';
    html += '</div>';
    html += '<div class="day-body hidden" id="hold-day-' + day + '">';
    html += '<button type="button" class="add-time-btn" onclick="addHoldWindow(\'' + day + '\')">';
    html += SVG_PLUS + 'Add hours</button>';
    html += '</div>';
    html += '</div>';
  });
  document.getElementById('hold-schedule-editor').innerHTML = html;
}

function addHoldWindow(day, startVal, endVal) {
  var row = document.getElementById('hold-day-' + day);
  var btn = row.querySelector('.add-time-btn');
  var group = document.createElement('div');
  group.style.display = 'flex';
  group.style.alignItems = 'center';
  group.style.gap = '8px';
  group.style.flex = '1';
  var wrap = document.createElement('div');
  wrap.className = 'day-time-inputs';
  wrap.innerHTML = timeFieldHtml(startVal) +
    '<span class="time-sep">\u2013</span>' +
    timeFieldHtml(endVal);
  var rmv = document.createElement('button');
  rmv.type = 'button';
  rmv.className = 'remove-time';
  rmv.innerHTML = SVG_X_SM;
  rmv.onclick = function() {
    group.remove();
    var header = document.getElementById('hold-day-wrap-' + day);
    if (header) {
      var h = header.querySelector('.day-header');
      if (!row.querySelector('.day-time-inputs') && h) h.classList.remove('has-block');
    }
    updateDaySummary(day, 'hold-');
  };
  group.appendChild(wrap);
  group.appendChild(rmv);
  row.insertBefore(group, btn);
  var wrapEl = document.getElementById('hold-day-wrap-' + day);
  if (wrapEl) {
    var h = wrapEl.querySelector('.day-header');
    if (h) { h.classList.add('has-block'); h.classList.remove('collapsed'); }
  }
  row.classList.remove('hidden');
  updateDaySummary(day, 'hold-');
}

/* ---------- Form dirty tracking ---------- */

document.addEventListener('input', function(e) {
  const edPanel = document.getElementById('panel-editor');
  if (edPanel && edPanel.contains(e.target)) {
    _formDirty = true;
  }
  // Sync date facades on change
  if (e.target.id === 'effective_start') syncDateFacade('effective_start');
  if (e.target.id === 'effective_end') syncDateFacade('effective_end');
  if (e.target.id === 'rb_effective_start') syncDateFacade('rb_effective_start');
  if (e.target.id === 'rb_effective_end') syncDateFacade('rb_effective_end');
  if (e.target.id === 'block_date') syncDateFacade('block_date');
  if (e.target.id === 'override_date') syncDateFacade('override_date');
  if (e.target.id === 'single_date') syncDateFacade('single_date');
  if (e.target.id === 'hold_effective_start') syncDateFacade('hold_effective_start');
  if (e.target.id === 'hold_effective_end') syncDateFacade('hold_effective_end');
});

/* ---------- Facility rounds ---------- */

// Active facilities and each provider's saved facilities, sent with the page
// (AvailabilityAPI._round_facilities) and kept current by settings.js.
function paFacilities() {
  var f = (window.__PRELOADED__ && window.__PRELOADED__.facilities) || {};
  return { facilities: f.facilities || [], by_provider: f.by_provider || {} };
}

function facilityName(id) {
  var hit = paFacilities().facilities.find(function(f) { return String(f.id) === String(id); });
  return hit ? hit.name : '';
}

// A searchable facility picker. Single mode picks one facility; multi mode picks
// many, shows up to 3 chips, and a one-line summary beyond that. groups() returns
// [[label, items]], items being {id, name, count?}, most likely facilities first.
// Pickers share one set of page listeners, which act on the open ones only, so a
// picker whose row is redrawn away leaves nothing behind.
var _fpOpenPickers = new Set();
document.addEventListener('mousedown', function(e) {
  // Check the event's path, not root.contains(): selecting an option redraws the list, so the
  // tapped element is already detached by the time this runs and would read as "outside".
  var path = e.composedPath();
  Array.from(_fpOpenPickers).forEach(function(p) { if (path.indexOf(p.root) < 0) p.close(); });
});
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') Array.from(_fpOpenPickers).forEach(function(p) { p.close(); });
});
window.addEventListener('scroll', function() { _fpOpenPickers.forEach(function(p) { p.place(); }); }, true);
window.addEventListener('resize', function() { _fpOpenPickers.forEach(function(p) { p.place(); }); });

function FacilityPicker(hostId, opts) {
  var host = document.getElementById(hostId);
  var selected = [];
  var query = '';
  var shown = null;
  host.innerHTML = '<div class="fp"><div class="fp-control"></div><div class="fp-list"></div></div>';
  var root = host.firstChild;
  var control = root.querySelector('.fp-control');
  var list = root.querySelector('.fp-list');

  function nameOf(id) {
    var hit = opts.all().find(function(f) { return String(f.id) === String(id); });
    return hit ? hit.name : '';
  }

  function changed() { if (opts.onChange) opts.onChange(selected.slice()); }

  function drawControl() {
    var isOpen = root.classList.contains('open');
    var html = '';
    if (opts.single) {
      html = selected[0] && !isOpen ? '<span class="fp-single-val">' + _escHtml(nameOf(selected[0])) + '</span>' : '';
    } else if (!isOpen && selected.length > 3) {
      html = '<span class="fp-summary"><b>' + selected.length + ' facilities:</b> ' + _escHtml(nameOf(selected[0])) + ', ' +
        _escHtml(nameOf(selected[1])) + ' + ' + (selected.length - 2) + ' more</span>';
    } else if (!isOpen) {
      html = selected.map(function(id) {
        return '<span class="ms-chip">' + _escHtml(nameOf(id)) + ' <span class="ms-chip-remove" data-rm="' + _escHtml(id) + '">&times;</span></span>';
      }).join('');
    }
    var showInput = isOpen || (opts.single ? !selected[0] : selected.length <= 3);
    control.innerHTML = html + (showInput ? '<input placeholder="Search facilities..." value="' + _escHtml(query) + '">' : '');
    var input = control.querySelector('input');
    if (input) input.oninput = function() { query = this.value; drawList(); };
    control.querySelectorAll('[data-rm]').forEach(function(x) {
      x.onclick = function(e) {
        e.stopPropagation();
        selected.splice(selected.indexOf(x.dataset.rm), 1);
        drawControl();
        changed();
        // The list is closed, so this is a finished change.
        if (opts.onClose) opts.onClose(selected.slice());
      };
    });
  }

  function drawList() {
    var q = query.trim().toLowerCase();
    var gs = opts.groups();
    if (!opts.single) {
      // Checked facilities move to Selected right away, like the other pickers.
      gs = gs.map(function(g) { return [g[0], g[1].filter(function(i) { return selected.indexOf(String(i.id)) < 0; })]; });
      gs.unshift(['Selected (' + selected.length + ')', selected.map(function(id) { return { id: id, name: nameOf(id) }; }), true]);
    }
    var html = '';
    gs.forEach(function(g) {
      var items = g[1].filter(function(i) { return !q || i.name.toLowerCase().indexOf(q) >= 0; });
      if (!items.length) return;
      html += '<div class="fp-group">' + _escHtml(g[0]) + (g[2] ? '<button type="button" class="fp-clear" data-clear>Clear</button>' : '') + '</div>' +
        items.map(function(i) {
          var on = selected.indexOf(String(i.id)) >= 0;
          return '<div class="fp-opt' + (on ? ' sel' : '') + '" data-id="' + _escHtml(i.id) + '">' +
            (opts.single ? '' : '<input type="checkbox"' + (on ? ' checked' : '') + '>') + _escHtml(i.name) +
            (i.count ? '<span class="fp-count">' + _escHtml(i.count) + '</span>' : '') + '</div>';
        }).join('');
    });
    list.innerHTML = html || '<div class="fp-empty">No facilities match.</div>';
    list.querySelectorAll('.fp-opt').forEach(function(o) {
      o.onmousedown = function(e) {
        e.preventDefault();
        var id = o.dataset.id;
        if (opts.single) { selected = [id]; query = ''; close(); changed(); return; }
        var k = selected.indexOf(id);
        if (k < 0) selected.push(id); else selected.splice(k, 1);
        drawList();
        changed();
      };
    });
    var clr = list.querySelector('[data-clear]');
    if (clr) clr.onmousedown = function(e) { e.preventDefault(); selected = []; drawList(); changed(); };
  }

  // The list floats over the page, so a scrolling container (Settings › Providers) can't cut it off.
  function place() {
    if (!root.classList.contains('open')) return;
    var r = control.getBoundingClientRect(), room = window.innerHeight - r.bottom;
    list.style.position = 'fixed'; list.style.left = r.left + 'px'; list.style.width = r.width + 'px'; list.style.right = 'auto';
    if (room < 300 && r.top > room) { list.style.top = 'auto'; list.style.bottom = (window.innerHeight - r.top + 4) + 'px'; }
    else { list.style.bottom = 'auto'; list.style.top = (r.bottom + 4) + 'px'; }
  }
  var self = { root: root, close: close, place: place };

  function open() {
    if (root.classList.contains('open') || root.classList.contains('fp-locked')) return;
    shown = selected.slice();
    root.classList.add('open');
    _fpOpenPickers.add(self);
    drawControl();
    drawList();
    place();
    var i = control.querySelector('input');
    if (i) i.focus();
    if (opts.onOpen) opts.onOpen();
  }
  function close() {
    var before = shown;
    _fpOpenPickers.delete(self);
    root.classList.remove('open');
    query = '';
    shown = null;
    drawControl();
    var changedNow = before && before.join('|') !== selected.join('|');
    // A picker redrawn off the page (Settings rebuilds its rows) saves nothing: the new
    // picker in its place shows the saved list, and an old selection would overwrite it.
    if (changedNow && opts.onClose && !root.isConnected) { showMsg('Facilities weren’t saved. Select them again.', 'error'); return; }
    if (changedNow && opts.onClose) opts.onClose(selected.slice());
  }
  control.onclick = open;
  drawControl();

  return {
    getValue: function() { return selected.slice(); },
    setValue: function(ids) { selected = (ids || []).map(String); drawControl(); if (root.classList.contains('open')) drawList(); },
    // A saved round keeps its facility while rounds are switched off.
    setLocked: function(locked) { root.classList.toggle('fp-locked', !!locked); },
    // Close the list if it's open, which saves a changed selection (onClose).
    closeIfOpen: function() { if (root.classList.contains('open')) close(); },
    isOpen: function() { return root.classList.contains('open'); },
    // What was selected when the list opened, or null while it's closed.
    openedWith: function() { return shown ? shown.slice() : null; },
    // Redraw after the groups' data arrives.
    redraw: function() { if (root.classList.contains('open')) drawList(); else drawControl(); },
  };
}

var _roundWhere = 'clinic';
var fpRoundFacility = null;
// The edited round's own facility, so its name shows even when it isn't in the list
// (made inactive since, or rounds switched off).
var _editingRoundFacility = null;

function _roundFacilityItems() { return _facilityItemsWith(_editingRoundFacility); }

// A form's Facility list, plus the edited item's own facility when it isn't listed.
function _facilityItemsWith(own) {
  var list = paFacilities().facilities;
  if (own && !list.some(function(f) { return String(f.id) === String(own.id); })) return list.concat([own]);
  return list;
}

// The round form's Facility list: the selected providers' facilities first, then the rest.
function _roundFacilityGroups() { return _facilityGroupsFor(msProvider); }

// A Facility list for a form: its selected providers' facilities first, then the rest.
function _facilityGroupsFor(ms) {
  var data = paFacilities();
  var mine = [];
  (ms ? ms.getValue() : []).forEach(function(pid) {
    (data.by_provider[pid] || []).forEach(function(id) { if (mine.indexOf(String(id)) < 0) mine.push(String(id)); });
  });
  var mineItems = mine.map(function(id) { return { id: id, name: facilityName(id) }; }).filter(function(i) { return i.name; });
  var rest = data.facilities.filter(function(f) { return mine.indexOf(String(f.id)) < 0; });
  if (!mineItems.length) return [['All facilities', rest]];
  var label = ms.getValue().length === 1 ? 'Provider’s facilities' : 'Providers’ facilities';
  return [[label, mineItems], ['All facilities', rest]];
}

function _updateRoundFacilityHint() { _updateFacilityHint('round-facility-hint', msProvider); }

function _updateFacilityHint(hintId, ms) {
  var hint = document.getElementById(hintId);
  if (!hint) return;
  var ids = ms ? ms.getValue() : [];
  var names = _providers.filter(function(p) { return ids.indexOf(String(p.id)) >= 0; }).map(function(p) { return p.name; });
  var lead = names.length === 1 ? _escHtml(names[0]) + '’s facilities are' : 'Each provider’s facilities are';
  hint.innerHTML = lead + ' listed first. Set them in <b>Settings</b> › <b>Providers</b>.';
}

// Clinic availability books at the chosen locations. A facility round books at the
// provider's primary location, and its visits are labeled with the facility.
function setRoundWhere(where) {
  _roundWhere = where === 'facility' ? 'facility' : 'clinic';
  var fac = _roundWhere === 'facility';
  document.getElementById('where-clinic').classList.toggle('active', !fac);
  document.getElementById('where-facility').classList.toggle('active', fac);
  document.querySelectorAll('.where-facility-only').forEach(function(e) { e.style.display = fac ? '' : 'none'; });
  document.querySelectorAll('.where-clinic-only').forEach(function(e) { e.style.display = fac ? 'none' : ''; });
  document.getElementById('where-hint').textContent = fac
    ? 'A facility round: visits booked in it are labeled with the facility.'
    : 'Bookable hours at one or more clinic locations.';
  document.getElementById('who-label').textContent = paFeatureOn('facility_rounds') || fac ? 'Who and where' : 'Who';
  _updateRoundFacilityHint();
}

function resetRoundFields() {
  _editingRoundFacility = null;
  if (fpRoundFacility) { fpRoundFacility.setValue([]); fpRoundFacility.setLocked(false); }
  document.getElementById('round_max_visits').value = '';
  document.getElementById('where-row').classList.remove('round-locked');
  setRoundWhere('clinic');
}

function fillRoundFields(r) {
  if (!r.facility_id) return;
  _editingRoundFacility = { id: String(r.facility_id), name: r.facility_name || '' };
  setRoundWhere('facility');
  fpRoundFacility.setValue([r.facility_id]);
  document.getElementById('round_max_visits').value = r.max_visits ? String(r.max_visits) : '';
  // Editing a round can't turn it into clinic hours or move it while rounds are off.
  document.getElementById('where-row').classList.add('round-locked');
  fpRoundFacility.setLocked(!paFeatureOn('facility_rounds'));
}

// The round fields for the save payload, or an error message.
function readRoundFields() {
  if (_roundWhere !== 'facility') return { fields: { facility_id: '', max_visits: null } };
  var facilityId = fpRoundFacility.getValue()[0] || '';
  if (!facilityId) return { error: 'Choose a facility for this round' };
  var raw = document.getElementById('round_max_visits').value.trim();
  var maxVisits = raw ? parseInt(raw, 10) : null;
  if (raw && !(maxVisits >= 1)) return { error: 'Visits per round must be a whole number of 1 or more' };
  return { fields: { facility_id: facilityId, max_visits: maxVisits, location_ids: [] } };
}

// Blocked: time off, or a facility block. A facility block is the provider at a
// facility: not bookable, and shown on Canvas's schedule as the facility's block.
var _blockWhat = 'off';
var fpBlockFacility = null;
var _editingBlockFacility = null;

function _blockFacilityItems() { return _facilityItemsWith(_editingBlockFacility); }

function setBlockWhat(what) {
  _blockWhat = what === 'facility' ? 'facility' : 'off';
  var fac = _blockWhat === 'facility';
  document.getElementById('block-what-off').classList.toggle('active', !fac);
  document.getElementById('block-what-facility').classList.toggle('active', fac);
  document.querySelectorAll('.block-facility-only').forEach(function(e) { e.style.display = fac ? '' : 'none'; });
  document.querySelectorAll('.block-off-only').forEach(function(e) { e.style.display = fac ? 'none' : ''; });
  document.getElementById('block-what-hint').textContent = fac
    ? 'The provider is at the facility and can’t be booked. It shows on the schedule with the facility’s name, and selecting it lists the facility’s patients.'
    : 'Time the provider can’t be booked.';
  document.getElementById('block-who-label').textContent = paFeatureOn('facility_blocks') || fac ? 'Who and where' : 'Who';
  _updateFacilityHint('block-facility-hint', msBlockProvider);
  _renderBlockEntries();
}

function resetBlockWhat() {
  _editingBlockFacility = null;
  if (fpBlockFacility) { fpBlockFacility.setValue([]); fpBlockFacility.setLocked(false); }
  document.getElementById('block-what-row').classList.remove('round-locked');
  setBlockWhat('off');
}

function fillBlockWhat(b) {
  if (!b.facility_id) return;
  _editingBlockFacility = { id: String(b.facility_id), name: b.facility_name || '' };
  setBlockWhat('facility');
  fpBlockFacility.setValue([b.facility_id]);
  // Editing a facility block can't turn it into time off, or move it while facility blocks are off.
  document.getElementById('block-what-row').classList.add('round-locked');
  fpBlockFacility.setLocked(!paFeatureOn('facility_blocks'));
}

// The facility fields for a block's save payload, or an error message.
function readBlockWhat() {
  if (_blockWhat !== 'facility') return { facilityId: '', locationIds: msBlockLocation.getValue() };
  var facilityId = fpBlockFacility.getValue()[0] || '';
  if (!facilityId) return { error: 'Choose a facility for this block' };
  return { facilityId: facilityId, locationIds: [] };
}

/* ---------- Initialize ---------- */

msProvider = new MultiSelect('ms-provider', { placeholder: 'Search providers...', displayKey: 'name', valueKey: 'id', summaryNoun: 'providers' });
msLocation = new MultiSelect('ms-location', { placeholder: 'Search locations...', displayKey: 'name', valueKey: 'id', summaryNoun: 'locations' });
msVisitType = new MultiSelect('ms-visit-type', { placeholder: 'Search visit types...', displayKey: 'name', valueKey: 'id', summaryNoun: 'visit types' });
msBlockProvider = new MultiSelect('ms-block-provider', { placeholder: 'Search providers...', displayKey: 'name', valueKey: 'id', summaryNoun: 'providers' });
msBlockLocation = new MultiSelect('ms-block-location', { placeholder: 'Search locations...', displayKey: 'name', valueKey: 'id', summaryNoun: 'locations' });
msHoldProvider = new MultiSelect('ms-hold-provider', { placeholder: 'Search providers...', displayKey: 'name', valueKey: 'id', summaryNoun: 'providers' });
msHoldLocation = new MultiSelect('ms-hold-location', { placeholder: 'Search locations...', displayKey: 'name', valueKey: 'id', summaryNoun: 'locations' });
msFilterProvider = new MultiSelect('ms-filter-provider', { placeholder: 'Filter by provider...', displayKey: 'name', valueKey: 'id', summaryNoun: 'providers', startAll: true });
msSchedulableRoles = new MultiSelect('ms-schedulable-roles', { placeholder: 'Search roles...', displayKey: 'name', valueKey: 'code', hintKey: 'hint', chipHintKey: 'chipHint' });

buildTimeOptions();

// Template-defined time fields (Single Event / Blocked start & end)
initTimeField('single_start_time_wrap', 'single_start_time');
initTimeField('single_end_time_wrap', 'single_end_time');
initTimeField('block_start_time_wrap', 'block_start_time');
initTimeField('block_end_time_wrap', 'block_end_time');

// Re-render accordion whenever filter MultiSelect changes
const _origUpdateChips = msFilterProvider.updateChips.bind(msFilterProvider);
msFilterProvider.updateChips = function() { _origUpdateChips(); renderAccordion(); };

// Update editor TZ labels when provider selection changes
var _origProvChips = msProvider.updateChips.bind(msProvider);
msProvider.updateChips = function() { _origProvChips(); updateEditorTzLabels(); _updateRoundFacilityHint(); };
var _origBlockProvChips = msBlockProvider.updateChips.bind(msBlockProvider);
msBlockProvider.updateChips = function() { _origBlockProvChips(); updateEditorTzLabels(); _updateFacilityHint('block-facility-hint', msBlockProvider); };
var _origHoldProvChips = msHoldProvider.updateChips.bind(msHoldProvider);
msHoldProvider.updateChips = function() { _origHoldProvChips(); updateEditorTzLabels(); };

initScheduleEditor();
initRecurringBlockScheduleEditor();
initHoldScheduleEditor();

fpRoundFacility = FacilityPicker('fp-round-facility', {
  single: true,
  all: _roundFacilityItems,
  groups: _roundFacilityGroups,
});
fpBlockFacility = FacilityPicker('fp-block-facility', {
  single: true,
  all: _blockFacilityItems,
  groups: function() { return _facilityGroupsFor(msBlockProvider); },
  onChange: function() { _renderBlockEntries(); },
});
document.getElementById('block_reason').addEventListener('input', function() { _renderBlockEntries(); });

try {
  if (window.__PRELOADED__) {
    // Use server-rendered data instead of fetch()
    var P = window.__PRELOADED__;

    _providers = (P.providers && P.providers.providers) || [];
    var provItems = _providers.map(function(p) { return { id: p.id, name: p.name, npi: p.npi_number || '' }; });
    var editableItems = editableProviderItems(_providers, provItems);
    if (msProvider) msProvider.setItems(editableItems);
    if (msBlockProvider) msBlockProvider.setItems(editableItems);
    if (msHoldProvider) msHoldProvider.setItems(editableItems);
    if (msFilterProvider) msFilterProvider.setItems(filterItems(_providers, provItems));

    _locations = (P.locations && P.locations.locations) || [];
    if (msLocation) { msLocation.setItems(_locations); msLocation.setValue(_locations.map(function(l) { return String(l.id); })); }
    if (msBlockLocation) { msBlockLocation.setItems(_locations); msBlockLocation.setValue(_locations.map(function(l) { return String(l.id); })); }
    if (msHoldLocation) { msHoldLocation.setItems(_locations); msHoldLocation.setValue(_locations.map(function(l) { return String(l.id); })); }

    _visitTypes = (P.visit_types && P.visit_types.visit_types) || [];
    if (msVisitType) { msVisitType.setItems(_visitTypes); msVisitType.setValue(_visitTypes.map(function(v) { return String(v.id); })); }

    var tzData = P.timezone || {};
    _practiceTz = tzData.timezone || 'UTC';
    _tzOptions = tzData.available || [];
    updateTzHints();
    updateEditorTzLabels();

    _overviewData = (P.overview && P.overview.providers) || [];
    _syncProviderTzMapFromOverview();

    // Land on the saved default view. Empty means show everyone.
    _savedView = ((P.my_view && P.my_view.provider_ids) || []).map(String);

    // Its own request, so a failure there is reported without stopping the page.
    loadExpiredBanner();
    if (_savedView.length && msFilterProvider) msFilterProvider.setValue(_savedView.slice());

    renderAccordion();

    // Show flash message from form-action redirect
    if (P.flash) {
      var isErr = P.flash.toLowerCase().indexOf('error') === 0;
      showMsg(P.flash, isErr ? 'error' : 'success');
    }
  } else {
    // Fallback: fetch from API
    Promise.all([loadProviders(), loadLocations(), loadVisitTypes(), loadTimezone()]).then(function() {
      loadOverview();
      loadExpiredBanner();
    });
  }
} catch (initErr) {
  // Surface init errors visibly on the page
  var container = document.getElementById('accordion-container');
  if (container) container.innerHTML = '<div class="empty-state" style="color:red;">Init error: ' + initErr.message + '</div>';
}

// Listen for user-initiated tab changes from the canvas-tabs component
var _mainTabsEl = document.getElementById('main-tabs');
if (_mainTabsEl) {
  // A click on a tab header switches tabs inside the tab component, which
  // never passes through showTab. Catch it first, in the capture phase, so
  // leaving a tab with unsaved changes asks the same question.
  var _tabNames = Object.keys(_tabIndexMap);
  document.addEventListener('click', function(e) {
    var path = e.composedPath ? e.composedPath() : [];
    var btn = path.find(function(n) { return n.classList && n.classList.contains('tab-button'); });
    if (!btn || !_mainTabsEl.shadowRoot || !_mainTabsEl.shadowRoot.contains(btn)) return;
    var toName = _tabNames.find(function(k) { return _tabIndexMap[k] === parseInt(btn.dataset.index, 10); });
    if (toName && toName === _activeTab) {
      // Re-selecting the open tab would reset its form or reload its settings.
      e.stopPropagation();
      e.preventDefault();
      return;
    }
    if (!toName || _confirmLeave(toName)) {
      if (toName && toName !== _activeTab && _activeTab === 'editor') _formDirty = false;
      return;
    }
    e.stopPropagation();
    e.preventDefault();
  }, true);

  _mainTabsEl.addEventListener('tab-change', function(e) {
    var panelId = e.detail && e.detail.panel;
    var name = _tabPanelMap[panelId] || 'availability';
    // Was this dispatched from inside a programmatic showTab() call? If so,
    // showTab will reset _fromEvent itself after its own check; we should not
    // reset it here. If it's a real user-initiated tab click, _fromEvent was
    // not pre-set by anyone, so we reset it before returning so the next
    // programmatic showTab still sees a clean state.
    var calledFromShowTab = !!showTab._inProgress;
    showTab._fromEvent = true;
    _fillingForm();
    if (name === 'editor') {
      if (!_skipDirtyCheck) resetForm();
    } else if (name === 'settings') {
      renderSettingsPanel();
      bulkReset();
      if (window.paSettings) window.paSettings.open();
    } else {
      if (!_skipDirtyCheck) loadOverview();
    }
    _skipDirtyCheck = false;
    if (!calledFromShowTab) {
      showTab._fromEvent = false;
    }
    _rememberTab(name);
  });
}

// Restore active tab from URL hash
var _initHash = location.hash.replace('#', '');
if (!_initHash) {
  try { _initHash = sessionStorage.getItem(_LAST_TAB_KEY) || ''; } catch (e) {}
}
if (_initHash === 'settings' && !paAccess().is_admin) _initHash = 'availability';
if (_initHash === 'settings' || _initHash === 'editor') {
  // The tab component picks its starting tab after this script runs, from the
  // tab marked active, so mark the restored one or it lands on Availability.
  document.querySelectorAll('#main-tabs > canvas-tab').forEach(function(t) {
    if (t.getAttribute('for') === 'panel-' + _initHash) t.setAttribute('active', ''); else t.removeAttribute('active');
  });
  showTab(_initHash);
} else if (_initHash === 'bulk-import') {
  // Bulk import used to be its own tab; an old link lands on its Settings section.
  showTab('settings');
  var bulkSection = document.getElementById('settings-bulk-import');
  if (bulkSection) bulkSection.scrollIntoView();
}

// Intercept browser back/forward so it stays inside the admin and behaves like
// the Cancel button (returns to the Availability tab) instead of navigating
// out to the home-app's previous (often blank) state. Users can still leave
// the admin via the home-app's own navigation.
history.pushState({tab: 'pa-admin'}, '', location.href);
window.addEventListener('popstate', function() {
  // Re-push so the next browser-back also lands here, then switch to the
  // availability tab (mirrors the Cancel button).
  history.pushState({tab: 'pa-admin'}, '', location.href);
  _skipDirtyCheck = true;
  _settingsDirty = false;
  showTab('availability');
});


/* ---------- Theme: header tabs, access and feature switches ---------- */

// The viewer's access, sent with the page (engine.access.Access.summary).
function paAccess() {
  return (window.__PRELOADED__ && window.__PRELOADED__.access) || { is_admin: true };
}

// The Scheduling switches, sent with the page and kept current by settings.js.
function paFeatureOn(name) {
  var f = (window.__PRELOADED__ && window.__PRELOADED__.features) || {};
  return f[name] !== false;
}

// Provider picker items limited to providers the viewer can edit.
function editableProviderItems(providers, items) {
  var editable = {};
  (providers || []).forEach(function(p) { if (p.can_edit !== false) editable[String(p.id)] = true; });
  return (items || []).filter(function(it) { return editable[String(it.id)]; });
}

// Hide parts of the editor for features switched off in Settings.
// A page-level class per switched-off feature; theme.css hides what goes with it,
// so code that shows those sections later can't bring them back.
function applyFeatureVisibility() {
  ['buffers', 'lead_time', 'holds', 'overrides', 'provider_timezones', 'facility_rounds', 'facility_blocks'].forEach(function(name) {
    document.body.classList.toggle('feature-off-' + name, !paFeatureOn(name));
  });
  ['buffer_pre', 'buffer_post', 'min_lead_hours'].forEach(function(id) {
    var input = document.getElementById(id);
    var item = input && input.closest('.setting-item');
    if (item) item.setAttribute('data-field', id);
  });
}

function syncHeaderTabs(name) {
  document.querySelectorAll('#ax-tabs button').forEach(function(b) { b.classList.toggle('on', b.dataset.t === name); });
  hideInnerTabStrip();
}

// The tab component draws its own strip; the header tabs replace it.
function hideInnerTabStrip() {
  var root = _mainTabsEl && _mainTabsEl.shadowRoot;
  if (!root || !root.querySelector('.tab-wrapper')) { setTimeout(hideInnerTabStrip, 30); return; }
  if (!root.getElementById('pa-hide-strip')) {
    var st = document.createElement('style');
    st.id = 'pa-hide-strip';
    st.textContent = '.tab-wrapper { display: none !important; }';
    root.appendChild(st);
  }
}

(function initHeaderTabs() {
  var nav = document.getElementById('ax-tabs');
  if (!nav) return;
  if (!paAccess().is_admin) {
    var settingsBtn = document.getElementById('ax-tab-settings');
    if (settingsBtn) settingsBtn.style.display = 'none';
    if (_activeTab === 'settings') { _skipDirtyCheck = true; showTab('availability'); }
  }
  nav.querySelectorAll('button').forEach(function(b) {
    b.addEventListener('click', function() { if (b.dataset.t !== _activeTab) showTab(b.dataset.t); });
  });
  syncHeaderTabs(_activeTab);
  applyFeatureVisibility();
})();
