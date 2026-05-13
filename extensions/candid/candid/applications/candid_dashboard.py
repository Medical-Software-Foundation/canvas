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

  .summary { font-size: 12px; color: #6b7280; margin-left: auto; }

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
  tbody tr { cursor: pointer; transition: background 0.1s; }
  tbody tr:hover { background: #f9fafb; }
  tbody tr.error { background: #fef2f2; }
  tbody tr.error:hover { background: #fee2e2; }
  tbody tr.denied { background: #fffbeb; }
  tbody tr.denied:hover { background: #fef3c7; }
  tbody tr:last-child td { border-bottom: none; }

  .patient { font-weight: 600; color: #111827; }
  .queue, .date { color: #4b5563; font-size: 12px; }

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
</style>
</head>
<body>

<div class="page">

  <div class="header">
    <h1>Candid Claims Dashboard</h1>
    <button class="refresh-btn" onclick="loadDashboard()">Refresh</button>
  </div>

  <div class="filters">
    <label><input type="checkbox" id="filter-errors" onchange="loadDashboard()"> Errors / denials only</label>
    <label>Limit
      <select id="filter-limit" onchange="loadDashboard()">
        <option value="50">50</option>
        <option value="100" selected>100</option>
        <option value="200">200</option>
        <option value="500">500</option>
      </select>
    </label>
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
    <div id="summary" class="summary"></div>
  </div>

  <div id="content"><div class="loading">Loading...</div></div>

</div>

<script>
const API_BASE = "/plugin-io/api/candid/dashboard";

let cachedClaims = [];
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

async function loadDashboard() {
  const errorsOnly = document.getElementById("filter-errors").checked;
  const limit = document.getElementById("filter-limit").value;

  const qs = new URLSearchParams();
  if (errorsOnly) qs.set("errors_only", "1");
  if (limit) qs.set("limit", limit);

  document.getElementById("content").innerHTML = '<div class="loading">Loading...</div>';
  try {
    const resp = await fetch(`${API_BASE}?${qs.toString()}`, {credentials: "same-origin"});
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    cachedClaims = data.claims || [];
    render();
  } catch (e) {
    document.getElementById("content").innerHTML =
      `<div class="error-banner">Failed to load: ${e.message}</div>`;
    document.getElementById("summary").textContent = "";
  }
}

function uniqueValues(claims, keyFn) {
  const set = new Set();
  claims.forEach(c => set.add(keyFn(c)));
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

function toggleFilterValue(filterId, value) {
  const set = filters[filterId].selected;
  if (set.has(value)) set.delete(value); else set.add(value);
  refreshHeader();
  renderBody();
  updateSummary();
}

function clearFilter(filterId) {
  filters[filterId].selected.clear();
  refreshHeader();
  renderBody();
  updateSummary();
}

function onPatientSearchInput(value) {
  patientSearchQuery = value;
  // Update only the trigger button in-place so the input keeps focus.
  const trigger = document.getElementById("filter-trigger-patient");
  if (trigger) {
    trigger.classList.toggle("active", !!value);
    trigger.firstChild.textContent = value ? `"${value}"` : "Search";
  }
  renderBody();
  updateSummary();
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
  renderBody();
  updateSummary();
  // Re-focus the input so the user can keep typing.
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
    <th>Candid Status${buildFilterWidget("status", uniqueValues(cachedClaims, statusKey))}</th>
    <th>Canvas Queue${buildFilterWidget("queue", uniqueValues(cachedClaims, queueKey))}</th>
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

function openClaim(claimId) {
  try {
    window.parent.location.href = `/revenue/claims/${claimId}`;
  } catch {
    window.location.href = `/revenue/claims/${claimId}`;
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]
  ));
}

function render() {
  pruneStaleSelections();
  const content = document.getElementById("content");

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
      <tr class="${cls}" onclick="openClaim('${escapeHtml(c.id)}')">
        <td>
          <div class="patient">${escapeHtml(c.patient_name)}</div>
        </td>
        <td>${statusPill(c.candid_status, c.is_denied, c.has_error)}</td>
        <td class="queue">${escapeHtml(c.current_queue || "—")}</td>
        <td class="date">${formatDate(c.submitted_at)}</td>
        <td class="date">${formatDate(c.last_sync_at)}</td>
      </tr>`;
  }).join("");
}

function updateSummary() {
  const summary = document.getElementById("summary");
  const total = cachedClaims.length;
  const hasFilter = !!patientSearchQuery || Object.values(filters).some(f => f.selected.size > 0);
  const visible = hasFilter ? cachedClaims.filter(claimVisible).length : total;
  const countText = hasFilter
    ? `${visible} of ${total} claim${total === 1 ? "" : "s"}`
    : `${total} claim${total === 1 ? "" : "s"}`;
  summary.textContent = countText;
}

document.addEventListener("click", (e) => {
  if (openFilter !== null && !e.target.closest(".filter-wrap")) {
    openFilter = null;
    refreshHeader();
  }
});

loadDashboard();
</script>
</body>
</html>"""
