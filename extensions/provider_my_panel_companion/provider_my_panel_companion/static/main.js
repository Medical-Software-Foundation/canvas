(function () {
    "use strict";

    const API_BASE = "/plugin-io/api/provider_my_panel_companion/app";

    document.addEventListener("DOMContentLoaded", init);

    function init() {
        loadPanel();
    }

    function loadPanel() {
        const content = document.getElementById("content");
        const summary = document.getElementById("panel-summary");
        content.innerHTML = '<div class="loading">Loading\u2026</div>';

        fetch(API_BASE + "/patients", { credentials: "same-origin" })
            .then((r) => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then((data) => {
                const patients = data.patients || [];
                summary.textContent = summaryText(patients.length);
                renderPatients(content, patients);
            })
            .catch((err) => {
                summary.textContent = "Panel unavailable";
                content.innerHTML =
                    '<div class="empty">Failed to load: ' + escapeHtml(String(err)) + "</div>";
            });
    }

    function summaryText(count) {
        if (count === 0) return "No patients on your panel yet.";
        if (count === 1) return "1 patient on your panel";
        return count + " patients on your panel";
    }

    function renderPatients(container, patients) {
        if (!patients.length) {
            container.innerHTML =
                '<div class="empty">You don\u2019t have any patients on your panel yet. ' +
                "Patients will appear here once you're added to their care team.</div>";
            return;
        }
        const list = document.createElement("div");
        list.className = "panel-list";
        patients.forEach((p) => list.appendChild(patientRow(p)));
        container.innerHTML = "";
        container.appendChild(list);
    }

    function patientRow(p) {
        const row = document.createElement("div");
        row.className = "patient-row";

        const badge = p.open_task_count > 0
            ? '<span class="open-task-badge">' + p.open_task_count +
              (p.open_task_count === 1 ? " open task" : " open tasks") + '</span>'
            : "";

        const nameHtml =
            '<a class="patient-link" target="_top" href="/companion/patient/' +
            encodeURIComponent(p.id) + '/">' + escapeHtml(p.name || "(unnamed)") + '</a>';

        row.innerHTML =
            '<div class="row-head">' +
                '<div class="patient-name">' + nameHtml + '</div>' +
                badge +
            '</div>' +
            '<div class="visits">' +
                '<div>' +
                    '<span class="label">Last visit</span>' +
                    '<span class="value' + (p.last_appointment ? '' : ' none') + '">' +
                        escapeHtml(formatVisit(p.last_appointment, "No prior visits")) +
                    '</span>' +
                '</div>' +
                '<div>' +
                    '<span class="label">Next visit</span>' +
                    '<span class="value' + (p.next_appointment ? '' : ' none') + '">' +
                        escapeHtml(formatVisit(p.next_appointment, "None scheduled")) +
                    '</span>' +
                '</div>' +
            '</div>';
        return row;
    }

    function formatVisit(iso, fallback) {
        if (!iso) return fallback;
        const d = new Date(iso);
        return d.toLocaleDateString(undefined, {
            month: "short", day: "numeric", year: "numeric",
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }
})();
