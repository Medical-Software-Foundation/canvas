"use strict";

// ---------------------------------------------------------------------------
// CMS ACCESS Inspector — per-track card UI over the /app SimpleAPI endpoints.
// Result display is driven by RESULT_MAP (the source of truth): every CMS result
// code maps to a plain-language, jargon-free message for care coordinators. The
// raw code + full request/response stay only in the Troubleshooting log.
// ---------------------------------------------------------------------------

const BASE = "/plugin-io/api/cms_access_fhir_client/app";
const PATIENT_ID =
  window.ACCESS_PATIENT_ID ||
  new URLSearchParams(window.location.search).get("patient_id") ||
  "";

// Async polling per Operations Manual §1: first poll 5–10s, then 10–30s, ~5-min cap.
const POLL_INITIAL_MS = 8000;
const POLL_INTERVAL_MS = 15000;
const POLL_MAX_ATTEMPTS = 20;

const TRACKS = ["eCKM", "CKM", "MSK", "BH"];

const ICON = {
  eCKM: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2 6 4-12 2 6h6"/></svg>',
  CKM: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.8 6.6a4.5 4.5 0 0 0-6.4 0L12 9l-2.4-2.4a4.5 4.5 0 1 0-6.4 6.4L12 22l8.8-9a4.5 4.5 0 0 0 0-6.4z"/></svg>',
  MSK: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.5 2.5 0 0 0-2.4 3.2L8.2 12.6A2.5 2.5 0 1 0 7 17a2.5 2.5 0 0 0 4.4 1.2l6.4-6.4A2.5 2.5 0 1 0 17 3z"/></svg>',
  BH: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 4A3 3 0 0 0 6.6 6 3 3 0 0 0 5 11a3 3 0 0 0 1.5 5.2A2.6 2.6 0 0 0 11 18V5.5A1.5 1.5 0 0 0 9.5 4zm5 0A1.5 1.5 0 0 0 13 5.5V18a2.6 2.6 0 0 0 4.5 1.2A3 3 0 0 0 19 14a3 3 0 0 0-1.6-5A3 3 0 0 0 14.5 4z"/></svg>',
};

const TRACK_META = {
  eCKM: { name: "eCKM", sub: "Early Cardio-Kidney-Metabolic", accent: "#185FA5", bg: "#E6F1FB" },
  CKM: { name: "CKM", sub: "Cardio-Kidney-Metabolic", accent: "#3B6D11", bg: "#EAF3DE" },
  MSK: { name: "MSK", sub: "Musculoskeletal", accent: "#854F0B", bg: "#FAEEDA" },
  BH: { name: "BH", sub: "Behavioral Health", accent: "#534AB7", bg: "#EEEDFE" },
};

// ACCESSUnalignmentReasonVS (OM v0.9.11) — the real codes.
const REASONS = [
  { val: "geographic-relocated", label: "Geographic relocation" },
  { val: "loss-of-contact", label: "Loss of contact" },
  { val: "no-longer-clinically-eligible", label: "No longer clinically eligible" },
  { val: "patient-initiated", label: "Patient initiated" },
];
const RTYPES = [
  { val: "baseline", label: "Baseline" },
  { val: "quarterly", label: "Quarterly" },
  { val: "end-of-period", label: "End of period" },
];

// Track-specific data-source note shown on the report form.
const REPORT_SOURCE = {
  CKM: "Pulls this patient's vitals & labs from Canvas. Any required measure that's missing is flagged by CMS as incomplete.",
  eCKM: "Pulls this patient's vitals & labs from Canvas. Any required measure that's missing is flagged by CMS as incomplete.",
  BH: "Pulls this patient's completed PHQ-9 / GAD-7 questionnaires from Canvas.",
  MSK: "Requires PROM questionnaires (PROMIS, Oswestry, etc.). These aren't set up yet, so an MSK report will come back as incomplete until they're added.",
};

