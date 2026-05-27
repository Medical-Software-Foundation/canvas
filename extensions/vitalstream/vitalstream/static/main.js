// State for interval-based vitals capture
let selectedRow = null;
let intervalSelections = {};
let mockInterval = null;
let sessionStartTime = null; // timestamp of first reading
let activeSocket = null;
let sessionClosed = false;
let seenTimestamps = new Set();  // dedupe across backfill + WS

// Map interval labels to Spravato charting app's row_id values (0, 1, 2).
var INTERVAL_ROW_IDS = {
  'Pre-administration': '0',
  '40-min post': '1',
  'Pre-discharge': '2',
};

// Raw reading log used to render the live table and compute averages.
// Each entry: { elapsedMin, time, displayTime, hr, sys, dia, rr, spo2 }
var allReadings = [];

window.addEventListener("load", () => {{
  var session_id = window._caretaker.session_id;
  var subdomain = window._caretaker.subdomain;
  var initialStatus = window._caretaker.session_status || "open";

  new QRCode(
    document.getElementById("qr-code"),
    {
      text: session_id,
      width: 128,
      height: 128,
    }
  );

  // Set up save intervals button (Spravato workflow only — does not end session).
  document.getElementById('save-intervals-btn').addEventListener('click', () => {
    saveIntervalsToChart(window._caretaker.session_id, subdomain);
  });

  // Set up end-session-and-save-summary button.
  var endBtn = document.getElementById('end-session-btn');
  if (endBtn) {
    endBtn.addEventListener('click', () => {
      endSessionAndSave(window._caretaker.session_id, subdomain);
    });
  }

  // Set up mock vitals button if enabled
  var mockBtn = document.getElementById('mock-vitals-btn');
  if (mockBtn) {
    mockBtn.addEventListener('click', () => {
      toggleMockVitals(window._caretaker.session_id, subdomain);
    });
  }

  // Live filter for the readings feed.
  var filterInput = document.getElementById('live-readings-filter');
  if (filterInput) {
    filterInput.addEventListener('input', applyLiveFilter);
  }

  // Recompute the increment averages when the size dropdown changes.
  var incrementSelect = document.getElementById('increment-size');
  if (incrementSelect) {
    incrementSelect.addEventListener('change', recomputeAverages);
  }

  // Persist form inputs to the server cache so they survive pane reopens.
  // Treatment select also fires toggleMode() inline via its onchange attr;
  // we just need to additionally save on change.
  ['treatment-type', 'increment-size', 'wrist-placement',
   'treatment-start', 'treatment-end'].forEach((id) => {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', () => {
        schedulePreferenceSave(window._caretaker.session_id, subdomain);
      });
    }
  });

  // Backfill any previously persisted readings, then open the WebSocket.
  // Reopening the chart pane resumes from history rather than starting blank.
  backfillReadings(session_id, subdomain)
    .catch((err) => console.error('VitalStream backfill failed', err))
    .finally(() => {
      if (initialStatus === 'closed') {
        markSessionClosed();
      }
      // TODO: convert hyphens in UUID to underscores
      connectToWebsocket(session_id.replaceAll('-', '_'), subdomain);
      // Auto-resume the mock-vitals timer if it was running before the user
      // closed the chart pane. localStorage survives the modal teardown so
      // testers don't have to re-click "Mock Vitals" on every reopen.
      if (!sessionClosed && isMockActiveInStorage(session_id)) {
        startMockVitals(session_id, subdomain);
      }
    });
}});

function mockStorageKey(session_id) {
  return 'vs_mock_active_' + session_id;
}

function isMockActiveInStorage(session_id) {
  try {
    return localStorage.getItem(mockStorageKey(session_id)) === '1';
  } catch (e) {
    return false;
  }
}

function setMockActiveInStorage(session_id, active) {
  try {
    if (active) {
      localStorage.setItem(mockStorageKey(session_id), '1');
    } else {
      localStorage.removeItem(mockStorageKey(session_id));
    }
  } catch (e) {
    // Ignore — localStorage may be unavailable in some embeds.
  }
}

async function backfillReadings(session_id, subdomain) {
  var resp = await fetch(
    `https://${subdomain}.canvasmedical.com/plugin-io/api/vitalstream/vitalstream-ui/sessions/${session_id}/readings/`,
    { method: 'GET', credentials: 'include' }
  );
  if (!resp.ok) return;
  var body = await resp.json();
  // Apply persisted preferences BEFORE handling readings so that the
  // increment-size affects the very first recomputeAverages() call.
  if (body.preferences) applyPreferences(body.preferences);
  var readings = body.readings || [];
  // Hide the QR instructions if we already have data — the device is paired.
  if (readings.length > 0) ensureInstructionsAreClosed();
  for (var r of readings) {
    handleNewDiscreteMeasurement(r.timestamp, {
      hr: r.hr,
      sys: r.sys,
      dia: r.dia,
      resp: r.resp,
      spo2: r.spo2,
    });
  }
  if (body.status === 'closed') {
    markSessionClosed();
  }
}

function applyPreferences(prefs) {
  if (!prefs || typeof prefs !== 'object') return;
  var treatment = document.getElementById('treatment-type');
  if (treatment && prefs.treatment_type) {
    treatment.value = prefs.treatment_type;
    toggleMode();
  }
  var increment = document.getElementById('increment-size');
  if (increment && prefs.increment_minutes) {
    increment.value = String(prefs.increment_minutes);
  }
  var wrist = document.getElementById('wrist-placement');
  if (wrist && prefs.bp_placement) {
    wrist.value = prefs.bp_placement;
  }
  var tStart = document.getElementById('treatment-start');
  if (tStart && prefs.treatment_start) {
    tStart.value = prefs.treatment_start;
  }
  var tEnd = document.getElementById('treatment-end');
  if (tEnd && prefs.treatment_end) {
    tEnd.value = prefs.treatment_end;
  }
}

function currentPreferences() {
  return {
    treatment_type: (document.getElementById('treatment-type') || {}).value || '',
    increment_minutes: parseInt(
      (document.getElementById('increment-size') || {}).value || '10', 10
    ),
    bp_placement: (document.getElementById('wrist-placement') || {}).value || 'left_wrist',
    treatment_start: (document.getElementById('treatment-start') || {}).value || '',
    treatment_end: (document.getElementById('treatment-end') || {}).value || '',
  };
}

var prefsSaveTimer = null;

function schedulePreferenceSave(session_id, subdomain) {
  if (sessionClosed) return;  // closed sessions own their saved-state forever
  // Debounce so dragging the time-picker doesn't fire dozens of PUTs.
  if (prefsSaveTimer) clearTimeout(prefsSaveTimer);
  prefsSaveTimer = setTimeout(() => savePreferences(session_id, subdomain), 400);
}

function savePreferences(session_id, subdomain) {
  fetch(
    `https://${subdomain}.canvasmedical.com/plugin-io/api/vitalstream/vitalstream-ui/sessions/${session_id}/preferences/`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(currentPreferences()),
    }
  ).catch((err) => console.error('VitalStream preference save failed', err));
}

