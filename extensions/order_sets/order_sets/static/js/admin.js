(function () {
    "use strict";

    var API = "/plugin-io/api/order_sets";
    var adminApp = document.getElementById("admin-app");
    var staffId = adminApp.dataset.staffId;
    var staffName = adminApp.dataset.staffName;

    // DOM refs
    var adminLoading = document.getElementById("admin-loading");
    var adminEmpty = document.getElementById("admin-empty");
    var adminSetsList = document.getElementById("admin-sets-list");
    var formOverlay = document.getElementById("form-overlay");
    var deleteOverlay = document.getElementById("delete-overlay");
    var toast = document.getElementById("toast");
    var setForm = document.getElementById("set-form");

    // State
    var allSets = [];
    var editingSetId = null;
    var deleteSetId = null;
    var selectedItems = []; // [{code, name, type}]
    var labPartners = [];
    var searchTimeout = null;
    var cptSearchTimeout = null;

    // ── Init ─────────────────────────────────────────────────────────

    function init() {
        loadSets();
        loadLabPartners();
        bindEvents();
    }

    function bindEvents() {
        document.getElementById("btn-new-set").addEventListener("click", openNewForm);
        document.getElementById("btn-close-form").addEventListener("click", closeForm);
        document.getElementById("btn-cancel-form").addEventListener("click", closeForm);
        document.getElementById("btn-cancel-delete").addEventListener("click", closeDeleteDialog);
        document.getElementById("btn-confirm-delete").addEventListener("click", confirmDelete);

        // Order type toggle
        document.getElementById("form-order-type").addEventListener("change", toggleOrderTypeFields);

        // Lab partner change -> clear tests
        document.getElementById("form-lab-partner").addEventListener("change", function () {
            selectedItems = [];
            renderSelectedItems();
        });

        // Test search
        document.getElementById("test-search").addEventListener("input", function () {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(searchTests, 300);
        });
        document.getElementById("test-search").addEventListener("focus", searchTests);

        // Add imaging item
        document.getElementById("btn-add-imaging").addEventListener("click", addImagingItem);

        // POC: CPT search + manual add
        document.getElementById("cpt-search").addEventListener("input", function () {
            clearTimeout(cptSearchTimeout);
            cptSearchTimeout = setTimeout(searchCPT, 300);
        });
        document.getElementById("cpt-search").addEventListener("focus", searchCPT);
        document.getElementById("btn-add-poc-manual").addEventListener("click", addPOCManual);

        // Form submit
        setForm.addEventListener("submit", function (e) {
            e.preventDefault();
            saveSet();
        });
    }

    // ── Data Loading ─────────────────────────────────────────────────

    async function loadSets() {
        show(adminLoading);
        hide(adminEmpty);
        hide(adminSetsList);
        try {
            var resp = await fetch(API + "/sets", { credentials: "same-origin" });
            var text = await resp.text();
            try {
                allSets = JSON.parse(text);
            } catch (_) {
                showToast("Load error " + resp.status + ": " + text.substring(0, 200), "error");
                allSets = [];
            }
            renderAdminSets();
        } catch (e) {
            showToast("Load error: " + e.message, "error");
        } finally {
            hide(adminLoading);
        }
    }

    async function loadLabPartners() {
        try {
            var resp = await fetch(API + "/lab-partners", { credentials: "same-origin" });
            labPartners = await resp.json();
            var select = document.getElementById("form-lab-partner");
            select.innerHTML = '<option value="">Select lab partner...</option>';
            labPartners.forEach(function (p) {
                var opt = document.createElement("option");
                opt.value = p.id;
                opt.textContent = p.name;
                select.appendChild(opt);
            });
        } catch (e) {
            // Lab partners may not be available
        }
    }

    async function searchTests() {
        var partnerId = document.getElementById("form-lab-partner").value;
        var query = document.getElementById("test-search").value.trim();
        var resultsDiv = document.getElementById("test-results");

        if (!partnerId) {
            resultsDiv.innerHTML = '<div class="test-result-item" style="color:#9CA3AF">Select a lab partner first</div>';
            show(resultsDiv);
            return;
        }

        try {
            var url = API + "/lab-tests/" + partnerId;
            if (query) url += "?search=" + encodeURIComponent(query);
            var resp = await fetch(url, { credentials: "same-origin" });
            var tests = await resp.json();

            // Filter out already selected
            var selectedCodes = new Set(selectedItems.map(function (i) { return i.code; }));
            tests = tests.filter(function (t) { return !selectedCodes.has(t.code); });

            if (tests.length === 0) {
                resultsDiv.innerHTML = '<div class="test-result-item" style="color:#9CA3AF">No matching tests</div>';
            } else {
                resultsDiv.innerHTML = tests.map(function (t) {
                    return '<div class="test-result-item" data-code="' + escapeHtml(t.code) + '" data-name="' + escapeHtml(t.name) + '">' +
                        '<span>' + escapeHtml(t.name) + '</span>' +
                        '<span class="code">' + escapeHtml(t.code) + '</span>' +
                    '</div>';
                }).join("");

                resultsDiv.querySelectorAll(".test-result-item[data-code]").forEach(function (el) {
                    el.addEventListener("click", function () {
                        selectedItems.push({ code: el.dataset.code, name: el.dataset.name, type: "lab_test" });
                        renderSelectedItems();
                        searchTests(); // Refresh to remove selected
                    });
                });
            }
            show(resultsDiv);
        } catch (e) {
            // Ignore
        }
    }

    async function searchCPT() {
        var query = document.getElementById("cpt-search").value.trim();
        var resultsDiv = document.getElementById("cpt-results");
        try {
            var url = API + "/cpt-search";
            if (query) url += "?q=" + encodeURIComponent(query);
            var resp = await fetch(url, { credentials: "same-origin" });
            var tests = await resp.json();

            var selectedCodes = new Set(selectedItems.map(function (i) { return i.code; }));
            tests = tests.filter(function (t) { return !selectedCodes.has(t.code); });

            if (tests.length === 0) {
                resultsDiv.innerHTML = '<div class="test-result-item" style="color:#9CA3AF">' +
                    (query ? 'No matching CPT codes. Add manually below.' : 'Start typing to search…') +
                    '</div>';
            } else {
                resultsDiv.innerHTML = tests.map(function (t) {
                    return '<div class="test-result-item" data-code="' + escapeHtml(t.code) + '" data-name="' + escapeHtml(t.name) + '">' +
                        '<span>' + escapeHtml(t.name) + '</span>' +
                        '<span class="code">' + escapeHtml(t.code) + '</span>' +
                    '</div>';
                }).join("");
                resultsDiv.querySelectorAll(".test-result-item[data-code]").forEach(function (el) {
                    el.addEventListener("click", function () {
                        selectedItems.push({ code: el.dataset.code, name: el.dataset.name, type: "poc" });
                        renderPOCItems();
                        searchCPT();
                    });
                });
            }
            show(resultsDiv);
        } catch (e) {
            // Ignore
        }
    }

    function addPOCManual() {
        var codeInput = document.getElementById("poc-manual-code");
        var nameInput = document.getElementById("poc-manual-name");
        var code = codeInput.value.trim();
        var name = nameInput.value.trim();
        if (!code || !name) {
            showToast("Enter both CPT code and test name", "error");
            return;
        }
        if (selectedItems.some(function (i) { return i.code === code; })) {
            showToast("Code already added", "error");
            return;
        }
        selectedItems.push({ code: code, name: name, type: "poc" });
        codeInput.value = "";
        nameInput.value = "";
        renderPOCItems();
    }

    // ── Rendering ────────────────────────────────────────────────────

    function renderAdminSets() {
        if (allSets.length === 0) {
            hide(adminSetsList);
            show(adminEmpty);
            return;
        }

        hide(adminEmpty);
        show(adminSetsList);
        adminSetsList.innerHTML = allSets.map(function (s) {
            var badge = s.order_type === "lab" ? "badge-lab" :
                        s.order_type === "imaging" ? "badge-imaging" : "badge-poc";
            var badgeText = s.order_type === "lab" ? "Lab" :
                            s.order_type === "imaging" ? "Imaging" : "POC";
            var visibility = s.is_shared ? "Shared" : "Personal";
            var itemCount = (s.items || []).length;
            return '<div class="admin-set-card">' +
                '<div class="admin-set-info">' +
                    '<div class="admin-set-name">' + escapeHtml(s.name) +
                        ' <span class="set-card-badge ' + badge + '">' + badgeText + '</span>' +
                    '</div>' +
                    '<div class="admin-set-detail">' + visibility + ' &middot; ' + itemCount + ' items' +
                        (s.created_by_name ? ' &middot; by ' + escapeHtml(s.created_by_name) : '') +
                    '</div>' +
                '</div>' +
                '<div class="admin-set-actions">' +
                    '<button class="btn btn-secondary btn-sm" data-action="edit" data-id="' + s.id + '">Edit</button>' +
                    '<button class="btn btn-danger btn-sm" data-action="delete" data-id="' + s.id + '">Delete</button>' +
                '</div>' +
            '</div>';
        }).join("");

        adminSetsList.querySelectorAll("[data-action='edit']").forEach(function (btn) {
            btn.addEventListener("click", function () { openEditForm(btn.dataset.id); });
        });
        adminSetsList.querySelectorAll("[data-action='delete']").forEach(function (btn) {
            btn.addEventListener("click", function () { openDeleteDialog(btn.dataset.id); });
        });
    }

    function renderSelectedItems() {
        var container = document.getElementById("selected-tests");
        if (selectedItems.length === 0) {
            container.innerHTML = '<span class="subtle">No tests selected</span>';
            return;
        }
        container.innerHTML = selectedItems.map(function (item, i) {
            return '<span class="selected-test-tag">' +
                escapeHtml(item.name) +
                ' <button type="button" data-index="' + i + '">&times;</button>' +
            '</span>';
        }).join("");

        container.querySelectorAll("button[data-index]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                selectedItems.splice(parseInt(btn.dataset.index), 1);
                renderSelectedItems();
            });
        });
    }

    function renderImagingItems() {
        var container = document.getElementById("imaging-items");
        if (selectedItems.length === 0) {
            container.innerHTML = '<span class="subtle">No imaging orders added</span>';
            return;
        }
        container.innerHTML = selectedItems.map(function (item, i) {
            return '<span class="selected-test-tag">' +
                escapeHtml(item.name) + ' (' + escapeHtml(item.code) + ')' +
                ' <button type="button" data-index="' + i + '">&times;</button>' +
            '</span>';
        }).join("");

        container.querySelectorAll("button[data-index]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                selectedItems.splice(parseInt(btn.dataset.index), 1);
                renderImagingItems();
            });
        });
    }

    function renderPOCItems() {
        var container = document.getElementById("poc-items");
        if (selectedItems.length === 0) {
            container.innerHTML = '<span class="subtle">No POC tests added</span>';
            return;
        }
        container.innerHTML = selectedItems.map(function (item, i) {
            return '<span class="selected-test-tag">' +
                escapeHtml(item.name) + ' (' + escapeHtml(item.code) + ')' +
                ' <button type="button" data-index="' + i + '">&times;</button>' +
            '</span>';
        }).join("");

        container.querySelectorAll("button[data-index]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                selectedItems.splice(parseInt(btn.dataset.index), 1);
                renderPOCItems();
            });
        });
    }

    // ── Form Operations ──────────────────────────────────────────────

    function openNewForm() {
        editingSetId = null;
        document.getElementById("form-title").textContent = "New Order Set";
        setForm.reset();
        document.getElementById("form-set-id").value = "";
        selectedItems = [];
        renderSelectedItems();
        toggleOrderTypeFields();
        hide(document.getElementById("test-results"));
        show(formOverlay);
    }

    function openEditForm(setId) {
        var s = allSets.find(function (x) { return x.id === setId; });
        if (!s) return;
        editingSetId = setId;
        document.getElementById("form-title").textContent = "Edit Order Set";
        document.getElementById("form-set-id").value = s.id;
        document.getElementById("form-name").value = s.name;
        document.getElementById("form-description").value = s.description || "";
        document.getElementById("form-order-type").value = s.order_type;
        document.getElementById("form-shared").value = s.is_shared ? "true" : "false";
        document.getElementById("form-lab-partner").value = s.lab_partner || "";
        document.getElementById("form-fasting").checked = s.fasting_required || false;
        document.getElementById("form-diagnosis").value = (s.diagnosis_codes || []).join(", ");
        document.getElementById("form-comment").value = s.comment || "";

        selectedItems = (s.items || []).map(function (item) {
            return { code: item.code, name: item.name, type: item.type || "lab_test" };
        });

        toggleOrderTypeFields();
        if (s.order_type === "lab") {
            renderSelectedItems();
        } else if (s.order_type === "imaging") {
            renderImagingItems();
        } else if (s.order_type === "poc") {
            renderPOCItems();
        }
        hide(document.getElementById("test-results"));
        hide(document.getElementById("cpt-results"));
        show(formOverlay);
    }

    function closeForm() {
        hide(formOverlay);
        editingSetId = null;
        selectedItems = [];
    }

    function toggleOrderTypeFields() {
        var orderType = document.getElementById("form-order-type").value;
        hide(document.getElementById("lab-fields"));
        hide(document.getElementById("imaging-fields"));
        hide(document.getElementById("poc-fields"));
        hide(document.getElementById("test-results"));
        hide(document.getElementById("cpt-results"));
        if (orderType === "lab") {
            show(document.getElementById("lab-fields"));
        } else if (orderType === "imaging") {
            show(document.getElementById("imaging-fields"));
            renderImagingItems();
        } else if (orderType === "poc") {
            show(document.getElementById("poc-fields"));
            renderPOCItems();
        }
    }

    function addImagingItem() {
        var codeInput = document.getElementById("imaging-code");
        var nameInput = document.getElementById("imaging-name");
        var code = codeInput.value.trim();
        var name = nameInput.value.trim();
        if (!code || !name) {
            showToast("Enter both code and name", "error");
            return;
        }
        selectedItems.push({ code: code, name: name, type: "imaging" });
        codeInput.value = "";
        nameInput.value = "";
        renderImagingItems();
    }

    async function saveSet() {
        var name = document.getElementById("form-name").value.trim();
        if (!name) { showToast("Name is required", "error"); return; }
        if (selectedItems.length === 0) { showToast("Add at least one item", "error"); return; }

        var orderType = document.getElementById("form-order-type").value;
        var diagStr = document.getElementById("form-diagnosis").value.trim();
        var diagCodes = diagStr ? diagStr.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];

        var labPartnerId = "";
        var labPartnerName = "";
        if (orderType === "lab") {
            labPartnerId = document.getElementById("form-lab-partner").value;
            var partnerOpt = document.getElementById("form-lab-partner").selectedOptions[0];
            labPartnerName = partnerOpt ? partnerOpt.textContent : "";
        }

        var payload = {
            name: name,
            description: document.getElementById("form-description").value.trim(),
            order_type: orderType,
            is_shared: document.getElementById("form-shared").value === "true",
            lab_partner: labPartnerId,
            lab_partner_name: labPartnerName,
            items: selectedItems,
            fasting_required: orderType === "lab" ? document.getElementById("form-fasting").checked : false,
            diagnosis_codes: diagCodes,
            comment: document.getElementById("form-comment").value.trim(),
        };

        var saveBtn = document.getElementById("btn-save-form");
        saveBtn.disabled = true;

        try {
            var url, method;
            if (editingSetId) {
                url = API + "/sets/" + editingSetId;
                method = "PUT";
            } else {
                url = API + "/sets";
                method = "POST";
            }

            var resp = await fetch(url, {
                method: method,
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify(payload),
            });

            if (resp.ok) {
                showToast(editingSetId ? "Order set updated" : "Order set created", "success");
                closeForm();
                loadSets();
            } else {
                var text = await resp.text();
                try {
                    var data = JSON.parse(text);
                    showToast("Error " + resp.status + ": " + (data.error || text.substring(0, 200)), "error");
                } catch (_) {
                    showToast("Error " + resp.status + ": " + text.substring(0, 200), "error");
                }
            }
        } catch (e) {
            showToast("Network error: " + e.message, "error");
        } finally {
            saveBtn.disabled = false;
        }
    }

    // ── Delete ───────────────────────────────────────────────────────

    function openDeleteDialog(setId) {
        var s = allSets.find(function (x) { return x.id === setId; });
        if (!s) return;
        deleteSetId = setId;
        document.getElementById("delete-name").textContent = s.name;
        show(deleteOverlay);
    }

    function closeDeleteDialog() {
        hide(deleteOverlay);
        deleteSetId = null;
    }

    async function confirmDelete() {
        if (!deleteSetId) return;
        try {
            var resp = await fetch(API + "/sets/" + deleteSetId, {
                method: "DELETE",
                credentials: "same-origin",
            });
            if (resp.ok) {
                showToast("Order set deleted", "success");
                closeDeleteDialog();
                loadSets();
            } else {
                showToast("Failed to delete", "error");
            }
        } catch (e) {
            showToast("Failed to delete order set", "error");
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────

    function show(el) { el.classList.remove("hidden"); }
    function hide(el) { el.classList.add("hidden"); }

    function escapeHtml(str) {
        var div = document.createElement("div");
        div.textContent = str || "";
        return div.innerHTML;
    }

    function showToast(msg, type) {
        toast.textContent = msg;
        toast.className = "toast toast-" + (type || "info");
        setTimeout(function () { toast.classList.add("hidden"); }, 3000);
    }

    // ── Start ────────────────────────────────────────────────────────
    init();
})();