// ----- Result code → plain-language display (the source of truth) -----
// tone: ok (green) | info (blue) | warn (amber) | neutral (gray) | error (red)
// One shared "already aligned" message — eligibility and align return different CMS codes
// for the same real situation, so both map to identical wording.
const ALREADY_ALIGNED = {
  tone: "warn", badge: "Already aligned",
  detail: "This patient is already aligned to this track — or the related CKM/eCKM track. They must be unaligned from it first.",
  recovery: [
    "If they're aligned with your organization, unalign them from that track first",
    "If with another organization, that provider must unalign the patient, then retry with switch consent",
  ],
};
const RESULT_MAP = {
  // Eligibility
  "eligible": { tone: "info", badge: "Eligible", detail: "This patient qualifies for this track. You can align them." },
  "eligible-pending-diagnosis": { tone: "warn", badge: "Eligible — needs diagnosis", detail: "This patient qualifies, but a qualifying diagnosis must be on the chart before they can be aligned.", recovery: ["Add the qualifying diagnosis to the patient's chart", "Then re-check eligibility"] },
  "eligible-switch-participants": { tone: "info", badge: "Can switch to you", detail: "This patient is aligned elsewhere but can switch to your organization with their consent." },
  "not-eligible-clinical-exclusion": { tone: "neutral", badge: "Not eligible", detail: "This patient has a condition that excludes them from this track.", recovery: ["Review the patient's diagnoses against this track's criteria", "Consider whether a different track fits"] },
  "not-eligible-not-medicare": { tone: "neutral", badge: "Not eligible", detail: "CMS records don't show this patient with active Medicare Part A & B as their primary coverage.", recovery: ["Confirm the patient's Medicare enrollment", "Check the Medicare ID on file is correct"] },
  "not-eligible-already-aligned": ALREADY_ALIGNED,
  "not-eligible-control-group": { tone: "neutral", badge: "Not eligible", detail: "This patient is in the model's control group and can't be aligned." },
  "not-eligible-diagnoses": { tone: "neutral", badge: "Not eligible — no diagnosis", detail: "This patient doesn't have a diagnosis that qualifies them for this track, so they can't be aligned.", recovery: ["Add a qualifying diagnosis for this track to the chart", "Then re-check eligibility"] },
  "not-eligible-mismatch": { tone: "warn", badge: "Details don't match", detail: "The patient's details don't match the records CMS has on file, so eligibility can't be confirmed.", recovery: ["Check the patient's name, date of birth, and Medicare ID (MBI) match their Medicare record", "Correct any mismatch, then re-check"] },
  "not-eligible-services": { tone: "neutral", badge: "Not eligible", detail: "This patient is receiving services that make them ineligible for the ACCESS Model — for example hospice, dialysis for end-stage renal disease (ESRD), or the PACE program." },

  // Alignment
  "aligned": { tone: "ok", badge: "Aligned", detail: "Aligned. The 12-month care period has started and monthly billing is active." },
  "aligned-switch-approved": { tone: "ok", badge: "Aligned (switched)", detail: "Aligned — the patient was switched from their previous organization." },
  "not-aligned-already-aligned": ALREADY_ALIGNED,
  "not-aligned-diagnoses": { tone: "warn", badge: "No qualifying diagnosis", detail: "Couldn't align — there's no qualifying diagnosis on file for this track.", recovery: ["Add the qualifying diagnosis to the chart", "Re-check eligibility, then align"] },
  "not-aligned-control-group": { tone: "neutral", badge: "Not eligible", detail: "This patient is in the model's control group and can't be aligned." },
  "not-aligned-clinical-exclusion": { tone: "neutral", badge: "Couldn't align", detail: "Couldn't align — this patient has a condition that excludes them from this track.", recovery: ["Review the patient's diagnoses against this track's criteria", "Consider whether a different track fits"] },
  "not-aligned-mismatch": { tone: "warn", badge: "Details don't match", detail: "Couldn't align — the patient's details don't match the records CMS has on file.", recovery: ["Check the patient's name, date of birth, and Medicare ID (MBI) match their Medicare record", "Correct any mismatch, then try again"] },
  "not-aligned-no-switch-attestation": { tone: "warn", badge: "Consent needed", detail: "Couldn't align — switching this patient from another organization requires their documented consent.", recovery: ["Obtain the patient's consent to switch", "Re-run align with switch consent attested"] },
  "not-aligned-not-medicare": { tone: "neutral", badge: "Couldn't align", detail: "Couldn't align — CMS records don't show this patient with active Medicare Part A & B as their primary coverage.", recovery: ["Confirm the patient's Medicare enrollment", "Check the Medicare ID on file is correct"] },
  "not-aligned-services": { tone: "neutral", badge: "Couldn't align", detail: "Couldn't align — this patient is receiving services that make them ineligible for the ACCESS Model — for example hospice, dialysis for end-stage renal disease (ESRD), or the PACE program." },

  // Unalignment
  "unaligned": { tone: "neutral", badge: "Unaligned", detail: "Unaligned. Monthly billing has stopped." },
  "unalignment-pending": { tone: "warn", badge: "Unalignment pending", detail: "Unalignment was requested and CMS is reviewing it. Billing continues until it's finalized." },
  "patient-not-aligned": { tone: "neutral", badge: "Not aligned", detail: "This patient isn't aligned to this track with your organization." },
  "cannot-unalign-during-lock-in": { tone: "warn", badge: "Locked in", detail: "This patient can't be unaligned yet — there's a 90-day minimum alignment period.", recovery: ["Wait until the 90-day alignment period ends", "Then try unaligning again"] },

  // Report
  "success": { tone: "ok", badge: "Report accepted", detail: "The report was accepted by CMS. All required measures were included." },
  "incomplete-data": { tone: "warn", badge: "Missing data", detail: "The report was received, but some required measures are missing. Add them and resubmit." },
  "reporting-period-closed": { tone: "warn", badge: "Period closed", detail: "The reporting window for this period has closed, so no further submissions are accepted." },
  "duplicate": { tone: "neutral", badge: "Already reported", detail: "This data was already reported for this period." },
  "validation-error": { tone: "error", badge: "Report rejected", detail: "The report couldn't be processed. Try again, or contact support if it keeps happening." },
  "incorrect-track": { tone: "warn", badge: "Wrong track", detail: "The submitted data doesn't match the track this patient is aligned to." },
};

