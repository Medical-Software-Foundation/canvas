(function () {
    "use strict";

    const API_BASE = "/plugin-io/api/provider_patient_messages_companion/app";
    const WS_URL_META = document.querySelector('meta[name="ws-url"]');
    const WS_PATH = WS_URL_META ? WS_URL_META.getAttribute("content") : "";

    const state = {
        threads: [],
        expandedPatientId: null,
        loadedConversations: new Set(), // patient ids whose messages have been fetched
    };

    document.addEventListener("DOMContentLoaded", init);

    function init() {
        loadThreads();
        connectWebSocket();
    }

    // ---------- Threads ----------

    function loadThreads() {
        const content = document.getElementById("content");
        const summary = document.getElementById("panel-summary");
        content.innerHTML = '<div class="loading">Loading\u2026</div>';

        fetch(API_BASE + "/threads", { credentials: "same-origin" })
            .then((r) => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then((data) => {
                state.threads = data.threads || [];
                summary.textContent = summaryText(state.threads.length);
                renderThreads();
            })
            .catch((err) => {
                summary.textContent = "Panel unavailable";
                content.innerHTML =
                    '<div class="empty">Failed to load: ' +
                    escapeHtml(String(err)) + "</div>";
            });
    }

    function summaryText(count) {
        if (count === 0) return "No patients on your panel.";
        if (count === 1) return "1 patient on your panel";
        return count + " patients on your panel";
    }

    function renderThreads() {
        const content = document.getElementById("content");
        if (!state.threads.length) {
            content.innerHTML =
                '<div class="empty">You don\u2019t have any patients on your panel yet.</div>';
            return;
        }
        const list = document.createElement("div");
        list.className = "thread-list";
        state.threads.forEach((t) => list.appendChild(threadRow(t)));
        content.innerHTML = "";
        content.appendChild(list);

        // Restore expanded state if a thread was open before a re-render.
        if (state.expandedPatientId) {
            const expandedRow = list.querySelector(
                '.thread-row[data-patient-id="' + cssEscape(state.expandedPatientId) + '"]'
            );
            if (expandedRow) {
                expandedRow.classList.add("expanded");
                const drawer = expandedRow.querySelector(".conversation");
                drawer.removeAttribute("hidden");
                state.loadedConversations.delete(state.expandedPatientId);
                renderConversation(state.expandedPatientId, drawer, { reload: true });
            }
        }
    }

    function threadRow(thread) {
        const row = document.createElement("div");
        row.className = "thread-row";
        row.dataset.patientId = thread.patient_id;

        const unreadBadge = thread.unread_count > 0
            ? '<span class="unread-badge">' + thread.unread_count + '</span>'
            : "";

        const link =
            '<a class="patient-link" target="_top" href="/companion/patient/' +
            encodeURIComponent(thread.patient_id) + '/">' +
            escapeHtml(thread.patient_name || "(unnamed)") + '</a>';

        const preview = thread.last_message
            ? '<div class="preview">' +
                '<span class="snippet">' +
                    (thread.last_message.sent_by_me
                        ? '<span class="me-prefix">You:</span>'
                        : "") +
                    escapeHtml(thread.last_message.content || "(empty)") +
                '</span>' +
                '<span class="time">' +
                    escapeHtml(formatPreviewTime(thread.last_message.created)) +
                '</span>' +
              '</div>'
            : '<div class="preview-empty">No messages yet.</div>';

        row.innerHTML =
            '<div class="row-head">' +
                '<div class="patient-name">' + link + '</div>' +
                unreadBadge +
                '<svg class="expand-caret" viewBox="0 0 24 24" aria-hidden="true">' +
                    '<path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" ' +
                    'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>' +
                '</svg>' +
            '</div>' +
            preview +
            '<div class="conversation" hidden></div>';

        const drawer = row.querySelector(".conversation");
        drawer.addEventListener("click", (e) => e.stopPropagation());
        row.querySelectorAll(".patient-link").forEach((a) => {
            a.addEventListener("click", (e) => e.stopPropagation());
        });

        row.addEventListener("click", () => toggleExpand(row, thread, drawer));
        return row;
    }

    function toggleExpand(row, thread, drawer) {
        const willOpen = drawer.hasAttribute("hidden");
        if (willOpen) {
            drawer.removeAttribute("hidden");
            row.classList.add("expanded");
            state.expandedPatientId = thread.patient_id;
            renderConversation(thread.patient_id, drawer);
            if (thread.unread_count > 0) {
                markRead(thread.patient_id, row);
            }
        } else {
            drawer.setAttribute("hidden", "");
            row.classList.remove("expanded");
            if (state.expandedPatientId === thread.patient_id) {
                state.expandedPatientId = null;
            }
        }
    }

    // ---------- Conversation ----------

    function renderConversation(patientId, drawer, opts) {
        opts = opts || {};
        if (state.loadedConversations.has(patientId) && !opts.reload) {
            return;
        }
        drawer.innerHTML = '<div class="loading small">Loading messages\u2026</div>';
        fetch(
            API_BASE + "/threads/" + encodeURIComponent(patientId) + "/messages",
            { credentials: "same-origin" }
        )
            .then((r) => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then((data) => {
                state.loadedConversations.add(patientId);
                paintConversation(drawer, patientId, data.messages || []);
            })
            .catch((err) => {
                drawer.innerHTML =
                    '<div class="loading small">Failed to load: ' +
                    escapeHtml(String(err)) + '</div>';
            });
    }

    function paintConversation(drawer, patientId, messages) {
        drawer.innerHTML = "";
        const messagesEl = document.createElement("div");
        messagesEl.className = "messages";
        renderMessages(messagesEl, messages);
        drawer.appendChild(messagesEl);

        const composer = document.createElement("form");
        composer.className = "composer";
        composer.innerHTML =
            '<textarea rows="1" placeholder="Reply\u2026"></textarea>' +
            '<button type="submit" class="btn primary">Send</button>';
        const textarea = composer.querySelector("textarea");
        const button = composer.querySelector("button");
        composer.addEventListener("submit", (e) => {
            e.preventDefault();
            const content = textarea.value.trim();
            if (!content) return;
            button.disabled = true;
            sendMessage(patientId, content, messagesEl)
                .then(() => {
                    textarea.value = "";
                })
                .catch((err) => alert("Send failed: " + err.message))
                .finally(() => {
                    button.disabled = false;
                });
        });
        drawer.appendChild(composer);

        scrollMessagesToBottom(messagesEl);
    }

    function renderMessages(container, messages) {
        if (!messages.length) {
            container.innerHTML =
                '<div class="no-messages">No messages yet. Start the conversation.</div>';
            return;
        }
        container.innerHTML = "";
        messages.forEach((m) => container.appendChild(messageBubble(m)));
    }

    function messageBubble(m) {
        const wrapper = document.createElement("div");
        wrapper.className = "message " + (m.sent_by_me ? "outbound" : "inbound");
        wrapper.innerHTML =
            '<div class="bubble">' + escapeHtml(m.content || "") + '</div>' +
            '<div class="meta">' + escapeHtml(formatMessageTime(m.created)) + '</div>';
        return wrapper;
    }

    function sendMessage(patientId, content, messagesEl) {
        // Optimistic append.
        const nowIso = new Date().toISOString();
        const pending = messageBubble({
            content, sent_by_me: true, created: nowIso,
        });
        const empty = messagesEl.querySelector(".no-messages");
        if (empty) empty.remove();
        messagesEl.appendChild(pending);
        scrollMessagesToBottom(messagesEl);

        return fetch(
            API_BASE + "/threads/" + encodeURIComponent(patientId) + "/messages",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ content }),
            }
        )
            .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
            .then(({ ok, data }) => {
                if (!ok) {
                    pending.remove();
                    throw new Error(data.error || "Request failed");
                }
            });
    }

    function markRead(patientId, row) {
        fetch(
            API_BASE + "/threads/" + encodeURIComponent(patientId) + "/mark-read",
            { method: "POST", credentials: "same-origin" }
        )
            .then((r) => {
                if (!r.ok) return;
                const thread = state.threads.find(
                    (t) => t.patient_id === patientId
                );
                if (thread) {
                    thread.unread_count = 0;
                }
                const badge = row.querySelector(".unread-badge");
                if (badge) badge.remove();
            })
            .catch(() => {});
    }

    // ---------- WebSocket ----------

    function connectWebSocket() {
        if (!WS_PATH) {
            setWsStatus("error", "Unavailable");
            return;
        }
        const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
        const url = scheme + "//" + window.location.host + WS_PATH;
        let socket;
        try {
            socket = new WebSocket(url);
        } catch (e) {
            setWsStatus("error", "Error");
            return;
        }

        socket.addEventListener("open", () => setWsStatus("live", "Live"));
        socket.addEventListener("close", () => {
            setWsStatus("error", "Reconnecting\u2026");
            setTimeout(connectWebSocket, 4000);
        });
        socket.addEventListener("error", () => {
            setWsStatus("error", "Error");
        });
        socket.addEventListener("message", (event) => handleWsMessage(event));
    }

    function handleWsMessage(event) {
        let payload;
        try {
            payload = JSON.parse(event.data);
        } catch (e) {
            return;
        }
        if (!payload || payload.type !== "new_message") return;
        // Refresh the thread list so previews + unread badges update.
        loadThreads();
    }

    function setWsStatus(classSuffix, label) {
        const indicator = document.getElementById("ws-indicator");
        const labelEl = document.getElementById("ws-label");
        if (!indicator || !labelEl) return;
        indicator.classList.remove("live", "error");
        if (classSuffix) indicator.classList.add(classSuffix);
        labelEl.textContent = label;
    }

    // ---------- Formatting ----------

    function formatPreviewTime(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        const now = new Date();
        const diffMs = now - d;
        if (diffMs < 0) return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
        const mins = Math.floor(diffMs / 60000);
        if (mins < 1) return "now";
        if (mins < 60) return mins + "m";
        const hours = Math.floor(mins / 60);
        if (hours < 24 && d.toDateString() === now.toDateString()) return hours + "h";
        const days = Math.floor(hours / 24);
        if (days < 7) return days + "d";
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }

    function formatMessageTime(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        const now = new Date();
        const same = d.toDateString() === now.toDateString();
        if (same) {
            return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
        }
        return d.toLocaleDateString(undefined, {
            month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
        });
    }

    function scrollMessagesToBottom(el) {
        el.scrollTop = el.scrollHeight;
    }

    function cssEscape(str) {
        if (window.CSS && CSS.escape) return CSS.escape(str);
        return String(str).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }
})();
