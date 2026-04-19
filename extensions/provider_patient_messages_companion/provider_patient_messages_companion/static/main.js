(function () {
    "use strict";

    const API_BASE = "/plugin-io/api/provider_patient_messages_companion/app";
    const WS_URL_META = document.querySelector('meta[name="ws-url"]');
    const WS_PATH = WS_URL_META ? WS_URL_META.getAttribute("content") : "";

    const state = {
        view: "threads",               // "threads" | "conversation"
        threads: [],
        threadsById: new Map(),
        conversationPatientId: null,
        conversationMessages: [],
    };

    document.addEventListener("DOMContentLoaded", init);

    function init() {
        document.getElementById("back-btn").addEventListener("click", showThreads);
        document.getElementById("composer").addEventListener("submit", onComposerSubmit);
        const input = document.getElementById("composer-input");
        input.addEventListener("input", () => autoGrowTextarea(input));
        loadThreads();
        connectWebSocket();
    }

    function autoGrowTextarea(el) {
        // Temporarily collapse so scrollHeight reflects actual content.
        el.style.height = "auto";
        const max = 160;
        const next = Math.min(el.scrollHeight, max);
        el.style.height = next + "px";
        // Show the scrollbar only once we've hit the cap.
        el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
    }

    function resetComposerHeight() {
        const input = document.getElementById("composer-input");
        if (!input) return;
        input.style.height = "40px";
        input.style.overflowY = "hidden";
    }

    // ---------- View switching ----------

    function showThreads() {
        state.view = "threads";
        state.conversationPatientId = null;
        state.conversationMessages = [];
        document.getElementById("threads-header").removeAttribute("hidden");
        document.getElementById("conv-header").setAttribute("hidden", "");
        document.getElementById("view-threads").removeAttribute("hidden");
        document.getElementById("view-conversation").setAttribute("hidden", "");
    }

    function showConversation(patientId) {
        state.view = "conversation";
        state.conversationPatientId = patientId;
        state.conversationMessages = [];

        document.getElementById("threads-header").setAttribute("hidden", "");
        document.getElementById("conv-header").removeAttribute("hidden");
        document.getElementById("view-threads").setAttribute("hidden", "");
        document.getElementById("view-conversation").removeAttribute("hidden");

        paintConversationHeader(patientId);
        document.getElementById("messages").innerHTML =
            '<div class="loading">Loading\u2026</div>';
        document.getElementById("composer-input").value = "";
        resetComposerHeight();

        loadConversation(patientId);

        const thread = state.threadsById.get(patientId);
        if (thread && thread.unread_count > 0) {
            markRead(patientId);
        }
    }

    function paintConversationHeader(patientId) {
        const thread = state.threadsById.get(patientId);
        const name = (thread && thread.patient_name) || "Patient";
        document.getElementById("conv-patient").textContent = name;
        const subEl = document.getElementById("conv-sub");
        subEl.innerHTML =
            '<a target="_top" href="/companion/patient/' +
            encodeURIComponent(patientId) + '/">Open patient page</a>';
    }

    // ---------- Threads ----------

    function loadThreads() {
        const view = document.getElementById("view-threads");
        const summary = document.getElementById("panel-summary");
        if (state.view === "threads") {
            view.innerHTML = '<div class="loading">Loading\u2026</div>';
        }

        return fetch(API_BASE + "/threads", { credentials: "same-origin" })
            .then((r) => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then((data) => {
                state.threads = data.threads || [];
                state.threadsById = new Map(
                    state.threads.map((t) => [t.patient_id, t])
                );
                summary.textContent = summaryText(state.threads.length);
                if (state.view === "threads") {
                    renderThreads();
                } else if (state.view === "conversation") {
                    paintConversationHeader(state.conversationPatientId);
                }
            })
            .catch((err) => {
                summary.textContent = "Panel unavailable";
                if (state.view === "threads") {
                    view.innerHTML =
                        '<div class="empty">Failed to load: ' +
                        escapeHtml(String(err)) + '</div>';
                }
            });
    }

    function summaryText(count) {
        if (count === 0) return "No patients on your panel.";
        if (count === 1) return "1 patient on your panel";
        return count + " patients on your panel";
    }

    function renderThreads() {
        const view = document.getElementById("view-threads");
        if (!state.threads.length) {
            view.innerHTML =
                '<div class="empty">You don\u2019t have any patients on your panel yet.</div>';
            return;
        }
        view.innerHTML = "";
        state.threads.forEach((t) => view.appendChild(threadRow(t)));
    }

    function threadRow(thread) {
        const row = document.createElement("div");
        row.className = "thread-row";
        row.dataset.patientId = thread.patient_id;

        const unreadBadge = thread.unread_count > 0
            ? '<span class="unread-badge">' + thread.unread_count + '</span>'
            : "";

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
                '<div class="patient-name">' +
                    escapeHtml(thread.patient_name || "(unnamed)") +
                '</div>' +
                unreadBadge +
            '</div>' +
            preview;

        row.addEventListener("click", () => showConversation(thread.patient_id));
        return row;
    }

    // ---------- Conversation ----------

    function loadConversation(patientId) {
        return fetch(
            API_BASE + "/threads/" + encodeURIComponent(patientId) + "/messages",
            { credentials: "same-origin" }
        )
            .then((r) => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.json();
            })
            .then((data) => {
                if (state.conversationPatientId !== patientId) return;
                state.conversationMessages = data.messages || [];
                renderConversation();
            })
            .catch((err) => {
                const messagesEl = document.getElementById("messages");
                messagesEl.innerHTML =
                    '<div class="no-messages">Failed to load: ' +
                    escapeHtml(String(err)) + '</div>';
            });
    }

    function renderConversation() {
        const messagesEl = document.getElementById("messages");
        messagesEl.innerHTML = "";
        if (!state.conversationMessages.length) {
            const empty = document.createElement("div");
            empty.className = "no-messages";
            empty.textContent = "No messages yet. Start the conversation.";
            messagesEl.appendChild(empty);
            return;
        }

        let lastDay = "";
        state.conversationMessages.forEach((m) => {
            const day = dayKey(m.created);
            if (day && day !== lastDay) {
                const divider = document.createElement("div");
                divider.className = "day-divider";
                divider.textContent = formatDayLabel(m.created);
                messagesEl.appendChild(divider);
                lastDay = day;
            }
            messagesEl.appendChild(messageBubble(m));
        });

        scrollMessagesToBottom();
    }

    function messageBubble(m) {
        const wrapper = document.createElement("div");
        wrapper.className = "message " + (m.sent_by_me ? "outbound" : "inbound");
        wrapper.innerHTML =
            '<div class="bubble">' + escapeHtml(m.content || "") + '</div>' +
            '<div class="meta">' + escapeHtml(formatMessageTime(m.created)) + '</div>';
        return wrapper;
    }

    function onComposerSubmit(e) {
        e.preventDefault();
        const input = document.getElementById("composer-input");
        const sendBtn = document.getElementById("composer-send");
        const content = input.value.trim();
        if (!content || !state.conversationPatientId) return;
        const patientId = state.conversationPatientId;

        const pending = {
            content,
            sent_by_me: true,
            created: new Date().toISOString(),
        };
        state.conversationMessages.push(pending);
        renderConversation();
        input.value = "";
        resetComposerHeight();

        sendBtn.disabled = true;
        fetch(
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
                    const idx = state.conversationMessages.indexOf(pending);
                    if (idx >= 0) state.conversationMessages.splice(idx, 1);
                    renderConversation();
                    alert("Send failed: " + (data.error || "Request failed"));
                }
            })
            .catch((err) => {
                alert("Send failed: " + err.message);
            })
            .finally(() => {
                sendBtn.disabled = false;
            });
    }

    function markRead(patientId) {
        fetch(
            API_BASE + "/threads/" + encodeURIComponent(patientId) + "/mark-read",
            { method: "POST", credentials: "same-origin" }
        )
            .then((r) => {
                if (!r.ok) return;
                const thread = state.threadsById.get(patientId);
                if (thread) thread.unread_count = 0;
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
        socket.addEventListener("error", () => setWsStatus("error", "Error"));
        socket.addEventListener("message", handleWsMessage);
    }

    function handleWsMessage(event) {
        let payload;
        try {
            payload = JSON.parse(event.data);
        } catch (e) {
            return;
        }
        if (!payload || payload.type !== "new_message") return;

        loadThreads();
        if (
            state.view === "conversation" &&
            state.conversationPatientId === payload.patient_id
        ) {
            loadConversation(state.conversationPatientId);
            const thread = state.threadsById.get(payload.patient_id);
            if (thread && thread.unread_count > 0) {
                markRead(payload.patient_id);
            }
        }
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
        return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    }

    function formatDayLabel(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const mid = new Date(d);
        mid.setHours(0, 0, 0, 0);
        const diffDays = Math.round((today - mid) / 86400000);
        if (diffDays === 0) return "Today";
        if (diffDays === 1) return "Yesterday";
        if (diffDays > 0 && diffDays < 7) {
            return d.toLocaleDateString(undefined, { weekday: "long" });
        }
        return d.toLocaleDateString(undefined, {
            month: "short", day: "numeric", year: "numeric",
        });
    }

    function dayKey(iso) {
        if (!iso) return "";
        const d = new Date(iso);
        return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate();
    }

    function scrollMessagesToBottom() {
        const messagesEl = document.getElementById("messages");
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
        ));
    }
})();