function codeInfo(code) {
  if (code && RESULT_MAP[code]) return RESULT_MAP[code];
  // Unknown code: stay friendly on the card; the exact code/text is in Troubleshooting.
  if (code) return { tone: "neutral", badge: "Result received", detail: "CMS returned a result for this track. Open Troubleshooting below for the full details." };
  return null;
}

// ----- App state -----
let LAST_STATE = [];          // alignment rows from /state
let PATIENT_INFO = { name: "", dob: "", mbi: "" };  // header identifiers from /state
let ENABLED_TRACKS = TRACKS.slice();  // tracks to display, from /state (ACCESS_ENABLED_TRACKS)
let inFlight = null;          // track with an op in progress (one at a time)
let activeForm = null;        // { track, op } — inline form currently open
let modalTrack = null;        // track being unenrolled (modal)
let actOpen = false;          // activity log expanded
const logs = [];              // activity entries

function el(id) { return document.getElementById(id); }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function nowTime() { return new Date().toLocaleTimeString(); }
function esc(v) {
  return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function rowFor(track) { return LAST_STATE.find(function (r) { return r.track === track; }); }
function fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); }
  catch (e) { return ""; }
}
// DOB as MM/DD/YYYY — parse the ISO string directly to avoid a timezone off-by-one.
function fmtDOB(iso) {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? m[2] + "/" + m[3] + "/" + m[1] : iso;
}

