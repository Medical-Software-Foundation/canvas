(function () {
    "use strict";

    const API = "/plugin-io/api/my_schedule/app";
    const PX_PER_MIN = 96 / 60;
    const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const STATUS_LABELS = {
        unconfirmed: "Unconfirmed", attempted: "Attempted", confirmed: "Confirmed", arrived: "Arrived",
        roomed: "Roomed", exited: "Exited", noshowed: "No-showed", cancelled: "Cancelled",
    };
    const SETTABLE = ["unconfirmed", "attempted", "confirmed", "arrived", "roomed", "exited"];
    const ALLOW = {
        status: document.body.dataset.allowStatus === "true",
        cancel: document.body.dataset.allowCancel === "true",
        noshow: document.body.dataset.allowNoshow === "true",
    };
    const STAFF_NAME = document.body.dataset.staffName || "";

    const state = { view: "day", cursor: startOfDay(new Date()), miniMonth: null, data: null, openId: null };
    const $ = (id) => document.getElementById(id);

    document.addEventListener("DOMContentLoaded", init);

    function init() {
        $("today-btn").addEventListener("click", () => go(startOfDay(new Date())));
        $("prev-btn").addEventListener("click", () => step(-1));
        $("next-btn").addEventListener("click", () => step(1));
        $("card-close").addEventListener("click", closeCard);
        document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCard(); });
        document.querySelectorAll(".view-btn").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
        render();
    }

    // ── Navigation ───────────────────────────────────────
    function go(day) { state.cursor = startOfDay(day); state.miniMonth = null; render(); }
    function setView(view) {
        state.view = view;
        document.querySelectorAll(".view-btn").forEach((b) => {
            const on = b.dataset.view === view;
            b.classList.toggle("active", on);
            b.setAttribute("aria-selected", on ? "true" : "false");
        });
        render();
    }
    function step(delta) {
        const d = new Date(state.cursor);
        if (state.view === "day") d.setDate(d.getDate() + delta);
        else if (state.view === "week") d.setDate(d.getDate() + 7 * delta);
        else d.setMonth(d.getMonth() + delta, 1);
        go(d);
    }

    function range() {
        const c = state.cursor;
        if (state.view === "day") return { start: c, end: addDays(c, 1), days: [c] };
        if (state.view === "week") {
            const s = startOfWeek(c);
            return { start: s, end: addDays(s, 7), days: Array.from({ length: 7 }, (_, i) => addDays(s, i)) };
        }
        const s = startOfWeek(new Date(c.getFullYear(), c.getMonth(), 1));
        return { start: s, end: addDays(s, 42), days: Array.from({ length: 42 }, (_, i) => addDays(s, i)) };
    }

    // ── Render ───────────────────────────────────────────
    function render() {
        const r = range();
        renderChrome(r);
        const content = $("content");
        content.innerHTML = '<div class="state">Loading your schedule…</div>';
        const url = API + "/appointments?start=" + encodeURIComponent(r.start.toISOString()) +
            "&end=" + encodeURIComponent(r.end.toISOString());
        fetch(url, { credentials: "same-origin" })
            .then((res) => res.json().then((body) => ({ ok: res.ok, body: body })))
            .then(({ ok, body }) => {
                if (!ok) throw new Error(body.error || "Couldn't load your schedule.");
                state.data = body;
                if (state.view === "month") renderMonth(content, r, body.appointments);
                else renderGrid(content, r.days, body);
                renderSummary(r, body.appointments);
                if (state.openId) {
                    const again = body.appointments.find((a) => a.id === state.openId);
                    again ? openCard(again) : closeCard();
                }
            })
            .catch((err) => {
                content.innerHTML = "";
                content.appendChild(el("div", "state", String(err.message || err) + " Reload the page to try again."));
            });
    }

    function renderChrome(r) {
        const c = state.cursor;
        const today = isSameDay(c, new Date());
        let title;
        if (state.view === "day") title = (today ? "Today, " : "") + c.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
        else if (state.view === "week") title = "Week of " + fmtShort(r.days[0]) + " to " + fmtShort(r.days[6]);
        else title = c.toLocaleDateString(undefined, { month: "long", year: "numeric" });
        $("view-title").textContent = title;
        $("stepper-label").textContent = state.view === "day"
            ? c.toLocaleDateString(undefined, { weekday: "long" }) + " " + c.getDate()
            : state.view === "week" ? fmtShort(r.days[0]) + " – " + fmtShort(r.days[6])
                : c.toLocaleDateString(undefined, { month: "short", year: "numeric" });
        renderMini();
    }

    function renderMini() {
        const box = $("mini");
        const m = state.miniMonth || new Date(state.cursor.getFullYear(), state.cursor.getMonth(), 1);
        state.miniMonth = m;
        box.innerHTML = "";
        const head = el("div", "mini-head");
        const prev = el("button", "mini-nav", "‹"); prev.type = "button"; prev.setAttribute("aria-label", "Previous month");
        const next = el("button", "mini-nav", "›"); next.type = "button"; next.setAttribute("aria-label", "Next month");
        prev.addEventListener("click", () => { state.miniMonth = new Date(m.getFullYear(), m.getMonth() - 1, 1); renderMini(); });
        next.addEventListener("click", () => { state.miniMonth = new Date(m.getFullYear(), m.getMonth() + 1, 1); renderMini(); });
        head.append(prev, el("span", "", m.toLocaleDateString(undefined, { month: "long", year: "numeric" })), next);
        const grid = el("div", "mini-grid");
        DOW.forEach((d) => grid.appendChild(el("span", "mini-dow", d.slice(0, 2))));
        const start = startOfWeek(m);
        for (let i = 0; i < 42; i++) {
            const d = addDays(start, i);
            const b = el("button", "mini-day", String(d.getDate()));
            b.type = "button";
            b.setAttribute("aria-label", d.toDateString());
            if (d.getMonth() !== m.getMonth()) b.classList.add("off");
            if (isSameDay(d, new Date())) b.classList.add("today");
            if (isSameDay(d, state.cursor)) b.classList.add("picked");
            b.addEventListener("click", () => go(d));
            grid.appendChild(b);
        }
        box.append(head, grid);
    }

    function renderSummary(r, appts) {
        const live = appts.filter((a) => a.status !== "noshowed");
        const n = live.length;
        const noun = n === 1 ? "visit" : "visits";
        let text;
        if (state.view === "day") text = n + " " + noun + " on this day.";
        else if (state.view === "week") text = n + " " + noun + " this week.";
        else {
            const inMonth = live.filter((a) => new Date(a.start_time).getMonth() === state.cursor.getMonth()).length;
            text = inMonth + (inMonth === 1 ? " visit in " : " visits in ") + state.cursor.toLocaleDateString(undefined, { month: "long" }) + ".";
        }
        const now = Date.now();
        const next = live.find((a) => new Date(a.end_time || a.start_time).getTime() > now);
        if (next && state.view !== "month") {
            const when = new Date(next.start_time);
            const day = isSameDay(when, new Date()) ? "" : when.toLocaleDateString(undefined, { weekday: "short" }) + " ";
            text += " Next: " + day + fmtTime(next.start_time) + " with " + (next.patient_name || "a patient") + ".";
        }
        $("summary").textContent = text;
    }

    // ── Day and week grid ────────────────────────────────
    function renderGrid(container, days, data) {
        const appts = data.appointments;
        const blocks = data.blocks || [];
        const bounds = gridBounds(days, appts, data.grid || { start: 7, end: 19 });
        const total = (bounds.end - bounds.start) * 60 * PX_PER_MIN;
        const grid = el("div", days.length === 1 ? "grid wide" : "grid");
        grid.style.setProperty("--cols", String(days.length));

        grid.appendChild(el("div", "col-head corner"));
        days.forEach((d) => {
            const head = el("div", "col-head");
            if (isSameDay(d, new Date())) head.classList.add("is-today");
            if (days.length === 1) {
                head.appendChild(document.createTextNode(STAFF_NAME || "My schedule"));
                head.appendChild(el("span", "sub", d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })));
            } else {
                const b = el("button", "", DOW[d.getDay()] + " " + d.getDate());
                b.type = "button";
                b.setAttribute("aria-label", "Open " + d.toDateString());
                b.addEventListener("click", () => { state.cursor = startOfDay(d); setView("day"); });
                head.appendChild(b);
            }
            grid.appendChild(head);
        });

        const gutter = el("div", "gutter");
        gutter.style.height = total + "px";
        for (let h = bounds.start; h <= bounds.end; h++) {
            if (h === bounds.start) continue;
            const lab = el("span", "gutter-label", fmtHour(h));
            lab.style.top = (h - bounds.start) * 60 * PX_PER_MIN + "px";
            gutter.appendChild(lab);
        }
        grid.appendChild(gutter);

        const hasHours = blocks.some((b) => b.kind === "available");
        days.forEach((d) => {
            const col = el("div", "day-col");
            col.style.height = total + "px";
            if (hasHours) col.classList.add("has-hours");
            const dayStart = d.getTime() + bounds.start * 3600000;
            const dayEnd = d.getTime() + bounds.end * 3600000;
            blocks.forEach((b) => {
                const s = Math.max(new Date(b.start).getTime(), dayStart);
                const e = Math.min(new Date(b.end).getTime(), dayEnd);
                if (e <= s) return;
                const div = el("div", b.kind === "available" ? "open-block" : "busy-block", b.kind === "busy" ? (b.title || "Blocked") : "");
                div.style.top = (s - dayStart) / 60000 * PX_PER_MIN + "px";
                div.style.height = (e - s) / 60000 * PX_PER_MIN + "px";
                col.appendChild(div);
            });
            for (let h = bounds.start; h < bounds.end; h++) {
                const top = (h - bounds.start) * 60 * PX_PER_MIN;
                if (h > bounds.start) { const l = el("div", "hour-line"); l.style.top = top + "px"; col.appendChild(l); }
                const half = el("div", "half-line"); half.style.top = top + 30 * PX_PER_MIN + "px"; col.appendChild(half);
            }
            if (isSameDay(d, new Date())) {
                const nowMin = (Date.now() - dayStart) / 60000;
                if (nowMin >= 0 && nowMin <= (bounds.end - bounds.start) * 60) {
                    const line = el("div", "now-line"); line.style.top = nowMin * PX_PER_MIN + "px"; col.appendChild(line);
                }
            }
            const mine = appts.filter((a) => isSameDay(new Date(a.start_time), d));
            layoutOverlaps(mine).forEach(({ appt, col: c, cols }) => {
                const s = new Date(appt.start_time).getTime();
                const mins = appt.duration_minutes || 15;
                const height = Math.max(mins * PX_PER_MIN, 24);
                const v = visitBlock(appt, height);
                v.style.top = (s - dayStart) / 60000 * PX_PER_MIN + "px";
                v.style.height = height - 2 + "px";
                v.style.left = "calc(" + (c * 100 / cols) + "% + 3px)";
                v.style.width = "calc(" + (100 / cols) + "% - 6px)";
                if (cols > 1) v.classList.add("is-narrow");
                col.appendChild(v);
            });
            grid.appendChild(col);
        });

        container.innerHTML = "";
        container.appendChild(grid);
        scrollToFocus(container, days, appts, bounds);
    }

    function gridBounds(days, appts, base) {
        let start = base.start, end = base.end;
        appts.forEach((a) => {
            const s = new Date(a.start_time);
            const e = new Date(a.end_time || a.start_time);
            start = Math.min(start, s.getHours());
            end = Math.max(end, e.getHours() + (e.getMinutes() > 0 ? 1 : 0) + (isSameDay(s, e) ? 0 : 24));
        });
        return { start: Math.max(0, start), end: Math.min(24, Math.max(end, start + 1)) };
    }

    function layoutOverlaps(appts) {
        const items = appts.slice().sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
        const out = [];
        let cluster = [], clusterEnd = -Infinity;
        const flush = () => {
            const colEnds = [];
            const placed = cluster.map((appt) => {
                const s = new Date(appt.start_time).getTime();
                let c = colEnds.findIndex((end) => end <= s);
                if (c === -1) { c = colEnds.length; colEnds.push(0); }
                colEnds[c] = s + (appt.duration_minutes || 15) * 60000;
                return { appt, col: c };
            });
            placed.forEach((p) => out.push({ appt: p.appt, col: p.col, cols: colEnds.length }));
            cluster = []; clusterEnd = -Infinity;
        };
        items.forEach((a) => {
            const s = new Date(a.start_time).getTime();
            if (s >= clusterEnd && cluster.length) flush();
            cluster.push(a);
            clusterEnd = Math.max(clusterEnd, s + (a.duration_minutes || 15) * 60000);
        });
        if (cluster.length) flush();
        return out;
    }

    function visitBlock(appt, height) {
        const b = el("button", "visit status-" + (appt.status || "unconfirmed"));
        b.type = "button";
        if (appt.status === "noshowed") b.classList.add("noshowed");
        const now = Date.now();
        const s = new Date(appt.start_time).getTime();
        const e = appt.end_time ? new Date(appt.end_time).getTime() : s;
        if (s <= now && now < e) b.classList.add("is-current");
        const time = fmtTime(appt.start_time) + (appt.end_time ? " – " + fmtTime(appt.end_time) : "");
        b.setAttribute("aria-label", time + ", " + (appt.patient_name || "No patient") + ", " + (appt.appointment_type || "visit"));
        b.appendChild(el("span", "v-name", appt.patient_name || "No patient"));
        b.appendChild(el("span", "v-time", height >= 40 ? time : fmtTime(appt.start_time)));
        if (appt.appointment_type) b.appendChild(el("span", "v-type", appt.appointment_type));
        if (height < 40) b.classList.add("is-short");
        else if (height < 56) b.classList.add("is-medium");
        if (height >= 76 && appt.labels && appt.labels.length) {
            const row = el("span", "v-labels");
            appt.labels.slice(0, 3).forEach((l) => row.appendChild(el("span", "label-chip label-" + (l.color || "grey"), l.name)));
            b.appendChild(row);
        }
        b.addEventListener("click", () => openCard(appt));
        return b;
    }

    function scrollToFocus(container, days, appts, bounds) {
        const now = new Date();
        let focus = null;
        if (days.some((d) => isSameDay(d, now))) focus = now;
        else if (appts.length) focus = new Date(appts[0].start_time);
        if (!focus) return;
        const mins = (focus.getHours() - bounds.start) * 60 + focus.getMinutes() - 45;
        container.scrollTop = Math.max(0, mins * PX_PER_MIN);
    }

    // ── Month ────────────────────────────────────────────
    function renderMonth(container, r, appts) {
        const grid = el("div", "month");
        DOW.forEach((d) => grid.appendChild(el("div", "month-dow", d)));
        r.days.forEach((d) => {
            const cell = el("button", "month-cell");
            cell.type = "button";
            if (d.getMonth() !== state.cursor.getMonth()) cell.classList.add("off");
            if (isSameDay(d, new Date())) cell.classList.add("is-today");
            const mine = appts.filter((a) => isSameDay(new Date(a.start_time), d));
            cell.setAttribute("aria-label", d.toDateString() + ", " + mine.length + (mine.length === 1 ? " visit" : " visits"));
            cell.appendChild(el("span", "m-date", String(d.getDate())));
            mine.slice(0, 3).forEach((a) => {
                const item = el("span", "m-item status-" + (a.status || "unconfirmed"), fmtTime(a.start_time) + "  " + (a.patient_name || "No patient"));
                cell.appendChild(item);
            });
            if (mine.length > 3) cell.appendChild(el("span", "m-more", (mine.length - 3) + " more"));
            cell.addEventListener("click", () => { state.cursor = startOfDay(d); setView("day"); });
            grid.appendChild(cell);
        });
        container.innerHTML = "";
        container.appendChild(grid);
    }

    // ── Visit card ───────────────────────────────────────
    function openCard(appt) {
        state.openId = appt.id;
        const body = $("card-body");
        body.innerHTML = "";
        const time = fmtTime(appt.start_time) + (appt.end_time ? " – " + fmtTime(appt.end_time) : "");
        body.appendChild(el("p", "c-time", new Date(appt.start_time).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }) + ", " + time));
        const name = el("h2", "c-name");
        if (appt.patient_id) {
            const a = el("a", "", appt.patient_name || "Patient");
            a.href = "/patient/" + encodeURIComponent(appt.patient_id);
            a.target = "_top";
            name.appendChild(a);
        } else {
            name.textContent = "No patient";
        }
        body.appendChild(name);
        if (appt.appointment_type) body.appendChild(el("p", "c-type", appt.appointment_type));

        const links = el("div", "c-links");
        if (appt.patient_id && appt.note_dbid) links.appendChild(link("Open visit note", "/patient/" + encodeURIComponent(appt.patient_id) + "#noteId=" + encodeURIComponent(appt.note_dbid), "_top", true));
        if (appt.patient_id) links.appendChild(link("Open chart", "/patient/" + encodeURIComponent(appt.patient_id), "_top"));
        if (/^https:\/\//i.test(appt.meeting_link || "")) links.appendChild(link("Join video", appt.meeting_link, "_blank"));
        if (links.children.length) body.appendChild(links);

        const rows = el("dl", "c-rows");
        addRow(rows, "Status", el("span", "pill status-" + (appt.status || "unconfirmed"), STATUS_LABELS[appt.status] || appt.status || "Unknown"));
        addRow(rows, "Duration", (appt.duration_minutes || "?") + " min");
        if (appt.reason_for_visit) addRow(rows, "Reason", appt.reason_for_visit);
        if (appt.location) addRow(rows, "Location", appt.location);
        if (appt.comment) addRow(rows, "Comment", appt.comment);
        if (appt.labels && appt.labels.length) {
            const chips = el("span");
            appt.labels.forEach((l) => chips.appendChild(el("span", "label-chip label-" + (l.color || "grey"), l.name)));
            addRow(rows, "Labels", chips);
        }
        body.appendChild(rows);

        const actions = actionsFor(appt);
        if (actions) body.appendChild(actions);
        const card = $("card");
        card.hidden = false;
        $("card-close").focus();
    }

    function closeCard() { state.openId = null; $("card").hidden = true; }

    function actionsFor(appt) {
        if (appt.status === "noshowed" || appt.status === "cancelled") return null;
        if (!(ALLOW.status || ALLOW.cancel || ALLOW.noshow)) return null;
        const box = el("div", "c-actions");
        const msg = el("p", "c-msg");
        if (ALLOW.status) {
            const sel = el("select");
            sel.setAttribute("aria-label", "Status");
            SETTABLE.forEach((s) => { const o = el("option", "", STATUS_LABELS[s]); o.value = s; o.selected = s === appt.status; sel.appendChild(o); });
            sel.addEventListener("change", () => post(appt, "status", { status: sel.value }, msg, [sel]));
            box.appendChild(sel);
        }
        if (ALLOW.noshow) box.appendChild(button("Mark no-show", "warn", (b) => { if (confirm("Mark this visit as a no-show?")) post(appt, "noshow", {}, msg, [b]); }));
        if (ALLOW.cancel) box.appendChild(button("Cancel visit", "danger", (b) => { if (confirm("Cancel this visit?")) post(appt, "cancel", {}, msg, [b]); }));
        box.appendChild(msg);
        return box;
    }

    function post(appt, action, payload, msg, controls) {
        msg.textContent = "";
        controls.forEach((c) => { c.disabled = true; });
        fetch(API + "/appointment/" + encodeURIComponent(appt.id) + "/" + action, {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        }).then((r) => r.json().then((d) => ({ ok: r.ok, d: d })))
            .then(({ ok, d }) => {
                if (!ok) throw new Error(d.error || "That didn't save. Try again.");
                // Canvas applies the change just after answering; reload once it has.
                setTimeout(render, 800);
            })
            .catch((err) => {
                msg.textContent = String(err.message || err);
                controls.forEach((c) => { c.disabled = false; });
            });
    }

    // ── Small helpers ────────────────────────────────────
    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }
    function link(text, href, target, primary) {
        const a = el("a", "c-link" + (primary ? " primary" : ""), text);
        a.href = href;
        a.target = target;
        if (target === "_blank") a.rel = "noopener noreferrer";
        return a;
    }
    function button(text, tone, onClick) {
        const b = el("button", "c-btn " + tone, text);
        b.type = "button";
        b.addEventListener("click", () => onClick(b));
        return b;
    }
    function addRow(dl, label, value) {
        dl.appendChild(el("dt", "", label));
        const dd = el("dd");
        if (value instanceof Node) dd.appendChild(value); else dd.textContent = value;
        dl.appendChild(dd);
    }
    function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
    function startOfWeek(d) { const s = startOfDay(d); s.setDate(s.getDate() - s.getDay()); return s; }
    function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
    function isSameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
    function fmtTime(iso) { return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }); }
    function fmtShort(d) { return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
    function fmtHour(h) { const d = new Date(2000, 0, 1, h % 24); return d.toLocaleTimeString(undefined, { hour: "numeric" }); }
})();