function connectToWebsocket(session_id, subdomain) {
  const socket = new WebSocket("wss://" + subdomain + ".canvasmedical.com/plugin-io/ws/vitalstream/" + session_id + "/");
  activeSocket = socket;

  socket.addEventListener("open", (event) => {
    if (sessionClosed) {
      setSessionStatus("Session ended");
      return;
    }
    if (allReadings.length === 0) {
      setSessionStatus("Waiting for data...");
    } else {
      setSessionStatus("Connected", true);
    }
  });

  socket.addEventListener("message", (event) => {
    var payload = JSON.parse(event.data).message || {};

    if (payload.event_type === 'session_closed') {
      markSessionClosed();
      return;
    }

    if (sessionClosed) return;  // ignore late readings after close

    if (Object.hasOwn(payload, "measurements")) {
      ensureInstructionsAreClosed();
      setSessionStatus("Receiving data...", true);
      setEndSessionVisible(true);
      for (var timestamp of Object.keys(payload.measurements).sort()) {
        handleNewDiscreteMeasurement(timestamp, payload.measurements[timestamp]);
      }
    }
  });

  socket.addEventListener("close", (event) => {
    if (sessionClosed) {
      setSessionStatus("Session ended");
      return;
    }
    setSessionStatus("Disconnected. Attempting to reconnect.");
    setTimeout(() => connectToWebsocket(session_id, subdomain), 3000);
  });

  socket.addEventListener("error", (event) => {
    setSessionStatus("Connection error");
  });
}

function markSessionClosed() {
  if (sessionClosed) return;
  sessionClosed = true;
  setSessionStatus("Session ended");
  setEndSessionVisible(false);

  // Stop mock generator if it's running, and clear its auto-resume flag so
  // the next pane reopen doesn't re-arm it against a closed session.
  setMockActiveInStorage(window._caretaker.session_id, false);
  if (mockInterval) {
    clearInterval(mockInterval);
    mockInterval = null;
  }
  var mockBtn = document.getElementById('mock-vitals-btn');
  if (mockBtn) {
    mockBtn.textContent = 'Mock Vitals';
    mockBtn.classList.remove('mock-active');
    mockBtn.disabled = true;
  }

  // Disable spravato save-intervals once the session is officially over.
  var saveIntervalsBtn = document.getElementById('save-intervals-btn');
  if (saveIntervalsBtn) saveIntervalsBtn.disabled = true;
  document.querySelectorAll('.capture-btn').forEach((b) => b.disabled = true);

  // Freeze the input form so its visible values can't drift away from the
  // ones that were submitted with the end-session POST and rendered into
  // the saved CustomCommand. Without this, a user changing the inputs
  // post-save would see UI values that contradict what's in the chart.
  ['treatment-type', 'increment-size', 'wrist-placement',
   'treatment-start', 'treatment-end'].forEach((id) => {
    var el = document.getElementById(id);
    if (el) el.disabled = true;
  });
}

function setEndSessionVisible(visible) {
  var btn = document.getElementById('end-session-btn');
  if (!btn) return;
  if (sessionClosed) {
    btn.style.display = 'none';
    return;
  }
  btn.style.display = visible ? '' : 'none';
}

function createTableCell(content) {
  const cell = document.createElement("td");
  if (typeof content !== 'undefined') {
    const cellContent = document.createTextNode(content);
    cell.appendChild(cellContent);
  }
  return cell;
}

function toHHMM(date) {
  return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
}

function handleNewDiscreteMeasurement(timestamp, data) {
  var dt = new Date(timestamp);
  var isoTimestamp = dt.toISOString();

  // Dedupe across backfill (HTTP) and the live WebSocket stream — a reading
  // that arrived just before we fetched /readings/ could otherwise show twice.
  if (seenTimestamps.has(isoTimestamp)) return;
  seenTimestamps.add(isoTimestamp);

  if (!sessionStartTime) sessionStartTime = dt.getTime();
  var elapsedMin = (dt.getTime() - sessionStartTime) / 60000;
  var displayTime = dt.toLocaleTimeString("en-US");
  var hhmmTime = toHHMM(dt);

  allReadings.push({
    elapsedMin: elapsedMin,
    timestamp: isoTimestamp,
    time: hhmmTime,
    displayTime: displayTime,
    hr: data.hr,
    sys: data.sys,
    dia: data.dia,
    rr: data.resp,
    spo2: data.spo2,
  });

  appendLiveRow(displayTime, hhmmTime, isoTimestamp, data);
  updateLiveCount();
  recomputeAverages();
  // First reading at any point in the session means there's something to
  // end-and-save. Keep hidden once we've closed the session.
  setEndSessionVisible(!sessionClosed);
}

function formatBPDisplay(sys, dia) {
  if (typeof sys === 'undefined' && typeof dia === 'undefined') return undefined;
  if (typeof sys === 'undefined') return '???/' + dia;
  if (typeof dia === 'undefined') return sys + '/???';
  return sys + '/' + dia;
}

function appendLiveRow(displayTime, hhmmTime, isoTimestamp, data) {
  var tbody = document.querySelector('#live-readings-table tbody');
  if (!tbody) return;

  var row = document.createElement('tr');
  row.appendChild(createTableCell(displayTime));
  row.appendChild(createTableCell(data.hr));
  row.appendChild(createTableCell(formatBPDisplay(data.sys, data.dia)));
  row.appendChild(createTableCell(data.resp));
  row.appendChild(createTableCell(data.spo2));

  row.dataset.timestamp = isoTimestamp || '';
  row.dataset.time = hhmmTime;
  row.dataset.displayTime = displayTime;
  row.dataset.hr = data.hr !== undefined ? data.hr : '';
  row.dataset.bpSys = data.sys !== undefined ? data.sys : '';
  row.dataset.bpDia = data.dia !== undefined ? data.dia : '';
  row.dataset.rr = data.resp !== undefined ? data.resp : '';
  row.dataset.spo2 = data.spo2 !== undefined ? data.spo2 : '';

  row.addEventListener('click', () => {
    var prev = document.querySelector('#live-readings-table tr.selected');
    if (prev) prev.classList.remove('selected');
    row.classList.add('selected');
    selectedRow = {
      timestamp: row.dataset.timestamp,
      time: row.dataset.time,
      displayTime: row.dataset.displayTime,
      hr: row.dataset.hr,
      bp_sys: row.dataset.bpSys,
      bp_dia: row.dataset.bpDia,
      rr: row.dataset.rr,
      spo2: row.dataset.spo2,
    };
  });

  tbody.prepend(row);

  // Hide immediately if there's an active filter that excludes this row.
  var filter = currentFilterValue();
  if (filter && !rowMatchesFilter(row, filter)) row.style.display = 'none';
}

function updateLiveCount() {
  var el = document.getElementById('live-readings-count');
  if (!el) return;
  el.textContent = allReadings.length + (allReadings.length === 1 ? ' reading' : ' readings');
}