// ----- Data load -----
async function loadState() {
  try {
    const resp = await fetch(BASE + "/state?patient_id=" + encodeURIComponent(PATIENT_ID), { credentials: "include" });
    const data = await resp.json();
    if (resp.ok) {
      LAST_STATE = data.alignments || [];
      if (data.patient) PATIENT_INFO = data.patient;
      if (Array.isArray(data.enabled_tracks)) {
        // Honor the server's enabled-track list, kept in canonical order.
        ENABLED_TRACKS = TRACKS.filter(function (t) { return data.enabled_tracks.indexOf(t) !== -1; });
      }
    }
  } catch (e) { /* keep last */ }
}

// Derive a card's kind (which drives available ACTIONS) from the alignment row.
// The badge + message always come from RESULT_MAP[code]; kind only picks actions.
function deriveCard(track) {
  if (inFlight === track) return { kind: "working" };
  const row = rowFor(track);
  if (!row || !row.status) return { kind: "not-checked", row: row };
  const s = row.status;
  const code = row.status_message || s;
  if (s === "aligned") return { kind: "aligned", code: code, row: row };
  if (s === "eligible") {
    if (code === "eligible-pending-diagnosis") return { kind: "eligible-pending", code: code, row: row };
    if (code === "eligible-switch-participants") return { kind: "switch-eligible", code: code, row: row };
    return { kind: "eligible", code: code, row: row };
  }
  if (s === "already-aligned") return { kind: "already-aligned", code: code, row: row };
  if (s === "ineligible") return { kind: "ineligible", code: code, row: row };
  if (s === "pending") return { kind: "pending", code: code, row: row };
  if (s === "unaligned") return { kind: "unenrolled", code: code, row: row };
  if (s === "error") {
    if (code === "patient-not-aligned") return { kind: "not-checked", code: code, row: row };
    return { kind: "error", code: code, row: row };
  }
  return { kind: "not-checked", row: row };
}

// ===========================================================================
// Rendering
// ===========================================================================
function render() {
  renderHeader();
  renderTracks();
  renderActivity();
  renderModal();
}

var COPY_SVG = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
var CHECK_SVG = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-11"/></svg>';

function copyIconBtn(field) {
  return '<button class="copy-icon" title="Copy" aria-label="Copy" onclick="copyValue(\'' + field + '\', this)">' + COPY_SVG + "</button>";
}

function renderHeader() {
  const p = PATIENT_INFO || {};
  el("pat-name").innerHTML = esc(p.name || "Patient") + (p.name ? copyIconBtn("name") : "");
  let meta = "";
  if (p.dob) meta += '<span class="pat-field">DOB ' + esc(fmtDOB(p.dob)) + copyIconBtn("dob") + "</span>";
  if (p.mbi) meta += '<span class="pat-field">MBI <code>' + esc(p.mbi) + "</code>" + copyIconBtn("mbi") + "</span>";
  else meta += '<span class="pat-field pat-faint">No Medicare ID on file</span>';
  el("pat-meta").innerHTML = meta;
}

function copyValue(field, btn) {
  const p = PATIENT_INFO || {};
  let v = "";
  if (field === "mbi") v = p.mbi || "";
  else if (field === "dob") v = fmtDOB(p.dob) || p.dob || "";
  else if (field === "name") v = p.name || "";
  let ok = false;
  try { navigator.clipboard.writeText(v); ok = true; } catch (e) { /* */ }
  if (btn) {
    const orig = btn.innerHTML;
    btn.innerHTML = ok ? CHECK_SVG : "✕";
    btn.classList.add("copied");
    setTimeout(function () { btn.innerHTML = orig; btn.classList.remove("copied"); }, 1300);
  }
}

function badgeHtml(code) {
  const info = codeInfo(code);
  if (!info) return "";
  return '<span class="badge tone-' + info.tone + '">' + esc(info.badge) + "</span>";
}

function renderTracks() {
  el("track-list").innerHTML = ENABLED_TRACKS.length
    ? ENABLED_TRACKS.map(renderCard).join("")
    : '<div class="info info-warn">No ACCESS tracks are enabled. Set the ACCESS_ENABLED_TRACKS configuration to choose which tracks appear.</div>';
}

