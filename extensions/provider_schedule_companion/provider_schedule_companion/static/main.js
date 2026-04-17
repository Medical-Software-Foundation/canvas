(function () {
    "use strict";

    const API_BASE = "/plugin-io/api/provider_schedule_companion/app";
    const DOW_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const MONTH_LONG = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ];

    const state = {
        view: "day",
        cursor: stripTime(new Date()),
    };

    document.addEventListener("DOMContentLoaded", init);

    function init() {
        document.querySelectorAll(".view-btn").forEach((btn) => {
            btn.addEventListener("click", () => setView(btn.dataset.view));
        });
        document.getElementById("prev-btn").addEventListener("click", () => shift(-1));
        document.getElementById("next-btn").addEventListener("click", () => shift(1));
        document.getElementById("today-btn").addEventListener("click", () => {
            state.cursor = stripTime(new Date());
            render();
        });
        render();
    }

    function setView(view) {
        if (state.view === view) return;
        state.view = view;
        document.querySelectorAll(".view-btn").forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.view === view);
        });
        render();
    }

    function shift(delta) {
        const d = new Date(state.cursor);
        if (state.view === "day") {
            d.setDate(d.getDate() + delta);
        } else if (state.view === "week") {
            d.setDate(d.getDate() + delta * 7);
        } else {
            d.setMonth(d.getMonth() + delta);
        }
        state.cursor = stripTime(d);
        render();
    }

    function render() {
        updateTitle();
        const content = document.getElementById("content");
        content.innerHTML = '<div class="loading">Loading\u2026</div>';

        const range = rangeForView();
        fetchAppointments(range.start, range.end)
            .then((appointments) => {
                if (state.view === "day") {
                    renderDay(content, appointments, state.cursor);
                } else if (state.view === "week") {
                    renderWeek(content, appointments, range.start);
                } else {
                    renderMonth(content, appointments, state.cursor);
                }
            })
            .catch((err) => {
                content.innerHTML =
                    '<div class="empty">Failed to load: ' + escapeHtml(String(err)) + "</div>";
            });
    }

    function updateTitle() {
        const t = document.getElementById("view-title");
        const c = state.cursor;
        if (state.view === "day") {
            t.textContent = formatDayHeader(c);
        } else if (state.view === "week") {
            const weekStart = startOfWeek(c);
            const weekEnd = new Date(weekStart);
            weekEnd.setDate(weekEnd.getDate() + 6);
            t.textContent = formatShort(weekStart) + " \u2013 " + formatShort(weekEnd);
        } else {
            t.textContent = MONTH_LONG[c.getMonth()] + " " + c.getFullYear();
        }
    }

    function rangeForView() {
        const c = state.cursor;
        if (state.view === "day") {
            const s = stripTime(c);
            const e = new Date(s);
            e.setDate(e.getDate() + 1);
            return { start: s, end: e };
        }
        if (state.view === "week") {
            const s = startOfWeek(c);
            const e = new Date(s);
            e.setDate(e.getDate() + 7);
            return { start: s, end: e };
        }
        const s = new Date(c.getFullYear(), c.getMonth(), 1);
        const e = new Date(c.getFullYear(), c.getMonth() + 1, 1);
        // Month view: pad out to the full 6-week grid so leading/trailing days
        // in adjacent months are counted when displayed.
        const gridStart = startOfWeek(s);
        const gridEnd = new Date(gridStart);
        gridEnd.setDate(gridEnd.getDate() + 42);
        return { start: gridStart, end: gridEnd, month: { start: s, end: e } };
    }

    function fetchAppointments(start, end) {
        const url = API_BASE + "/appointments?start=" +
            encodeURIComponent(start.toISOString()) +
            "&end=" + encodeURIComponent(end.toISOString());
        return fetch(url, { credentials: "same-origin" }).then((r) => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        }).then((data) => data.appointments || []);
    }

    function renderDay(container, appointments, day) {
        if (!appointments.length) {
            container.innerHTML = '<div class="empty">No appointments scheduled.</div>';
            return;
        }
        const list = document.createElement("div");
        list.className = "day-list";
        appointments.forEach((a) => list.appendChild(dayRow(a)));
        container.innerHTML = "";
        container.appendChild(list);
    }

    function dayRow(a) {
        const row = document.createElement("div");
        row.className = "appt-row";
        row.innerHTML =
            '<div class="row-head">' +
            '<div class="time">' + escapeHtml(formatTime(a.start_time)) + '</div>' +
            '<div class="patient">' + patientLinkHtml(a) + '</div>' +
            '</div>' +
            '<div class="detail"><dl>' +
            detailRow("Type", a.appointment_type) +
            detailRow("Reason", a.reason_for_visit) +
            detailRow("Duration", (a.duration_minutes || "?") + " min") +
            '<dt>Status</dt><dd><span class="status-pill">' +
            escapeHtml(a.status || "") + '</span></dd>' +
            '</dl></div>';
        row.addEventListener("click", () => row.classList.toggle("expanded"));
        const link = row.querySelector(".patient-link");
        if (link) link.addEventListener("click", (e) => e.stopPropagation());
        return row;
    }

    function patientLinkHtml(a) {
        const name = escapeHtml(a.patient_name || "(no patient)");
        if (!a.patient_id) return name;
        return '<a class="patient-link" target="_top" href="/companion/patient/' +
            encodeURIComponent(a.patient_id) + '/">' + name + '</a>';
    }

    function detailRow(label, value) {
        const shown = value && String(value).trim() ? value : "\u2014";
        return '<dt>' + escapeHtml(label) + '</dt><dd>' + escapeHtml(shown) + '</dd>';
    }

    function renderWeek(container, appointments, weekStart) {
        const byDay = groupByDateKey(appointments);
        const today = stripTime(new Date()).getTime();
        const stack = document.createElement("div");
        stack.className = "week-stack";
        let todaySection = null;

        for (let i = 0; i < 7; i++) {
            const d = new Date(weekStart);
            d.setDate(d.getDate() + i);
            const key = toISODate(d);
            const dayAppts = byDay[key] || [];
            const isToday = stripTime(d).getTime() === today;

            const section = document.createElement("section");
            section.className = "week-day-section" + (isToday ? " today" : "");
            if (isToday) todaySection = section;

            const header = document.createElement("button");
            header.type = "button";
            header.className = "week-day-header";
            header.innerHTML =
                '<span class="wd-dow">' + DOW_SHORT[d.getDay()] + '</span>' +
                '<span class="wd-date">' + formatShort(d) + '</span>';
            header.addEventListener("click", () => {
                state.view = "day";
                state.cursor = stripTime(d);
                document.querySelectorAll(".view-btn").forEach((b) => {
                    b.classList.toggle("active", b.dataset.view === "day");
                });
                render();
            });
            section.appendChild(header);

            if (dayAppts.length) {
                const list = document.createElement("div");
                list.className = "day-list";
                dayAppts.forEach((a) => list.appendChild(dayRow(a)));
                section.appendChild(list);
            } else {
                const empty = document.createElement("div");
                empty.className = "week-empty";
                empty.textContent = "No appointments";
                section.appendChild(empty);
            }

            stack.appendChild(section);
        }

        container.innerHTML = "";
        container.appendChild(stack);

        if (todaySection) {
            todaySection.scrollIntoView({ block: "start", behavior: "auto" });
        }
    }

    function renderMonth(container, appointments, cursor) {
        const countsByKey = {};
        appointments.forEach((a) => {
            const k = toISODate(new Date(a.start_time));
            countsByKey[k] = (countsByKey[k] || 0) + 1;
        });

        const monthStart = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
        const gridStart = startOfWeek(monthStart);
        const today = stripTime(new Date()).getTime();

        const grid = document.createElement("div");
        grid.className = "month-grid";

        DOW_SHORT.forEach((dow) => {
            const h = document.createElement("div");
            h.className = "month-dow";
            h.textContent = dow;
            grid.appendChild(h);
        });

        for (let i = 0; i < 42; i++) {
            const d = new Date(gridStart);
            d.setDate(d.getDate() + i);
            const key = toISODate(d);
            const count = countsByKey[key] || 0;
            const offMonth = d.getMonth() !== cursor.getMonth();
            const isToday = stripTime(d).getTime() === today;

            const cell = document.createElement("div");
            cell.className = "month-cell" +
                (offMonth ? " off-month" : "") +
                (isToday ? " today" : "");
            cell.innerHTML =
                '<div>' + d.getDate() + '</div>' +
                (count > 0 ? '<div class="count-badge">' + count + '</div>' : "");
            cell.addEventListener("click", () => {
                state.view = "day";
                state.cursor = stripTime(d);
                document.querySelectorAll(".view-btn").forEach((b) => {
                    b.classList.toggle("active", b.dataset.view === "day");
                });
                render();
            });
            grid.appendChild(cell);
        }
        container.innerHTML = "";
        container.appendChild(grid);
    }

    function groupByDateKey(appointments) {
        const out = {};
        appointments.forEach((a) => {
            const k = toISODate(new Date(a.start_time));
            (out[k] = out[k] || []).push(a);
        });
        return out;
    }

    function stripTime(d) {
        return new Date(d.getFullYear(), d.getMonth(), d.getDate());
    }

    function startOfWeek(d) {
        const s = stripTime(d);
        s.setDate(s.getDate() - s.getDay());
        return s;
    }

    function toISODate(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        return y + "-" + m + "-" + dd;
    }

    function formatTime(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    }

    function formatDayHeader(d) {
        const today = stripTime(new Date()).getTime();
        const prefix = stripTime(d).getTime() === today ? "Today \u00b7 " : "";
        return prefix + d.toLocaleDateString(undefined, {
            weekday: "short", month: "short", day: "numeric", year: "numeric"
        });
    }

    function formatShort(d) {
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }
})();