function currentFilterValue() {
  var input = document.getElementById('live-readings-filter');
  return input ? (input.value || '').trim().toLowerCase() : '';
}

function rowMatchesFilter(row, filter) {
  var time = (row.dataset.displayTime || '').toLowerCase();
  var hhmm = (row.dataset.time || '').toLowerCase();
  return time.indexOf(filter) !== -1 || hhmm.indexOf(filter) !== -1;
}

function applyLiveFilter() {
  var filter = currentFilterValue();
  var rows = document.querySelectorAll('#live-readings-table tbody tr');
  rows.forEach(function (row) {
    row.style.display = (!filter || rowMatchesFilter(row, filter)) ? '' : 'none';
  });
}

function computeIncrementBuckets() {
  if (allReadings.length === 0) return [];
  var incrementMin = getIncrementSizeMinutes();
  // Average the 30 seconds before and after each increment mark.
  var windowMin = 0.5;

  var maxElapsedMin = 0;
  for (var i = 0; i < allReadings.length; i++) {
    if (allReadings[i].elapsedMin > maxElapsedMin) maxElapsedMin = allReadings[i].elapsedMin;
  }

  var buckets = [];
  for (var t = 0; t <= maxElapsedMin + windowMin; t += incrementMin) {
    var lo = t - windowMin;
    var hi = t + windowMin;

    var totals = { hr: 0, sys: 0, dia: 0, rr: 0, spo2: 0 };
    var counts = { hr: 0, sys: 0, dia: 0, rr: 0, spo2: 0 };
    var windowCount = 0;
    var firstReading = null;

    for (var j = 0; j < allReadings.length; j++) {
      var r = allReadings[j];
      if (r.elapsedMin < lo || r.elapsedMin > hi) continue;
      windowCount++;
      if (firstReading === null) firstReading = r;
      if (r.hr !== undefined) { totals.hr += Number(r.hr); counts.hr++; }
      if (r.sys !== undefined) { totals.sys += Number(r.sys); counts.sys++; }
      if (r.dia !== undefined) { totals.dia += Number(r.dia); counts.dia++; }
      if (r.rr !== undefined) { totals.rr += Number(r.rr); counts.rr++; }
      if (r.spo2 !== undefined) { totals.spo2 += Number(r.spo2); counts.spo2++; }
    }

    if (windowCount === 0) continue;

    var timeStr = '';
    var timestampStr = '';
    if (sessionStartTime) {
      var bucketDate = new Date(sessionStartTime + t * 60 * 1000);
      timeStr = toHHMM(bucketDate);
      timestampStr = bucketDate.toISOString();
    } else if (firstReading) {
      timeStr = firstReading.time || '';
      timestampStr = firstReading.timestamp || '';
    }

    buckets.push({
      label: t + ' min',
      count: String(windowCount),
      timestamp: timestampStr,
      time: timeStr,
      elapsedMin: t,
      hr: counts.hr ? String(Math.round(totals.hr / counts.hr)) : '',
      bp_sys: counts.sys ? String(Math.round(totals.sys / counts.sys)) : '',
      bp_dia: counts.dia ? String(Math.round(totals.dia / counts.dia)) : '',
      rr: counts.rr ? String(Math.round(totals.rr / counts.rr)) : '',
      spo2: counts.spo2 ? String(Math.round(totals.spo2 / counts.spo2)) : '',
    });
  }
  return buckets;
}

function recomputeAverages() {
  var tbody = document.querySelector('#averages-table tbody');
  if (!tbody) return;
  var rows = computeIncrementBuckets();
  tbody.innerHTML = '';
  rows.forEach(function (b) {
    var tr = document.createElement('tr');
    tr.appendChild(createTableCell(b.label));
    tr.appendChild(createTableCell(b.count));
    tr.appendChild(createTableCell(b.hr || '--'));
    var bp = (b.bp_sys && b.bp_dia) ? b.bp_sys + '/' + b.bp_dia : '--';
    tr.appendChild(createTableCell(bp));
    tr.appendChild(createTableCell(b.rr || '--'));
    tr.appendChild(createTableCell(b.spo2 || '--'));
    tbody.appendChild(tr);
  });
}

// The averages table is a live preview only. Phase classification and the
// trailing discharge bucket are computed server-side at end-session time so
// the persisted Observations and the displayed preview stay independently
// correct even if the client-side state drifts.

// Resolve a wall-clock HH:MM (from the treatment-start/end inputs) into
// minutes elapsed since sessionStartTime. The server can't do this itself
// because the reading timestamps are UTC and the HH:MM the user typed is
// in their browser's local timezone. Rolls forward one day if the candidate
// is more than 12 hours before session_start (cross-midnight session).
function hhmmToElapsedMin(hhmm) {
  if (!hhmm || !sessionStartTime) return null;
  var parts = hhmm.split(':');
  if (parts.length < 2) return null;
  var hours = parseInt(parts[0], 10);
  var mins = parseInt(parts[1], 10);
  if (isNaN(hours) || isNaN(mins)) return null;
  var session = new Date(sessionStartTime);
  var candidate = new Date(
    session.getFullYear(), session.getMonth(), session.getDate(), hours, mins, 0, 0
  );
  if (candidate.getTime() < session.getTime() - 12 * 60 * 60 * 1000) {
    candidate.setDate(candidate.getDate() + 1);
  }
  return (candidate.getTime() - session.getTime()) / 60000;
}

function assignToInterval(intervalName) {
  if (!selectedRow) {
    alert('Select a reading from the feed first.');
    return;
  }

  intervalSelections[intervalName] = {
    ...selectedRow,
    label: intervalName,
    row_id: INTERVAL_ROW_IDS[intervalName] || '',
    temp: '',
    comments: '',
  };
  delete intervalSelections[intervalName].displayTime;

  if (Object.keys(intervalSelections).length === Object.keys(INTERVAL_ROW_IDS).length) {
    document.getElementById('save-intervals-btn').style.display = '';
  }

  var intervalRow = document.querySelector('#interval-table tr[data-interval="' + intervalName + '"]');
  if (intervalRow) {
    intervalRow.querySelector('.iv-time').textContent = selectedRow.displayTime || selectedRow.time;
    intervalRow.querySelector('.iv-hr').textContent = selectedRow.hr || '--';
    var bp = (selectedRow.bp_sys && selectedRow.bp_dia) ? selectedRow.bp_sys + '/' + selectedRow.bp_dia : '--';
    intervalRow.querySelector('.iv-bp').textContent = bp;
    intervalRow.querySelector('.iv-resp').textContent = selectedRow.rr || '--';
    intervalRow.querySelector('.iv-spo2').textContent = selectedRow.spo2 || '--';
  }
}