function renderCard(track) {
  const meta = TRACK_META[track];
  const st = deriveCard(track);
  const dimmed = inFlight && inFlight !== track ? " dimmed" : "";
  const expanded = activeForm && activeForm.track === track ? " expanded" : "";

  let badge = "", right = "", meta_line = "", body = "";

  if (st.kind === "working") {
    right = '<span class="working"><span class="spinner"></span>Working…</span>';
  } else if (st.kind === "not-checked" || st.kind === "unenrolled") {
    badge = st.kind === "unenrolled" ? badgeHtml(st.code) : "";
    right = btn("primary", "Check eligibility", "doEligibility('" + track + "')");
  } else if (st.kind === "eligible" || st.kind === "eligible-pending") {
    badge = badgeHtml(st.code);
    right = btn("accent", "Align", "openForm('" + track + "','align')");
  } else if (st.kind === "switch-eligible") {
    badge = badgeHtml(st.code);
    right = btn("accent", "Switch to us", "openForm('" + track + "','align')");
  } else if (st.kind === "aligned") {
    badge = badgeHtml(st.code);
    meta_line = alignedMeta(track, st.row);
    right =
      btn("primary", "Submit report", "openForm('" + track + "','report')") +
      '<span class="sep"></span>' +
      '<button class="btn-unalign" onclick="openUnalignModal(\'' + track + '\')">Unalign</button>';
  } else if (st.kind === "already-aligned") {
    badge = badgeHtml(st.code);
    right =
      btn("ghost", "Check again", "doEligibility('" + track + "')") +
      '<span class="sep"></span>' +
      '<button class="btn-unalign" onclick="openUnalignModal(\'' + track + '\')">Unalign</button>';
  } else if (st.kind === "ineligible") {
    badge = badgeHtml(st.code);
    right = btn("ghost", "Check again", "doEligibility('" + track + "')");
  } else if (st.kind === "pending") {
    badge = badgeHtml(st.code);
    right = btn("ghost", "Check status", "doPoll('" + track + "')");
  } else if (st.kind === "error") {
    badge = '<span class="badge tone-error">Error</span>';
    right = btn("ghost", "Try again", "doEligibility('" + track + "')");
  }

  // Card body: open inline form, or a guidance/result panel for the current code.
  if (activeForm && activeForm.track === track) {
    body = activeForm.op === "align" ? alignForm(track) : reportForm(track);
  } else {
    body = guidancePanel(track, st);
  }

  return (
    '<div class="card track tone-accent-' + track + dimmed + expanded + '" data-accent="' + meta.accent + '">' +
      '<div class="track-head">' +
        '<div class="track-left">' +
          '<span class="track-icon" style="background:' + meta.bg + ';color:' + meta.accent + '">' + ICON[track] + "</span>" +
          '<span class="track-info">' +
            '<span class="track-name-row"><span class="track-name">' + meta.name + "</span>" + badge + "</span>" +
            '<span class="track-sub">' + meta.sub + "</span>" + meta_line + "</span>" +
        "</div>" +
        '<div class="track-right">' + right + "</div>" +
      "</div>" +
      (body ? '<div class="track-body" style="border-left-color:' + meta.accent + '">' + body + "</div>" : "") +
    "</div>"
  );
}

function btn(kind, label, onclick) {
  const cls = { primary: "btn-primary", accent: "btn-accent", ghost: "btn-ghost" }[kind] || "btn-ghost";
  return '<button class="' + cls + '" onclick="' + onclick + '">' + esc(label) + "</button>";
}

function alignedMeta(track, row) {
  const since = row && row.updated_at ? fmtDate(row.updated_at) : "";
  let s = '<span class="meta-line"><span class="meta-ok">✓ Aligned' + (since ? " · since " + esc(since) : "") + "</span>";
  if (row && row.report_result) {
    const info = codeInfo(row.report_result);
    const label = info ? info.badge : row.report_result;
    s += '<span class="meta-dot">·</span><span class="meta-muted">Last report: ' + esc(label) + "</span>";
  }
  return s + "</span>";
}

