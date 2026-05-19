(function () {
    "use strict";

    const API = "/plugin-io/api/order_sets";
    const app = document.getElementById("app");
    const patientId = app.dataset.patientId;
    const staffId = app.dataset.staffId;

    // DOM refs
    const searchInput = document.getElementById("search-input");
    const setsList = document.getElementById("sets-list");
    const loading = document.getElementById("loading");
    const emptyState = document.getElementById("empty-state");
    const previewOverlay = document.getElementById("preview-overlay");
    const providerOverlay = document.getElementById("provider-overlay");
    const toast = document.getElementById("toast");

    // State
    let allSets = [];
    let activeTab = "shared";
    let activeType = "all";
    let currentPreviewSet = null;
    let providers = [];
    let currentStaffIsProvider = false;

    // ── Init ─────────────────────────────────────────────────────────

    function init() {
        loadSets();
        loadProviders();
        bindEvents();
    }

    function bindEvents() {
        document.querySelectorAll(".tab").forEach(function (tab) {
            tab.addEventListener("click", function () {
                document.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
                tab.classList.add("active");
                activeTab = tab.dataset.tab;
                renderSets();
            });
        });

        document.querySelectorAll(".type-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                document.querySelectorAll(".type-btn").forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                activeType = btn.dataset.type;
                renderSets();
            });
        });

        searchInput.addEventListener("input", renderSets);

        document.getElementById("btn-admin").addEventListener("click", function () {
            window.location.href = API + "/admin-ui";
        });

        document.getElementById("btn-close-preview").addEventListener("click", closePreview);
        document.getElementById("btn-cancel-preview").addEventListener("click", closePreview);
        document.getElementById("btn-confirm-order").addEventListener("click", confirmOrder);

        document.getElementById("check-all").addEventListener("change", function () {
            var checked = this.checked;
            document.querySelectorAll("#preview-items input[type='checkbox']").forEach(function (cb) {
                cb.checked = checked;
            });
        });
    }

    // ── Data Loading ─────────────────────────────────────────────────

    async function loadSets() {
        show(loading);
        hide(emptyState);
        hide(setsList);
        try {
            var resp = await fetch(API + "/sets", { credentials: "same-origin" });
            if (!resp.ok) {
                allSets = [];
                showToast("Failed to load order sets (server error " + resp.status + ")", "error");
                renderSets();
                return;
            }
            var text = await resp.text();
            try { allSets = JSON.parse(text); } catch (_) {
                allSets = [];
                showToast("Failed to load order sets (unexpected response)", "error");
            }
            renderSets();
        } catch (e) {
            showToast("Failed to load order sets: " + e.message, "error");
        } finally {
            hide(loading);
        }
    }

    async function loadProviders() {
        try {
            var resp = await fetch(API + "/providers", { credentials: "same-origin" });
            if (!resp.ok) {
                providers = [];
                showToast("Failed to load providers (server error " + resp.status + ")", "error");
                return;
            }
            var data = await resp.json();
            if (Array.isArray(data)) providers = data;
            // Check if current staff is in the providers list
            currentStaffIsProvider = providers.some(function (p) { return p.id === staffId; });
        } catch (e) {
            providers = [];
            showToast("Failed to load providers: " + e.message, "error");
        }
    }

    // ── Rendering ────────────────────────────────────────────────────

    function renderSets() {
        var query = searchInput.value.toLowerCase().trim();
        var filtered = allSets.filter(function (s) {
            if (activeTab === "shared" && !s.is_shared) return false;
            if (activeTab === "personal" && s.is_shared) return false;
            if (activeType !== "all" && s.order_type !== activeType) return false;
            if (query && s.name.toLowerCase().indexOf(query) === -1 &&
                (s.description || "").toLowerCase().indexOf(query) === -1) return false;
            return true;
        });

        if (filtered.length === 0) {
            hide(setsList);
            show(emptyState);
            return;
        }

        hide(emptyState);
        show(setsList);
        setsList.innerHTML = filtered.map(renderCard).join("");

        setsList.querySelectorAll("[data-action='quick']").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var s = allSets.find(function (x) { return x.id === btn.dataset.id; });
                startOrder("quick", btn.dataset.id, null, s ? s.order_type : "");
            });
        });
        setsList.querySelectorAll("[data-action='preview']").forEach(function (btn) {
            btn.addEventListener("click", function () { openPreview(btn.dataset.id); });
        });
    }

    function renderCard(s) {
        var badgeClass = s.order_type === "lab" ? "badge-lab" :
                         s.order_type === "imaging" ? "badge-imaging" : "badge-poc";
        var badgeText = s.order_type === "lab" ? "Lab" :
                        s.order_type === "imaging" ? "Imaging" : "POC";
        var itemCount = (s.items || []).length;
        var desc = escapeHtml(s.description || "");
        var meta = [];
        if (s.lab_partner_name) meta.push(escapeHtml(s.lab_partner_name));
        meta.push(itemCount + " item" + (itemCount !== 1 ? "s" : ""));
        if (s.fasting_required) meta.push("Fasting required");

        return '<div class="set-card">' +
            '<div class="set-card-header">' +
                '<span class="set-card-name">' + escapeHtml(s.name) + '</span>' +
                '<span class="set-card-badge ' + badgeClass + '">' + badgeText + '</span>' +
            '</div>' +
            (desc ? '<div class="set-card-desc">' + desc + '</div>' : '') +
            '<div class="set-card-meta">' + meta.join(" &middot; ") + '</div>' +
            '<div class="set-card-actions">' +
                '<button class="btn btn-primary btn-sm" data-action="quick" data-id="' + escapeHtml(s.id) + '">Quick Order</button>' +
                '<button class="btn btn-secondary btn-sm" data-action="preview" data-id="' + escapeHtml(s.id) + '">Preview</button>' +
            '</div>' +
        '</div>';
    }

    // ── Preview ──────────────────────────────────────────────────────

    function openPreview(setId) {
        var s = allSets.find(function (x) { return x.id === setId; });
        if (!s) return;
        currentPreviewSet = s;

        document.getElementById("preview-title").textContent = s.name;
        document.getElementById("preview-description").textContent = s.description || "";

        var metaHtml = "";
        if (s.order_type) {
            var badge = s.order_type === "lab" ? "badge-lab" :
                        s.order_type === "imaging" ? "badge-imaging" : "badge-poc";
            var label = s.order_type === "lab" ? "Lab" :
                        s.order_type === "imaging" ? "Imaging" : "POC";
            metaHtml += '<span class="set-card-badge ' + badge + '">' + label + '</span>';
        }
        if (s.lab_partner_name) metaHtml += "<span>" + escapeHtml(s.lab_partner_name) + "</span>";
        if (s.fasting_required) metaHtml += "<span>Fasting required</span>";
        // POC orders use PerformCommand, which has no diagnosis_codes field —
        // don't surface a Dx tag for POC sets even if codes were saved.
        if (s.order_type !== "poc" && s.diagnosis_codes && s.diagnosis_codes.length) {
            metaHtml += "<span>Dx: " + s.diagnosis_codes.map(escapeHtml).join(", ") + "</span>";
        }
        document.getElementById("preview-meta").innerHTML = metaHtml;

        var itemsHtml = (s.items || []).map(function (item) {
            return '<div class="preview-item">' +
                '<input type="checkbox" checked value="' + escapeHtml(item.code) + '" />' +
                '<span class="preview-item-name">' + escapeHtml(item.name) + '</span>' +
                '<span class="preview-item-code">' + escapeHtml(item.code) + '</span>' +
            '</div>';
        }).join("");
        document.getElementById("preview-items").innerHTML = itemsHtml;
        document.getElementById("check-all").checked = true;

        show(previewOverlay);
    }

    function closePreview() {
        hide(previewOverlay);
        currentPreviewSet = null;
    }

    // ── Provider Prompt (shown for lab/imaging if user isn't a provider) ──

    function startOrder(kind, setId, selectedCodes, setOrderType) {
        // POC orders go through PerformCommand which has no ordering_provider_key
        // field, so there's nothing to attribute — skip the provider overlay
        // entirely. Lab/imaging orders are attributed: if the current user is
        // a provider we use their id, otherwise we prompt for one.
        if (setOrderType === "poc" || currentStaffIsProvider) {
            submitOrder(kind, setId, selectedCodes, staffId);
            return;
        }

        // Non-provider: show provider selection overlay
        var select = document.getElementById("provider-select");
        if (providers.length === 0) {
            select.innerHTML = '<option value="">No providers found</option>';
        } else {
            select.innerHTML = '<option value="">-- Select ordering provider --</option>';
            providers.forEach(function (p) {
                var label = p.name + (p.credentials ? " (" + p.credentials + ")" : "");
                var opt = document.createElement("option");
                opt.value = p.id;
                opt.textContent = label;
                select.appendChild(opt);
            });
        }

        // Remove old listeners by cloning
        var confirmBtn = document.getElementById("btn-confirm-provider");
        var cancelBtn = document.getElementById("btn-cancel-provider");
        var newConfirm = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirm, confirmBtn);
        var newCancel = cancelBtn.cloneNode(true);
        cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);

        newConfirm.addEventListener("click", function () {
            var providerId = document.getElementById("provider-select").value;
            if (!providerId) {
                showToast("Please select an ordering provider", "error");
                return;
            }
            hide(providerOverlay);
            submitOrder(kind, setId, selectedCodes, providerId);
        });

        newCancel.addEventListener("click", function () {
            hide(providerOverlay);
        });

        show(providerOverlay);
    }

    async function submitOrder(kind, setId, selectedCodes, providerId) {
        if (kind === "quick") {
            await executeOrder(API + "/execute/" + setId, {
                patient_id: patientId,
                provider_id: providerId,
            });
        } else {
            await executeOrder(API + "/execute-custom", {
                set_id: setId,
                selected_codes: selectedCodes,
                patient_id: patientId,
                provider_id: providerId,
            });
        }
    }

    function confirmOrder() {
        if (!currentPreviewSet) return;
        var checkboxes = document.querySelectorAll("#preview-items input[type='checkbox']:checked");
        var selectedCodes = [];
        checkboxes.forEach(function (cb) { selectedCodes.push(cb.value); });

        if (selectedCodes.length === 0) {
            showToast("Select at least one item", "error");
            return;
        }

        // Capture id BEFORE closePreview() nulls currentPreviewSet.
        var setId = currentPreviewSet.id;
        var orderType = currentPreviewSet.order_type;
        closePreview();
        startOrder("custom", setId, selectedCodes, orderType);
    }

    // ── Order Execution ──────────────────────────────────────────────

    async function executeOrder(url, payload) {
        try {
            var resp = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify(payload),
            });
            var text = await resp.text();
            var data;
            try { data = JSON.parse(text); } catch (_) { data = {}; }

            if (!resp.ok) {
                // Backend handlers no longer wrap with try/except, so a 500
                // may not have an {error: ...} envelope. Always surface a
                // toast so the user gets feedback.
                var msg = data.error || ("Order failed (server error " + resp.status + ")");
                showToast(msg, "error");
                return;
            }

            if (data.status === "ordered") {
                showToast("Ordered " + data.items_count + " items from \"" + data.set_name + "\"", "success");
            } else if (data.error) {
                showToast(data.error, "error");
            } else {
                showToast("Order placed (unexpected response)", "error");
            }
        } catch (e) {
            showToast("Failed to place order: " + e.message, "error");
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────

    function show(el) { if (el) el.classList.remove("hidden"); }
    function hide(el) { if (el) el.classList.add("hidden"); }

    // Escapes the five HTML/attribute-meaningful characters. textContent →
    // innerHTML only escapes &<> (per the HTML serialization algorithm for
    // text nodes), which is unsafe in attribute contexts where `"` and `'`
    // are terminators. We use this everywhere — it's safe in both text and
    // attribute contexts.
    function escapeHtml(str) {
        return String(str == null ? "" : str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    var toastTimeout = null;
    function showToast(msg, type) {
        toast.textContent = msg;
        toast.className = "toast toast-" + (type || "info");
        // Cancel any previously-scheduled hide so a stale timer can't
        // close the toast we just opened.
        if (toastTimeout !== null) clearTimeout(toastTimeout);
        toastTimeout = setTimeout(function () {
            toast.classList.add("hidden");
            toastTimeout = null;
        }, 3000);
    }

    // ── Start ────────────────────────────────────────────────────────
    init();
})();
