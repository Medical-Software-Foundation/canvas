"""Candid dashboard application.

Full-page application launched from the Canvas provider menu. Lists all claims
that have been submitted to Candid along with their current status, last sync,
and any submission errors.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class CandidDashboard(Application):
    """Full-page list view of all Candid-submitted claims with status."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            content=_html(),
            target=LaunchModalEffect.TargetType.PAGE,
            title="Candid Dashboard",
        ).apply()


def _html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #333; font-size: 13px; background: #f9fafb;
  }

  .page { max-width: 1400px; margin: 0 auto; padding: 24px 32px 48px; }

  .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .header h1 { font-size: 22px; font-weight: 600; color: #111827; }
  .refresh-btn {
    padding: 6px 14px; font-size: 12px; font-weight: 600;
    background: #2563eb; color: white; border: none; border-radius: 6px;
    cursor: pointer; transition: background 0.15s;
  }
  .refresh-btn:hover { background: #1d4ed8; }

  .filters {
    display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; align-items: center;
    padding: 14px 16px; background: white; border: 1px solid #e5e7eb; border-radius: 8px;
  }
  .filters label { font-size: 12px; color: #374151; display: flex; align-items: center; gap: 6px; }
  .filters select {
    font-size: 12px; padding: 5px 10px; border: 1px solid #d1d5db; border-radius: 5px; background: white;
  }
  .filters input[type="checkbox"] { margin: 0; }

  .filters-right { display: flex; align-items: center; gap: 16px; margin-left: auto; }
  .summary { font-size: 12px; color: #6b7280; }

  .table-wrap { background: white; border: 1px solid #e5e7eb; border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; }
  thead { background: #f9fafb; }
  thead tr:first-child th:first-child { border-top-left-radius: 8px; }
  thead tr:first-child th:last-child { border-top-right-radius: 8px; }
  th {
    text-align: left; font-size: 11px; font-weight: 600; color: #6b7280;
    text-transform: uppercase; letter-spacing: 0.05em;
    padding: 10px 14px; border-bottom: 1px solid #e5e7eb;
    vertical-align: middle;
  }
  .filter-wrap { position: relative; display: inline-block; margin-left: 8px; vertical-align: middle; }
  .col-filter {
    font-size: 11px; font-weight: 500; text-transform: none; letter-spacing: 0;
    color: #374151; padding: 3px 8px; border: 1px solid #d1d5db; border-radius: 4px;
    background: white; cursor: pointer;
  }
  .col-filter:hover { background: #f9fafb; }
  .col-filter.active { background: #eff6ff; border-color: #93c5fd; color: #1e40af; }
  .filter-popup {
    display: none; position: absolute; top: 0px; left: 100%; margin-left: 2px;
    background: white; border: 1px solid #d1d5db; border-radius: 6px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1); min-width: 220px; z-index: 10;
    font-weight: 400; text-transform: none; letter-spacing: 0;
    max-height: 320px; overflow-y: auto;
  }
  .filter-popup.open { display: block; }
  .filter-popup-header {
    padding: 8px 12px; border-bottom: 1px solid #f3f4f6;
    display: flex; justify-content: space-between; align-items: center;
    position: sticky; top: 0; background: white;
  }
  .filter-popup-header .count { font-size: 11px; color: #6b7280; }
  .filter-popup-header button {
    font-size: 11px; color: #2563eb; background: none; border: none;
    cursor: pointer; padding: 0; font-weight: 500;
  }
  .filter-popup-header button:hover { text-decoration: underline; }
  .filter-popup label {
    display: flex; align-items: center; gap: 8px; padding: 6px 12px;
    font-size: 12px; cursor: pointer; color: #374151;
  }
  .filter-popup label:hover { background: #f9fafb; }
  .filter-popup label input { margin: 0; }
  .patient-search-popup { padding: 10px; }
  .patient-search-popup.open { display: flex; gap: 8px; align-items: center; }
  .patient-search-popup input[type="text"] {
    flex: 1; padding: 5px 8px; font-size: 12px;
    border: 1px solid #d1d5db; border-radius: 4px; outline: none;
  }
  .patient-search-popup input[type="text"]:focus { border-color: #93c5fd; }
  .patient-search-popup .patient-clear {
    font-size: 11px; color: #2563eb; background: none; border: none;
    cursor: pointer; padding: 0; font-weight: 500; white-space: nowrap;
  }
  .patient-search-popup .patient-clear:hover { text-decoration: underline; }
  td {
    padding: 12px 14px; border-bottom: 1px solid #f3f4f6; font-size: 13px; vertical-align: top;
    word-break: break-word;
  }
  tbody tr { transition: background 0.1s; }
  tbody tr:hover { background: #f9fafb; }
  tbody tr.error { background: #fef2f2; }
  tbody tr.error:hover { background: #fee2e2; }
  tbody tr.denied { background: #fffbeb; }
  tbody tr.denied:hover { background: #fef3c7; }
  tbody tr:last-child td { border-bottom: none; }

  td.row-link-cell { padding: 0; }
  .row-link {
    display: grid;
    grid-template-columns: 30% 20% 20% 15% 15%;
    text-decoration: none; color: inherit;
  }
  .row-link .cell { padding: 12px 14px; font-size: 13px; }
  .row-link .cell:first-child { font-weight: 600; color: #111827; }
  .row-link .cell.queue, .row-link .cell.date { color: #4b5563; font-size: 12px; }

  .pill {
    display: inline-block; padding: 3px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 600; text-transform: capitalize;
    white-space: nowrap;
  }
  .pill-ok { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
  .pill-warn { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
  .pill-bad { background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }
  .pill-info { background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }
  .pill-neutral { background: #f3f4f6; color: #4b5563; border: 1px solid #e5e7eb; }

  .empty, .loading {
    text-align: center; padding: 48px 0; color: #9ca3af; font-size: 13px;
    background: white; border: 1px solid #e5e7eb; border-radius: 8px;
  }
  .error-banner {
    padding: 14px; background: #fef2f2; color: #991b1b;
    border: 1px solid #fecaca; border-radius: 8px; font-size: 13px;
  }
  .pagination-bar { display: flex; align-items: center; gap: 12px; }
  .pagination {
    display: flex; align-items: center; gap: 4px;
  }
  .page-btn {
    min-width: 32px; height: 32px; padding: 0 8px;
    font-size: 12px; font-weight: 500; border: 1px solid #d1d5db;
    border-radius: 6px; background: white; color: #374151;
    cursor: pointer; transition: all 0.15s;
  }
  .page-btn:hover { background: #f9fafb; border-color: #93c5fd; }
  .page-btn.active { background: #2563eb; color: white; border-color: #2563eb; }
  .page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .page-btn.ellipsis { border: none; background: none; cursor: default; }
  .page-btn.ellipsis:hover { background: none; }
  .page-jump {
    display: flex; align-items: center; gap: 6px; margin-left: 12px; font-size: 12px; color: #6b7280;
  }
  .page-jump select {
    padding: 4px 6px; font-size: 12px;
    border: 1px solid #d1d5db; border-radius: 4px; background: white;
  }
</style>
</head>
<body>

<div class="page">

  <div class="header">
    <h1>Candid Claims Dashboard</h1>
    <button class="refresh-btn" onclick="resetAndLoad()">Refresh</button>
  </div>

  <div class="filters">
    <label><input type="checkbox" id="filter-errors" onchange="resetAndLoad()"> Errors / denials only</label>
    <label>Sorted by
      <select id="filter-sort" onchange="onSortChange(this.value)">
        <option value="activity" selected>most recent activity</option>
        <option value="submitted">submitted</option>
        <option value="last_sync">last sync</option>
        <option value="status">candid status</option>
        <option value="queue">canvas queue</option>
      </select>
      <select id="filter-sort-dir" onchange="onSortDirChange(this.value)">
        <option value="desc" selected>desc</option>
        <option value="asc">asc</option>
      </select>
    </label>
    <div class="filters-right">
      <span id="pagination-bar" class="pagination-bar"></span>
      <div id="summary" class="summary"></div>
    </div>
  </div>

  <div id="content"><div class="loading">Loading...</div></div>

</div>

<script>
const API_BASE = "/plugin-io/api/candid/dashboard";

const PAGE_SIZE = 50;
let allClaims = [];       // full dataset when client-filtering
let cachedClaims = [];    // current page's claims for rendering
let allStatuses = [];     // distinct statuses across ALL claims (from server)
let allQueues = [];       // distinct queues across ALL claims (from server)
let currentPage = 1;
let totalPages = 1;
let totalClaims = 0;
let clientMode = false;   // true when client-side filters are active
let patientSearchQuery = "";
let sortKey = "activity";
let sortDirection = "desc";
let openFilter = null;

const SORT_CONFIG = {
  activity:  {naturalDesc: true,  keyFn: null},
  submitted: {naturalDesc: true,  keyFn: c => c.submitted_at},
  last_sync: {naturalDesc: true,  keyFn: c => c.last_sync_at},
  status:    {naturalDesc: false, keyFn: c => statusKey(c)},
  queue:     {naturalDesc: false, keyFn: c => queueKey(c)},
};

const filters = {
  status: {selected: new Set(), keyFn: c => statusKey(c), labelFn: statusLabel},
  queue:  {selected: new Set(), keyFn: c => queueKey(c),  labelFn: queueLabel},
};

function hasClientFilters() {
  return !!patientSearchQuery || Object.values(filters).some(f => f.selected.size > 0);
}

async function loadDashboard(page = 1) {
  const errorsOnly = document.getElementById("filter-errors").checked;
  const useClientMode = hasClientFilters();

  const qs = new URLSearchParams();
  if (errorsOnly) qs.set("errors_only", "1");

  if (useClientMode) {
    // Fetch everything so we can filter + paginate client-side
    qs.set("page", "all");
  } else {
    qs.set("page", String(page));
  }

  document.getElementById("content").innerHTML = '<div class="loading">Loading...</div>';
  try {
    const resp = await fetch(`${API_BASE}?${qs.toString()}`, {credentials: "same-origin"});
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    // Store global filter options from the server
    if (data.filter_options) {
      allStatuses = data.filter_options.statuses || [];
      allQueues = data.filter_options.queues || [];
    }

    if (useClientMode) {
      allClaims = data.claims || [];
      clientMode = true;
      clientPaginate(page);
    } else {
      allClaims = [];
      clientMode = false;
      cachedClaims = data.claims || [];
      currentPage = data.page || 1;
      totalPages = data.total_pages || 1;
      totalClaims = data.total || 0;
    }
    render();
  } catch (e) {
    document.getElementById("content").innerHTML =
      `<div class="error-banner">Failed to load: ${e.message}</div>`;
    document.getElementById("summary").textContent = "";
  }
}

function clientPaginate(page = 1) {
  const filtered = allClaims.filter(claimVisible);
  totalClaims = filtered.length;
  totalPages = Math.max(Math.ceil(filtered.length / PAGE_SIZE), 1);
  currentPage = Math.min(Math.max(page, 1), totalPages);
  const start = (currentPage - 1) * PAGE_SIZE;
  cachedClaims = filtered.slice(start, start + PAGE_SIZE);
}

function resetAndLoad() {
  loadDashboard(1);
}

function goToPage(page) {
  if (page < 1 || page > totalPages || page === currentPage) return;
  if (clientMode) {
    clientPaginate(page);
    render();
  } else {
    loadDashboard(page);
  }
}

function buildPagination() {
  const btns = [];
  // Prev
  btns.push(`<button class="page-btn" ${currentPage <= 1 ? "disabled" : ""} onclick="goToPage(${currentPage - 1})">←</button>`);

  // Page numbers with ellipsis
  const pages = paginationRange(currentPage, totalPages);
  for (const p of pages) {
    if (p === "...") {
      btns.push(`<button class="page-btn ellipsis" disabled>…</button>`);
    } else {
      const active = p === currentPage ? " active" : "";
      btns.push(`<button class="page-btn${active}" onclick="goToPage(${p})">${p}</button>`);
    }
  }

  // Next
  btns.push(`<button class="page-btn" ${currentPage >= totalPages ? "disabled" : ""} onclick="goToPage(${currentPage + 1})">→</button>`);

  return btns.join("");
}

function updatePaginationBar() {
  const container = document.getElementById("pagination-bar");
  if (!container) return;
  const options = Array.from({length: totalPages}, (_, i) => {
    const p = i + 1;
    const sel = p === currentPage ? " selected" : "";
    return `<option value="${p}"${sel}>${p}</option>`;
  }).join("");
  const jumpHtml = `<span class="page-jump">Page <select onchange="goToPage(Number(this.value))">${options}</select> of ${totalPages}</span>`;
  container.innerHTML = `<span class="pagination">${buildPagination()}</span>${jumpHtml}`;
}

function paginationRange(current, total) {
  // Always show first, last, and a window around current
  const delta = 2;
  const range = [];
  for (let i = 1; i <= total; i++) {
    if (i === 1 || i === total || (i >= current - delta && i <= current + delta)) {
      range.push(i);
    }
  }
  // Insert ellipsis
  const result = [];
  let prev = 0;
  for (const p of range) {
    if (prev && p - prev > 1) result.push("...");
    result.push(p);
    prev = p;
  }
  return result;
}

function uniqueValues(claims, keyFn) {
  const set = new Set();
  claims.forEach(c => set.add(keyFn(c)));
  return Array.from(set).sort();
}

function allStatusOptions() {
  // Combine server-provided statuses with synthetic keys
  const set = new Set(allStatuses);
  // Add synthetic entries that might apply
  const claims = clientMode ? allClaims : cachedClaims;
  claims.forEach(c => set.add(statusKey(c)));
  return Array.from(set).sort();
}

function allQueueOptions() {
  const set = new Set(allQueues);
  const claims = clientMode ? allClaims : cachedClaims;
  claims.forEach(c => set.add(queueKey(c)));
  return Array.from(set).sort();
}

function statusKey(c) {
  if (c.has_error) return "__error__";
  if (!c.candid_status) return "__pending__";
  return c.candid_status;
}

function queueKey(c) {
  return c.current_queue || "__none__";
}

function statusLabel(value) {
  if (value === "__error__") return "Submission Error";
  if (value === "__pending__") return "Pending";
  return value.replace(/_/g, " ").replace(/\\b\\w/g, c => c.toUpperCase());
}

function queueLabel(value) {
  return value === "__none__" ? "(no queue)" : value;
}

function claimVisible(c) {
  for (const f of Object.values(filters)) {
    if (f.selected.size > 0 && !f.selected.has(f.keyFn(c))) return false;
  }
  if (patientSearchQuery) {
    const name = (c.patient_name || "").toLowerCase();
    if (!name.includes(patientSearchQuery.toLowerCase())) return false;
  }
  return true;
}

function pruneStaleSelections() {
  for (const f of Object.values(filters)) {
    const valid = new Set(cachedClaims.map(f.keyFn));
    f.selected = new Set([...f.selected].filter(v => valid.has(v)));
  }
}

function toggleFilterPopup(filterId) {
  openFilter = openFilter === filterId ? null : filterId;
  refreshHeader();
  if (openFilter === "patient") {
    requestAnimationFrame(() => {
      const input = document.getElementById("patient-search-input");
      if (input) { input.focus(); input.select(); }
    });
  }
}

function onClientFilterChange() {
  if (!clientMode || allClaims.length === 0) {
    // First time a filter is applied — need to fetch all data
    loadDashboard(1);
    return;
  }
  // Already have all data — re-paginate and update just the table + pagination
  clientPaginate(1);
  renderBody();
  updatePaginationBar();
  updateSummary();
}

function toggleFilterValue(filterId, value) {
  const set = filters[filterId].selected;
  if (set.has(value)) set.delete(value); else set.add(value);
  // Update just the filter button appearance, not the whole header
  const trigger = document.querySelector(`[onclick="toggleFilterPopup('${filterId}')"]`);
  if (trigger) {
    const label = set.size === 0 ? "All" : `${set.size} selected`;
    trigger.textContent = `${label} ▾`;
    trigger.classList.toggle("active", set.size > 0);
  }
  onClientFilterChange();
}

function clearFilter(filterId) {
  filters[filterId].selected.clear();
  refreshHeader();
  if (hasClientFilters()) {
    onClientFilterChange();
  } else {
    clientMode = false;
    allClaims = [];
    loadDashboard(1);
  }
}

function onPatientSearchInput(value) {
  patientSearchQuery = value;
  const trigger = document.getElementById("filter-trigger-patient");
  if (trigger) {
    trigger.classList.toggle("active", !!value);
    trigger.firstChild.textContent = value ? `"${value}"` : "Search";
  }
  if (clientMode && allClaims.length > 0) {
    clientPaginate(1);
    renderBody();
    updatePaginationBar();
    updateSummary();
  } else {
    // First keystroke — need to fetch all data; restore focus after
    openFilter = "patient";
    loadDashboard(1).then(() => {
      requestAnimationFrame(() => {
        const input = document.getElementById("patient-search-input");
        if (input) { input.focus(); input.selectionStart = input.selectionEnd = input.value.length; }
      });
    });
  }
}

function onSortChange(value) {
  sortKey = value;
  sortDirection = SORT_CONFIG[value].naturalDesc ? "desc" : "asc";
  const dirSelect = document.getElementById("filter-sort-dir");
  if (dirSelect) dirSelect.value = sortDirection;
  renderBody();
}

function onSortDirChange(value) {
  sortDirection = value;
  renderBody();
}

function sortClaims(claims) {
  const keyFn = SORT_CONFIG[sortKey].keyFn;
  if (!keyFn) {
    return sortDirection === "desc" ? claims : claims.slice().reverse();
  }
  const copy = claims.slice();
  copy.sort((x, y) => {
    const a = keyFn(x), b = keyFn(y);
    if (!a && !b) return 0;
    if (!a) return 1;
    if (!b) return -1;
    return sortDirection === "desc" ? b.localeCompare(a) : a.localeCompare(b);
  });
  return copy;
}

function clearPatientSearch() {
  patientSearchQuery = "";
  refreshHeader();
  if (hasClientFilters()) {
    onClientFilterChange();
  } else {
    // No more filters — go back to server-side pagination
    clientMode = false;
    allClaims = [];
    loadDashboard(1);
  }
  requestAnimationFrame(() => {
    const input = document.getElementById("patient-search-input");
    if (input) input.focus();
  });
}

function buildFilterWidget(filterId, values) {
  const {selected, labelFn} = filters[filterId];
  const triggerLabel = selected.size === 0 ? "All" : `${selected.size} selected`;
  const activeClass = selected.size > 0 ? " active" : "";
  const openClass = openFilter === filterId ? " open" : "";

  const options = values.map(v => {
    const checked = selected.has(v) ? " checked" : "";
    return `<label><input type="checkbox" data-value="${escapeHtml(v)}"${checked} onchange="toggleFilterValue('${filterId}', this.dataset.value)"> ${escapeHtml(labelFn(v))}</label>`;
  }).join("");

  const clearBtn = selected.size > 0
    ? `<button onclick="clearFilter('${filterId}')">Clear</button>`
    : "<span></span>";

  return `
    <div class="filter-wrap" onclick="event.stopPropagation()">
      <button class="col-filter${activeClass}" onclick="toggleFilterPopup('${filterId}')">${escapeHtml(triggerLabel)} ▾</button>
      <div class="filter-popup${openClass}">
        <div class="filter-popup-header">
          <span class="count">${values.length} option${values.length === 1 ? "" : "s"}</span>
          ${clearBtn}
        </div>
        ${options}
      </div>
    </div>`;
}

function refreshHeader() {
  const head = document.getElementById("thead-row");
  if (head) head.innerHTML = headerCellsHtml();
}

function buildPatientSearchWidget() {
  const isActive = !!patientSearchQuery;
  const activeClass = isActive ? " active" : "";
  const openClass = openFilter === "patient" ? " open" : "";
  const triggerLabel = isActive ? `"${escapeHtml(patientSearchQuery)}"` : "Search";
  const clearBtn = isActive
    ? `<button class="patient-clear" onclick="clearPatientSearch()">Clear</button>`
    : "";
  return `
    <div class="filter-wrap" onclick="event.stopPropagation()">
      <button id="filter-trigger-patient" class="col-filter${activeClass}" onclick="toggleFilterPopup('patient')">${triggerLabel} ▾</button>
      <div class="filter-popup patient-search-popup${openClass}">
        <input type="text" id="patient-search-input"
               placeholder="Search by name…"
               value="${escapeHtml(patientSearchQuery)}"
               oninput="onPatientSearchInput(this.value)">
        ${clearBtn}
      </div>
    </div>`;
}

function headerCellsHtml() {
  return `
    <th>Patient${buildPatientSearchWidget()}</th>
    <th>Candid Status${buildFilterWidget("status", allStatusOptions())}</th>
    <th>Canvas Queue${buildFilterWidget("queue", allQueueOptions())}</th>
    <th>Submitted</th>
    <th>Last Sync</th>`;
}

function statusPill(status, isDenied, hasError) {
  if (hasError) return '<span class="pill pill-bad">Submission Error</span>';
  if (!status) return '<span class="pill pill-neutral">Pending</span>';
  const s = status.toLowerCase();
  const display = status.replace(/_/g, " ");
  let cls = "pill-info";
  if (isDenied) cls = "pill-warn";
  else if (s.includes("paid")) cls = "pill-ok";
  else if (s.includes("reject") || s.includes("fail")) cls = "pill-bad";
  return `<span class="pill ${cls}">${display}</span>`;
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString("en-US", {month: "short", day: "numeric", year: "numeric"});
  } catch { return iso.slice(0, 10); }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]
  ));
}

function render() {
  pruneStaleSelections();
  const content = document.getElementById("content");

  updatePaginationBar();

  if (cachedClaims.length === 0) {
    updateSummary();
    content.innerHTML = '<div class="empty">No claims match the current filters.</div>';
    return;
  }

  content.innerHTML = `
    <div class="table-wrap">
      <table>
        <colgroup>
          <col style="width: 30%">
          <col style="width: 20%">
          <col style="width: 20%">
          <col style="width: 15%">
          <col style="width: 15%">
        </colgroup>
        <thead>
          <tr id="thead-row">${headerCellsHtml()}</tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>`;

  renderBody();
  updateSummary();
}

function renderBody() {
  const tbody = document.getElementById("tbody");
  if (!tbody) return;
  const visible = sortClaims(cachedClaims.filter(claimVisible));

  if (visible.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:32px; color:#9ca3af;">No claims match the selected filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = visible.map(c => {
    const cls = c.has_error ? "error" : (c.is_denied ? "denied" : "");
    return `
      <tr class="${cls}">
        <td colspan="5" class="row-link-cell">
          <a href="/revenue/claims/${escapeHtml(c.dbid)}" class="row-link" target="_top">
            <span class="cell">${escapeHtml(c.patient_name)}</span>
            <span class="cell">${statusPill(c.candid_status, c.is_denied, c.has_error)}</span>
            <span class="cell queue">${escapeHtml(c.current_queue || "—")}</span>
            <span class="cell date">${formatDate(c.submitted_at)}</span>
            <span class="cell date">${formatDate(c.last_sync_at)}</span>
          </a>
        </td>
      </tr>`;
  }).join("");
}

function updateSummary() {
  const summary = document.getElementById("summary");
  const hasClientFilter = !!patientSearchQuery || Object.values(filters).some(f => f.selected.size > 0);
  const visible = hasClientFilter ? cachedClaims.filter(claimVisible).length : cachedClaims.length;
  const countText = hasClientFilter
    ? `${visible} of ${totalClaims} claim${totalClaims === 1 ? "" : "s"}`
    : `${totalClaims} claim${totalClaims === 1 ? "" : "s"}`;
  summary.textContent = countText;
}

document.addEventListener("click", (e) => {
  if (openFilter !== null && !e.target.closest(".filter-wrap")) {
    openFilter = null;
    refreshHeader();
  }
});

resetAndLoad();
</script>
</body>
</html>"""
