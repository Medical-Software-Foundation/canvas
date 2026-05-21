const API_BASE = '/plugin-io/api/provider_availability/api';
const DAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday'];
const DAY_ABBR = {monday:'Mon',tuesday:'Tue',wednesday:'Wed',thursday:'Thu',friday:'Fri',saturday:'Sat',sunday:'Sun'};
const USER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const AVATAR_CLASSES = ['avatar-a','avatar-b','avatar-c'];

const SVG_CHECK = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path d="M5 13l4 4L19 7"/></svg>';
const SVG_X = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path d="M6 18L18 6M6 6l12 12"/></svg>';
const SVG_PAUSE = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M9 4v16m6-16v16"/></svg>';
const SVG_OVERRIDE = '<svg fill="currentColor" viewBox="0 0 24 24" stroke="none"><path d="M12 3l9.5 16.5H2.5L12 3z"/></svg>';
const SVG_PLUS = '<svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M12 4v16m8-8H4"/></svg>';
const SVG_X_SM = '<svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M6 18L18 6M6 6l12 12"/></svg>';

const TABLE_COLGROUP = '<colgroup><col class="col-when"><col class="col-hours"><col class="col-where"><col class="col-repeats"><col class="col-status"><col class="col-actions"></colgroup>';
const TABLE_HEADER = '<thead><tr>' +
  '<th><span class="th-inner"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>When</span></th>' +
  '<th><span class="th-inner"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>Hours</span></th>' +
  '<th><span class="th-inner"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>Reason</span></th>' +
  '<th><span class="th-inner"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/><path d="M16 14l-4 0m4 3l-4 0"/></svg>Effective</span></th>' +
  '<th><span class="th-inner"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>Status</span></th>' +
  '<th><span class="th-inner"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"/></svg>Actions</span></th></tr></thead>';

const SVG_CHEVRON_RIGHT = '<svg class="row-chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M9 5l7 7-7 7"/></svg>';