async function saveIntervalsToChart(session_id, subdomain) {
  var rows = Object.values(intervalSelections);
  if (rows.length === 0) {
    alert('Assign at least one interval before saving.');
    return;
  }

  var btn = document.getElementById('save-intervals-btn');
  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    var resp = await fetch(
      `https://${subdomain}.canvasmedical.com/plugin-io/api/vitalstream/vitalstream-ui/sessions/${session_id}/save-intervals/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          rows: rows,
          bp_placement: document.getElementById('wrist-placement').value,
        }),
      }
    );

    if (resp.ok) {
      btn.textContent = 'Saved to Chart!';
      document.querySelectorAll('.capture-btn').forEach(b => b.disabled = true);
    } else {
      btn.textContent = 'Error - Try Again';
      btn.disabled = false;
    }
  } catch (e) {
    btn.textContent = 'Error - Try Again';
    btn.disabled = false;
  }
}

function toggleMode() {
  var isSpravato = document.getElementById('treatment-type').value === 'spravato';
  document.getElementById('interval-selection').style.display = isSpravato ? 'block' : 'none';
}

function getIncrementSizeMinutes() {
  var el = document.getElementById('increment-size');
  var val = el ? parseInt(el.value, 10) : 10;
  return [5, 10, 15, 20, 30].includes(val) ? val : 10;
}

async function endSessionAndSave(session_id, subdomain) {
  if (sessionClosed) return;
  if (allReadings.length === 0) {
    alert('No readings to summarize.');
    return;
  }
  if (!confirm('End this VitalStream session and save the summary to the chart? Further readings from the device will be rejected.')) {
    return;
  }

  // Show a saving state, but DO NOT mark the session closed until the server
  // confirms. Closing optimistically meant the inputs could be edited after
  // save while the server preserved a stale snapshot — the visible UI then
  // didn't match the saved command.
  var btn = document.getElementById('end-session-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Saving...';
  }
  setSessionStatus('Saving...');

  var treatmentStart = (document.getElementById('treatment-start').value || '').trim();
  var treatmentEnd = (document.getElementById('treatment-end').value || '').trim();
  // Elapsed-minute offsets done client-side so the user's local-time HH:MM
  // inputs resolve correctly against the reading_time stored in UTC.
  var startElapsedMin = hhmmToElapsedMin(treatmentStart);
  var endElapsedMin = hhmmToElapsedMin(treatmentEnd);

  try {
    var resp = await fetch(
      `https://${subdomain}.canvasmedical.com/plugin-io/api/vitalstream/vitalstream-ui/sessions/${session_id}/end-session/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          summary_increment_minutes: getIncrementSizeMinutes(),
          bp_placement: document.getElementById('wrist-placement').value,
          treatment_start: treatmentStart,
          treatment_end: treatmentEnd,
          treatment_start_elapsed_min: startElapsedMin,
          treatment_end_elapsed_min: endElapsedMin,
          // getTimezoneOffset() is positive west of UTC, e.g. 240 in EDT.
          tz_offset_minutes: new Date().getTimezoneOffset(),
        }),
      }
    );

    if (resp.ok) {
      // Server has flipped status=closed and written the command. Only now
      // do we freeze the UI — guarantees the saved command matches what the
      // user can still see on screen.
      markSessionClosed();
      setSessionStatus('Session ended — saved to chart');
    } else {
      setSessionStatus('Error saving summary — try again');
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'End Session & Save Summary';
      }
    }
  } catch (e) {
    setSessionStatus('Error saving summary — try again');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'End Session & Save Summary';
    }
  }
}

function toggleMockVitals(session_id, subdomain) {
  if (sessionClosed) return;
  if (mockInterval) {
    stopMockVitals(session_id);
  } else {
    startMockVitals(session_id, subdomain);
  }
}

function startMockVitals(session_id, subdomain) {
  if (mockInterval) return;
  var btn = document.getElementById('mock-vitals-btn');
  if (btn) {
    btn.textContent = 'Stop Mock';
    btn.classList.add('mock-active');
  }
  setMockActiveInStorage(session_id, true);
  postMockVital(session_id, subdomain);
  mockInterval = setInterval(() => postMockVital(session_id, subdomain), 3000);
}

function stopMockVitals(session_id) {
  if (mockInterval) {
    clearInterval(mockInterval);
    mockInterval = null;
  }
  var btn = document.getElementById('mock-vitals-btn');
  if (btn) {
    btn.textContent = 'Mock Vitals';
    btn.classList.remove('mock-active');
  }
  setMockActiveInStorage(session_id, false);
}