// Guidance / result panel (shown when no form is open and there's something to say).
function guidancePanel(track, st) {
  const info = codeInfo(st.code);
  if (!info) return "";
  if (st.kind === "aligned" || st.kind === "working") return ""; // aligned says it in the meta line
  let html = '<div class="panel-msg">' + esc(info.detail) + "</div>";
  if (info.recovery && info.recovery.length) {
    html += '<ul class="panel-steps">' + info.recovery.map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("") + "</ul>";
  }
  return html;
}

function alignForm(track) {
  const switching = deriveCard(track).kind === "switch-eligible";
  const info = switching
    ? "Switching moves this patient to your organization. The patient's consent to switch is required (the 90-day lock-in does not apply to eCKM↔CKM changes)."
    : "Aligning starts the 12-month care period and begins monthly billing.";
  const checked = switching ? " checked" : "";
  const label = switching ? "Switch & align " + track : "Align " + track;
  return (
    '<div class="info info-blue">' + info + "</div>" +
    '<label class="check-row"><input type="checkbox" id="sw-' + track + '"' + checked + "> " +
      "<span>Patient consents to switch from another ACCESS provider</span></label>" +
    '<div class="form-actions">' +
      '<button class="btn-primary" onclick="doAlign(\'' + track + '\')">' + label + "</button>" +
      '<button class="btn-text" onclick="closeForms()">Cancel</button>' +
    "</div>"
  );
}

function reportForm(track) {
  const opts = RTYPES.map(function (r) { return '<option value="' + r.val + '">' + r.label + "</option>"; }).join("");
  return (
    '<label class="flabel">Report type</label>' +
    '<select id="rt-' + track + '">' + opts + "</select>" +
    '<div class="info info-blue">' + esc(REPORT_SOURCE[track] || "") + "</div>" +
    '<div class="form-actions">' +
      '<button class="btn-primary" onclick="doReport(\'' + track + '\')">Submit report</button>' +
      '<button class="btn-text" onclick="closeForms()">Cancel</button>' +
    "</div>"
  );
}

function openForm(track, op) {
  if (inFlight) return;
  activeForm = { track: track, op: op };
  render();
}
function closeForms() { activeForm = null; render(); }

// ===========================================================================
// Operations (async submit → poll → reload state)
// ===========================================================================
const OP_VERB = {
  eligibility: "Checking eligibility",
  align: "Aligning",
  unalign: "Unaligning",
  report: "Submitting report",
};

async function runOp(op, track, path, payload) {
  if (inFlight) return;
  inFlight = track;
  activeForm = null;
  const entry = { time: nowTime(), op: "$" + (op === "eligibility" ? "check-eligibility" : op === "report" ? "report-data" : op), track: track, tone: "info", outcome: OP_VERB[op] + "…", exchanges: [], open: false };
  logs.unshift(entry);
  render();

  let data = {};
  try {
    const resp = await fetch(BASE + path, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    try { data = await resp.json(); } catch (e) { /* */ }
    if (data && data.exchange) entry.exchanges.push({ label: entry.op, exchange: data.exchange });
    if (!resp.ok) {
      entry.tone = "error";
      entry.outcome = friendlyError(data, resp.status);
      await loadState(); inFlight = null; render(); return;
    }
    if (data && data.content_location) {
      await pollLoop(entry);
    }
  } catch (e) {
    entry.tone = "error";
    entry.outcome = "Couldn't reach CMS — check the connection and try again.";
    inFlight = null; render(); return;
  }

  await loadState();
  inFlight = null;
  describeOutcome(entry, op, track);
  render();
}

async function pollLoop(entry) {
  for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
    await sleep(i === 0 ? POLL_INITIAL_MS : POLL_INTERVAL_MS);
    let data = {};
    try {
      const resp = await fetch(BASE + "/poll", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patient_id: PATIENT_ID }),
      });
      try { data = await resp.json(); } catch (e) { /* */ }
      if (resp.status === 404) return;               // nothing in progress → resolved
      if (data && data.exchange) entry.exchanges.push({ label: "$submission-status", exchange: data.exchange });
    } catch (e) { continue; }                          // transient → keep trying
    if (!data || data.submission_state !== "in-progress") return;
  }
}