let _providers = [];
let _locations = [];
let _visitTypes = [];
let _overviewData = [];
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
    } else if (document.getElementById('editing_rule_id').value) {
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
  lbl.innerHTML = (freq === 'daily' ? 'Time Windows' : 'Weekly Schedule') + asterisk;
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
  lbl.innerHTML = (freq === 'daily' ? 'Block Time Windows' : 'Weekly Block Schedule') + asterisk;
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

/* ---------- Daily mode flat time-windows editor ---------- */

function addDailyTimeWindow(containerId, startVal, endVal) {
  var container = document.getElementById(containerId);
  if (!container) return;
  var row = document.createElement('div');
  row.className = 'day-time-inputs';
  row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;';
  row.innerHTML =
    '<input class="time-input" type="time" value="' + (startVal || '') + '">' +
    '<span class="time-sep">→</span>' +
    '<input class="time-input" type="time" value="' + (endVal || '') + '">';
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

var _blockDateChips = [];
// When set, the form is editing a multi-date block group (one provider, many
// dates) — saving will replace the entire group instead of updating one block.
var _editingBlockGroup = null;

function onBlockAllDayToggle(checked) {
  var startField = document.getElementById('block-start-time-field');
  var endField = document.getElementById('block-end-time-field');
  var timeRow = document.getElementById('block-time-row');
  if (startField) startField.style.display = checked ? 'none' : '';
  if (endField) endField.style.display = checked ? 'none' : '';
  if (timeRow) timeRow.style.gridTemplateColumns = checked ? '1fr' : '1fr 1fr 1fr';
}

function _renderBlockDateChips() {
  var box = document.getElementById('block-date-chips');
  if (!box) return;
  box.innerHTML = '';
  _blockDateChips.forEach(function(d, idx) {
    var chip = document.createElement('span');
    chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;padding:4px 8px;background:var(--surface-muted, #f0f0f0);border-radius:12px;font-size:13px;';
    chip.textContent = d;
    var x = document.createElement('button');
    x.type = 'button';
    x.textContent = '×';
    x.style.cssText = 'background:none;border:0;cursor:pointer;font-size:16px;line-height:1;padding:0 0 0 2px;color:var(--text-muted);';
    x.onclick = function() { _blockDateChips.splice(idx, 1); _renderBlockDateChips(); };
    chip.appendChild(x);
    box.appendChild(chip);
  });
}

function addBlockDateChip() {
  var d = document.getElementById('block_date').value;
  if (!d) { showMsg('Pick a date first', 'error'); return; }
  if (_blockDateChips.indexOf(d) === -1) _blockDateChips.push(d);
  _blockDateChips.sort();
  _renderBlockDateChips();
  // Clear the date input so the next pick adds another chip cleanly
  document.getElementById('block_date').value = '';
  syncDateFacade('block_date');
}

function _resetBlockDateChips() {
  _blockDateChips = [];
  _renderBlockDateChips();
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

  setItems(items) { this.items = items; this.renderDropdown(); }

  open() { this.isOpen = true; this.dropdown.classList.add('open'); this.renderDropdown(); }
  close() { this.isOpen = false; this.dropdown.classList.remove('open'); this.filterText = ''; this.input.value = ''; }

  renderDropdown() {
    if (!this.isOpen) return;
    const filter = this.filterText.toLowerCase();
    const filtered = this.items.filter(item => {
      const label = String(item[this.displayKey] || '').toLowerCase();
      const extra = this.extraDisplayKey ? String(item[this.extraDisplayKey] || '').toLowerCase() : '';
      return label.includes(filter) || extra.includes(filter);
    });
    this.dropdown.innerHTML = '';
    if (filtered.length === 0) { this.dropdown.innerHTML = '<div class="ms-empty">No matches</div>'; return; }

    // Select All option
    if (filtered.length > 1 && !filter) {
      const allVals = filtered.map(i => String(i[this.valueKey]));
      const allSelected = allVals.every(v => this.selected.includes(v));
      const selAll = document.createElement('div');
      selAll.className = 'ms-option' + (allSelected ? ' selected' : '');
      selAll.style.fontWeight = '600';
      selAll.style.borderBottom = '1px solid var(--border)';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = allSelected;
      selAll.appendChild(cb);
      const span = document.createElement('span');
      span.textContent = 'Select All';
      selAll.appendChild(span);
      selAll.addEventListener('click', (e) => {
        e.stopPropagation();
        if (allSelected) { allVals.forEach(v => { const idx = this.selected.indexOf(v); if (idx >= 0) this.selected.splice(idx, 1); }); }
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
      let label = item[this.displayKey] || val;
      if (this.extraDisplayKey && item[this.extraDisplayKey]) label += ' (' + item[this.extraDisplayKey] + ')';
      const span = document.createElement('span');
      span.textContent = label;
      opt.appendChild(span);
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
    this.selected.forEach(val => {
      const item = this.items.find(i => String(i[this.valueKey]) === val);
      const label = item ? (item[this.displayKey] || val) : val;
      const chip = document.createElement('span');
      chip.className = 'ms-chip';
      chip.innerHTML = label + ' <span class="ms-chip-remove">&times;</span>';
      chip.querySelector('.ms-chip-remove').addEventListener('click', (e) => { e.stopPropagation(); this.toggle(val); });
      this.chipsArea.appendChild(chip);
    });
    this.input.placeholder = this.selected.length > 0 ? '' : this.placeholder;
  }

  getValue() { return this.selected.slice(); }
  setValue(values) { this.selected = (values || []).map(String); this.updateChips(); }
  clear() { this.selected = []; this.updateChips(); }
}

let msProvider, msLocation, msVisitType, msBlockProvider, msBlockLocation, msFilterProvider, msHoldProvider, msHoldLocation;

/* ---------- Tab management ---------- */

let _formDirty = false;
let _skipDirtyCheck = false;

window.addEventListener('beforeunload', function(e) {
  if (_formDirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});

var _tabIndexMap = { 'availability': 0, 'editor': 1, 'settings': 2 };
var _tabPanelMap = { 'panel-availability': 'availability', 'panel-editor': 'editor', 'panel-settings': 'settings' };

function _isEditorVisible() {
  var edPanel = document.getElementById('panel-editor');
  return edPanel && !edPanel.hasAttribute('hidden');
}

function showTab(name) {
  // Unsaved changes prompt when leaving editor
  if (_isEditorVisible() && name !== 'editor' && _formDirty && !_skipDirtyCheck) {
    if (!confirm('You have unsaved changes. Leave without saving?')) return;
  }
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
    } else {
      if (!_skipDirtyCheck) loadOverview();
    }
    _skipDirtyCheck = false;
  } else {
    showTab._fromEvent = false;
  }
  try { history.replaceState(null, '', '#' + name); } catch (e) {}
}
showTab._fromEvent = false;

function showMsg(msg, type) {
  const dismissBtn = '<button class="alert-dismiss" onclick="dismissMsg()">&times;</button>';
  const alertHtml = '<div class="alert alert-' + type + '"><span>' + msg + '</span>' + dismissBtn + '</div>';
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
      try { return JSON.parse(text); } catch (e) { return { error: text || ('HTTP ' + resp.status) }; }
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
  if (msProvider) msProvider.setItems(items);
  if (msBlockProvider) msBlockProvider.setItems(items);
  if (msHoldProvider) msHoldProvider.setItems(items);
  if (msFilterProvider) msFilterProvider.setItems(items);
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
  if (event && event.target.closest('.action-chip')) return;
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
    var btn = card.querySelector('[onclick*="addForProvider"]');
    if (btn) {
      var match = btn.getAttribute('onclick').match(/addForProvider\('([^']+)'/);
      if (match) expandedProviders.push(match[1]);
    }
  });
  var savedScroll = window.scrollY;
  // Build TZ hint HTML for embedding in the legend bar
  // Update legend bar in filter bar
  var legendContainer = document.getElementById('legend-bar-container');
  if (legendContainer) {
    var tzList = COMMON_TZS.slice();
    if (tzList.indexOf(_practiceTz) === -1) tzList.unshift(_practiceTz);
    var activeTz = _viewTz || 'provider';
    var legendHtml = '<span class="tz-hint-bar" style="margin-bottom:0;">' +
      '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>' +
      'View times in: <select id="view-tz-select" onchange="changeViewTz(this.value)">' +
      '<option value="provider"' + (activeTz === 'provider' ? ' selected' : '') + '>Provider\'s Timezone</option>' +
      tzList.map(function(tz) { return '<option value="' + tz + '"' + (tz === activeTz ? ' selected' : '') + '>' + tz + '</option>'; }).join('') +
      '</select></span>';
    legendHtml += '<span style="display:flex;gap:12px;align-items:center;">';
    legendHtml += '<span class="legend-item"><span class="type-chip chip-avail">' + SVG_CHECK + '</span> Available</span>';
    legendHtml += '<span class="legend-item"><span class="type-chip chip-block">' + SVG_X + '</span> Blocked</span>';
    legendHtml += '<span class="legend-item"><span class="type-chip chip-hold">' + SVG_PAUSE + '</span> Hold</span>';
    legendHtml += '<span class="legend-item"><span class="type-chip chip-override">' + SVG_OVERRIDE + '</span> Override</span>';
    legendHtml += '</span>';
    legendContainer.innerHTML = legendHtml;
  }

  const selectedIds = msFilterProvider ? msFilterProvider.getValue() : [];

  let providers = _overviewData;
  if (selectedIds.length > 0) {
    providers = providers.filter(p => selectedIds.includes(p.provider_id));
  }

  if (providers.length === 0) {
    if (selectedIds.length > 0) {
      container.innerHTML = '<div class="empty-state">No availability configured for the selected provider(s).<br><span style="font-size:13px;margin-top:6px;display:inline-block;">Use <strong>Add / Edit</strong> to set up rules.</span></div>';
    } else {
      container.innerHTML = '<div class="empty-state">No availability or blocks configured yet</div>';
    }
    return;
  }

  providers = providers.slice().sort(function(a, b) {
    var aLast = (a.provider_name || '').split(' ').slice(-1)[0].toLowerCase();
    var bLast = (b.provider_name || '').split(' ').slice(-1)[0].toLowerCase();
    return aLast.localeCompare(bLast);
  });

  let html = '';
  providers.forEach((p, idx) => {
    const pid = p.provider_id;
    const name = p.provider_name || pid.slice(0, 8) + '...';
    const initials = getInitials(name);
    const avatarClass = AVATAR_CLASSES[idx % 3];
    // Count Available rules (one row per rule). Counting weekdays would
    // miss daily-frequency rules (which keep weekly_schedule empty), so
    // a "Mon-Fri" rule and an "Every 2 days" rule both count as 1 here.
    const availableCount = (p.rules || []).length;
    let overrideCount = 0;
    let holdCount = 0;
    p.rules.forEach(r => { overrideCount += (r.date_overrides || []).length; });
    p.recurring_blocks.forEach(rb => {
      if (rb.hold_type && rb.hold_type !== 'none') holdCount++;
    });
    const pureBlockCount = p.blocks.length + p.recurring_blocks.filter(rb => !rb.hold_type || rb.hold_type === 'none').length;
    const hasData = availableCount > 0 || pureBlockCount > 0 || holdCount > 0;

    html += '<div class="provider-card">';

    // Header
    html += '<div class="provider-card-header" onclick="toggleCard(this)">';
    html += '<div class="provider-info">';
    html += '<div class="provider-avatar ' + avatarClass + '">' + initials + '</div>';
    var pTz = p.provider_timezone || _practiceTz;
    var pTzExplicit = p.provider_timezone_explicit;
    html += '<div class="provider-name-col">';
    html += '<span class="provider-name">' + name + '</span>';
    if (!_viewTz) {
      html += '<div class="provider-tz-subtitle">' + pTz + (pTzExplicit ? '' : ' (default)') + '</div>';
    }
    html += '</div></div>';
    html += '<div class="provider-chips">';
    if (availableCount > 0) html += '<span class="meta-pip pip-avail">' + availableCount + ' available</span>';
    if (pureBlockCount > 0) html += '<span class="meta-pip pip-block">' + pureBlockCount + ' blocked</span>';
    if (holdCount > 0) html += '<span class="meta-pip pip-hold">' + holdCount + ' hold</span>';
    if (overrideCount > 0) html += '<span class="meta-pip pip-override">' + overrideCount + ' override</span>';
    html += '</div>';
    html += '<div class="provider-header-right">';
    html += '<button class="btn btn-avail" onclick="event.stopPropagation();addForProvider(\'' + pid + '\',\'available\')">+ Available</button>';
    html += '<button class="btn btn-block-add" onclick="event.stopPropagation();addForProvider(\'' + pid + '\',\'blocked\')">+ Blocked</button>';
    html += '<svg class="chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M19 9l-7 7-7-7"/></svg>';
    html += '</div></div>';

    if (!hasData) {
      html += '<div style="padding:32px 24px;text-align:center;color:var(--text-muted);font-size:14px;">No availability or blocks configured';
      html += '<br><button class="btn btn-primary btn-sm" style="margin-top:12px;" onclick="addForProvider(\'' + pid + '\',\'available\')">+ Add Availability</button>';
      html += '</div>';
    } else {
      // Schedule table
      html += '<table class="schedule-table">';
      html += TABLE_COLGROUP;
      html += TABLE_HEADER;
      html += '<tbody>';

      var rows = [];

      // Available rules — expandable rows
      p.rules.forEach(r => {
        const schedule = r.weekly_schedule || {};
        const isExpired = r.effective_end && new Date(r.effective_end + 'T23:59:59') < new Date();
        const reasonChipHtml = r.reason
          ? '<div class="chip-group"><span class="detail-tag tag-avail">' + r.reason + '</span></div>'
          : '<span class="col-empty">\u2014</span>';

        // Build repeats cell
        let repeatsHtml = '';
        if (r.effective_start && r.effective_end) {
          if (r.effective_start === r.effective_end) {
            repeatsHtml = '<span class="date-range">' + fmtDate(r.effective_start) + '</span>';
          } else {
            repeatsHtml = '<span class="date-range">' + fmtDateRange(r.effective_start, r.effective_end) + '</span>';
          }
        } else if (r.effective_start) {
          repeatsHtml = '<span class="date-range">Since ' + fmtDate(r.effective_start) + '</span>';
        } else {
          repeatsHtml = '<span class="date-range">Always</span>';
        }

        // Build detail panel content
        let detailHtml = '<div class="detail-panel">';
        const vtNames = r.visit_type_names || [];
        var metaCols = vtNames.length > 0 ? 5 : 4;
        detailHtml += '<div class="detail-meta-grid" style="grid-template-columns:repeat(' + metaCols + ',1fr);">';
        detailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Frequency</div><div class="detail-meta-value">' + frequencyLabel(r) + '</div></div>';
        detailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Reason</div><div class="detail-meta-value">' + (r.reason || '\u2014') + '</div></div>';
        var buf = r.buffer_minutes || {};
        var booking = r.booking_interval || {};
        var bufParts = [];
        if (buf.pre > 0) bufParts.push('<span class="detail-tag tag-buffer">' + buf.pre + 'm Pre</span>');
        if (buf.post > 0) bufParts.push('<span class="detail-tag tag-buffer">' + buf.post + 'm Post</span>');
        if (booking.min_lead_hours > 0) bufParts.push('<span class="detail-tag tag-buffer">' + booking.min_lead_hours + 'h Lead</span>');
        detailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Buffers</div><div class="detail-meta-value">' + (bufParts.length > 0 ? '<div class="chip-group">' + bufParts.join(' ') + '</div>' : '\u2014') + '</div></div>';
        var locNames = resolveLocationNames(r.location_ids);
        var locHtml = locNames.length > 0 ? '<div class="chip-group">' + locNames.map(function(n) { return '<span class="detail-tag tag-location">' + n + '</span>'; }).join('') + '</div>' : 'All';
        detailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Locations</div><div class="detail-meta-value">' + locHtml + '</div></div>';
        if (vtNames.length > 0) {
          detailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Visit Types</div><div class="detail-meta-value"><div class="chip-group">';
          vtNames.forEach(function(vt) { detailHtml += '<span class="detail-tag tag-visit-type">' + vt + '</span>'; });
          detailHtml += '</div></div></div>';
        }
        detailHtml += '</div>';
        detailHtml += '</div>';

        // Group days by identical time windows — no splitting for overrides
        // Daily-frequency rules: synthesize one group from time_windows.
        var isDailyRule = r.recurrence_frequency === 'daily';
        var groups;
        if (isDailyRule) {
          var dailyWins = r.time_windows || [];
          groups = dailyWins.length > 0
            ? [{ days: [], windows: dailyWins, dailyLabel: dailyDayLabel(r) }]
            : [];
        } else {
          groups = groupDaysByWindows(schedule);
        }
        const ruleJson = JSON.stringify(JSON.stringify(r));

        var rowHtml = '';

        groups.forEach((group) => {
          const dayLabel = group.dailyLabel || formatDayRange(group.days);
          const timeStr = group.windows.map(w => fmtHHMMConverted(w.start, pTz) + ' \u2013 ' + fmtHHMMConverted(w.end, pTz)).join('<br>');

          // Data row
          rowHtml += '<tr class="row-available data-row" onclick="toggleRowDetail(this, event)">';
          rowHtml += '<td><div class="td-cell"><div style="display:flex;align-items:center;gap:6px;">';
          rowHtml += SVG_CHEVRON_RIGHT;
          rowHtml += '<span class="type-chip chip-avail">' + SVG_CHECK + '</span>';
          rowHtml += '<span class="day-text">' + dayLabel + '</span>';
          rowHtml += '</div></div></td>';
          rowHtml += '<td><div class="td-cell"><span class="time-text">' + timeStr + '</span></div></td>';
          rowHtml += '<td><div class="td-cell">' + reasonChipHtml + '</div></td>';
          rowHtml += '<td><div class="td-cell">' + repeatsHtml + '</div></td>';
          rowHtml += '<td><div class="td-cell"><span class="badge ' + (isExpired ? 'badge-expired">Expired' : 'badge-active">Active') + '</span></div></td>';
          rowHtml += '<td><div class="td-cell"><div class="row-actions">';
          rowHtml += '<button class="action-chip action-chip-edit" onclick=\'editRule(' + ruleJson + ')\'>Edit</button>';
          rowHtml += '<button class="action-chip action-chip-delete" onclick=\'deleteRuleDays("' + r.provider_id + '","' + r.id + '",' + JSON.stringify(group.days) + ',' + ruleJson + ')\'>Delete</button>';
          rowHtml += '</div></div></td>';
          rowHtml += '</tr>';
          // Detail row
          rowHtml += '<tr class="detail-row row-available"><td colspan="6">' + detailHtml + '</td></tr>';
        });

        // Fallback: rule with no active days
        if (groups.length === 0) {
          rowHtml += '<tr class="row-available data-row" onclick="toggleRowDetail(this, event)">';
          rowHtml += '<td><div class="td-cell"><div style="display:flex;align-items:center;gap:6px;">' + SVG_CHEVRON_RIGHT + '<span class="type-chip chip-avail">' + SVG_CHECK + '</span><span class="day-text">No days</span></div></div></td>';
          rowHtml += '<td><div class="td-cell"><span class="col-empty">\u2014</span></div></td>';
          rowHtml += '<td><div class="td-cell">' + reasonChipHtml + '</div></td>';
          rowHtml += '<td><div class="td-cell">' + repeatsHtml + '</div></td>';
          rowHtml += '<td><div class="td-cell"><span class="badge ' + (isExpired ? 'badge-expired">Expired' : 'badge-active">Active') + '</span></div></td>';
          rowHtml += '<td><div class="td-cell"><div class="row-actions">';
          rowHtml += '<button class="action-chip action-chip-edit" onclick=\'editRule(' + ruleJson + ')\'>Edit</button>';
          rowHtml += '<button class="action-chip action-chip-delete" onclick="confirmDeleteRule(\'' + r.provider_id + '\',\'' + r.id + '\')">Delete</button>';
          rowHtml += '</div></div></td></tr>';
          rowHtml += '<tr class="detail-row row-available"><td colspan="6">' + detailHtml + '</td></tr>';
        }

        rows.push({ typeOrder: 1, sortKey: r.effective_start || '0000-00-00', html: rowHtml });

        // Override rows pushed separately so they sort after ALL available rows
        (r.date_overrides || []).forEach(function(ovr) {
          var ovrDateStr = fmtDate(ovr.date);
          var ovrDateObj = new Date(ovr.date + 'T12:00:00');
          var ovrDayAbbr = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][ovrDateObj.getDay()];
          var ovrHours = ovr.is_closed
            ? 'Closed'
            : ovr.time_windows.map(function(w) { return fmtHHMMConverted(w.start, pTz) + ' \u2013 ' + fmtHHMMConverted(w.end, pTz); }).join(', ');
          var ovrReasonHtml = ovr.reason
            ? '<span class="detail-tag tag-override">' + ovr.reason + '</span>'
            : '<span class="type-chip chip-override">Override</span>';
          var ovrJson = JSON.stringify(ovr).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
          var ovrHtml = '<tr class="row-override">';
          ovrHtml += '<td><div class="td-cell"><div style="display:flex;align-items:center;gap:6px;"><span style="visibility:hidden">' + SVG_CHEVRON_RIGHT + '</span><span class="type-chip chip-override">' + SVG_OVERRIDE + '</span><span class="day-text">' + ovrDayAbbr + '</span></div></div></td>';
          ovrHtml += '<td><div class="td-cell"><span class="time-text">' + ovrHours + '</span></div></td>';
          ovrHtml += '<td><div class="td-cell">' + ovrReasonHtml + '</div></td>';
          ovrHtml += '<td><div class="td-cell"><span class="date-range">' + ovrDateStr + '</span></div></td>';
          var ovrExpired = new Date(ovr.date + 'T23:59:59') < new Date();
          ovrHtml += '<td><div class="td-cell"><span class="badge ' + (ovrExpired ? 'badge-expired">Expired' : 'badge-active">Active') + '</span></div></td>';
          ovrHtml += '<td><div class="td-cell"><div class="row-actions">';
          ovrHtml += '<button class="action-chip action-chip-edit" onclick="editOverrideFromAccordion(\'' + r.provider_id + '\',\'' + r.id + '\',\'' + ovrJson + '\')">Edit</button>';
          ovrHtml += '<button class="action-chip action-chip-delete" onclick="deleteOverrideFromAccordion(\'' + r.provider_id + '\',\'' + r.id + '\',\'' + ovr.date + '\')">Delete</button>';
          ovrHtml += '</div></div></td>';
          ovrHtml += '</tr>';
          rows.push({ typeOrder: 1.5, sortKey: ovr.date, html: ovrHtml });
        });
      });

      // One-off blocks
      p.blocks.forEach(b => {
        const blockDateStr = (b.start || '').slice(0, 10);
        const blockDateParts = blockDateStr.split('-');
        const blockDateObj = new Date(Number(blockDateParts[0]), Number(blockDateParts[1]) - 1, Number(blockDateParts[2]));
        const blockDayAbbr = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][blockDateObj.getDay()];
        const blockEffective = fmtDate(blockDateStr);
        const viewTz = _viewTz || pTz;
        const timeStr = convertIsoTime(b.start, pTz, viewTz) + ' \u2013 ' + convertIsoTime(b.end, pTz, viewTz);
        const blockJson = JSON.stringify(JSON.stringify(b));
        const blockReasonChip = b.reason
          ? '<span class="detail-tag tag-block">' + b.reason + '</span>'
          : '<span class="col-empty">\u2014</span>';

        // Detail panel
        var bLocNames = resolveLocationNames(b.location_ids);
        var bLocHtml = bLocNames.length > 0 ? '<div class="chip-group">' + bLocNames.map(function(n) { return '<span class="detail-tag tag-location">' + n + '</span>'; }).join('') + '</div>' : 'All';
        var bDetailHtml = '<div class="detail-panel"><div class="detail-meta-grid">';
        bDetailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Reason</div><div class="detail-meta-value">' + (b.reason || '\u2014') + '</div></div>';
        bDetailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Locations</div><div class="detail-meta-value">' + bLocHtml + '</div></div>';
        bDetailHtml += '</div></div>';

        // Single-event blocks expire once their end datetime is in the past.
        const blockEndDate = b.end ? new Date(b.end) : null;
        const blockExpired = blockEndDate && blockEndDate < new Date();

        var rowHtml = '';
        rowHtml += '<tr class="row-blocked data-row" onclick="toggleRowDetail(this, event)">';
        rowHtml += '<td><div class="td-cell"><div style="display:flex;align-items:center;gap:6px;">';
        rowHtml += SVG_CHEVRON_RIGHT;
        rowHtml += '<span class="type-chip chip-block">' + SVG_X + '</span>';
        rowHtml += '<span class="day-text">' + blockDayAbbr + '</span>';
        rowHtml += '</div></div></td>';
        rowHtml += '<td><div class="td-cell"><span class="time-text">' + timeStr + '</span></div></td>';
        rowHtml += '<td><div class="td-cell">' + blockReasonChip + '</div></td>';
        rowHtml += '<td><div class="td-cell"><span class="date-range">' + blockEffective + '</span></div></td>';
        rowHtml += '<td><div class="td-cell"><span class="badge ' + (blockExpired ? 'badge-expired">Expired' : 'badge-active">Active') + '</span></div></td>';
        rowHtml += '<td><div class="td-cell"><div class="row-actions">';
        rowHtml += '<button class="action-chip action-chip-edit" onclick=\'editBlock(' + blockJson + ')\'>Edit</button>';
        rowHtml += '<button class="action-chip action-chip-delete" onclick="confirmDeleteBlock(\'' + b.provider_id + '\',\'' + b.id + '\')">Delete</button>';
        rowHtml += '</div></div></td>';
        rowHtml += '</tr>';
        rowHtml += '<tr class="detail-row row-blocked"><td colspan="6">' + bDetailHtml + '</td></tr>';

        rows.push({ typeOrder: 3, sortKey: blockDateStr, html: rowHtml });
      });

      // Recurring blocks — expandable rows
      p.recurring_blocks.forEach(rb => {
        const schedule = rb.weekly_schedule || {};
        const isExpired = rb.effective_end && new Date(rb.effective_end + 'T23:59:59') < new Date();
        const isHold = rb.hold_type && rb.hold_type !== 'none';
        const holdLabels = { none: '', same_day: 'Same Day Hold', next_day: 'Next Day Hold' };
        const holdLabel = holdLabels[rb.hold_type || 'none'] || '';

        // Build repeats cell
        let repeatsHtml = '';
        if (rb.effective_start && rb.effective_end) {
          if (rb.effective_start === rb.effective_end) {
            repeatsHtml = '<span class="date-range">' + fmtDate(rb.effective_start) + '</span>';
          } else {
            repeatsHtml = '<span class="date-range">' + fmtDateRange(rb.effective_start, rb.effective_end) + '</span>';
          }
        } else if (rb.effective_start) {
          repeatsHtml = '<span class="date-range">Since ' + fmtDate(rb.effective_start) + '</span>';
        } else {
          repeatsHtml = '<span class="date-range">Always</span>';
        }

        // Build inline chips: hold + reason
        let rbChipsHtml = '';
        if (holdLabel && rb.reason) {
          rbChipsHtml += '<span class="detail-tag tag-hold">' + holdLabel + ': ' + rb.reason + '</span>';
        } else if (holdLabel) {
          rbChipsHtml += '<span class="detail-tag tag-hold">' + holdLabel + '</span>';
        } else if (rb.reason) {
          rbChipsHtml += '<span class="detail-tag tag-block">' + rb.reason + '</span>';
        }
        if (!rbChipsHtml) rbChipsHtml = '<span class="col-empty">\u2014</span>';
        else rbChipsHtml = '<div class="chip-group">' + rbChipsHtml + '</div>';

        // Detail panel
        var rbReasonText = '';
        if (holdLabel && rb.reason) rbReasonText = holdLabel + ': ' + rb.reason;
        else if (holdLabel) rbReasonText = holdLabel;
        else if (rb.reason) rbReasonText = rb.reason;
        var rbLocNames = resolveLocationNames(rb.location_ids);
        var rbLocHtml = rbLocNames.length > 0 ? '<div class="chip-group">' + rbLocNames.map(function(n) { return '<span class="detail-tag tag-location">' + n + '</span>'; }).join('') + '</div>' : 'All';
        var rbDetailHtml = '<div class="detail-panel"><div class="detail-meta-grid" style="grid-template-columns:repeat(3,1fr);">';
        rbDetailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Frequency</div><div class="detail-meta-value">' + frequencyLabel(rb) + '</div></div>';
        rbDetailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Reason</div><div class="detail-meta-value">' + (rbReasonText || '\u2014') + '</div></div>';
        rbDetailHtml += '<div class="detail-meta-item"><div class="detail-section-label">Locations</div><div class="detail-meta-value">' + rbLocHtml + '</div></div>';
        rbDetailHtml += '</div></div>';

        var isDailyBlock = rb.recurrence_frequency === 'daily';
        var groups;
        if (isDailyBlock) {
          var dailyBlockWins = rb.time_windows || [];
          groups = dailyBlockWins.length > 0
            ? [{ days: [], windows: dailyBlockWins, dailyLabel: dailyDayLabel(rb) }]
            : [];
        } else {
          groups = groupDaysByWindows(schedule);
        }
        const rbJson = JSON.stringify(JSON.stringify(rb));

        const rbRowClass = isHold ? 'row-hold' : 'row-blocked';

        var rowHtml = '';
        groups.forEach((group) => {
          const dayLabel = group.dailyLabel || formatDayRange(group.days);
          const timeStr = group.windows.map(w => fmtHHMMConverted(w.start, pTz) + ' \u2013 ' + fmtHHMMConverted(w.end, pTz)).join('<br>');

          rowHtml += '<tr class="' + rbRowClass + ' data-row" onclick="toggleRowDetail(this, event)">';
          rowHtml += '<td><div class="td-cell"><div style="display:flex;align-items:center;gap:6px;">';
          rowHtml += SVG_CHEVRON_RIGHT;
          rowHtml += '<span class="type-chip ' + (isHold ? 'chip-hold' : 'chip-block') + '">' + (isHold ? SVG_PAUSE : SVG_X) + '</span>';
          rowHtml += '<span class="day-text">' + dayLabel + '</span>';
          rowHtml += '</div></div></td>';
          rowHtml += '<td><div class="td-cell"><span class="time-text">' + timeStr + '</span></div></td>';
          rowHtml += '<td><div class="td-cell">' + rbChipsHtml + '</div></td>';
          rowHtml += '<td><div class="td-cell">' + repeatsHtml + '</div></td>';
          rowHtml += '<td><div class="td-cell"><span class="badge ' + (isExpired ? 'badge-expired">Expired' : 'badge-active">Active') + '</span></div></td>';
          rowHtml += '<td><div class="td-cell"><div class="row-actions">';
          if (isHold) {
            rowHtml += '<button class="action-chip action-chip-edit" onclick=\'editHold(' + rbJson + ')\'>Edit</button>';
            rowHtml += '<button class="action-chip action-chip-delete" onclick=\'deleteHold("' + rb.provider_id + '","' + rb.id + '")\'>Delete</button>';
          } else {
            rowHtml += '<button class="action-chip action-chip-edit" onclick=\'editRecurringBlock(' + rbJson + ')\'>Edit</button>';
            rowHtml += '<button class="action-chip action-chip-delete" onclick=\'deleteRecurringBlockDays("' + rb.provider_id + '","' + rb.id + '",' + JSON.stringify(group.days) + ',' + rbJson + ')\'>Delete</button>';
          }
          rowHtml += '</div></div></td>';
          rowHtml += '</tr>';
          rowHtml += '<tr class="detail-row ' + rbRowClass + '"><td colspan="6">' + rbDetailHtml + '</td></tr>';
        });

        rows.push({ typeOrder: isHold ? 2 : 3, sortKey: rb.effective_start || '0000-00-00', html: rowHtml });
      });

      rows.sort(function(a, b) {
        if (a.typeOrder !== b.typeOrder) return a.typeOrder - b.typeOrder;
        return a.sortKey.localeCompare(b.sortKey);
      });
      rows.forEach(function(r) { html += r.html; });

      html += '</tbody></table>';
    }

    html += '</div>';
  });
  container.innerHTML = html;
  // Restore expanded card state — collapse cards that weren't open before
  container.querySelectorAll('.provider-card').forEach(function(card) {
    var btn = card.querySelector('[onclick*="addForProvider"]');
    if (btn) {
      var match = btn.getAttribute('onclick').match(/addForProvider\('([^']+)'/);
      if (match && expandedProviders.indexOf(match[1]) === -1) {
        card.classList.add('collapsed');
      }
    }
  });
  // Sync expand/collapse button label
  var ecBtn = document.querySelector('.btn-expand-collapse');
  if (ecBtn) {
    var anyCollapsed = container.querySelector('.provider-card.collapsed');
    ecBtn.textContent = anyCollapsed ? 'Expand All' : 'Collapse All';
  }
  window.scrollTo(0, savedScroll);
}

function toggleCard(header) {
  header.closest('.provider-card').classList.toggle('collapsed');
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
  if (btn) btn.textContent = allExpanded ? 'Expand All' : 'Collapse All';
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
    html += '<span class="day-label">' + DAY_ABBR[day] + '</span>';
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
  wrap.innerHTML = '<input class="time-input" type="time" value="' + (startVal || '') + '">' +
    '<span class="time-sep">\u2192</span>' +
    '<input class="time-input" type="time" value="' + (endVal || '') + '">';
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
    html += '<span class="day-label">' + DAY_ABBR[day] + '</span>';
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
  wrap.innerHTML = '<input class="time-input" type="time" value="' + (startVal || '') + '">' +
    '<span class="time-sep">\u2192</span>' +
    '<input class="time-input" type="time" value="' + (endVal || '') + '">';
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

function renderOverridesList() {
  const ruleId = document.getElementById('editing_rule_id').value;
  const providerId = msProvider.getValue()[0];
  if (!ruleId || !providerId) return;

  const rule = _findCurrentRule(providerId, ruleId);
  const overrides = (rule && rule.date_overrides) || [];
  const container = document.getElementById('overrides-list');
  if (overrides.length === 0) {
    container.innerHTML = '<p style="font-size:13px;color:var(--text-muted);">No date overrides.</p>';
    return;
  }
  let html = '<div style="display:flex;flex-direction:column;gap:6px;">';
  overrides.sort((a, b) => a.date.localeCompare(b.date));
  overrides.forEach(o => {
    const dateStr = o.date;
    const dateObj = new Date(dateStr + 'T12:00:00');
    const dayAbbr = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][dateObj.getDay()];
    const detail = (o.time_windows || []).map(w => fmtHHMM(w.start) + ' \u2013 ' + fmtHHMM(w.end)).join(', ') || 'No hours';
    const reasonLabel = o.reason ? ' \u2014 ' + o.reason : '';
    html += '<div style="display:flex;align-items:center;gap:10px;padding:6px 10px;background:var(--override-bg);border:1px solid var(--override-border);border-radius:6px;">';
    html += '<span style="font-weight:600;font-size:13px;min-width:120px;">' + dayAbbr + ', ' + fmtDate(dateStr) + '</span>';
    html += '<span style="font-size:13px;color:var(--text-muted);flex:1;">' + detail + reasonLabel + '</span>';
    html += '<button type="button" class="action-chip action-chip-edit" style="font-size:12px;padding:3px 8px;" onclick=\'editOverrideInPlace(' + JSON.stringify(JSON.stringify(o)) + ')\'>Edit</button>';
    html += '<button type="button" class="remove-time" onclick="deleteOverride(\'' + dateStr + '\')">' + SVG_X_SM + '</button>';
    html += '</div>';
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
  wrap.innerHTML = '<input class="time-input" type="time" value="' + (startVal || '') + '">' +
    '<span class="time-sep">\u2192</span>' +
    '<input class="time-input" type="time" value="' + (endVal || '') + '">';
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
  // If editing an existing override and the date changed, delete the old one first
  var editingDate = document.getElementById('editing_override_date') ? document.getElementById('editing_override_date').value : '';
  if (editingDate && editingDate !== dateVal) {
    await apiCall('/rules/' + providerId + '/' + ruleId + '/overrides/' + editingDate, { method: 'DELETE' });
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
  const ruleId = document.getElementById('editing_rule_id').value;
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
  document.getElementById('editor-title').textContent = 'Add New Rule';
  document.getElementById('editing_rule_id').value = '';
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

  document.getElementById('buffer_pre').value = '0';
  document.getElementById('buffer_post').value = '0';
  document.getElementById('min_lead_hours').value = '0';
  document.getElementById('effective_start').value = today;
  document.getElementById('effective_end').value = '';
  document.getElementById('no_end_date').checked = true;
  toggleNoEndDate('effective_end', true);
  syncDateFacade('effective_start');
  syncDateFacade('effective_end');
  document.getElementById('rule_reason').value = '';
  document.getElementById('block_reason').value = '';
  document.getElementById('rb_effective_start').value = today;
  document.getElementById('rb_effective_end').value = '';
  document.getElementById('rb_no_end_date').checked = true;
  toggleNoEndDate('rb_effective_end', true);
  syncDateFacade('rb_effective_start');
  syncDateFacade('rb_effective_end');
  document.getElementById('block_date').value = '';
  document.getElementById('block_start_time').value = '';
  document.getElementById('block_end_time').value = '';
  syncDateFacade('block_date');

  // Reset single event fields
  document.getElementById('single_date').value = '';
  document.getElementById('single_start_time').value = '';
  document.getElementById('single_end_time').value = '';
  syncDateFacade('single_date');

  // Reset the All-day checkbox and the multi-date chip queue
  // (block_date/start/end are already cleared above).
  var allDayEl = document.getElementById('block_all_day');
  if (allDayEl) {
    allDayEl.checked = false;
    onBlockAllDayToggle(false);
  }
  _resetBlockDateChips();
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

  // Reset block mode to single
  setBlockMode('single');

  // Reset hold form
  document.getElementById('editing_hold_id').value = '';
  document.getElementById('editing_hold_group_id').value = '';
  document.getElementById('hold_reason').value = '';
  document.getElementById('hold_type_select').value = 'same_day';
  document.getElementById('hold_effective_start').value = today;
  document.getElementById('hold_effective_end').value = '';
  document.getElementById('hold_no_end_date').checked = true;
  toggleNoEndDate('hold_effective_end', true);
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

function toggleNoEndDate(inputId, checked) {
  const el = document.getElementById(inputId);
  const facade = document.getElementById(inputId + '_display');
  if (checked) {
    el.value = '';
    if (facade) { facade.style.display = 'none'; facade.value = ''; }
  } else {
    if (facade) facade.style.display = '';
  }
}

function editRule(ruleJson) {
  const r = JSON.parse(ruleJson);
  resetForm();
  selectType('available');
  document.getElementById('type-selector-section').style.display = 'none';
  _skipDirtyCheck = true;
  showTab('editor');
  document.getElementById('editor-title').textContent = 'Edit Availability';
  document.getElementById('editing_rule_id').value = r.id || '';
  document.getElementById('editing_group_id').value = r.group_id || '';
  msProvider.setValue([r.provider_id]);
  msLocation.setValue(r.location_ids || []);
  msVisitType.setValue(r.visit_types || []);

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
    document.getElementById('single_start_time').value = win.start;
    document.getElementById('single_end_time').value = win.end;
  } else {
    setScheduleMode('recurring');
    document.getElementById('effective_start').value = r.effective_start || '';
    document.getElementById('effective_end').value = r.effective_end || '';
    document.getElementById('no_end_date').checked = !hasEnd;
    toggleNoEndDate('effective_end', !hasEnd);
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
  document.getElementById('editor-title').textContent = 'Edit Block';
  document.getElementById('editing_recurring_block_id').value = b.id || '';
  document.getElementById('editing_group_id').value = b.group_id || '';
  msBlockProvider.setValue([b.provider_id]);
  msBlockLocation.setValue(b.location_ids || []);

  document.getElementById('block_reason').value = b.reason || '';
  document.getElementById('rb_effective_start').value = b.effective_start || '';
  document.getElementById('rb_effective_end').value = b.effective_end || '';

  const hasEnd = !!b.effective_end;
  document.getElementById('rb_no_end_date').checked = !hasEnd;
  toggleNoEndDate('rb_effective_end', !hasEnd);
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
  document.getElementById('editor-title').textContent = 'Edit Block';
  document.getElementById('editing_block_id').value = b.id || '';
  document.getElementById('editing_group_id').value = b.group_id || '';
  msBlockProvider.setValue([b.provider_id]);
  msBlockLocation.setValue(b.location_ids || []);

  document.getElementById('block_reason').value = b.reason || '';

  // Populate date/time from block start/end ISO strings
  document.getElementById('block_date').value = (b.start || '').slice(0, 10);
  document.getElementById('block_start_time').value = (b.start || '').slice(11, 16);
  document.getElementById('block_end_time').value = (b.end || '').slice(11, 16);
  syncDateFacade('block_date');

  // Restore the all-day checkbox from the saved block
  var allDayEl = document.getElementById('block_all_day');
  if (allDayEl) {
    allDayEl.checked = !!b.all_day;
    onBlockAllDayToggle(!!b.all_day);
  }

  // Multi-date group detection: if siblings have different dates than this
  // block, the group represents a holiday-list-style batch. Load all the
  // group's dates into the chip list so the user sees and can edit the
  // whole list (saving will replace the whole group).
  _editingBlockGroup = null;
  if (b.group_id) {
    var siblingDates = [];
    var sameDate = (b.start || '').slice(0, 10);
    _overviewData.forEach(function(p) {
      (p.blocks || []).forEach(function(pb) {
        if (pb.group_id === b.group_id) {
          var d = (pb.start || '').slice(0, 10);
          if (siblingDates.indexOf(d) === -1) siblingDates.push(d);
        }
      });
    });
    var hasDifferentDates = siblingDates.some(function(d) { return d !== sameDate; });
    if (hasDifferentDates) {
      _editingBlockGroup = b.group_id;
      _resetBlockDateChips();
      // Put every group date into chips except the one shown in block_date
      // (the active date input doubles as the "primary" entry on save).
      siblingDates.sort().forEach(function(d) {
        if (d !== sameDate && _blockDateChips.indexOf(d) === -1) _blockDateChips.push(d);
      });
      _renderBlockDateChips();
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

async function saveRule() {
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
  }

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

  for (const pid of providerIds) {
    const rule = Object.assign({}, ruleBase, { provider_id: pid, group_id: newGroupId });
    const data = await apiCall('/rules', { method: 'POST', body: JSON.stringify(rule) });
    if (data.error) errors.push(data.error);
    else saved++;
  }

  if (errors.length > 0) {
    showMsg(errors.join('; '), 'error');
  } else {
    showMsg(saved === 1 ? 'Availability saved' : saved + ' availability rules created', 'success');
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
  }
}

async function saveRecurringBlock() {
  const providerIds = msBlockProvider.getValue();
  if (providerIds.length === 0) { showMsg('Please select at least one provider', 'error'); return; }

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

  const locationIds = msBlockLocation.getValue();

  if (editingId && providerIds.length === 1) {
    const body = {
      id: editingId,
      provider_id: providerIds[0],
      weekly_schedule: schedule,
      reason: document.getElementById('block_reason').value,
      location_ids: locationIds,
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
      reason: document.getElementById('block_reason').value,
      location_ids: locationIds,
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
      reason: document.getElementById('block_reason').value,
      location_ids: locationIds,
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

  const allDayEl = document.getElementById('block_all_day');
  const allDay = !!(allDayEl && allDayEl.checked);

  // Collect all dates: queued chips + the date input (if filled)
  const liveDate = document.getElementById('block_date').value;
  const dateSet = {};
  _blockDateChips.forEach(function(d) { dateSet[d] = true; });
  if (liveDate) dateSet[liveDate] = true;
  const allDates = Object.keys(dateSet).sort();

  const startTime = document.getElementById('block_start_time').value;
  const endTime = document.getElementById('block_end_time').value;
  const reason = document.getElementById('block_reason').value;
  const groupId = document.getElementById('editing_group_id').value;
  const applyToGroup = document.getElementById('apply_to_group').checked && groupId;
  const locationIds = msBlockLocation.getValue();

  if (allDates.length === 0) {
    showMsg('Pick at least one date', 'error'); return;
  }
  if (!allDay && (!startTime || !endTime)) {
    showMsg('Start and end time are required (or check All day)', 'error'); return;
  }
  if (!allDay && startTime >= endTime) {
    showMsg('Start time must be before end time', 'error'); return;
  }

  // Multi-date edit path. Enters when either:
  //   (a) editing an existing multi-date group, or
  //   (b) editing a single-date block AND the user added more dates as chips.
  if (providerIds.length === 1 && blockId && (_editingBlockGroup || allDates.length > 1)) {
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
    // Per affected provider, gather the block ids that need to be removed
    // before posting the fresh batch. We must NOT use the server's
    // ?apply_to_group=true here because that flag is cross-provider and
    // would wipe sibling providers' blocks unconditionally.
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
      for (const bid of blockIdsToDelete) {
        const delResp = await apiCall(
          '/blocks/' + pid + '/' + bid + '?apply_to_group=false',
          { method: 'DELETE' }
        );
        if (delResp && delResp.error) { showMsg(delResp.error, 'error'); return; }
      }
    }
    const batchGroupId = _editingBlockGroup
      || groupId
      || (allDates.length > 1 || groupProviderIds.length > 1 ? crypto.randomUUID() : null);
    let totalCreated = 0;
    for (const pid of groupProviderIds) {
      const body = {
        provider_id: pid,
        dates: allDates,
        all_day: allDay,
        reason: reason,
        location_ids: locationIds,
        group_id: batchGroupId,
      };
      if (!allDay) {
        body.start = '1970-01-01T' + startTime + ':00';
        body.end = '1970-01-01T' + endTime + ':00';
      }
      const data = await apiCall('/blocks', { method: 'POST', body: JSON.stringify(body) });
      if (data.error) { showMsg(data.error, 'error'); return; }
      totalCreated += allDates.length;
    }
    showMsg(totalCreated + ' block(s) saved', 'success');
    _editingBlockGroup = null;
    _resetBlockDateChips();
    _skipDirtyCheck = true;
    await loadOverview();
    showTab('availability');
    return;
  }

  // Multi-date or all-day batch path: use new dates[] payload to fan out server-side.
  const isBatch = allDates.length > 1 || allDay;
  if (isBatch && !blockId) {
    // Per provider, send one request with the list of dates so the server can
    // mint a shared group_id and create N blocks atomically per provider.
    const newGroupId = providerIds.length > 1 ? crypto.randomUUID() : null;
    let errors = [];
    let saved = 0;
    for (const pid of providerIds) {
      const body = {
        provider_id: pid,
        dates: allDates,
        all_day: allDay,
        reason: reason,
        location_ids: locationIds,
        group_id: newGroupId,
      };
      if (!allDay) {
        body.start = '1970-01-01T' + startTime + ':00';
        body.end = '1970-01-01T' + endTime + ':00';
      }
      const data = await apiCall('/blocks', { method: 'POST', body: JSON.stringify(body) });
      if (data.error) errors.push(data.error);
      else saved += (data.blocks ? data.blocks.length : 1);
    }
    _resetBlockDateChips();
    if (errors.length > 0) showMsg(errors.join('; '), 'error');
    else {
      showMsg(saved + ' block(s) created', 'success');
      _skipDirtyCheck = true;
      await loadOverview();
      showTab('availability');
    }
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
  await apiCall('/rules/' + providerId + '/' + ruleId, { method: 'DELETE' });
  showMsg('Rule deleted', 'success');
  loadOverview();
}

function confirmDeleteBlock(providerId, blockId) {
  showConfirm('Delete this block?', () => doDeleteBlock(providerId, blockId));
}
async function doDeleteBlock(providerId, blockId) {
  await apiCall('/blocks/' + providerId + '/' + blockId, { method: 'DELETE' });
  showMsg('Block deleted', 'success');
  loadOverview();
}

function confirmDeleteRecurringBlock(providerId, blockId) {
  showConfirm('Delete this recurring block?', () => doDeleteRecurringBlock(providerId, blockId));
}
async function doDeleteRecurringBlock(providerId, blockId) {
  await apiCall('/recurring-blocks/' + providerId + '/' + blockId, { method: 'DELETE' });
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

/* ---------- Settings tab ---------- */

const PROVISION_BASE = '/plugin-io/api/provider_availability/provision';

async function loadAllowedStaff() {
  const container = document.getElementById('allowed-staff-list');
  try {
    const data = await apiCall('/overview');  // reuse to check auth
  } catch(e) { /* ignore */ }

  try {
    const resp = await fetch(PROVISION_BASE + '/allowed-staff', { credentials: 'same-origin' });
    if (!resp.ok) { container.innerHTML = '<div class="empty-state" style="padding:16px;">Could not load allowed staff</div>'; return; }
    const data = await resp.json();
    const ids = data.allowed_staff || [];

    if (ids.length === 0) {
      container.innerHTML = '<div class="empty-state" style="padding:16px;">No staff restrictions. All staff have access.</div>';
      return;
    }

    // Look up names from _providers
    let html = '';
    ids.forEach(id => {
      const prov = _providers.find(p => String(p.id) === String(id));
      const name = prov ? prov.name : 'Unknown';
      html += '<div class="staff-item">';
      html += '<div><span class="staff-name">' + name + '</span><span class="staff-id">' + id + '</span></div>';
      html += '<button class="btn btn-danger btn-sm" onclick="removeStaff(\'' + id + '\')">Remove</button>';
      html += '</div>';
    });
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div class="empty-state" style="padding:16px;">Could not load allowed staff</div>';
  }
}

async function addStaffToAllowed() {
  const ids = msSettingsStaff.getValue();
  if (ids.length === 0) { showMsg('Select a staff member to add', 'error'); return; }
  for (const id of ids) {
    await fetch(PROVISION_BASE + '/allowed-staff', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ staff_id: id }),
    });
  }
  msSettingsStaff.clear();
  showMsg('Staff added', 'success');
  loadAllowedStaff();
}

async function removeStaff(staffId) {
  await fetch(PROVISION_BASE + '/allowed-staff/' + staffId, {
    method: 'DELETE', credentials: 'same-origin',
  });
  showMsg('Staff removed', 'success');
  loadAllowedStaff();
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
  try {
    const data = await apiCall('/timezone');
    _practiceTz = data.timezone || 'UTC';
    _tzOptions = data.available || [];
  } catch (e) {
    _practiceTz = 'UTC';
  }

  updateTzHints();
  updateEditorTzLabels();
}

function updateEditorTzLabels() {
  var icon = '<svg style="width:13px;height:13px;vertical-align:-2px;margin-right:3px;" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
  var selectedPids = (msProvider ? msProvider.getValue() : []).concat(msBlockProvider ? msBlockProvider.getValue() : []).concat(msHoldProvider ? msHoldProvider.getValue() : []);
  var editorProvTz = selectedPids.length === 1 ? providerTz(selectedPids[0]) : _practiceTz;
  var hint = icon + 'Times in provider\u2019s timezone: <strong>' + editorProvTz + '</strong>';
  ['single-event-tz-hint', 'block-event-tz-hint', 'weekly-avail-tz-hint', 'weekly-block-tz-hint', 'weekly-hold-tz-hint'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = hint;
  });
}

function getEditorTimezone() {
  return null;  // Always use provider's timezone
}



/* ---------- Settings panel ---------- */

async function renderSettingsPanel() {
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
    Object.keys(serverTzs).forEach(function(pid) {
      _providerTzMap[pid] = { timezone: serverTzs[pid], explicit: true };
    });
  } catch (e) {}

  var container = document.getElementById('provider-tz-list');
  if (!container) return;

  if (_providers.length === 0) {
    container.innerHTML = '<div class="empty-state">No providers found</div>';
    return;
  }

  var sortedProviders = _providers.slice().sort(function(a, b) {
    var aLast = (a.name || '').split(' ').slice(-1)[0].toLowerCase();
    var bLast = (b.name || '').split(' ').slice(-1)[0].toLowerCase();
    return aLast.localeCompare(bLast);
  });

  var html = '<table class="settings-tz-table"><thead><tr><th>Provider</th><th>Timezone</th><th>Status</th></tr></thead><tbody>';
  sortedProviders.forEach(function(p) {
    var entry = _providerTzMap[p.id];
    var isExplicit = entry && entry.explicit;
    var currentTz = isExplicit ? entry.timezone : '';
    html += '<tr>';
    html += '<td><strong>' + (p.name || p.id) + '</strong></td>';
    html += '<td><select class="input provider-tz-dropdown" data-provider-id="' + p.id + '" onchange="saveProviderTz(this)">';
    html += '<option value=""' + (!currentTz ? ' selected' : '') + '>— Select timezone —</option>';
    COMMON_TZS.forEach(function(tz) {
      html += '<option value="' + tz + '"' + (tz === currentTz ? ' selected' : '') + '>' + tz + '</option>';
    });
    html += '</select></td>';
    html += '<td>';
    if (isExplicit) {
      html += '<span class="badge badge-active">Set</span>';
    } else {
      html += '<span class="badge badge-expired">Not Set</span>';
    }
    html += '</td>';
    html += '</tr>';
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

async function saveProviderTz(selectEl) {
  var pid = selectEl.getAttribute('data-provider-id');
  var tz = selectEl.value;
  if (!tz) return;
  var data = await apiCall('/provider-timezone', {
    method: 'PUT',
    body: JSON.stringify({ provider_id: pid, timezone: tz }),
  });
  if (data.error) {
    showMsg(data.error, 'error');
  } else {
    showMsg(data.message || 'Timezone updated', 'success');
    // Update local TZ map directly — no overview dependency
    _providerTzMap[pid] = { timezone: tz, explicit: true };
    // Also refresh overview for accordion display
    try {
      var ovData = await apiCall('/overview');
      _overviewData = ovData.providers || [];
      _syncProviderTzMapFromOverview();
    } catch (e) {}
    renderSettingsPanel();
  }
}

async function applyBulkTimezone() {
  var bulkSel = document.getElementById('bulk-tz-select');
  if (!bulkSel || !bulkSel.value) return;
  var tz = bulkSel.value;
  var pids = _providers.map(function(p) { return p.id; });
  if (pids.length === 0) { showMsg('No providers loaded', 'error'); return; }
  if (!confirm('Set timezone to ' + tz + ' for all ' + pids.length + ' providers?')) return;
  var data = await apiCall('/provider-timezones/bulk', {
    method: 'PUT',
    body: JSON.stringify({ provider_ids: pids, timezone: tz }),
  });
  if (data.error) {
    showMsg(data.error, 'error');
  } else {
    showMsg(data.message || 'Timezones updated', 'success');
    // Update local TZ map for ALL providers — no overview dependency
    pids.forEach(function(pid) {
      _providerTzMap[pid] = { timezone: tz, explicit: true };
    });
    // Also refresh overview for accordion display
    try {
      var ovData = await apiCall('/overview');
      _overviewData = ovData.providers || [];
      _syncProviderTzMapFromOverview();
    } catch (e) {}
    renderSettingsPanel();
  }
}

/* ---------- Holds ---------- */

function editHold(holdJson) {
  var h = JSON.parse(holdJson);
  resetForm();
  selectType('hold');
  document.getElementById('type-selector-section').style.display = 'none';
  _skipDirtyCheck = true;
  showTab('editor');
  document.getElementById('editor-title').textContent = 'Edit Hold';
  document.getElementById('editing_hold_id').value = h.id || '';
  document.getElementById('editing_hold_group_id').value = h.group_id || '';
  document.getElementById('hold_reason').value = h.reason || '';
  document.getElementById('hold_type_select').value = h.hold_type || 'same_day';
  document.getElementById('hold_effective_start').value = h.effective_start || '';
  document.getElementById('hold_effective_end').value = h.effective_end || '';
  var hasEnd = !!h.effective_end;
  document.getElementById('hold_no_end_date').checked = !hasEnd;
  toggleNoEndDate('hold_effective_end', !hasEnd);
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
    html += '<span class="day-label">' + DAY_ABBR[day] + '</span>';
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
  wrap.innerHTML = '<input class="time-input" type="time" value="' + (startVal || '') + '">' +
    '<span class="time-sep">\u2192</span>' +
    '<input class="time-input" type="time" value="' + (endVal || '') + '">';
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

/* ---------- Initialize ---------- */

msProvider = new MultiSelect('ms-provider', { placeholder: 'Search providers...', displayKey: 'name', valueKey: 'id' });
msLocation = new MultiSelect('ms-location', { placeholder: 'Search locations...', displayKey: 'name', valueKey: 'id' });
msVisitType = new MultiSelect('ms-visit-type', { placeholder: 'Search visit types...', displayKey: 'name', valueKey: 'id' });
msBlockProvider = new MultiSelect('ms-block-provider', { placeholder: 'Search providers...', displayKey: 'name', valueKey: 'id' });
msBlockLocation = new MultiSelect('ms-block-location', { placeholder: 'Search locations...', displayKey: 'name', valueKey: 'id' });
msHoldProvider = new MultiSelect('ms-hold-provider', { placeholder: 'Search providers...', displayKey: 'name', valueKey: 'id' });
msHoldLocation = new MultiSelect('ms-hold-location', { placeholder: 'Search locations...', displayKey: 'name', valueKey: 'id' });
msFilterProvider = new MultiSelect('ms-filter-provider', { placeholder: 'Filter by provider...', displayKey: 'name', valueKey: 'id' });
// msSettingsStaff removed — access control now via plugin secret

// Re-render accordion whenever filter MultiSelect changes
const _origUpdateChips = msFilterProvider.updateChips.bind(msFilterProvider);
msFilterProvider.updateChips = function() { _origUpdateChips(); renderAccordion(); };

// Update editor TZ labels when provider selection changes
var _origProvChips = msProvider.updateChips.bind(msProvider);
msProvider.updateChips = function() { _origProvChips(); updateEditorTzLabels(); };
var _origBlockProvChips = msBlockProvider.updateChips.bind(msBlockProvider);
msBlockProvider.updateChips = function() { _origBlockProvChips(); updateEditorTzLabels(); };
var _origHoldProvChips = msHoldProvider.updateChips.bind(msHoldProvider);
msHoldProvider.updateChips = function() { _origHoldProvChips(); updateEditorTzLabels(); };

initScheduleEditor();
initRecurringBlockScheduleEditor();
initHoldScheduleEditor();

try {
  if (window.__PRELOADED__) {
    // Use server-rendered data instead of fetch()
    var P = window.__PRELOADED__;

    _providers = (P.providers && P.providers.providers) || [];
    var provItems = _providers.map(function(p) { return { id: p.id, name: p.name, npi: p.npi_number || '' }; });
    if (msProvider) msProvider.setItems(provItems);
    if (msBlockProvider) msBlockProvider.setItems(provItems);
    if (msHoldProvider) msHoldProvider.setItems(provItems);
    if (msFilterProvider) msFilterProvider.setItems(provItems);
    // Staff access control now via plugin secret — no msSettingsStaff

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
    if (name === 'editor') {
      if (!_skipDirtyCheck) resetForm();
    } else if (name === 'settings') {
      renderSettingsPanel();
    } else {
      if (!_skipDirtyCheck) loadOverview();
    }
    _skipDirtyCheck = false;
    if (!calledFromShowTab) {
      showTab._fromEvent = false;
    }
    try { history.replaceState(null, '', '#' + name); } catch (ex) {}
  });
}

// Restore active tab from URL hash
var _initHash = location.hash.replace('#', '');
if (_initHash === 'settings' || _initHash === 'editor') {
  showTab(_initHash);
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
  showTab('availability');
});
