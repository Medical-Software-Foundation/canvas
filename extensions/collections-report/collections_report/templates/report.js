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

    // Balances view
    const tabCollections = document.getElementById("tabCollections");
    const tabBalances = document.getElementById("tabBalances");
    const collectionsView = document.getElementById("collectionsView");
    const balancesView = document.getElementById("balancesView");
    const balancesBody = document.getElementById("balancesBody");
    const balancesTable = document.getElementById("balancesTable");
    const balancesEmpty = document.getElementById("balancesEmpty");
    const balancesLoading = document.getElementById("balancesLoading");
    const balancesCount = document.getElementById("balancesCount");
    const balancesTotal = document.getElementById("balancesTotal");
    const balancesPatients = document.getElementById("balancesPatients");

    // Current data for CSV export
    let currentData = [];
    let currentBalances = [];
    let activeView = "collections";
    let balancesLoaded = false;

    /**
     * Format a Date as YYYY-MM-DD in LOCAL time.
     *
     * Note: we deliberately avoid toISOString() here — it converts to UTC,
     * which can shift the calendar date forward or back a day depending on
     * the browser's timezone, producing (for example) a "from" date in the
     * future. Reading the local year/month/day keeps it consistent with
     * how "today" is computed below.
     */
    function toISODate(d) {
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }

    /**
     * Get today's date in local time as YYYY-MM-DD.
     */
    function todayStr() {
        return toISODate(new Date());
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
     * Fetch patients with outstanding balances (current, not date filtered).
     */
    async function fetchBalances() {
        balancesBody.innerHTML = "";
        balancesEmpty.style.display = "none";
        balancesTable.style.display = "none";
        balancesLoading.style.display = "flex";

        try {
            const resp = await fetch(`${API_BASE}/balances`, { credentials: "same-origin" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            renderBalances(await resp.json());
            balancesLoaded = true;
        } catch (err) {
            console.error("Failed to fetch balances:", err);
            balancesLoading.style.display = "none";
            balancesEmpty.querySelector("p").textContent = "Failed to load balances. Please try again.";
            balancesEmpty.style.display = "flex";
        }
    }

    /**
     * Render the balances table and summary cards.
     */
    function renderBalances(data) {
        balancesLoading.style.display = "none";
        currentBalances = data.balances || [];

        const summary = data.summary || {};
        balancesTotal.textContent = summary.total_display || "$0.00";
        balancesPatients.textContent = String(summary.patients || 0);
        const count = data.count || 0;
        balancesCount.textContent = `${count} patient${count !== 1 ? "s" : ""}`;

        if (currentBalances.length === 0) {
            balancesEmpty.querySelector("p").textContent = "No patients currently have a balance.";
            balancesEmpty.style.display = "flex";
            balancesTable.style.display = "none";
            return;
        }

        balancesTable.style.display = "table";
        balancesEmpty.style.display = "none";
        balancesBody.innerHTML = "";
        for (const row of currentBalances) {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${escapeHtml(row.patient_name)}</td>
                <td class="col-amount">${escapeHtml(row.balance_display)}</td>
                <td class="col-amount">${escapeHtml(String(row.open_claims))}</td>
                <td>${escapeHtml(row.oldest_dos_display || "—")}</td>
            `;
            balancesBody.appendChild(tr);
        }
    }

    /**
     * Switch between the Collections and Balances Owed views.
     */
    function showView(view) {
        activeView = view;
        const isBalances = view === "balances";
        collectionsView.style.display = isBalances ? "none" : "";
        balancesView.style.display = isBalances ? "" : "none";
        tabCollections.classList.toggle("report-tab-active", !isBalances);
        tabBalances.classList.toggle("report-tab-active", isBalances);
        tabCollections.setAttribute("aria-selected", String(!isBalances));
        tabBalances.setAttribute("aria-selected", String(isBalances));
        dateRangeLabel.style.visibility = isBalances ? "hidden" : "";
        if (isBalances && !balancesLoaded) fetchBalances();
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
     * Download the current view as CSV.
     *
     * The report runs inside an embedded frame, where building a file in
     * the browser and triggering a download is blocked. Instead we ask the
     * server for the CSV: it responds with a Content-Disposition attachment
     * header, so the browser downloads it natively without leaving the page.
     */
    let toastTimer = null;

    /**
     * Show a brief message that fades away on its own.
     */
    function showToast(msg) {
        let toast = document.getElementById("toast");
        if (!toast) {
            toast = document.createElement("div");
            toast.id = "toast";
            toast.className = "toast";
            document.body.appendChild(toast);
        }
        toast.textContent = msg;
        toast.classList.add("toast-visible");
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            toast.classList.remove("toast-visible");
        }, 2500);
    }

    function downloadCsv() {
        if (activeView === "balances") {
            if (!currentBalances.length) {
                showToast("No balances to export.");
                return;
            }
            openDownload(`${API_BASE}/balances.csv`);
            return;
        }

        if (!currentData.length) {
            showToast("No data to export for the selected dates.");
            return;
        }

        const params = new URLSearchParams();
        if (startDateInput.value) params.set("start_date", startDateInput.value);
        if (endDateInput.value) params.set("end_date", endDateInput.value);
        if (methodFilter.value) params.set("method", methodFilter.value);

        openDownload(`${API_BASE}/report.csv?${params.toString()}`);
    }

    /**
     * Open a server CSV URL in a new browsing context. This reliably triggers
     * the server's file download even from inside the embedded report frame,
     * where a same-frame navigation can be blocked.
     */
    function openDownload(url) {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
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
    tabCollections.addEventListener("click", function () { showView("collections"); });
    tabBalances.addEventListener("click", function () { showView("balances"); });

    // Initial load
    initDates();
    fetchCollections();
})();
