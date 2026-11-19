document.addEventListener("DOMContentLoaded", function () {
    var roles = window.__ROLES__ || [];
    var container = document.getElementById("role-list");
    var saveBtn = document.getElementById("save-btn");
    var statusMsg = document.getElementById("status-msg");

    var initialState = {};
    roles.forEach(function (r) {
        initialState[r.internal_code] = r.allowed;
    });

    var currentState = JSON.parse(JSON.stringify(initialState));

    function hasChanges() {
        for (var code in currentState) {
            if (currentState[code] !== initialState[code]) return true;
        }
        return false;
    }

    function render() {
        container.innerHTML = "";

        var groups = {};
        var domainOrder = ["ADM", "CLI", "HYB"];
        var domainNames = {ADM: "Administrative", CLI: "Clinical", HYB: "Hybrid"};
        domainOrder.forEach(function (d) { groups[d] = []; });

        roles.forEach(function (r) {
            var d = r.domain || "CLI";
            if (!groups[d]) groups[d] = [];
            groups[d].push(r);
        });

        domainOrder.forEach(function (domain) {
            var list = groups[domain];
            if (!list || list.length === 0) return;

            var group = document.createElement("div");
            group.className = "domain-group";

            var header = document.createElement("div");
            header.className = "domain-header";

            var label = document.createElement("span");
            label.className = "domain-label";
            label.textContent = domainNames[domain] || domain;

            var badge = document.createElement("span");
            badge.className = "domain-badge badge-" + domain.toLowerCase();
            badge.textContent = domain;

            header.appendChild(label);
            header.appendChild(badge);
            group.appendChild(header);

            list.forEach(function (r) {
                var row = document.createElement("label");
                row.className = "role-row";

                var cb = document.createElement("input");
                cb.type = "checkbox";
                cb.checked = !!currentState[r.internal_code];

                var accessLabel = document.createElement("span");
                accessLabel.className = "access-label " + (cb.checked ? "granted" : "denied");
                accessLabel.textContent = cb.checked ? "Has access" : "No access";

                cb.addEventListener("change", function () {
                    currentState[r.internal_code] = cb.checked;
                    accessLabel.className = "access-label " + (cb.checked ? "granted" : "denied");
                    accessLabel.textContent = cb.checked ? "Has access" : "No access";
                    saveBtn.disabled = !hasChanges();
                    statusMsg.textContent = "";
                });

                var info = document.createElement("div");
                info.className = "role-info";

                var name = document.createElement("div");
                name.className = "role-name";
                name.textContent = r.name;

                var meta = document.createElement("div");
                meta.className = "role-meta";
                meta.textContent = r.role_type ? r.role_type + " \u00b7 " + r.internal_code : r.internal_code;

                info.appendChild(name);
                info.appendChild(meta);

                row.appendChild(cb);
                row.appendChild(info);
                row.appendChild(accessLabel);
                group.appendChild(row);
            });

            container.appendChild(group);
        });
    }

    saveBtn.addEventListener("click", function () {
        saveBtn.disabled = true;
        statusMsg.textContent = "Saving...";
        statusMsg.className = "status-msg";

        var allowed = [];
        for (var code in currentState) {
            if (currentState[code]) allowed.push(code);
        }

        fetch("/plugin-io/api/hide_settings/admin/config", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({allowed_role_codes: allowed}),
        })
        .then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok) throw new Error(data.error || "Save failed");
                return data;
            });
        })
        .then(function () {
            statusMsg.textContent = "Saved. Staff see the change after they refresh.";
            statusMsg.className = "status-msg";
            initialState = JSON.parse(JSON.stringify(currentState));
            saveBtn.disabled = true;
        })
        .catch(function (err) {
            statusMsg.textContent = "Error: " + err.message;
            statusMsg.className = "status-msg error";
            saveBtn.disabled = false;
        });
    });

    render();
});