// Translate the resulting state into a plain-language activity message.
function describeOutcome(entry, op, track) {
  const row = rowFor(track);
  let code = null;
  if (op === "report") code = row && row.report_result;
  else code = row && row.status_message;
  const info = codeInfo(code);
  if (info) { entry.tone = info.tone; entry.outcome = info.badge; }
  else if (row) { entry.tone = "neutral"; entry.outcome = code || row.status || "Done"; }
  else { entry.tone = "neutral"; entry.outcome = "Done"; }
}

function friendlyError(data, status) {
  if (data && data.error) return data.error;            // our endpoints return plain-language errors
  if (status === 401 || status === 403) return "There's a configuration problem with the CMS connection — contact your administrator.";
  if (status >= 500) return "CMS is having trouble right now. Wait a few minutes and try again.";
  return "Couldn't complete the request. The details are in Troubleshooting below.";
}

function doEligibility(track) { runOp("eligibility", track, "/eligibility", { patient_id: PATIENT_ID, track: track }); }
function doAlign(track) {
  const sw = el("sw-" + track);
  runOp("align", track, "/align", { patient_id: PATIENT_ID, track: track, switch_consent: !!(sw && sw.checked) });
}
function doReport(track) {
  const rt = el("rt-" + track);
  runOp("report", track, "/report-data", { patient_id: PATIENT_ID, track: track, report_type: rt ? rt.value : "baseline" });
}
function doPoll(track) { runOp("unalign-status", track, "/poll", { patient_id: PATIENT_ID }); }

// ===========================================================================
// Unalign modal
// ===========================================================================
function openUnalignModal(track) {
  if (inFlight) return;
  modalTrack = track;
  render();
}
function closeModal() { modalTrack = null; render(); }
function confirmUnalign() {
  const track = modalTrack;
  const reason = el("modal-reason") ? el("modal-reason").value : REASONS[0].val;
  modalTrack = null;
  runOp("unalign", track, "/unalign", { patient_id: PATIENT_ID, track: track, reason_code: reason });
}

function renderModal() {
  const overlay = el("modal-overlay");
  if (!modalTrack) { overlay.className = "modal-overlay"; overlay.innerHTML = ""; return; }
  const opts = REASONS.map(function (r) { return '<option value="' + r.val + '">' + r.label + "</option>"; }).join("");
  overlay.className = "modal-overlay open";
  overlay.innerHTML =
    '<div class="modal-box">' +
      '<div class="modal-title">Unalign patient from ' + modalTrack + "?</div>" +
      '<div class="modal-sub">Patient ' + esc(PATIENT_ID) + " · " + modalTrack + "</div>" +
      '<label class="flabel">Reason for unalignment</label>' +
      '<select id="modal-reason">' + opts + "</select>" +
      '<div class="info info-warn">This stops monthly billing. It can\'t be reversed for 90 days (CMS lock-in period).</div>' +
      '<div class="form-actions">' +
        '<button class="btn-danger" onclick="confirmUnalign()">Confirm unalign</button>' +
        '<button class="btn-text" onclick="closeModal()">Cancel</button>' +
      "</div>" +
    "</div>";
}

// ===========================================================================
// Activity log (collapsed "Troubleshooting")
// ===========================================================================
function toggleActivity() { actOpen = !actOpen; render(); }
function clearLog() { logs.length = 0; render(); }