function postMockVital(session_id, subdomain) {
  fetch(
    `https://${subdomain}.canvasmedical.com/plugin-io/api/vitalstream/vitalstream-ui/sessions/${session_id}/mock-vitals/`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
}

let sessionTimeout = null;

function setSessionStatus(message, setIdleTimer = false) {
  const status = document.getElementById('session-status');
  status.innerHTML = message;

  clearTimeout(sessionTimeout);

  if (setIdleTimer) {
    sessionTimeout = setTimeout(() => {
      status.innerHTML = 'Connected, idle...';
    }, 5000);
  }
}

function ensureInstructionsAreClosed() {
  var details = document.getElementById('instructions');
  if (details.hasAttribute('open')) {
    details.removeAttribute('open');
  }
}

// We use qrcode.js, included below the license.
//
// https://github.com/davidshimjs/qrcodejs/blob/master/qrcode.min.js
// The MIT License (MIT)
// ---------------------
// Copyright (c) 2012 davidshimjs
// 
// Permission is hereby granted, free of charge,
// to any person obtaining a copy of this software and associated documentation files (the "Software"),
// to deal in the Software without restriction,
// including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
// and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
// subject to the following conditions:
// 
// The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
// 
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
var QRCode;!function(){function a(a){this.mode=c.MODE_8BIT_BYTE,this.data=a,this.parsedData=[];for(var b=[],d=0,e=this.data.length;e>d;d++){var f=this.data.charCodeAt(d);f>65536?(b[0]=240|(1835008&f)>>>18,b[1]=128|(258048&f)>>>12,b[2]=128|(4032&f)>>>6,b[3]=128|63&f):f>2048?(b[0]=224|(61440&f)>>>12,b[1]=128|(4032&f)>>>6,b[2]=128|63&f):f>128?(b[0]=192|(1984&f)>>>6,b[1]=128|63&f):b[0]=f,this.parsedData=this.parsedData.concat(b)}this.parsedData.length!=this.data.length&&(this.parsedData.unshift(191),this.parsedData.unshift(187),this.parsedData.unshift(239))}function b(a,b){this.typeNumber=a,this.errorCorrectLevel=b,this.modules=null,this.moduleCount=0,this.dataCache=null,this.dataList=[]}function i(a,b){if(void 0==a.length)throw new Error(a.length+"/"+b);for(var c=0;c<a.length&&0==a[c];)c++;this.num=new Array(a.length-c+b);for(var d=0;d<a.length-c;d++)this.num[d]=a[d+c]}function j(a,b){this.totalCount=a,this.dataCount=b}function k(){this.buffer=[],this.length=0}function m(){return"undefined"!=typeof CanvasRenderingContext2D}function n(){var a=!1,b=navigator.userAgent;return/android/i.test(b)&&(a=!0,aMat=b.toString().match(/android ([0-9]\.[0-9])/i),aMat&&aMat[1]&&(a=parseFloat(aMat[1]))),a}function r(a,b){for(var c=1,e=s(a),f=0,g=l.length;g>=f;f++){var h=0;switch(b){case d.L:h=l[f][0];break;case d.M:h=l[f][1];break;case d.Q:h=l[f][2];break;case d.H:h=l[f][3]}if(h>=e)break;c++}if(c>l.length)throw new Error("Too long data");return c}function s(a){var b=encodeURI(a).toString().replace(/\%[0-9a-fA-F]{2}/g,"a");return b.length+(b.length!=a?3:0)}a.prototype={getLength:function(){return this.parsedData.length},write:function(a){for(var b=0,c=this.parsedData.length;c>b;b++)a.put(this.parsedData[b],8)}},b.prototype={addData:function(b){var c=new a(b);this.dataList.push(c),this.dataCache=null},isDark:function(a,b){if(0>a||this.moduleCount<=a||0>b||this.moduleCount<=b)throw new Error(a+","+b);return this.modules[a][b]},getModuleCount:function(){return this.moduleCount},make:function(){this.makeImpl(!1,this.getBestMaskPattern())},makeImpl:function(a,c){this.moduleCount=4*this.typeNumber+17,this.modules=new Array(this.moduleCount);for(var d=0;d<this.moduleCount;d++){this.modules[d]=new Array(this.moduleCount);for(var e=0;e<this.moduleCount;e++)this.modules[d][e]=null}this.setupPositionProbePattern(0,0),this.setupPositionProbePattern(this.moduleCount-7,0),this.setupPositionProbePattern(0,this.moduleCount-7),this.setupPositionAdjustPattern(),this.setupTimingPattern(),this.setupTypeInfo(a,c),this.typeNumber>=7&&this.setupTypeNumber(a),null==this.dataCache&&(this.dataCache=b.createData(this.typeNumber,this.errorCorrectLevel,this.dataList)),this.mapData(this.dataCache,c)},setupPositionProbePattern:function(a,b){for(var c=-1;7>=c;c++)if(!(-1>=a+c||this.moduleCount<=a+c))for(var d=-1;7>=d;d++)-1>=b+d||this.moduleCount<=b+d||(this.modules[a+c][b+d]=c>=0&&6>=c&&(0==d||6==d)||d>=0&&6>=d&&(0==c||6==c)||c>=2&&4>=c&&d>=2&&4>=d?!0:!1)},getBestMaskPattern:function(){for(var a=0,b=0,c=0;8>c;c++){this.makeImpl(!0,c);var d=f.getLostPoint(this);(0==c||a>d)&&(a=d,b=c)}return b},createMovieClip:function(a,b,c){var d=a.createEmptyMovieClip(b,c),e=1;this.make();for(var f=0;f<this.modules.length;f++)for(var g=f*e,h=0;h<this.modules[f].length;h++){var i=h*e,j=this.modules[f][h];j&&(d.beginFill(0,100),d.moveTo(i,g),d.lineTo(i+e,g),d.lineTo(i+e,g+e),d.lineTo(i,g+e),d.endFill())}return d},setupTimingPattern:function(){for(var a=8;a<this.moduleCount-8;a++)null==this.modules[a][6]&&(this.modules[a][6]=0==a%2);for(var b=8;b<this.moduleCount-8;b++)null==this.modules[6][b]&&(this.modules[6][b]=0==b%2)},setupPositionAdjustPattern:function(){for(var a=f.getPatternPosition(this.typeNumber),b=0;b<a.length;b++)for(var c=0;c<a.length;c++){var d=a[b],e=a[c];if(null==this.modules[d][e])for(var g=-2;2>=g;g++)for(var h=-2;2>=h;h++)this.modules[d+g][e+h]=-2==g||2==g||-2==h||2==h||0==g&&0==h?!0:!1}},setupTypeNumber:function(a){for(var b=f.getBCHTypeNumber(this.typeNumber),c=0;18>c;c++){var d=!a&&1==(1&b>>c);this.modules[Math.floor(c/3)][c%3+this.moduleCount-8-3]=d}for(var c=0;18>c;c++){var d=!a&&1==(1&b>>c);this.modules[c%3+this.moduleCount-8-3][Math.floor(c/3)]=d}},setupTypeInfo:function(a,b){for(var c=this.errorCorrectLevel<<3|b,d=f.getBCHTypeInfo(c),e=0;15>e;e++){var g=!a&&1==(1&d>>e);6>e?this.modules[e][8]=g:8>e?this.modules[e+1][8]=g:this.modules[this.moduleCount-15+e][8]=g}for(var e=0;15>e;e++){var g=!a&&1==(1&d>>e);8>e?this.modules[8][this.moduleCount-e-1]=g:9>e?this.modules[8][15-e-1+1]=g:this.modules[8][15-e-1]=g}this.modules[this.moduleCount-8][8]=!a},mapData:function(a,b){for(var c=-1,d=this.moduleCount-1,e=7,g=0,h=this.moduleCount-1;h>0;h-=2)for(6==h&&h--;;){for(var i=0;2>i;i++)if(null==this.modules[d][h-i]){var j=!1;g<a.length&&(j=1==(1&a[g]>>>e));var k=f.getMask(b,d,h-i);k&&(j=!j),this.modules[d][h-i]=j,e--,-1==e&&(g++,e=7)}if(d+=c,0>d||this.moduleCount<=d){d-=c,c=-c;break}}}},b.PAD0=236,b.PAD1=17,b.createData=function(a,c,d){for(var e=j.getRSBlocks(a,c),g=new k,h=0;h<d.length;h++){var i=d[h];g.put(i.mode,4),g.put(i.getLength(),f.getLengthInBits(i.mode,a)),i.write(g)}for(var l=0,h=0;h<e.length;h++)l+=e[h].dataCount;if(g.getLengthInBits()>8*l)throw new Error("code length overflow. ("+g.getLengthInBits()+">"+8*l+")");for(g.getLengthInBits()+4<=8*l&&g.put(0,4);0!=g.getLengthInBits()%8;)g.putBit(!1);for(;;){if(g.getLengthInBits()>=8*l)break;if(g.put(b.PAD0,8),g.getLengthInBits()>=8*l)break;g.put(b.PAD1,8)}return b.createBytes(g,e)},b.createBytes=function(a,b){for(var c=0,d=0,e=0,g=new Array(b.length),h=new Array(b.length),j=0;j<b.length;j++){var k=b[j].dataCount,l=b[j].totalCount-k;d=Math.max(d,k),e=Math.max(e,l),g[j]=new Array(k);for(var m=0;m<g[j].length;m++)g[j][m]=255&a.buffer[m+c];c+=k;var n=f.getErrorCorrectPolynomial(l),o=new i(g[j],n.getLength()-1),p=o.mod(n);h[j]=new Array(n.getLength()-1);for(var m=0;m<h[j].length;m++){var q=m+p.getLength()-h[j].length;h[j][m]=q>=0?p.get(q):0}}for(var r=0,m=0;m<b.length;m++)r+=b[m].totalCount;for(var s=new Array(r),t=0,m=0;d>m;m++)for(var j=0;j<b.length;j++)m<g[j].length&&(s[t++]=g[j][m]);for(var m=0;e>m;m++)for(var j=0;j<b.length;j++)m<h[j].length&&(s[t++]=h[j][m]);return s};for(var c={MODE_NUMBER:1,MODE_ALPHA_NUM:2,MODE_8BIT_BYTE:4,MODE_KANJI:8},d={L:1,M:0,Q:3,H:2},e={PATTERN000:0,PATTERN001:1,PATTERN010:2,PATTERN011:3,PATTERN100:4,PATTERN101:5,PATTERN110:6,PATTERN111:7},f={PATTERN_POSITION_TABLE:[[],[6,18],[6,22],[6,26],[6,30],[6,34],[6,22,38],[6,24,42],[6,26,46],[6,28,50],[6,30,54],[6,32,58],[6,34,62],[6,26,46,66],[6,26,48,70],[6,26,50,74],[6,30,54,78],[6,30,56,82],[6,30,58,86],[6,34,62,90],[6,28,50,72,94],[6,26,50,74,98],[6,30,54,78,102],[6,28,54,80,106],[6,32,58,84,110],[6,30,58,86,114],[6,34,62,90,118],[6,26,50,74,98,122],[6,30,54,78,102,126],[6,26,52,78,104,130],[6,30,56,82,108,134],[6,34,60,86,112,138],[6,30,58,86,114,142],[6,34,62,90,118,146],[6,30,54,78,102,126,150],[6,24,50,76,102,128,154],[6,28,54,80,106,132,158],[6,32,58,84,110,136,162],[6,26,54,82,110,138,166],[6,30,58,86,114,142,170]],G15:1335,G18:7973,G15_MASK:21522,getBCHTypeInfo:function(a){for(var b=a<<10;f.getBCHDigit(b)-f.getBCHDigit(f.G15)>=0;)b^=f.G15<<f.getBCHDigit(b)-f.getBCHDigit(f.G15);return(a<<10|b)^f.G15_MASK},getBCHTypeNumber:function(a){for(var b=a<<12;f.getBCHDigit(b)-f.getBCHDigit(f.G18)>=0;)b^=f.G18<<f.getBCHDigit(b)-f.getBCHDigit(f.G18);return a<<12|b},getBCHDigit:function(a){for(var b=0;0!=a;)b++,a>>>=1;return b},getPatternPosition:function(a){return f.PATTERN_POSITION_TABLE[a-1]},getMask:function(a,b,c){switch(a){case e.PATTERN000:return 0==(b+c)%2;case e.PATTERN001:return 0==b%2;case e.PATTERN010:return 0==c%3;case e.PATTERN011:return 0==(b+c)%3;case e.PATTERN100:return 0==(Math.floor(b/2)+Math.floor(c/3))%2;case e.PATTERN101:return 0==b*c%2+b*c%3;case e.PATTERN110:return 0==(b*c%2+b*c%3)%2;case e.PATTERN111:return 0==(b*c%3+(b+c)%2)%2;default:throw new Error("bad maskPattern:"+a)}},getErrorCorrectPolynomial:function(a){for(var b=new i([1],0),c=0;a>c;c++)b=b.multiply(new i([1,g.gexp(c)],0));return b},getLengthInBits:function(a,b){if(b>=1&&10>b)switch(a){case c.MODE_NUMBER:return 10;case c.MODE_ALPHA_NUM:return 9;case c.MODE_8BIT_BYTE:return 8;case c.MODE_KANJI:return 8;default:throw new Error("mode:"+a)}else if(27>b)switch(a){case c.MODE_NUMBER:return 12;case c.MODE_ALPHA_NUM:return 11;case c.MODE_8BIT_BYTE:return 16;case c.MODE_KANJI:return 10;default:throw new Error("mode:"+a)}else{if(!(41>b))throw new Error("type:"+b);switch(a){case c.MODE_NUMBER:return 14;case c.MODE_ALPHA_NUM:return 13;case c.MODE_8BIT_BYTE:return 16;case c.MODE_KANJI:return 12;default:throw new Error("mode:"+a)}}},getLostPoint:function(a){for(var b=a.getModuleCount(),c=0,d=0;b>d;d++)for(var e=0;b>e;e++){for(var f=0,g=a.isDark(d,e),h=-1;1>=h;h++)if(!(0>d+h||d+h>=b))for(var i=-1;1>=i;i++)0>e+i||e+i>=b||(0!=h||0!=i)&&g==a.isDark(d+h,e+i)&&f++;f>5&&(c+=3+f-5)}for(var d=0;b-1>d;d++)for(var e=0;b-1>e;e++){var j=0;a.isDark(d,e)&&j++,a.isDark(d+1,e)&&j++,a.isDark(d,e+1)&&j++,a.isDark(d+1,e+1)&&j++,(0==j||4==j)&&(c+=3)}for(var d=0;b>d;d++)for(var e=0;b-6>e;e++)a.isDark(d,e)&&!a.isDark(d,e+1)&&a.isDark(d,e+2)&&a.isDark(d,e+3)&&a.isDark(d,e+4)&&!a.isDark(d,e+5)&&a.isDark(d,e+6)&&(c+=40);for(var e=0;b>e;e++)for(var d=0;b-6>d;d++)a.isDark(d,e)&&!a.isDark(d+1,e)&&a.isDark(d+2,e)&&a.isDark(d+3,e)&&a.isDark(d+4,e)&&!a.isDark(d+5,e)&&a.isDark(d+6,e)&&(c+=40);for(var k=0,e=0;b>e;e++)for(var d=0;b>d;d++)a.isDark(d,e)&&k++;var l=Math.abs(100*k/b/b-50)/5;return c+=10*l}},g={glog:function(a){if(1>a)throw new Error("glog("+a+")");return g.LOG_TABLE[a]},gexp:function(a){for(;0>a;)a+=255;for(;a>=256;)a-=255;return g.EXP_TABLE[a]},EXP_TABLE:new Array(256),LOG_TABLE:new Array(256)},h=0;8>h;h++)g.EXP_TABLE[h]=1<<h;for(var h=8;256>h;h++)g.EXP_TABLE[h]=g.EXP_TABLE[h-4]^g.EXP_TABLE[h-5]^g.EXP_TABLE[h-6]^g.EXP_TABLE[h-8];for(var h=0;255>h;h++)g.LOG_TABLE[g.EXP_TABLE[h]]=h;i.prototype={get:function(a){return this.num[a]},getLength:function(){return this.num.length},multiply:function(a){for(var b=new Array(this.getLength()+a.getLength()-1),c=0;c<this.getLength();c++)for(var d=0;d<a.getLength();d++)b[c+d]^=g.gexp(g.glog(this.get(c))+g.glog(a.get(d)));return new i(b,0)},mod:function(a){if(this.getLength()-a.getLength()<0)return this;for(var b=g.glog(this.get(0))-g.glog(a.get(0)),c=new Array(this.getLength()),d=0;d<this.getLength();d++)c[d]=this.get(d);for(var d=0;d<a.getLength();d++)c[d]^=g.gexp(g.glog(a.get(d))+b);return new i(c,0).mod(a)}},j.RS_BLOCK_TABLE=[[1,26,19],[1,26,16],[1,26,13],[1,26,9],[1,44,34],[1,44,28],[1,44,22],[1,44,16],[1,70,55],[1,70,44],[2,35,17],[2,35,13],[1,100,80],[2,50,32],[2,50,24],[4,25,9],[1,134,108],[2,67,43],[2,33,15,2,34,16],[2,33,11,2,34,12],[2,86,68],[4,43,27],[4,43,19],[4,43,15],[2,98,78],[4,49,31],[2,32,14,4,33,15],[4,39,13,1,40,14],[2,121,97],[2,60,38,2,61,39],[4,40,18,2,41,19],[4,40,14,2,41,15],[2,146,116],[3,58,36,2,59,37],[4,36,16,4,37,17],[4,36,12,4,37,13],[2,86,68,2,87,69],[4,69,43,1,70,44],[6,43,19,2,44,20],[6,43,15,2,44,16],[4,101,81],[1,80,50,4,81,51],[4,50,22,4,51,23],[3,36,12,8,37,13],[2,116,92,2,117,93],[6,58,36,2,59,37],[4,46,20,6,47,21],[7,42,14,4,43,15],[4,133,107],[8,59,37,1,60,38],[8,44,20,4,45,21],[12,33,11,4,34,12],[3,145,115,1,146,116],[4,64,40,5,65,41],[11,36,16,5,37,17],[11,36,12,5,37,13],[5,109,87,1,110,88],[5,65,41,5,66,42],[5,54,24,7,55,25],[11,36,12],[5,122,98,1,123,99],[7,73,45,3,74,46],[15,43,19,2,44,20],[3,45,15,13,46,16],[1,135,107,5,136,108],[10,74,46,1,75,47],[1,50,22,15,51,23],[2,42,14,17,43,15],[5,150,120,1,151,121],[9,69,43,4,70,44],[17,50,22,1,51,23],[2,42,14,19,43,15],[3,141,113,4,142,114],[3,70,44,11,71,45],[17,47,21,4,48,22],[9,39,13,16,40,14],[3,135,107,5,136,108],[3,67,41,13,68,42],[15,54,24,5,55,25],[15,43,15,10,44,16],[4,144,116,4,145,117],[17,68,42],[17,50,22,6,51,23],[19,46,16,6,47,17],[2,139,111,7,140,112],[17,74,46],[7,54,24,16,55,25],[34,37,13],[4,151,121,5,152,122],[4,75,47,14,76,48],[11,54,24,14,55,25],[16,45,15,14,46,16],[6,147,117,4,148,118],[6,73,45,14,74,46],[11,54,24,16,55,25],[30,46,16,2,47,17],[8,132,106,4,133,107],[8,75,47,13,76,48],[7,54,24,22,55,25],[22,45,15,13,46,16],[10,142,114,2,143,115],[19,74,46,4,75,47],[28,50,22,6,51,23],[33,46,16,4,47,17],[8,152,122,4,153,123],[22,73,45,3,74,46],[8,53,23,26,54,24],[12,45,15,28,46,16],[3,147,117,10,148,118],[3,73,45,23,74,46],[4,54,24,31,55,25],[11,45,15,31,46,16],[7,146,116,7,147,117],[21,73,45,7,74,46],[1,53,23,37,54,24],[19,45,15,26,46,16],[5,145,115,10,146,116],[19,75,47,10,76,48],[15,54,24,25,55,25],[23,45,15,25,46,16],[13,145,115,3,146,116],[2,74,46,29,75,47],[42,54,24,1,55,25],[23,45,15,28,46,16],[17,145,115],[10,74,46,23,75,47],[10,54,24,35,55,25],[19,45,15,35,46,16],[17,145,115,1,146,116],[14,74,46,21,75,47],[29,54,24,19,55,25],[11,45,15,46,46,16],[13,145,115,6,146,116],[14,74,46,23,75,47],[44,54,24,7,55,25],[59,46,16,1,47,17],[12,151,121,7,152,122],[12,75,47,26,76,48],[39,54,24,14,55,25],[22,45,15,41,46,16],[6,151,121,14,152,122],[6,75,47,34,76,48],[46,54,24,10,55,25],[2,45,15,64,46,16],[17,152,122,4,153,123],[29,74,46,14,75,47],[49,54,24,10,55,25],[24,45,15,46,46,16],[4,152,122,18,153,123],[13,74,46,32,75,47],[48,54,24,14,55,25],[42,45,15,32,46,16],[20,147,117,4,148,118],[40,75,47,7,76,48],[43,54,24,22,55,25],[10,45,15,67,46,16],[19,148,118,6,149,119],[18,75,47,31,76,48],[34,54,24,34,55,25],[20,45,15,61,46,16]],j.getRSBlocks=function(a,b){var c=j.getRsBlockTable(a,b);if(void 0==c)throw new Error("bad rs block @ typeNumber:"+a+"/errorCorrectLevel:"+b);for(var d=c.length/3,e=[],f=0;d>f;f++)for(var g=c[3*f+0],h=c[3*f+1],i=c[3*f+2],k=0;g>k;k++)e.push(new j(h,i));return e},j.getRsBlockTable=function(a,b){switch(b){case d.L:return j.RS_BLOCK_TABLE[4*(a-1)+0];case d.M:return j.RS_BLOCK_TABLE[4*(a-1)+1];case d.Q:return j.RS_BLOCK_TABLE[4*(a-1)+2];case d.H:return j.RS_BLOCK_TABLE[4*(a-1)+3];default:return void 0}},k.prototype={get:function(a){var b=Math.floor(a/8);return 1==(1&this.buffer[b]>>>7-a%8)},put:function(a,b){for(var c=0;b>c;c++)this.putBit(1==(1&a>>>b-c-1))},getLengthInBits:function(){return this.length},putBit:function(a){var b=Math.floor(this.length/8);this.buffer.length<=b&&this.buffer.push(0),a&&(this.buffer[b]|=128>>>this.length%8),this.length++}};var l=[[17,14,11,7],[32,26,20,14],[53,42,32,24],[78,62,46,34],[106,84,60,44],[134,106,74,58],[154,122,86,64],[192,152,108,84],[230,180,130,98],[271,213,151,119],[321,251,177,137],[367,287,203,155],[425,331,241,177],[458,362,258,194],[520,412,292,220],[586,450,322,250],[644,504,364,280],[718,560,394,310],[792,624,442,338],[858,666,482,382],[929,711,509,403],[1003,779,565,439],[1091,857,611,461],[1171,911,661,511],[1273,997,715,535],[1367,1059,751,593],[1465,1125,805,625],[1528,1190,868,658],[1628,1264,908,698],[1732,1370,982,742],[1840,1452,1030,790],[1952,1538,1112,842],[2068,1628,1168,898],[2188,1722,1228,958],[2303,1809,1283,983],[2431,1911,1351,1051],[2563,1989,1423,1093],[2699,2099,1499,1139],[2809,2213,1579,1219],[2953,2331,1663,1273]],o=function(){var a=function(a,b){this._el=a,this._htOption=b};return a.prototype.draw=function(a){function g(a,b){var c=document.createElementNS("http://www.w3.org/2000/svg",a);for(var d in b)b.hasOwnProperty(d)&&c.setAttribute(d,b[d]);return c}var b=this._htOption,c=this._el,d=a.getModuleCount();Math.floor(b.width/d),Math.floor(b.height/d),this.clear();var h=g("svg",{viewBox:"0 0 "+String(d)+" "+String(d),width:"100%",height:"100%",fill:b.colorLight});h.setAttributeNS("http://www.w3.org/2000/xmlns/","xmlns:xlink","http://www.w3.org/1999/xlink"),c.appendChild(h),h.appendChild(g("rect",{fill:b.colorDark,width:"1",height:"1",id:"template"}));for(var i=0;d>i;i++)for(var j=0;d>j;j++)if(a.isDark(i,j)){var k=g("use",{x:String(i),y:String(j)});k.setAttributeNS("http://www.w3.org/1999/xlink","href","#template"),h.appendChild(k)}},a.prototype.clear=function(){for(;this._el.hasChildNodes();)this._el.removeChild(this._el.lastChild)},a}(),p="svg"===document.documentElement.tagName.toLowerCase(),q=p?o:m()?function(){function a(){this._elImage.src=this._elCanvas.toDataURL("image/png"),this._elImage.style.display="block",this._elCanvas.style.display="none"}function d(a,b){var c=this;if(c._fFail=b,c._fSuccess=a,null===c._bSupportDataURI){var d=document.createElement("img"),e=function(){c._bSupportDataURI=!1,c._fFail&&_fFail.call(c)},f=function(){c._bSupportDataURI=!0,c._fSuccess&&c._fSuccess.call(c)};return d.onabort=e,d.onerror=e,d.onload=f,d.src="data:image/gif;base64,iVBORw0KGgoAAAANSUhEUgAAAAUAAAAFCAYAAACNbyblAAAAHElEQVQI12P4//8/w38GIAXDIBKE0DHxgljNBAAO9TXL0Y4OHwAAAABJRU5ErkJggg==",void 0}c._bSupportDataURI===!0&&c._fSuccess?c._fSuccess.call(c):c._bSupportDataURI===!1&&c._fFail&&c._fFail.call(c)}if(this._android&&this._android<=2.1){var b=1/window.devicePixelRatio,c=CanvasRenderingContext2D.prototype.drawImage;CanvasRenderingContext2D.prototype.drawImage=function(a,d,e,f,g,h,i,j){if("nodeName"in a&&/img/i.test(a.nodeName))for(var l=arguments.length-1;l>=1;l--)arguments[l]=arguments[l]*b;else"undefined"==typeof j&&(arguments[1]*=b,arguments[2]*=b,arguments[3]*=b,arguments[4]*=b);c.apply(this,arguments)}}var e=function(a,b){this._bIsPainted=!1,this._android=n(),this._htOption=b,this._elCanvas=document.createElement("canvas"),this._elCanvas.width=b.width,this._elCanvas.height=b.height,a.appendChild(this._elCanvas),this._el=a,this._oContext=this._elCanvas.getContext("2d"),this._bIsPainted=!1,this._elImage=document.createElement("img"),this._elImage.style.display="none",this._el.appendChild(this._elImage),this._bSupportDataURI=null};return e.prototype.draw=function(a){var b=this._elImage,c=this._oContext,d=this._htOption,e=a.getModuleCount(),f=d.width/e,g=d.height/e,h=Math.round(f),i=Math.round(g);b.style.display="none",this.clear();for(var j=0;e>j;j++)for(var k=0;e>k;k++){var l=a.isDark(j,k),m=k*f,n=j*g;c.strokeStyle=l?d.colorDark:d.colorLight,c.lineWidth=1,c.fillStyle=l?d.colorDark:d.colorLight,c.fillRect(m,n,f,g),c.strokeRect(Math.floor(m)+.5,Math.floor(n)+.5,h,i),c.strokeRect(Math.ceil(m)-.5,Math.ceil(n)-.5,h,i)}this._bIsPainted=!0},e.prototype.makeImage=function(){this._bIsPainted&&d.call(this,a)},e.prototype.isPainted=function(){return this._bIsPainted},e.prototype.clear=function(){this._oContext.clearRect(0,0,this._elCanvas.width,this._elCanvas.height),this._bIsPainted=!1},e.prototype.round=function(a){return a?Math.floor(1e3*a)/1e3:a},e}():function(){var a=function(a,b){this._el=a,this._htOption=b};return a.prototype.draw=function(a){for(var b=this._htOption,c=this._el,d=a.getModuleCount(),e=Math.floor(b.width/d),f=Math.floor(b.height/d),g=['<table style="border:0;border-collapse:collapse;">'],h=0;d>h;h++){g.push("<tr>");for(var i=0;d>i;i++)g.push('<td style="border:0;border-collapse:collapse;padding:0;margin:0;width:'+e+"px;height:"+f+"px;background-color:"+(a.isDark(h,i)?b.colorDark:b.colorLight)+';"></td>');g.push("</tr>")}g.push("</table>"),c.innerHTML=g.join("");var j=c.childNodes[0],k=(b.width-j.offsetWidth)/2,l=(b.height-j.offsetHeight)/2;k>0&&l>0&&(j.style.margin=l+"px "+k+"px")},a.prototype.clear=function(){this._el.innerHTML=""},a}();QRCode=function(a,b){if(this._htOption={width:256,height:256,typeNumber:4,colorDark:"#000000",colorLight:"#ffffff",correctLevel:d.H},"string"==typeof b&&(b={text:b}),b)for(var c in b)this._htOption[c]=b[c];"string"==typeof a&&(a=document.getElementById(a)),this._android=n(),this._el=a,this._oQRCode=null,this._oDrawing=new q(this._el,this._htOption),this._htOption.text&&this.makeCode(this._htOption.text)},QRCode.prototype.makeCode=function(a){this._oQRCode=new b(r(a,this._htOption.correctLevel),this._htOption.correctLevel),this._oQRCode.addData(a),this._oQRCode.make(),this._el.title=a,this._oDrawing.draw(this._oQRCode),this.makeImage()},QRCode.prototype.makeImage=function(){"function"==typeof this._oDrawing.makeImage&&(!this._android||this._android>=3)&&this._oDrawing.makeImage()},QRCode.prototype.clear=function(){this._oDrawing.clear()},QRCode.CorrectLevel=d}();
