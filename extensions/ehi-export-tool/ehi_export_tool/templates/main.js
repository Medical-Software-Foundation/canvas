/* EHI Export workspace — vanilla JS client.
 *
 * Responsibilities:
 *   - Browse/search/sort the patient list (server-paginated).
 *   - Track a selection set across pages (and "select all matching").
 *   - Kick off per-patient EHI exports (fire-and-forget): start each $export,
 *     tagged with one batch id, then watch status. A background cron prepares
 *     each completed patient's JSON in S3.
 *   - Download per patient via a short-lived presigned S3 URL (prepared on
 *     demand if the cron hasn't gotten to it yet). No in-browser ZIP — the
 *     plugin sandbox can't build archives, and this keeps browser memory flat.
 */

(function () {
  "use strict";

  const API = "{{ api_prefix }}/app";

  // Tuning knobs.
  const PAGE_LIMIT = 50;
  const REFRESH_MS = 12000;      // auto-refresh the list/runs while on the main view
  const POLL_INTERVAL_MS = 3000; // single-patient status poll cadence
  const POLL_MAX_ATTEMPTS = 200; // ~10 min before giving up on a single export

  // ── state ──────────────────────────────────────────────────────────────
  const state = {
    offset: 0,
    total: 0,
    pagePatients: [],            // patients on the current page
    selected: new Map(),         // id -> {id, first_name, last_name, name, dob}
    searchTerm: "",
    includeInactive: false,
    exportFilter: "",            // "" | completed | failed | in_progress | none
    exportFormat: "ehi",         // "ehi" | "continuity" | "referral" (CCDA doc types)
    ccdaStart: "",               // optional CCDA start_date (YYYY-MM-DD)
    ccdaEnd: "",                 // optional CCDA end_date (YYYY-MM-DD)
    cancelRequested: false,
    configured: true,            // FHIR creds present (pre-flight)
    s3Configured: true,          // S3 creds present (pre-flight)
    sort: "last_name",           // last_name | first_name | dob | id
    dir: "asc",                  // asc | desc
    currentBatchId: "",
    // run view
    runBatchId: "",
    runStatus: "",
    runSearch: "",
    runOffset: 0,
    // all-runs view
    allRunsSearch: "",
    allRunsProgress: "",         // "" | running | completed | completed_with_errors
    allRunsOffset: 0,
    allRunsSort: "started",      // started | started_by
    allRunsDir: "desc",          // asc | desc
  };

  // ── element refs ─────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const els = {
    search: $("search"),
    exportFilter: $("export-filter"),
    activeFilter: $("active-filter"),
    searchBtn: $("search-btn"),
    resetBtn: $("reset-btn"),
    selectAllPage: $("select-all-page"),
    clearSelection: $("clear-selection"),
    selectionSummary: $("selection-summary"),
    statusBanner: $("status-banner"),
    patientRows: $("patient-rows"),
    emptyState: $("empty-state"),
    prevPage: $("prev-page"),
    nextPage: $("next-page"),
    pageInfo: $("page-info"),
    exportBtn: $("export-btn"),
    exportAllBtn: $("export-all-btn"),
    zipSelectedBtn: $("zip-selected-btn"),
    exportFormat: $("export-format"),
    ccdaDates: $("ccda-dates"),
    ccdaStart: $("ccda-start"),
    ccdaEnd: $("ccda-end"),
    exportHint: $("export-hint"),
    refreshRuns: $("refresh-runs"),
    runsEmpty: $("runs-empty"),
    runsTable: $("runs-table"),
    runsRows: $("runs-rows"),
    runsMore: $("runs-more"),
    showAllRuns: $("show-all-runs"),
    allRunsView: $("all-runs-view"),
    allRunsBack: $("all-runs-back"),
    allRunsRefresh: $("all-runs-refresh"),
    allRunsRows: $("all-runs-rows"),
    allRunsEmpty: $("all-runs-empty"),
    allRunsSearch: $("all-runs-search"),
    allRunsProgress: $("all-runs-progress"),
    allRunsPrev: $("all-runs-prev"),
    allRunsNext: $("all-runs-next"),
    allRunsPageInfo: $("all-runs-page-info"),
    mainView: $("main-view"),
    runView: $("run-view"),
    runBack: $("run-back"),
    runTitle: $("run-title"),
    runZipBtn: $("run-zip-btn"),
    runRefresh: $("run-refresh"),
    runSummary: $("run-summary"),
    runSync: $("run-sync"),
    runStatus: $("run-status"),
    runSearch: $("run-search"),
    runRows: $("run-rows"),
    runEmpty: $("run-empty"),
    runPrev: $("run-prev"),
    runNext: $("run-next"),
    runPageInfo: $("run-page-info"),
  };

  // ── helpers ──────────────────────────────────────────────────────────────

  function showBanner(message, isError) {
    els.statusBanner.textContent = message;
    els.statusBanner.classList.remove("status-banner--hidden");
    els.statusBanner.classList.toggle("status-banner--error", !!isError);
  }
  function hideBanner() {
    els.statusBanner.classList.add("status-banner--hidden");
  }

  function buildQuery(params) {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, v);
    });
    return usp.toString();
  }

  async function getJSON(url) {
    const resp = await fetch(url, { headers: { Accept: "application/json" } });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
    return data;
  }

  async function postJSON(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
    return data;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function cssEscape(s) {
    return String(s).replace(/["\\]/g, "\\$&");
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  function formatDateTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }
  function formatDateTimeTz(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", timeZoneName: "short",
    });
  }

  // Shared cell builders so the run table matches the main patient table.
  function patientIdCell(id) {
    const td = document.createElement("td");
    td.className = "patient-table__id";
    const a = document.createElement("a");
    a.className = "id-link";
    a.href = `/patient/${encodeURIComponent(id)}`;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = id;
    a.title = "Open patient chart in a new tab";
    td.appendChild(a);
    return td;
  }

  function activeCell(active) {
    const td = document.createElement("td");
    td.className = "status-check";
    const icon = document.createElement("span");
    icon.className = active ? "status-icon status-icon--active" : "status-icon status-icon--inactive";
    icon.textContent = active ? "✓" : "✗";
    icon.title = active ? "Active" : "Inactive";
    icon.setAttribute("aria-label", active ? "Active" : "Inactive");
    td.appendChild(icon);
    return td;
  }

  // ── patient list ──────────────────────────────────────────────────────────

  async function loadPage() {
    hideBanner();
    const query = buildQuery({
      search: state.searchTerm,
      include_inactive: state.includeInactive ? "true" : "",
      export: state.exportFilter,
      offset: state.offset,
      limit: PAGE_LIMIT,
      sort: state.sort,
      dir: state.dir,
    });
    let data;
    try {
      data = await getJSON(API + "/patients?" + query);
    } catch (err) {
      showBanner("Failed to load patients: " + err.message, true);
      return;
    }
    state.pagePatients = data.patients || [];
    state.total = data.total || 0;
    renderRows();
    renderPager(data.has_more);
    syncSelectionUI();
    loadJobStatuses();
  }

  async function loadJobStatuses() {
    const ids = state.pagePatients.map((p) => p.id);
    if (ids.length === 0) return;
    let jobs = {};
    try {
      const data = await getJSON(API + "/jobs?" + buildQuery({ patient_ids: ids.join(",") }));
      jobs = data.jobs || {};
    } catch (err) {
      return; // non-fatal
    }
    state.pagePatients.forEach((p) => renderPatientJob(p, jobs[p.id]));
  }

  // Locate a patient's two cells (status + export action) in the current page.
  function jobCells(patientId) {
    const sel = `[data-pid="${cssEscape(patientId)}"]`;
    return {
      status: els.patientRows.querySelector(`td.last-export${sel}`),
      action: els.patientRows.querySelector(`td.export-action${sel}`),
    };
  }

  function renderPatientJob(patient, job) {
    const c = jobCells(patient.id);
    if (c.status) renderJobStatusCell(c.status, patient, job);
    if (c.action) renderExportCell(c.action, patient, job);
  }

  // "Last export" column: status pill + datetime (with timezone) + Download.
  function renderJobStatusCell(cell, patient, job) {
    cell.innerHTML = "";
    if (!job) {
      cell.textContent = "—";
      return;
    }
    const when = document.createElement("span");
    when.className = "job-date";
    when.textContent = formatDateTimeTz(job.updated_at);

    if (job.status === "complete") {
      cell.append(statusPill("done", "Complete"), when, makeDownloadLink(patient, job.job_id));
    } else if (job.status === "queued") {
      cell.append(statusPill("pending", "Queued"), when);
    } else if (job.status === "in-progress") {
      cell.append(statusPill("running", "In progress"), when);
    } else {
      const pill = statusPill("error", "Failed");
      if (job.last_error) pill.title = job.last_error;
      cell.append(pill, when);
    }
  }

  function statusPill(kind, text) {
    const span = document.createElement("span");
    span.className = `pill pill--${kind}`;
    span.textContent = text;
    return span;
  }

  // "Export" column: a one-click export action, always present.
  function renderExportCell(cell, patient, job) {
    cell.innerHTML = "";
    cell.appendChild(makeExportButton(patient));
  }

  function makeExportButton(patient) {
    const btn = document.createElement("button");
    btn.className = "btn btn--sm";
    btn.textContent = "Export";
    btn.addEventListener("click", () => exportOne(patient));
    return btn;
  }

  // One-click single-patient export. EHI starts immediately (no queue/cron
  // wait) and polls to completion. C-CDA is synchronous — one enqueue creates a
  // ready-to-download row instantly, no polling.
  async function exportOne(patient) {
    if (!state.configured) {
      showBanner("Configure FHIR credentials before exporting.", true);
      return;
    }
    const now = () => new Date().toISOString();

    if (isCcda()) {
      renderPatientJob(patient, { status: "in-progress", updated_at: now() });
      try {
        await postJSON(API + "/export/enqueue", {
          patient_ids: [patient.id],
          ...currentExportOptions(),
        });
      } catch (err) {
        renderPatientJob(patient, { status: "error", last_error: err.message, updated_at: now() });
        return;
      }
      loadJobStatuses();
      loadRuns();
      return;
    }

    const batchId = newBatchId();
    renderPatientJob(patient, { status: "in-progress", updated_at: now() });

    let jobId;
    try {
      const resp = await postJSON(API + "/export/start", {
        patient_id: patient.id,
        batch_id: batchId,
      });
      jobId = resp.job_id;
    } catch (err) {
      renderPatientJob(patient, { status: "error", last_error: err.message, updated_at: now() });
      loadRuns();
      return;
    }
    loadRuns();

    let attempts = 0;
    while (attempts < POLL_MAX_ATTEMPTS) {
      let st;
      try {
        st = await getJSON(API + "/export/status?" + buildQuery({ job_id: jobId }));
      } catch (err) {
        renderPatientJob(patient, { status: "error", last_error: err.message, updated_at: now() });
        loadRuns();
        return;
      }
      if (st.ready) {
        renderPatientJob(patient, { status: "complete", job_id: jobId, updated_at: now() });
        loadRuns();
        return;
      }
      if (st.status === "error") {
        renderPatientJob(patient, { status: "error", last_error: st.progress, updated_at: now() });
        loadRuns();
        return;
      }
      attempts++;
      await sleep(POLL_INTERVAL_MS);
    }
    renderPatientJob(patient, {
      status: "error", last_error: "timed out waiting for export", updated_at: now(),
    });
  }

  function newBatchId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "batch-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
  }

  // ── selection / sort / pager ────────────────────────────────────────────

  function renderRows() {
    els.patientRows.innerHTML = "";
    const empty = state.pagePatients.length === 0;
    els.emptyState.classList.toggle("empty-state--hidden", !empty);

    state.pagePatients.forEach((p) => {
      const tr = document.createElement("tr");

      const checkTd = document.createElement("td");
      checkTd.className = "patient-table__check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.selected.has(p.id);
      cb.addEventListener("change", () => {
        if (cb.checked) state.selected.set(p.id, p);
        else state.selected.delete(p.id);
        syncSelectionUI();
      });
      checkTd.appendChild(cb);

      const lastTd = document.createElement("td");
      lastTd.textContent = p.last_name || "—";
      const firstTd = document.createElement("td");
      firstTd.textContent = p.first_name || "—";
      const dobTd = document.createElement("td");
      dobTd.textContent = p.dob || "—";
      const statusTd = activeCell(p.active);
      const idTd = patientIdCell(p.id);

      const jobTd = document.createElement("td");
      jobTd.className = "last-export";
      jobTd.dataset.pid = p.id;
      jobTd.textContent = "…";

      const exportTd = document.createElement("td");
      exportTd.className = "export-action";
      exportTd.dataset.pid = p.id;

      tr.append(checkTd, lastTd, firstTd, dobTd, statusTd, idTd, jobTd, exportTd);
      els.patientRows.appendChild(tr);
    });
    syncSelectAllPageCheckbox();
    updateSortIndicators();
  }

  function updateSortIndicators() {
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      const ind = th.querySelector(".sort-ind");
      if (!ind) return;
      ind.textContent = th.dataset.sort === state.sort ? (state.dir === "asc" ? "▲" : "▼") : "";
    });
  }

  function updateAllRunsSortIndicators() {
    document.querySelectorAll("th[data-runsort]").forEach((th) => {
      const ind = th.querySelector(".sort-ind");
      if (!ind) return;
      ind.textContent =
        th.dataset.runsort === state.allRunsSort ? (state.allRunsDir === "asc" ? "▲" : "▼") : "";
    });
  }

  function applyAllRunsSort(field) {
    if (state.allRunsSort === field) {
      state.allRunsDir = state.allRunsDir === "asc" ? "desc" : "asc";
    } else {
      state.allRunsSort = field;
      state.allRunsDir = "asc";
    }
    state.allRunsOffset = 0;
    loadAllRuns();
  }

  function applySort(field) {
    if (state.sort === field) {
      state.dir = state.dir === "asc" ? "desc" : "asc";
    } else {
      state.sort = field;
      state.dir = "asc";
    }
    state.offset = 0;
    loadPage();
  }

  function renderPager(hasMore) {
    const from = state.total === 0 ? 0 : state.offset + 1;
    const to = Math.min(state.offset + PAGE_LIMIT, state.total);
    els.pageInfo.textContent = `${from}–${to} of ${state.total}`;
    els.prevPage.disabled = state.offset === 0;
    els.nextPage.disabled = !hasMore;
  }

  function syncSelectAllPageCheckbox() {
    const ids = state.pagePatients.map((p) => p.id);
    const allSelected = ids.length > 0 && ids.every((id) => state.selected.has(id));
    els.selectAllPage.checked = allSelected;
  }

  function syncSelectionUI() {
    const n = state.selected.size;
    // Group export no longer needs S3: results download per-patient or as one
    // browser-built ZIP ("Download .zip"). S3 just adds presigned downloads and
    // `aws s3 sync` for whole-instance scale. Only FHIR creds gate exporting.
    const canExport = state.configured;
    els.selectionSummary.textContent = `${n} selected`;
    els.exportBtn.textContent = `Export selected (${n})`;
    els.exportBtn.disabled = n === 0 || !canExport;
    els.exportAllBtn.textContent = `Export all matching (${state.total})`;
    els.exportAllBtn.disabled = state.total === 0 || !canExport;
    // Client-side ZIP needs no S3 — only that something is selected and FHIR is set up.
    els.zipSelectedBtn.textContent = `Download .zip (${n})`;
    els.zipSelectedBtn.disabled = n === 0 || !state.configured;
    els.zipSelectedBtn.title = "Download the selected patients' completed exports as one .zip (built in your browser)";
    if (!state.configured) {
      els.exportHint.textContent = "Configure FHIR credentials before exporting.";
    } else if (!state.s3Configured) {
      els.exportHint.textContent =
        "Exports queue and run in the background. Download a group with “Download .zip” " +
        "(built in your browser) — or configure S3 for presigned downloads + aws s3 sync.";
    } else {
      els.exportHint.textContent =
        "Exports queue and run in the background — track them under Export runs.";
    }
    syncSelectAllPageCheckbox();
  }

  // ── pre-flight ──────────────────────────────────────────────────────────

  async function checkConfig() {
    try {
      const cfg = await getJSON(API + "/config");
      state.configured = !!cfg.configured;
      state.s3Configured = !!cfg.s3_configured;
    } catch (err) {
      state.configured = true;
      state.s3Configured = true;
    }
    if (!state.configured) {
      showBanner(
        "EHI export credentials are not configured. Set CANVAS_FHIR_CLIENT_ID and " +
        "CANVAS_FHIR_CLIENT_SECRET on the plugin configuration page before exporting.",
        true
      );
    } else if (!state.s3Configured) {
      showBanner(
        "S3 isn't configured — that's fine. Single and group exports both work; download a " +
        "group with “Download .zip” (assembled in your browser). Configure S3 only for " +
        "presigned downloads and whole-instance aws s3 sync.",
        false
      );
    }
    syncSelectionUI();
  }

  // ── download (presigned S3) ────────────────────────────────────────────

  // A "Download" link for one patient's NDJSON. The plugin serves the file
  // (streamed directly, or redirected to S3 when configured) — the user just
  // clicks; they never hit a Canvas endpoint themselves.
  function makeDownloadLink(patient, jobId) {
    const a = document.createElement("a");
    a.className = "btn btn--link";
    a.textContent = "Download";
    a.title = "Download this patient's export (.ndjson)";
    a.href = API + "/download?" + buildQuery({ job_id: jobId });
    a.target = "_blank";
    a.rel = "noopener";
    return a;
  }

  // ── client-side ZIP (no S3, no external library) ────────────────────────
  // The plugin can't build a ZIP server-side (the RestrictedPython sandbox
  // blocks zipfile/zlib/io). Instead the browser fetches each patient's NDJSON
  // from /download (inline=1, so it streams same-origin even when S3 exists)
  // and assembles a .zip locally. Good for selections / a single run; for a
  // whole-instance dump use S3 + `aws s3 sync`.
  const ZIP_FETCH_CONC = 5;       // parallel NDJSON downloads
  const ZIP_CONFIRM_OVER = 300;   // ask before zipping more than this many patients

  const _crcTable = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = _crcTable[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  // DEFLATE via the native CompressionStream; fall back to "stored" (no compression).
  async function deflateRaw(bytes) {
    if (typeof CompressionStream === "function") {
      try {
        const cs = new CompressionStream("deflate-raw");
        const stream = new Blob([bytes]).stream().pipeThrough(cs);
        const out = new Uint8Array(await new Response(stream).arrayBuffer());
        return { data: out, method: 8 };
      } catch (e) { /* fall through to stored */ }
    }
    return { data: bytes, method: 0 };
  }

  function _dosDateTime(d) {
    const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    const date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    return { time: time & 0xffff, date: date & 0xffff };
  }

  // entries: [{name, bytes(Uint8Array)}] -> Blob (a valid ZIP, stored or deflated).
  async function buildZip(entries) {
    const enc = new TextEncoder();
    const body = [];      // local headers + data, in order
    const central = [];   // central directory records
    let offset = 0;
    const { time, date } = _dosDateTime(new Date());

    for (const entry of entries) {
      const nameBytes = enc.encode(entry.name);
      const crc = crc32(entry.bytes);
      const { data, method } = await deflateRaw(entry.bytes);
      const compSize = data.length;
      const uncompSize = entry.bytes.length;

      const lfh = new DataView(new ArrayBuffer(30));
      lfh.setUint32(0, 0x04034b50, true);
      lfh.setUint16(4, 20, true);
      lfh.setUint16(6, 0x0800, true);   // bit 11: UTF-8 filename
      lfh.setUint16(8, method, true);
      lfh.setUint16(10, time, true);
      lfh.setUint16(12, date, true);
      lfh.setUint32(14, crc, true);
      lfh.setUint32(18, compSize, true);
      lfh.setUint32(22, uncompSize, true);
      lfh.setUint16(26, nameBytes.length, true);
      lfh.setUint16(28, 0, true);
      body.push(new Uint8Array(lfh.buffer), nameBytes, data);

      const cdr = new DataView(new ArrayBuffer(46));
      cdr.setUint32(0, 0x02014b50, true);
      cdr.setUint16(4, 20, true);
      cdr.setUint16(6, 20, true);
      cdr.setUint16(8, 0x0800, true);
      cdr.setUint16(10, method, true);
      cdr.setUint16(12, time, true);
      cdr.setUint16(14, date, true);
      cdr.setUint32(16, crc, true);
      cdr.setUint32(20, compSize, true);
      cdr.setUint32(24, uncompSize, true);
      cdr.setUint16(28, nameBytes.length, true);
      cdr.setUint32(42, offset, true);  // offset of local header
      central.push(new Uint8Array(cdr.buffer), nameBytes);

      offset += 30 + nameBytes.length + compSize;
    }

    let cdSize = 0;
    for (const c of central) cdSize += c.length;
    const eocd = new DataView(new ArrayBuffer(22));
    eocd.setUint32(0, 0x06054b50, true);
    eocd.setUint16(8, entries.length, true);
    eocd.setUint16(10, entries.length, true);
    eocd.setUint32(12, cdSize, true);
    eocd.setUint32(16, offset, true);   // central directory start
    return new Blob([...body, ...central, new Uint8Array(eocd.buffer)], { type: "application/zip" });
  }

  function zipSegment(s) {
    return String(s || "").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "") || "x";
  }
  function zipEntryName(last, first, pid, format) {
    const ext = format === "ccda" ? "xml" : "ndjson";
    return `${zipSegment(last)}_${zipSegment(first)}_${zipSegment(pid)}.${ext}`;
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // Fetch each item's file (bounded concurrency), then build + save the ZIP.
  // items: [{job_id, name}]. A file that fails to download (e.g. a C-CDA whose
  // patient has no Team Lead) is skipped, not fatal — we still zip the rest and
  // return the list of failures so the caller can report them.
  // Returns {ok, failures: [{name, error}]}.
  async function downloadZip(items, zipName, onProgress) {
    const results = new Array(items.length);
    const failures = [];
    let next = 0;
    let done = 0;
    async function worker() {
      while (next < items.length) {
        const i = next++;
        const it = items[i];
        try {
          const resp = await fetch(
            API + "/download?" + buildQuery({ job_id: it.job_id, inline: 1 }),
            { headers: { Accept: "application/x-ndjson, application/xml" } }
          );
          if (!resp.ok) {
            const detail = await resp.json().catch(() => ({}));
            throw new Error(detail.error || `HTTP ${resp.status}`);
          }
          results[i] = { name: it.name, bytes: new Uint8Array(await resp.arrayBuffer()) };
        } catch (err) {
          failures.push({ name: it.name, error: err.message });
        }
        done++;
        if (onProgress) onProgress(done, items.length);
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(ZIP_FETCH_CONC, items.length) }, worker)
    );
    const entries = results.filter(Boolean);
    if (entries.length > 0) {
      saveBlob(await buildZip(entries), zipName);
    }
    return { ok: entries.length > 0, failures };
  }

  // "Download .zip" for the current selection — zips each selected patient's
  // latest COMPLETED export; patients without one are skipped (and reported).
  async function zipSelected() {
    if (state.selected.size === 0) return;
    const patients = Array.from(state.selected.values());
    const ids = patients.map((p) => p.id);
    let jobs;
    try {
      jobs = (await getJSON(API + "/jobs?" + buildQuery({ patient_ids: ids.join(",") }))).jobs || {};
    } catch (err) {
      showBanner("Could not look up export status: " + err.message, true);
      return;
    }
    const items = [];
    let skipped = 0;
    patients.forEach((p) => {
      const job = jobs[p.id];
      if (job && job.status === "complete" && job.job_id) {
        items.push({ job_id: job.job_id, name: zipEntryName(p.last_name, p.first_name, p.id, job.format) });
      } else {
        skipped++;
      }
    });
    if (items.length === 0) {
      showBanner("None of the selected patients have a completed export to download yet.", true);
      return;
    }
    if (items.length > ZIP_CONFIRM_OVER &&
        !window.confirm(
          `You're about to build a ZIP of ${items.length} patient files in your browser. ` +
          `That can use a lot of memory — for very large exports use S3 instead. Continue?`
        )) {
      return;
    }
    const note = skipped > 0 ? ` (${skipped} skipped — no completed export)` : "";
    await runZipJob(els.zipSelectedBtn, items, `ehi-export-selected-${items.length}.zip`, note);
  }

  // "Download .zip" on a run page — zips every COMPLETED patient in the run
  // (pages through the whole run, not just the visible page).
  async function zipRun() {
    const batchId = state.runBatchId;
    if (!batchId) return;
    const items = [];
    let offset = 0;
    const PAGE = 200;
    try {
      for (;;) {
        const data = await getJSON(API + "/batch?" + buildQuery({
          batch_id: batchId, status: "complete", offset, limit: PAGE,
        }));
        (data.jobs || []).forEach((j) => {
          if (j.job_id) {
            items.push({ job_id: j.job_id, name: zipEntryName(j.last_name, j.first_name, j.patient_id, j.format) });
          }
        });
        if (!data.has_more) break;
        offset += PAGE;
      }
    } catch (err) {
      showBanner("Could not load the run's files: " + err.message, true);
      return;
    }
    if (items.length === 0) {
      showBanner("This run has no completed patient exports to download yet.", true);
      return;
    }
    if (items.length > ZIP_CONFIRM_OVER &&
        !window.confirm(
          `You're about to build a ZIP of ${items.length} patient files in your browser. ` +
          `That can use a lot of memory — for very large exports use S3 instead. Continue?`
        )) {
      return;
    }
    await runZipJob(els.runZipBtn, items, `ehi-export-run-${items.length}.zip`, "");
  }

  // Shared button-state + progress wrapper for a zip job.
  async function runZipJob(btn, items, zipName, note) {
    const original = btn.textContent;
    btn.disabled = true;
    try {
      const { ok, failures } = await downloadZip(items, zipName, (done, total) => {
        btn.textContent = `Zipping… ${done}/${total}`;
      });
      const got = items.length - failures.length;
      if (!ok) {
        const why = failures.length ? ` First error: ${failures[0].error}` : "";
        showBanner(`No files could be downloaded, so no ZIP was created.${why}`, true);
      } else if (failures.length) {
        showBanner(
          `Downloaded ${got} of ${items.length} as ${zipName}${note}. ` +
          `${failures.length} skipped (e.g. ${failures[0].name}: ${failures[0].error}).`,
          true
        );
      } else {
        showBanner(`Downloaded ${got} patient file(s) as ${zipName}${note}.`, false);
      }
    } catch (err) {
      showBanner("ZIP download failed: " + err.message, true);
    } finally {
      btn.textContent = original;
      btn.disabled = false;
      syncSelectionUI();
    }
  }

  // ── export orchestration (fire-and-forget) ──────────────────────────────

  // The export format chosen in the toolbar, as request-body fields.
  // "ehi" -> FHIR $export (NDJSON); "continuity"/"referral" -> C-CDA XML.
  function currentExportOptions() {
    const v = state.exportFormat;
    if (v === "ehi") return { format: "ehi" };
    return {
      format: "ccda",
      document_type: v,
      start_date: state.ccdaStart || "",
      end_date: state.ccdaEnd || "",
    };
  }

  function isCcda() {
    return state.exportFormat === "continuity" || state.exportFormat === "referral";
  }

  // Queue the selected patients (server starts them, throttled). Fire-and-forget.
  async function startExport() {
    if (state.selected.size === 0) return;
    const ids = Array.from(state.selected.keys());
    await enqueueExport({ patient_ids: ids, ...currentExportOptions() }, ids.length);
  }

  // Queue every patient matching the current filters — server-side, no cap.
  async function exportAllMatching() {
    const n = state.total;
    if (!n) return;
    if (!confirm(`Queue an export for all ${n} matching patient${n === 1 ? "" : "s"}?`)) return;
    await enqueueExport(
      {
        all_matching: true,
        search: state.searchTerm,
        include_inactive: state.includeInactive,
        export: state.exportFilter,
        ...currentExportOptions(),
      },
      n
    );
  }

  // POST an enqueue request and report it. Returns the new batch id (or null).
  async function enqueueExport(body, expected) {
    if (!state.configured) {
      showBanner("Configure FHIR credentials before exporting.", true);
      return null;
    }
    let data;
    try {
      data = await postJSON(API + "/export/enqueue", body);
    } catch (err) {
      showBanner("Failed to queue export: " + err.message, true);
      return null;
    }
    showBanner(
      `Queued ${data.queued} export${data.queued === 1 ? "" : "s"}. They run in the background — ` +
      "track progress and download under Export runs. You can leave this page.",
      false
    );
    state.selected.clear();
    renderRows();
    syncSelectionUI();
    loadRuns();
    loadJobStatuses();
    return data.batch_id;
  }

  // ── export runs (batches) ──────────────────────────────────────────────

  const RUNS_PANEL_LIMIT = 5;    // newest runs shown on the main page
  const ALL_RUNS_PAGE = 50;      // runs per page on the "all runs" page
  let allRunsSearchTimer = null;

  // Main-page panel: show the latest few runs + a "Show all" button.
  async function loadRuns() {
    let batches = [];
    try {
      const data = await getJSON(API + "/batches?" + buildQuery({ limit: RUNS_PANEL_LIMIT }));
      batches = data.batches || [];
    } catch (err) {
      return;
    }
    const empty = batches.length === 0;
    els.runsEmpty.style.display = empty ? "" : "none";
    els.runsTable.style.display = empty ? "none" : "";
    els.runsMore.style.display = empty ? "none" : "";
    renderRunsRows(els.runsRows, batches);
  }

  // Full "all runs" page — searchable + paginated.
  async function loadAllRuns() {
    let data;
    try {
      data = await getJSON(API + "/batches?" + buildQuery({
        limit: ALL_RUNS_PAGE,
        offset: state.allRunsOffset,
        search: state.allRunsSearch,
        progress: state.allRunsProgress,
        sort: state.allRunsSort,
        dir: state.allRunsDir,
      }));
    } catch (err) {
      showBanner("Failed to load runs: " + err.message, true);
      return;
    }
    const batches = data.batches || [];
    els.allRunsEmpty.classList.toggle("empty-state--hidden", batches.length !== 0);
    renderRunsRows(els.allRunsRows, batches);
    updateAllRunsSortIndicators();

    const from = data.total === 0 ? 0 : data.offset + 1;
    const to = Math.min(data.offset + data.limit, data.total);
    els.allRunsPageInfo.textContent = `${from}–${to} of ${data.total}`;
    els.allRunsPrev.disabled = data.offset === 0;
    els.allRunsNext.disabled = !data.has_more;
  }

  function renderRunsRows(tbody, batches) {
    tbody.innerHTML = "";
    batches.forEach((b) => {
      const tr = document.createElement("tr");

      const whenTd = document.createElement("td");
      whenTd.textContent = formatDateTime(b.created_at);

      const byTd = document.createElement("td");
      byTd.textContent = b.started_by || "—";

      const progTd = document.createElement("td");
      const done = b.complete || 0;
      progTd.append(document.createTextNode(`${done} / ${b.total || 0} complete`));
      if (b.queued) {
        progTd.append(document.createTextNode(` · ${b.queued} queued`));
      }
      if (b.in_progress) {
        progTd.append(document.createTextNode(` · ${b.in_progress} in progress`));
      }
      if (b.failed) {
        const f = document.createElement("span");
        f.className = "runs-failed";
        f.textContent = ` · ${b.failed} failed`;
        progTd.append(f);
      }

      const actionTd = document.createElement("td");
      actionTd.className = "runs-table__action";
      const open = document.createElement("button");
      open.className = "btn btn--sm";
      open.textContent = "Open";
      open.addEventListener("click", () => openRunView(b.batch_id, b.created_at, b.started_by));
      actionTd.appendChild(open);

      tr.append(whenTd, byTd, progTd, actionTd);
      tbody.appendChild(tr);
    });
  }

  // ── view switching (main / single run / all runs) ───────────────────────────

  const RUN_LIMIT = 100;
  let runSearchTimer = null;

  function setView(view) {
    els.mainView.hidden = view !== "main";
    els.runView.hidden = view !== "run";
    els.allRunsView.hidden = view !== "all-runs";
    hideBanner();
    window.scrollTo(0, 0);
  }

  function showRunView() {
    setView("run");
  }

  function showMainView() {
    setView("main");
    loadRuns();
    loadJobStatuses();
  }

  function openAllRuns() {
    state.allRunsSearch = "";
    state.allRunsProgress = "";
    state.allRunsOffset = 0;
    els.allRunsSearch.value = "";
    if (els.allRunsProgress) els.allRunsProgress.value = "";
    setView("all-runs");
    loadAllRuns();
  }

  function openRunView(batchId, createdAt, startedBy) {
    state.runBatchId = batchId;
    state.runStatus = "";
    state.runSearch = "";
    state.runOffset = 0;
    els.runStatus.value = "";
    els.runSearch.value = "";
    const when = formatDateTime(createdAt);
    let title = when ? `Export run — ${when}` : "Export run";
    if (startedBy) title += ` · started by ${startedBy}`;
    els.runTitle.textContent = title;
    showRunView();
    loadRunPage();
  }

  // Re-run only the failed patients of a run as a brand-new queued run, then jump to it.
  async function rerunFailed(batchId) {
    let data;
    try {
      data = await getJSON(API + "/batch?" + buildQuery({
        batch_id: batchId, status: "error", limit: 500,
      }));
    } catch (err) {
      showBanner("Couldn't load failed patients: " + err.message, true);
      return;
    }
    const ids = (data.jobs || []).map((j) => j.patient_id);
    if (ids.length === 0) {
      showBanner("No failed patients to re-run.", true);
      return;
    }
    const newBatch = await enqueueExport({ patient_ids: ids }, ids.length);
    if (newBatch) openRunView(newBatch, new Date().toISOString(), "");
  }

  async function loadRunPage() {
    hideBanner();
    const query = buildQuery({
      batch_id: state.runBatchId,
      status: state.runStatus,
      search: state.runSearch,
      offset: state.runOffset,
      limit: RUN_LIMIT,
    });
    let data;
    try {
      data = await getJSON(API + "/batch?" + query);
    } catch (err) {
      showBanner("Failed to load run: " + err.message, true);
      return;
    }
    renderRunPage(data);
  }

  function renderRunPage(data) {
    const c = data.counts || {};

    // ZIP the whole run only when it has completed patient exports.
    els.runZipBtn.disabled = !c.complete;
    els.runZipBtn.title = c.complete
      ? `Download all ${c.complete} completed patient export(s) as one .zip (built in your browser)`
      : "No completed patient exports to download yet";

    // Whole-run status summary (unfiltered).
    els.runSummary.innerHTML = "";
    const total = c.total || 0;
    const parts = [`${total} patient${total === 1 ? "" : "s"}`];
    if (c.complete) parts.push(`${c.complete} complete`);
    if (c.queued) parts.push(`${c.queued} queued`);
    if (c.in_progress) parts.push(`${c.in_progress} in progress`);
    els.runSummary.append(document.createTextNode(parts.join(" · ")));
    if (c.error) {
      const f = document.createElement("span");
      f.className = "runs-failed";
      f.textContent = ` · ${c.error} failed`;
      els.runSummary.append(f);

      // Offer to re-run just the failed patients as a fresh run.
      const rerun = document.createElement("button");
      rerun.className = "btn btn--sm runs-rerun";
      rerun.textContent = `Re-run failed (${c.error})`;
      rerun.addEventListener("click", () => rerunFailed(state.runBatchId));
      els.runSummary.append(rerun);
    }

    if (data.s3_bucket && data.s3_prefix) {
      els.runSync.style.display = "";
      els.runSync.textContent = `Grab the whole run: aws s3 sync s3://${data.s3_bucket}/${data.s3_prefix} .`;
    } else {
      els.runSync.style.display = "none";
    }

    const jobs = data.jobs || [];
    els.runRows.innerHTML = "";
    els.runEmpty.classList.toggle("empty-state--hidden", jobs.length !== 0);
    jobs.forEach((j) => els.runRows.appendChild(runRow(j)));

    const from = data.total === 0 ? 0 : data.offset + 1;
    const to = Math.min(data.offset + data.limit, data.total);
    els.runPageInfo.textContent = `${from}–${to} of ${data.total}`;
    els.runPrev.disabled = data.offset === 0;
    els.runNext.disabled = !data.has_more;
  }

  // A run-view row: matches the main table columns + an Export status column.
  function runRow(j) {
    const tr = document.createElement("tr");
    const lastTd = document.createElement("td");
    lastTd.textContent = j.last_name || "—";
    const firstTd = document.createElement("td");
    firstTd.textContent = j.first_name || "—";
    const dobTd = document.createElement("td");
    dobTd.textContent = j.dob || "—";
    const statusTd = activeCell(j.patient_active);
    const idTd = patientIdCell(j.patient_id);

    const exportTd = document.createElement("td");
    if (j.status === "complete") {
      exportTd.innerHTML = '<span class="pill pill--done">Complete</span> ';
      exportTd.appendChild(makeDownloadLink({ id: j.patient_id, name: j.patient_name }, j.job_id));
    } else if (j.status === "error") {
      exportTd.innerHTML = '<span class="pill pill--error">Failed</span>';
      if (j.last_error) {
        const err = document.createElement("div");
        err.className = "row-error";
        err.textContent = j.last_error;
        exportTd.appendChild(err);
      }
    } else if (j.status === "queued") {
      exportTd.innerHTML = '<span class="pill pill--pending">Queued</span>';
    } else {
      exportTd.innerHTML = '<span class="pill pill--running">In progress</span>';
    }

    tr.append(lastTd, firstTd, dobTd, statusTd, idTd, exportTd);
    return tr;
  }

  // ── event wiring ──────────────────────────────────────────────────────────

  function runSearch() {
    state.searchTerm = els.search.value.trim();
    state.includeInactive = els.activeFilter.value === "all";
    state.exportFilter = els.exportFilter.value;
    state.offset = 0;
    loadPage();
  }

  function resetFilters() {
    els.search.value = "";
    els.exportFilter.value = "";
    els.activeFilter.value = "active";
    runSearch();
  }

  els.searchBtn.addEventListener("click", runSearch);
  els.resetBtn.addEventListener("click", resetFilters);
  // Filters only take effect on Apply (or Enter in the search box) — changing a
  // dropdown stages the value but does not re-query until applied.
  els.search.addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

  els.prevPage.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_LIMIT);
    loadPage();
  });
  els.nextPage.addEventListener("click", () => {
    state.offset += PAGE_LIMIT;
    loadPage();
  });

  els.selectAllPage.addEventListener("change", () => {
    state.pagePatients.forEach((p) => {
      if (els.selectAllPage.checked) state.selected.set(p.id, p);
      else state.selected.delete(p.id);
    });
    renderRows();
    syncSelectionUI();
  });
  els.clearSelection.addEventListener("click", () => {
    state.selected.clear();
    renderRows();
    syncSelectionUI();
  });

  els.exportBtn.addEventListener("click", startExport);
  els.exportAllBtn.addEventListener("click", exportAllMatching);
  els.zipSelectedBtn.addEventListener("click", zipSelected);
  els.exportFormat.addEventListener("change", () => {
    state.exportFormat = els.exportFormat.value;
    els.ccdaDates.style.display = isCcda() ? "" : "none";
    syncSelectionUI();
  });
  els.ccdaStart.addEventListener("change", () => { state.ccdaStart = els.ccdaStart.value; });
  els.ccdaEnd.addEventListener("change", () => { state.ccdaEnd = els.ccdaEnd.value; });
  els.refreshRuns.addEventListener("click", loadRuns);
  els.showAllRuns.addEventListener("click", openAllRuns);
  els.allRunsBack.addEventListener("click", showMainView);
  els.allRunsRefresh.addEventListener("click", loadAllRuns);
  els.allRunsSearch.addEventListener("input", () => {
    clearTimeout(allRunsSearchTimer);
    allRunsSearchTimer = setTimeout(() => {
      state.allRunsSearch = els.allRunsSearch.value.trim();
      state.allRunsOffset = 0;
      loadAllRuns();
    }, 300);
  });
  els.allRunsProgress.addEventListener("change", () => {
    state.allRunsProgress = els.allRunsProgress.value;
    state.allRunsOffset = 0;
    loadAllRuns();
  });
  els.allRunsPrev.addEventListener("click", () => {
    state.allRunsOffset = Math.max(0, state.allRunsOffset - ALL_RUNS_PAGE);
    loadAllRuns();
  });
  els.allRunsNext.addEventListener("click", () => {
    state.allRunsOffset += ALL_RUNS_PAGE;
    loadAllRuns();
  });

  // Run view
  els.runBack.addEventListener("click", showMainView);
  els.runZipBtn.addEventListener("click", zipRun);
  els.runRefresh.addEventListener("click", loadRunPage);
  els.runStatus.addEventListener("change", () => {
    state.runStatus = els.runStatus.value;
    state.runOffset = 0;
    loadRunPage();
  });
  els.runSearch.addEventListener("input", () => {
    clearTimeout(runSearchTimer);
    runSearchTimer = setTimeout(() => {
      state.runSearch = els.runSearch.value.trim();
      state.runOffset = 0;
      loadRunPage();
    }, 300);
  });
  els.runPrev.addEventListener("click", () => {
    state.runOffset = Math.max(0, state.runOffset - RUN_LIMIT);
    loadRunPage();
  });
  els.runNext.addEventListener("click", () => {
    state.runOffset += RUN_LIMIT;
    loadRunPage();
  });

  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => applySort(th.dataset.sort));
  });
  document.querySelectorAll("th[data-runsort]").forEach((th) => {
    th.addEventListener("click", () => applyAllRunsSort(th.dataset.runsort));
  });

  // Auto-refresh statuses while on the main view, so queued → in-progress →
  // complete transitions (driven by the cron) appear without manual refresh.
  setInterval(() => {
    if (!els.mainView.hidden && !document.hidden) {
      loadJobStatuses();
      loadRuns();
    } else if (!els.allRunsView.hidden && !document.hidden) {
      loadAllRuns();
    }
  }, REFRESH_MS);

  // ── init ──────────────────────────────────────────────────────────────────
  syncSelectionUI();
  checkConfig();
  loadPage();
  loadRuns();
})();
