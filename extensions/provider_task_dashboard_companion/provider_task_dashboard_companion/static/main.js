(function () {
    "use strict";

    const API_BASE = "/plugin-io/api/provider_task_dashboard_companion/app";
    const STATUSES = ["OPEN", "COMPLETED", "CLOSED"];
    const DEFAULT_STATUSES = new Set(["OPEN"]);

    const PATIENT_ID = metaContent("patient-id");
    const PATIENT_NAME = metaContent("patient-name");
    const PATIENT_MODE = !!PATIENT_ID;

    const state = {
        mine: true,
        selectedStatuses: new Set(DEFAULT_STATUSES),
        selectedLabels: new Set(),
        labels: [],
    };

    document.addEventListener("DOMContentLoaded", init);

    function init() {
        applyPatientMode();
        renderStatusChips();
        if (!PATIENT_MODE) {
            document.getElementById("mine-toggle").addEventListener("change", (e) => {
                state.mine = e.target.checked;
                loadTasks();
            });
        }
        loadFilters().then(loadTasks);
    }

    function metaContent(name) {
        const el = document.querySelector('meta[name="' + name + '"]');
        return (el && el.getAttribute("content")) || "";
    }

    function applyPatientMode() {
        if (!PATIENT_MODE) return;
        document.getElementById("app-title").textContent = "Patient Tasks";
        const subtitle = document.getElementById("app-subtitle");
        if (subtitle) {
            subtitle.textContent = "Tasks for " + (PATIENT_NAME || "this patient");
            subtitle.removeAttribute("hidden");
        }
        const mineLabel = document.getElementById("mine-toggle-label");
        if (mineLabel) mineLabel.setAttribute("hidden", "");
    }

    function loadFilters() {
        return fetch(API_BASE + "/filters", { credentials: "same-origin" })
            .then((r) => r.json())
            .then((data) => {
                state.labels = data.labels || [];
                renderLabelChips();
            })
            .catch(() => {
                document.getElementById("label-chips").innerHTML =
                    '<span class="chip-empty">Could not load labels</span>';
            });
    }

    function renderStatusChips() {
        const container = document.getElementById("status-chips");
        container.innerHTML = "";
        STATUSES.forEach((status) => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "filter-chip" +
                (state.selectedStatuses.has(status) ? " active" : "");
            chip.textContent = titleCase(status);
            chip.addEventListener("click", () => {
                if (state.selectedStatuses.has(status)) {
                    state.selectedStatuses.delete(status);
                } else {
                    state.selectedStatuses.add(status);
                }
                renderStatusChips();
                loadTasks();
            });
            container.appendChild(chip);
        });
    }

    function renderLabelChips() {
        const container = document.getElementById("label-chips");
        container.innerHTML = "";
        if (!state.labels.length) {
            container.innerHTML = '<span class="chip-empty">No labels defined</span>';
            return;
        }
        state.labels.forEach((label) => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "filter-chip" +
                (state.selectedLabels.has(label.id) ? " active" : "");
            const dot = '<span class="color-dot" style="background:' +
                (colorHex(label.color) || "#fde68a") + '"></span>';
            chip.innerHTML = dot + escapeHtml(label.name);
            chip.addEventListener("click", () => {
                if (state.selectedLabels.has(label.id)) {
                    state.selectedLabels.delete(label.id);
                } else {
                    state.selectedLabels.add(label.id);
                }
                renderLabelChips();
                loadTasks();
            });
            container.appendChild(chip);
        });
    }

    function loadTasks() {
        const content = document.getElementById("content");
        content.innerHTML = '<div class="loading">Loading\u2026</div>';

        const params = new URLSearchParams();
        if (PATIENT_MODE) {
            params.set("patient_id", PATIENT_ID);
        } else {
            params.set("mine", state.mine ? "1" : "0");
        }
        if (state.selectedStatuses.size) {
            params.set("statuses", Array.from(state.selectedStatuses).join(","));
        }
        if (state.selectedLabels.size) {
            params.set("labels", Array.from(state.selectedLabels).join(","));
        }

        fetch(API_BASE + "/tasks?" + params.toString(), { credentials: "same-origin" })
            .then((r) => r.json())
            .then((data) => renderTasks(data.tasks || []))
            .catch((err) => {
                content.innerHTML =
                    '<div class="empty">Failed to load: ' + escapeHtml(String(err)) + '</div>';
            });
    }

    function renderTasks(tasks) {
        const content = document.getElementById("content");
        if (!tasks.length) {
            content.innerHTML = '<div class="empty">No tasks match the current filters.</div>';
            return;
        }
        const list = document.createElement("div");
        list.className = "task-list";
        tasks.forEach((t) => list.appendChild(taskRow(t)));
        content.innerHTML = "";
        content.appendChild(list);
    }

    function taskRow(t) {
        const row = document.createElement("div");
        row.className = "task-row";
        row.dataset.taskId = t.id;

        const statusClass = (t.status || "").toLowerCase();
        const dueText = t.due ? formatDue(t.due) : "No due date";
        const dueClass = t.due && new Date(t.due) < new Date() && t.status === "OPEN" ? " overdue" : "";

        const metaParts = ['<span class="due' + dueClass + '">' + escapeHtml(dueText) + '</span>'];
        if (PATIENT_MODE || !state.mine) {
            const assignee = t.assignee_name || "Unassigned";
            metaParts.push('<span>Assignee: ' + escapeHtml(assignee) + '</span>');
        }
        // Suppress the "Patient:" meta in patient-scoped mode (we're already
        // scoped to a single patient — showing it per row is noise).
        if (!PATIENT_MODE && t.patient_name) {
            const patientHtml = t.patient_id
                ? '<a class="patient-link" target="_top" href="/companion/patient/' +
                    encodeURIComponent(t.patient_id) + '/">' + escapeHtml(t.patient_name) + '</a>'
                : escapeHtml(t.patient_name);
            metaParts.push('<span>Patient: ' + patientHtml + '</span>');
        }

        const labelHtml = (t.labels || []).map((lbl) => {
            const color = colorHex(lbl.color) || "#d97706";
            return '<span class="label-pill"><span class="color-dot" style="background:' +
                color + '"></span>' + escapeHtml(lbl.name) + '</span>';
        }).join("");

        const commentCount = t.comment_count || 0;
        const commentSummary = commentCount > 0
            ? '<div class="comment-summary">' + commentCount +
              (commentCount === 1 ? " comment" : " comments") + '</div>'
            : "";

        row.innerHTML =
            '<div class="row-head">' +
                '<div class="title">' + escapeHtml(t.title || "(untitled)") + '</div>' +
                '<span class="status-pill ' + statusClass + '">' +
                    titleCase(t.status || "") + '</span>' +
                '<svg class="expand-caret" viewBox="0 0 24 24" aria-hidden="true">' +
                    '<path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" ' +
                    'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>' +
                '</svg>' +
            '</div>' +
            '<div class="meta">' + metaParts.join("") + '</div>' +
            (labelHtml ? '<div class="label-row">' + labelHtml + '</div>' : "") +
            commentSummary +
            '<div class="task-detail" hidden></div>';

        const detailEl = row.querySelector(".task-detail");
        detailEl.addEventListener("click", (e) => e.stopPropagation());

        row.querySelectorAll(".patient-link").forEach((a) => {
            a.addEventListener("click", (e) => e.stopPropagation());
        });

        row.addEventListener("click", () => {
            const willOpen = detailEl.hasAttribute("hidden");
            if (willOpen) {
                detailEl.removeAttribute("hidden");
                row.classList.add("expanded");
                if (!detailEl.dataset.loaded) {
                    loadTaskDetail(t, detailEl);
                }
            } else {
                detailEl.setAttribute("hidden", "");
                row.classList.remove("expanded");
            }
        });

        return row;
    }

    function loadTaskDetail(initialTask, detailEl) {
        detailEl.innerHTML = '<div class="loading small">Loading\u2026</div>';
        fetch(API_BASE + "/tasks/" + encodeURIComponent(initialTask.id), {
            credentials: "same-origin",
        })
            .then((r) => r.json())
            .then((data) => {
                detailEl.dataset.loaded = "1";
                renderTaskDetail(detailEl, data.task || initialTask, data.comments || []);
            })
            .catch((err) => {
                detailEl.innerHTML =
                    '<div class="detail-error">Failed to load: ' + escapeHtml(String(err)) + '</div>';
            });
    }

    function renderTaskDetail(detailEl, task, comments) {
        detailEl.innerHTML = "";

        const commentsWrap = document.createElement("div");
        commentsWrap.className = "comments";
        renderComments(commentsWrap, comments);
        detailEl.appendChild(commentsWrap);

        const composer = document.createElement("form");
        composer.className = "comment-composer";
        composer.innerHTML =
            '<textarea class="comment-input" rows="2" placeholder="Add a comment\u2026"></textarea>' +
            '<button type="submit" class="btn primary compact">Post</button>';
        const textarea = composer.querySelector("textarea");
        const submitBtn = composer.querySelector("button");
        composer.addEventListener("submit", (e) => {
            e.preventDefault();
            const body = textarea.value.trim();
            if (!body) return;
            submitBtn.disabled = true;
            fetch(API_BASE + "/tasks/" + encodeURIComponent(task.id) + "/comments", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ body }),
            })
                .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
                .then(({ ok, data }) => {
                    if (!ok) throw new Error(data.error || "Request failed");
                    comments.push({
                        id: "pending-" + Date.now(),
                        body,
                        created: new Date().toISOString(),
                        creator_name: "You",
                    });
                    renderComments(commentsWrap, comments);
                    textarea.value = "";
                })
                .catch((err) => {
                    alert("Could not post comment: " + err.message);
                })
                .finally(() => {
                    submitBtn.disabled = false;
                });
        });
        detailEl.appendChild(composer);

        if (task.can_complete || task.can_assign_to_me) {
            const actions = document.createElement("div");
            actions.className = "task-actions";

            if (task.can_assign_to_me) {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "btn";
                btn.textContent = "Assign to me";
                btn.addEventListener("click", () => performAction(task.id, "assign-to-me", btn));
                actions.appendChild(btn);
            }
            if (task.can_complete) {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "btn primary";
                btn.textContent = "Mark complete";
                btn.addEventListener("click", () => performAction(task.id, "complete", btn));
                actions.appendChild(btn);
            }

            detailEl.appendChild(actions);
        }
    }

    function renderComments(container, comments) {
        if (!comments.length) {
            container.innerHTML = '<div class="no-comments">No comments yet.</div>';
            return;
        }
        container.innerHTML = "";
        comments.forEach((c) => {
            const item = document.createElement("div");
            item.className = "comment";
            const meta =
                '<div class="comment-meta">' +
                '<span class="comment-author">' +
                escapeHtml(c.creator_name || "Unknown") +
                '</span>' +
                (c.created
                    ? '<span class="comment-time">' + escapeHtml(formatCommentTime(c.created)) + '</span>'
                    : "") +
                '</div>';
            item.innerHTML = meta + '<div class="comment-body">' + escapeHtml(c.body || "") + '</div>';
            container.appendChild(item);
        });
    }

    function performAction(taskId, action, button) {
        button.disabled = true;
        fetch(API_BASE + "/tasks/" + encodeURIComponent(taskId) + "/" + action, {
            method: "POST",
            credentials: "same-origin",
        })
            .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
            .then(({ ok, data }) => {
                if (!ok) throw new Error(data.error || "Request failed");
                loadTasks();
            })
            .catch((err) => {
                alert("Action failed: " + err.message);
                button.disabled = false;
            });
    }

    function formatCommentTime(iso) {
        const d = new Date(iso);
        const now = new Date();
        if (d.toDateString() === now.toDateString()) {
            return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
        }
        return d.toLocaleDateString(undefined, {
            month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
        });
    }

    function formatDue(iso) {
        const d = new Date(iso);
        const today = new Date();
        const sameDay = d.toDateString() === today.toDateString();
        if (sameDay) {
            return "Due today, " + d.toLocaleTimeString(undefined, {
                hour: "numeric", minute: "2-digit"
            });
        }
        return "Due " + d.toLocaleDateString(undefined, {
            month: "short", day: "numeric", year: "numeric"
        });
    }

    function titleCase(s) {
        if (!s) return "";
        return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
    }

    function colorHex(name) {
        const map = {
            red: "#dc2626",
            orange: "#ea580c",
            yellow: "#ca8a04",
            green: "#16a34a",
            blue: "#1d4ed8",
            purple: "#7c3aed",
            pink: "#db2777",
            gray: "#6b7280",
            grey: "#6b7280",
            black: "#1f2937",
        };
        return map[(name || "").toLowerCase()] || "";
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }
})();
