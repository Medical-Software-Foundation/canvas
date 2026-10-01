/**
 * Collections Report — client-side logic.
 *
 * Fetches payment collection data from the plugin API and renders
 * a filterable, downloadable table view for clinic staff.
 */

(function () {
    "use strict";

    const API_BASE = "/plugin-io/api/collections_report/collections";

    // DOM refs
    const startDateInput = document.getElementById("startDate");
    const endDateInput = document.getElementById("endDate");
    const methodFilter = document.getElementById("methodFilter");
    const todayBtn = document.getElementById("todayBtn");
    const weekBtn = document.getElementById("weekBtn");
    const monthBtn = document.getElementById("monthBtn");
    const downloadCsvBtn = document.getElementById("downloadCsvBtn");
    const collectionsBody = document.getElementById("collectionsBody");
    const emptyState = document.getElementById("emptyState");
    const loadingState = document.getElementById("loadingState");
    const collectionsTable = document.getElementById("collectionsTable");
    const recordCount = document.getElementById("recordCount");
    const dateRangeLabel = document.getElementById("dateRangeLabel");

    // Summary elements
    const summaryTotal = document.getElementById("summaryTotal");
    const summaryCash = document.getElementById("summaryCash");
    const summaryCard = document.getElementById("summaryCard");
    const summaryCheck = document.getElementById("summaryCheck");
    const summaryOther = document.getElementById("summaryOther");

    // Current data for CSV export
    let currentData = [];

    /**
     * Format a date string as YYYY-MM-DD for the API.
     */
    function toISODate(d) {
        return d.toISOString().split("T")[0];
    }

    /**
     * Get today's date in local time as YYYY-MM-DD.
     */
    function todayStr() {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }

    /**
     * Initialize date inputs to today.
     */
    function initDates() {
        const today = todayStr();
        startDateInput.value = today;
        endDateInput.value = today;
    }

    /**
     * Update the date range label in the header.
     */
    function updateDateLabel() {
        const start = startDateInput.value;
        const end = endDateInput.value;

        if (start === end) {
            const d = new Date(start + "T00:00:00");
            const today = todayStr();
            if (start === today) {
                dateRangeLabel.textContent = "Today";
            } else {
                dateRangeLabel.textContent = d.toLocaleDateString("en-US", {
                    weekday: "short", month: "short", day: "numeric", year: "numeric"
                });
            }
        } else {
            const ds = new Date(start + "T00:00:00");
            const de = new Date(end + "T00:00:00");
            const opts = { month: "short", day: "numeric" };
            dateRangeLabel.textContent = `${ds.toLocaleDateString("en-US", opts)} — ${de.toLocaleDateString("en-US", { ...opts, year: "numeric" })}`;
        }
    }

    /**
     * Fetch collections data from the API.
     */
    async function fetchCollections() {
        const params = new URLSearchParams();
        if (startDateInput.value) params.set("start_date", startDateInput.value);
        if (endDateInput.value) params.set("end_date", endDateInput.value);
        if (methodFilter.value) params.set("method", methodFilter.value);

        collectionsBody.innerHTML = "";
        emptyState.style.display = "none";
        collectionsTable.style.display = "none";
        loadingState.style.display = "flex";

        try {
            const resp = await fetch(`${API_BASE}/data?${params.toString()}`, {
                credentials: "same-origin",
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            renderData(data);
        } catch (err) {
            console.error("Failed to fetch collections:", err);
            loadingState.style.display = "none";
            emptyState.querySelector("p").textContent = "Failed to load data. Please try again.";
            emptyState.style.display = "flex";
        }
    }

    /**
     * Render API response data into the table and summary cards.
     */
    function renderData(data) {
        loadingState.style.display = "none";
        currentData = data.collections || [];

        // Update summary
        const summary = data.summary || {};
        summaryTotal.textContent = summary.total_display || "$0.00";
        summaryCash.textContent = summary.cash_display || "$0.00";
        summaryCard.textContent = summary.card_display || "$0.00";
        summaryCheck.textContent = summary.check_display || "$0.00";
        summaryOther.textContent = summary.other_display || "$0.00";

        // Update record count
        const count = data.count || 0;
        recordCount.textContent = `${count} record${count !== 1 ? "s" : ""}`;

        if (currentData.length === 0) {
            emptyState.querySelector("p").textContent = "No collections found for the selected date range.";
            emptyState.style.display = "flex";
            collectionsTable.style.display = "none";
            return;
        }

        collectionsTable.style.display = "table";
        emptyState.style.display = "none";

        collectionsBody.innerHTML = "";
        for (const item of currentData) {
            const tr = document.createElement("tr");

            const methodClass = `method-${(item.method || "other").toLowerCase()}`;

            tr.innerHTML = `
                <td>${escapeHtml(item.date_display)}</td>
                <td>${escapeHtml(item.patient_name)}</td>
                <td class="col-amount">${escapeHtml(item.amount_display)}</td>
                <td><span class="method-badge ${methodClass}">${escapeHtml(item.method_display)}</span></td>
                <td class="cell-description" title="${escapeAttr(item.description)}">${escapeHtml(item.description || "—")}</td>
            `;
            collectionsBody.appendChild(tr);
        }

        updateDateLabel();
    }

    /**
     * Escape HTML entities to prevent XSS.
     */
    function escapeHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    /**
     * Escape for use in HTML attributes.
     */
    function escapeAttr(str) {
        if (!str) return "";
        return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;")
                  .replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    /**
     * Download current data as CSV.
     */
    function downloadCsv() {
        if (!currentData.length) return;

        const headers = ["Date/Time", "Patient", "Amount", "Method", "Description", "Check Number", "Deposit Date"];
        const rows = currentData.map(item => [
            item.date_display,
            item.patient_name,
            item.amount,
            item.method_display,
            item.description || "",
            item.check_number || "",
            item.deposit_date || "",
        ]);

        let csv = headers.join(",") + "\n";
        for (const row of rows) {
            csv += row.map(cell => {
                const val = String(cell).replace(/"/g, '""');
                return `"${val}"`;
            }).join(",") + "\n";
        }

        const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;

        const dateLabel = startDateInput.value === endDateInput.value
            ? startDateInput.value
            : `${startDateInput.value}_to_${endDateInput.value}`;
        link.download = `collections_${dateLabel}.csv`;

        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    /**
     * Set date range to this week (Monday to today).
     */
    function setThisWeek() {
        const now = new Date();
        const day = now.getDay();
        const diff = day === 0 ? 6 : day - 1; // Monday = 0
        const monday = new Date(now);
        monday.setDate(now.getDate() - diff);

        startDateInput.value = toISODate(monday);
        endDateInput.value = todayStr();
        fetchCollections();
    }

    /**
     * Set date range to this month (1st to today).
     */
    function setThisMonth() {
        const now = new Date();
        const first = new Date(now.getFullYear(), now.getMonth(), 1);

        startDateInput.value = toISODate(first);
        endDateInput.value = todayStr();
        fetchCollections();
    }

    /**
     * Set date range to today.
     */
    function setToday() {
        const today = todayStr();
        startDateInput.value = today;
        endDateInput.value = today;
        fetchCollections();
    }

    // Event listeners
    startDateInput.addEventListener("change", fetchCollections);
    endDateInput.addEventListener("change", fetchCollections);
    methodFilter.addEventListener("change", fetchCollections);
    todayBtn.addEventListener("click", setToday);
    weekBtn.addEventListener("click", setThisWeek);
    monthBtn.addEventListener("click", setThisMonth);
    downloadCsvBtn.addEventListener("click", downloadCsv);

    // Initial load
    initDates();
    fetchCollections();
})();
