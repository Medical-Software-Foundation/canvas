/* Recent Patients — desktop modal frontend.
   Fetches the staff member's recent-interaction rows, groups them by
   day-bucket in the user's local timezone, and renders a searchable list. */

const API_BASE = location.pathname.replace(/\/[^/]*$/, "");
const SEARCH_DEBOUNCE_MS = 120;

const CLIPBOARD_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="8" y="3" width="8" height="4" rx="1"/>' +
    '<path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/>' +
    '<path d="M8 12h8"/>' +
    '<path d="M8 16h5"/>' +
    "</svg>";

const PROFILE_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' +
    '<circle cx="12" cy="8" r="4"/>' +
    '<path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>' +
    "</svg>";

const INTERACTION_META = {
    chart_view: { icon: CLIPBOARD_ICON, label: "Chart" },
    profile_view: { icon: PROFILE_ICON, label: "Profile" },
};
const DEFAULT_META = INTERACTION_META.chart_view;

const BUCKET_ORDER = ["today", "yesterday", "thisWeek"];
const BUCKET_LABELS = {
    today: "Today",
    yesterday: "Yesterday",
    thisWeek: "This Week",
};

const $ = (sel) => document.querySelector(sel);
const escapeHTML = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    })[c]);

function startOfLocalDay(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
}

function bucketFor(occurredAt, today) {
    const occurred = new Date(occurredAt);
    const occurredDay = startOfLocalDay(occurred);
    const todayDay = startOfLocalDay(today);
    const dayDiff = Math.round(
        (todayDay - occurredDay) / (1000 * 60 * 60 * 24)
    );
    if (dayDiff <= 0) return "today";
    if (dayDiff === 1) return "yesterday";
    return "thisWeek";
}

function relativeTime(occurredAt, now) {
    const occurred = new Date(occurredAt);
    const diffMs = now - occurred;
    const sec = Math.max(0, Math.floor(diffMs / 1000));
    if (sec < 60) return "just now";
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.floor(hr / 24);
    if (day < 7) return `${day}d ago`;
    const wk = Math.floor(day / 7);
    if (wk < 5) return `${wk}w ago`;
    return occurred.toLocaleDateString();
}

function formatDob(dobIso) {
    if (!dobIso) return null;
    const d = new Date(dobIso);
    if (isNaN(d)) return null;
    return d.toLocaleDateString();
}

function renderRow(row, now) {
    const meta = INTERACTION_META[row.interaction_type] || DEFAULT_META;
    const dobPart = formatDob(row.dob);
    const dobHtml = dobPart ? `DOB ${escapeHTML(dobPart)}` : "";
    return `
        <a class="row" href="/patient/${encodeURIComponent(
            row.patient_id
        )}" target="_top">
            <span class="interaction-icon" title="${escapeHTML(meta.label)}"
                  aria-label="${escapeHTML(meta.label)}">${meta.icon}</span>
            <div class="body">
                <div class="patient-name">${escapeHTML(row.name)}</div>
                <div class="meta">${dobHtml}</div>
            </div>
            <div class="time">${escapeHTML(relativeTime(row.occurred_at, now))}</div>
        </a>
    `;
}

function groupRowsByBucket(rows, today) {
    const buckets = { today: [], yesterday: [], thisWeek: [] };
    for (const row of rows) {
        buckets[bucketFor(row.occurred_at, today)].push(row);
    }
    return buckets;
}

function filterRows(rows, query) {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) => (row.name || "").toLowerCase().includes(q));
}

function renderResults(rows, query) {
    const content = $("#content");
    const summary = $("#results-summary");
    const now = new Date();

    const filtered = filterRows(rows, query);

    if (filtered.length === 0) {
        summary.textContent = query
            ? `No matches for "${query}"`
            : "No recent patients yet";
        content.innerHTML =
            '<div class="empty-state">Nothing to show.</div>';
        return;
    }

    summary.textContent = `${filtered.length} of ${rows.length} ${
        rows.length === 1 ? "patient" : "patients"
    }`;

    const buckets = groupRowsByBucket(filtered, now);
    const html = BUCKET_ORDER.flatMap((bucket) => {
        const rowsInBucket = buckets[bucket];
        if (rowsInBucket.length === 0) return [];
        return [
            '<section class="bucket">',
            `<h2 class="bucket-label">${BUCKET_LABELS[bucket]}</h2>`,
            ...rowsInBucket.map((row) => renderRow(row, now)),
            "</section>",
        ];
    }).join("");

    content.innerHTML = html;
}

let allRows = [];
let searchTimer = null;

async function loadData() {
    try {
        const res = await fetch(`${API_BASE}/data`, {
            headers: { Accept: "application/json" },
            credentials: "same-origin",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = await res.json();
        allRows = Array.isArray(payload.rows) ? payload.rows : [];
        renderResults(allRows, $("#search-input").value);
    } catch (err) {
        $("#content").innerHTML =
            '<div class="empty-state">Couldn\'t load your recent patients. Please refresh.</div>';
        $("#results-summary").textContent = "Error";
        console.error(err);
    }
}

function bindSearch() {
    const input = $("#search-input");
    input.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            renderResults(allRows, input.value);
        }, SEARCH_DEBOUNCE_MS);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    bindSearch();
    loadData();
});