function renderActivity() {
  const cnt = el("act-count");
  cnt.textContent = logs.length;
  cnt.style.display = logs.length ? "inline-flex" : "none";
  el("act-chevron").style.transform = actOpen ? "rotate(180deg)" : "rotate(0deg)";
  el("clear-btn").style.display = logs.length ? "inline" : "none";

  const body = el("act-body");
  body.className = actOpen ? "act-body open" : "act-body";
  if (!actOpen) { body.innerHTML = ""; return; }
  if (!logs.length) { body.innerHTML = '<p class="muted">No operations run yet.</p>'; return; }
  body.innerHTML = logs.map(logHtml).join("");
}

function logHtml(e, idx) {
  const dot = e.tone === "ok" ? "✓" : e.tone === "error" ? "✕" : e.tone === "warn" ? "!" : "○";
  let ex = "";
  if (e.exchanges.length) {
    const open = e.open ? " open" : "";
    const label = e.open ? "Hide payload" : "See payload";
    const inner = e.open ? e.exchanges.map(function (x, i) { return exchangeHtml(x.exchange, x.label, idx, i); }).join("") : "";
    ex =
      '<button class="ts-toggle" onclick="toggleLog(' + idx + ')">' +
        '<span class="chev' + open + '">▸</span> ' + label + "</button>" +
      '<div class="ts-body' + open + '">' + inner + "</div>";
  }
  return (
    '<div class="log-entry">' +
      '<div class="log-top"><span class="log-dot tone-' + e.tone + '">' + dot + "</span>" +
        '<span class="log-op">' + esc(e.op) + "</span>" +
        '<span class="log-track">· ' + esc(e.track) + "</span>" +
        '<span class="log-time">' + esc(e.time) + "</span></div>" +
      '<div class="log-msg">' + esc(e.outcome) + "</div>" + ex +
    "</div>"
  );
}
function toggleLog(idx) { if (logs[idx]) { logs[idx].open = !logs[idx].open; render(); } }

function exchangeHtml(x, label, li, xi) {
  if (!x) return "";
  const req = x.request || {}, res = x.response || {};
  const reqStr = JSON.stringify(req, null, 2);
  const resStr = JSON.stringify(res, null, 2);
  const method = req.method || "";
  const status = res.status_code != null ? res.status_code : "";
  const stCls = status === "" ? "" : status >= 200 && status < 300 ? "st-ok" : status >= 400 ? "st-err" : "st-other";
  const bar =
    (method ? '<span class="exch-method">' + esc(method) + "</span>" : "") +
    '<span class="exch-label">' + esc(label || "exchange") + "</span>" +
    (status === "" ? "" : '<span class="exch-st ' + stCls + '">' + esc(status) + "</span>");
  return (
    '<div class="exch-group">' +
      '<div class="exch-bar">' + bar + "</div>" +
      '<div class="exch">' +
        '<div class="exch-col"><div class="exch-h">Request <button class="copy" onclick="copyText(this,' + li + ',' + xi + ",'req')\">Copy</button></div><pre>" + esc(reqStr) + "</pre></div>" +
        '<div class="exch-col"><div class="exch-h">Response <button class="copy" onclick="copyText(this,' + li + ',' + xi + ",'res')\">Copy</button></div><pre>" + esc(resStr) + "</pre></div>" +
      "</div>" +
    "</div>"
  );
}
function copyText(btn, li, xi, which) {
  const e = logs[li]; if (!e || !e.exchanges[xi]) return;
  const x = e.exchanges[xi].exchange;
  const v = which === "req" ? x.request : x.response;
  let ok = false;
  try { navigator.clipboard.writeText(JSON.stringify(v, null, 2)); ok = true; } catch (err) { /* */ }
  if (btn) {
    const orig = btn.textContent;
    btn.textContent = ok ? "Copied!" : "Press ⌘C";
    btn.classList.add("copied");
    setTimeout(function () { btn.textContent = orig; btn.classList.remove("copied"); }, 1400);
  }
}

// ===========================================================================
// Init
// ===========================================================================
(async function init() {
  await loadState();
  render();
})();
