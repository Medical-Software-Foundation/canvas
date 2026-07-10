// Daily Readiness Dashboard — client.
// Loads today's board (appointments, readiness cells, action panels) and wires
// the scope/provider/location filters and the in-dashboard action popovers.

(function () {
  "use strict";

  var BASE = (document.body && document.body.dataset.base) || "";
  var READINESS_KEYS = ["labs", "imaging", "referral", "auth"];
  var STATE_SYMBOL = { complete: "✓", incomplete: "✗", "not-needed": "—" };
  var CATEGORY_LABEL = {
    labs: "Labs",
    imaging: "Imaging",
    referral: "Referral",
    auth: "Authorization",
  };

  // Default landing view is "My day" (the signed-in user's schedule + tasks).
  var state = { scope: "mine", day: "today", provider: "", location: "" };
  var chartBase = "";
  var messagingApp = "";
  var staffOptions = [];
  var teamOptions = [];
  var taskPriorities = [];
  var panelLinks = {};
  var assistantPanelApp = "";
  // The signed-in user, used to default the provider filter to them.
  var currentStaffId = "";
  var currentStaffIsProvider = false;
  var didDefaultProvider = false;

  // Stage the prep prompt on the patient, then open the Assistant panel in the
  // chart (new tab) — ChatApp.on_open reads + sends the staged prompt once.
  function openAppointmentPrep(patientId) {
    if (!patientId || !chartBase || !assistantPanelApp) {
      return;
    }
    postJSON("/prep", { patient_id: patientId })
      .then(function () {
        window.open(
          chartBase + "/patient/" + patientId + "#application=" + btoa(assistantPanelApp),
          "_blank",
          "noopener"
        );
      })
      .catch(function (err) {
        console.error("Appointment Prep failed:", err);
      });
  }

  function openWorklist(url) {
    if (!url) {
      return;
    }
    var full = /^https?:\/\//.test(url) ? url : (chartBase || "") + url;
    window.open(full, "_blank", "noopener");
  }

  function wirePanelHeaders() {
    [
      ["drb-tasks-title", panelLinks.tasks],
      ["drb-refills-title", panelLinks.refills],
      ["drb-messages-title", panelLinks.messages],
    ].forEach(function (pair) {
      var el = document.getElementById(pair[0]);
      if (!el) {
        return;
      }
      if (pair[1]) {
        el.classList.add("drb-link");
        el.title = "Open in Canvas";
        el.onclick = function () {
          openWorklist(pair[1]);
        };
      } else {
        el.classList.remove("drb-link");
        el.onclick = null;
      }
    });
  }

  function openChart(patientId) {
    if (!patientId || !chartBase) {
      return;
    }
    window.open(chartBase + "/patient/" + patientId + "/", "_blank", "noopener");
  }

  function positionPopover(pop, anchor) {
    var r = anchor.getBoundingClientRect();
    var width = pop.offsetWidth || 240;
    pop.style.top = window.scrollY + r.bottom + 6 + "px";
    pop.style.left =
      window.scrollX + Math.min(r.left, window.innerWidth - width - 12) + "px";
  }

  function td(text, className) {
    var cell = document.createElement("td");
    if (className) {
      cell.className = className;
    }
    cell.textContent = text;
    return cell;
  }

  function stateCell(value, category, row, overridden) {
    var s = value || "not-needed";
    var cell = document.createElement("td");
    cell.className = "drb-col-state drb-clickable";
    cell.title = "Click for details";
    var span = document.createElement("span");
    span.className = "drb-state " + s;
    span.textContent = STATE_SYMBOL[s] || "—";
    cell.appendChild(span);
    cell.addEventListener("click", function (e) {
      e.stopPropagation();
      openDetail(cell, row, category, overridden);
    });
    return cell;
  }

  function detailHeaderText(category, state, overridden) {
    if (category === "auth") {
      return "Authorization · " + (overridden ? "Obtained (manual)" : "Not recorded");
    }
    var label =
      state === "complete"
        ? "Result received"
        : state === "incomplete"
        ? "Ordered — awaiting result"
        : "None on file";
    if (overridden) {
      label = "Manually marked complete";
    }
    return CATEGORY_LABEL[category] + " · " + label;
  }

  function closeDetail() {
    var p = document.getElementById("drb-detail-popover");
    if (p) {
      p.remove();
    }
    document.removeEventListener("mousedown", outsideCloseDetail);
  }

  function outsideCloseDetail(e) {
    var p = document.getElementById("drb-detail-popover");
    if (p && !p.contains(e.target)) {
      closeDetail();
    }
  }

  function openDetail(anchor, row, category, overridden) {
    closeDetail();
    var state = (row.readiness || {})[category] || "not-needed";
    var items = (row.details || {})[category] || [];

    var pop = document.createElement("div");
    pop.className = "drb-popover";
    pop.id = "drb-detail-popover";

    var head = document.createElement("div");
    head.className = "drb-pop-head";
    head.textContent = detailHeaderText(category, state, overridden);
    pop.appendChild(head);

    if (category === "auth") {
      var note = document.createElement("div");
      note.className = "drb-pop-empty";
      note.textContent = "Authorization is tracked manually in this dashboard.";
      pop.appendChild(note);
    } else if (items.length === 0) {
      var empty = document.createElement("div");
      empty.className = "drb-pop-empty";
      empty.textContent = "Nothing on file for this patient.";
      pop.appendChild(empty);
    } else {
      items.forEach(function (it) {
        var line = document.createElement("div");
        line.className = "drb-pop-item";
        var mark = it.kind === "report" ? "✓" : "•";
        var verb = it.kind === "report" ? "received" : "ordered";
        var when = it.date ? " — " + verb + " " + it.date : " — " + verb;
        line.textContent = mark + " " + it.label + when;
        pop.appendChild(line);
      });
    }

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "drb-pop-btn";
    btn.textContent = overridden
      ? "Clear manual override"
      : category === "auth"
      ? "Mark authorization obtained"
      : "Mark complete";
    btn.addEventListener("click", function () {
      toggleOverride(row.patient_id, category, overridden);
      closeDetail();
    });
    pop.appendChild(btn);

    document.body.appendChild(pop);
    positionPopover(pop, anchor);
    setTimeout(function () {
      document.addEventListener("mousedown", outsideCloseDetail);
    }, 0);
  }

  function outreachCell(row) {
    var cell = document.createElement("td");
    cell.className = "drb-outreach drb-clickable";
    var hasLog = !!row.outreach && (row.outreach_detail || []).length > 0;
    cell.title = hasLog ? "View outreach log" : "Log outreach attempt";
    var span = document.createElement("span");
    if (row.outreach) {
      span.textContent = row.outreach;
    } else {
      span.textContent = "Log…";
      span.className = "drb-faint";
    }
    cell.appendChild(span);
    if (row.outreach_count > 1) {
      var badge = document.createElement("span");
      badge.className = "drb-mini-badge";
      badge.textContent = String(row.outreach_count);
      cell.appendChild(badge);
    }
    cell.addEventListener("click", function (e) {
      e.stopPropagation();
      // An existing log opens a detail popover (with its note); otherwise log one.
      if (hasLog) {
        openOutreachDetail(cell, row);
      } else {
        openOutreach(row.patient_id, row.patient_name);
      }
    });
    return cell;
  }

  function openOutreachDetail(anchor, row) {
    closeDetail();
    var pop = document.createElement("div");
    pop.className = "drb-popover";
    pop.id = "drb-detail-popover";

    var head = document.createElement("div");
    head.className = "drb-pop-head";
    head.textContent = "Outreach — " + row.patient_name;
    pop.appendChild(head);

    var attempts = row.outreach_detail || [];
    attempts.forEach(function (a) {
      var item = document.createElement("div");
      item.className = "drb-pop-item";

      var bits = [];
      var who = [a.recipient_type, a.channel].filter(Boolean).join(" ");
      if (who) bits.push(who);
      if (a.outcome) bits.push(a.outcome);
      if (a.when) bits.push(a.when);
      var line1 = document.createElement("div");
      line1.textContent = bits.join(" · ");
      item.appendChild(line1);

      if (a.recipient) {
        var rec = document.createElement("div");
        rec.className = "drb-faint";
        rec.textContent = "To: " + a.recipient;
        item.appendChild(rec);
      }
      // The optional free-text message that accompanied the log.
      if (a.note) {
        var note = document.createElement("div");
        note.className = "drb-pop-note";
        note.textContent = "“" + a.note + "”";
        item.appendChild(note);
      }
      if (a.user) {
        var by = document.createElement("div");
        by.className = "drb-faint";
        by.textContent = "— " + a.user;
        item.appendChild(by);
      }
      pop.appendChild(item);
    });

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "drb-pop-btn";
    btn.textContent = "Log outreach…";
    btn.addEventListener("click", function () {
      closeDetail();
      openOutreach(row.patient_id, row.patient_name);
    });
    pop.appendChild(btn);

    document.body.appendChild(pop);
    positionPopover(pop, anchor);
    setTimeout(function () {
      document.addEventListener("mousedown", outsideCloseDetail);
    }, 0);
  }

  function actionsCell(row) {
    var cell = document.createElement("td");
    cell.className = "drb-col-actions";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "drb-actions-btn";
    btn.textContent = "⋯";
    btn.title = "Actions";
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      openActionsMenu(btn, row);
    });
    cell.appendChild(btn);
    return cell;
  }

  function openActionsMenu(anchor, row) {
    closeDetail();
    var pop = document.createElement("div");
    pop.className = "drb-popover drb-menu";
    pop.id = "drb-detail-popover";

    // Chart-dependent actions are only offered when a chart base is configured
    // (CUSTOMER_IDENTIFIER); otherwise the links wouldn't resolve.
    var actions = [];
    if (chartBase && assistantPanelApp) {
      actions.push(["Appointment Prep", function () { openAppointmentPrep(row.patient_id); }]);
    }
    if (chartBase) {
      actions.push(["Open chart", function () { openChart(row.patient_id); }]);
    }
    actions.push(["Log outreach…", function () { openOutreach(row.patient_id, row.patient_name); }]);
    actions.push(["Create task…", function () { openTaskModal(row); }]);
    actions.forEach(function (pair) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "drb-menu-item";
      item.textContent = pair[0];
      item.addEventListener("click", function () {
        closeDetail();
        pair[1]();
      });
      pop.appendChild(item);
    });

    document.body.appendChild(pop);
    positionPopover(pop, anchor);
    setTimeout(function () {
      document.addEventListener("mousedown", outsideCloseDetail);
    }, 0);
  }

  function patientCell(row) {
    var cell = document.createElement("td");
    var name = document.createElement("div");
    name.className = "drb-link";
    name.textContent = row.patient_name;
    name.title = "Open chart";
    name.addEventListener("click", function () {
      openChart(row.patient_id);
    });
    cell.appendChild(name);

    var meta = document.createElement("div");
    meta.className = "drb-row-meta";
    var bits = [];
    if (row.provider) {
      bits.push(row.provider);
    }
    if (row.location) {
      bits.push(row.location);
    }
    meta.textContent = bits.join(" · ");
    cell.appendChild(meta);
    return cell;
  }

  function renderRows(rows) {
    var tbody = document.getElementById("drb-rows");
    tbody.textContent = "";

    if (!rows || rows.length === 0) {
      var emptyRow = document.createElement("tr");
      emptyRow.className = "drb-empty-row";
      var cell = document.createElement("td");
      cell.colSpan = 8;
      var msg = document.createElement("div");
      msg.className = "drb-empty";
      msg.textContent = "No patients match the current filters.";
      cell.appendChild(msg);
      emptyRow.appendChild(cell);
      tbody.appendChild(emptyRow);
      return;
    }

    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.appendChild(td(row.time_display, "drb-col-time"));
      tr.appendChild(patientCell(row));
      var cells = row.readiness || {};
      var overrides = row.overrides || [];
      READINESS_KEYS.forEach(function (key) {
        var overridden = overrides.indexOf(key) !== -1;
        tr.appendChild(stateCell(cells[key], key, row, overridden));
      });
      tr.appendChild(outreachCell(row));
      tr.appendChild(actionsCell(row));
      tbody.appendChild(tr);
    });
  }

  function fillOptions(select, options, selectedValue, labelPrefix) {
    var current = selectedValue || "";
    select.textContent = "";

    var first = document.createElement("option");
    first.value = "";
    first.textContent = labelPrefix + ": All";
    select.appendChild(first);

    options.forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.id;
      o.textContent = opt.name;
      if (opt.id === current) {
        o.selected = true;
      }
      select.appendChild(o);
    });
  }

  function setText(id, text) {
    var node = document.getElementById(id);
    if (node) {
      node.textContent = text;
    }
  }

  function renderPanel(countId, bodyId, panel, lineFn, kind) {
    panel = panel || { count: 0, items: [] };
    setText(countId, String(panel.count || 0));

    var body = document.getElementById(bodyId);
    if (!body) {
      return;
    }
    body.textContent = "";

    if (!panel.items || panel.items.length === 0) {
      var empty = document.createElement("div");
      empty.className = "drb-placeholder";
      empty.textContent = "Nothing for today's patients";
      body.appendChild(empty);
      return;
    }

    panel.items.forEach(function (item) {
      var line = lineFn(item);
      var row = document.createElement("div");
      row.className = "drb-panel-item";

      var content = document.createElement("div");
      content.className = "drb-item-content drb-clickable";
      content.title = kind === "Task" ? "Edit task" : "Details";
      content.addEventListener("click", function (e) {
        e.stopPropagation();
        if (kind === "Task") {
          openTaskEditModal(item);
        } else {
          openPanelDetail(content, item, line, kind);
        }
      });

      var primary = document.createElement("div");
      primary.className = "drb-item-primary";
      primary.textContent = line.primary;
      content.appendChild(primary);

      if (line.secondary) {
        var secondary = document.createElement("div");
        secondary.className = "drb-item-secondary";
        secondary.textContent = line.secondary;
        content.appendChild(secondary);
      }
      row.appendChild(content);

      // One-click "Done" on tasks (Carallel-style), without opening the editor.
      if (kind === "Task") {
        row.classList.add("drb-task-row");
        var done = document.createElement("button");
        done.type = "button";
        done.className = "drb-done-btn";
        done.textContent = "Done";
        done.title = "Mark task done";
        done.addEventListener("click", function (e) {
          e.stopPropagation();
          completeTask(item.id, done);
        });
        row.appendChild(done);
      }

      body.appendChild(row);
    });
  }

  function completeTask(taskId, btn) {
    if (!taskId) {
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = "…";
    }
    postJSON("/task-action", { task_id: taskId, status: "COMPLETED" })
      .then(load)
      .catch(function (err) {
        console.error("Complete task failed:", err);
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Done";
        }
      });
  }

  function renderPanels(panels) {
    panels = panels || {};
    renderPanel("drb-tasks-count", "drb-tasks-body", panels.tasks, function (i) {
      return { primary: i.title, secondary: [i.patient_name, i.meta].filter(Boolean).join(" · ") };
    }, "Task");
    renderPanel("drb-refills-count", "drb-refills-body", panels.refills, function (i) {
      return { primary: i.medication, secondary: [i.patient_name, i.meta].filter(Boolean).join(" · ") };
    }, "Refill");
    renderPanel("drb-messages-count", "drb-messages-body", panels.messages, function (i) {
      return { primary: i.patient_name, secondary: [i.snippet, i.meta].filter(Boolean).join(" — ") };
    }, "Message");
  }

  function telButton(phone, cls) {
    var a = document.createElement("a");
    a.className = cls;
    a.href = "tel:" + phone.replace(/[^0-9+]/g, "");
    a.textContent = "Call " + phone;
    return a;
  }

  function openPanelDetail(anchor, item, line, kind) {
    closeDetail();
    var pop = document.createElement("div");
    pop.className = "drb-popover";
    pop.id = "drb-detail-popover";

    var head = document.createElement("div");
    head.className = "drb-pop-head";
    head.textContent = kind;
    pop.appendChild(head);

    var primary = document.createElement("div");
    primary.className = "drb-pop-item";
    primary.style.fontWeight = "600";
    primary.textContent = line.primary;
    pop.appendChild(primary);

    if (line.secondary) {
      var sub = document.createElement("div");
      sub.className = "drb-pop-empty";
      sub.style.fontStyle = "normal";
      sub.textContent = line.secondary;
      pop.appendChild(sub);
    }

    if (item.patient_id && kind === "Message" && messagingApp && chartBase) {
      // The dashboard iframe can't navigate the top window (sandboxed), so open
      // the chart with the messaging app's #application=<base64> hash in a new
      // tab. Whether the SPA activates the app on cold load is instance-dependent.
      var msgBtn = document.createElement("button");
      msgBtn.type = "button";
      msgBtn.className = "drb-pop-btn drb-call-btn";
      msgBtn.textContent = "Open messages";
      msgBtn.addEventListener("click", function () {
        window.open(
          chartBase + "/patient/" + item.patient_id + "#application=" + btoa(messagingApp),
          "_blank",
          "noopener"
        );
        closeDetail();
      });
      pop.appendChild(msgBtn);
    }
    if (item.patient_id && chartBase) {
      var chartBtn = document.createElement("button");
      chartBtn.type = "button";
      chartBtn.className = "drb-pop-btn";
      chartBtn.textContent = "Open chart";
      chartBtn.addEventListener("click", function () {
        openChart(item.patient_id);
        closeDetail();
      });
      pop.appendChild(chartBtn);
    }
    // Click-to-dial only for call-type tasks (title mentions "call").
    var isCallTask = kind === "Task" && item.title && /\bcall\b/i.test(item.title);
    if (item.phone && isCallTask) {
      pop.appendChild(telButton(item.phone, "drb-pop-btn drb-call-btn"));
    }

    document.body.appendChild(pop);
    positionPopover(pop, anchor);
    setTimeout(function () {
      document.addEventListener("mousedown", outsideCloseDetail);
    }, 0);
  }

  // ── writes ───────────────────────────────────────────────────────────
  function postJSON(path, body) {
    return fetch(BASE + path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (resp) {
      return resp.text().then(function (text) {
        var data = {};
        if (text) {
          try {
            data = JSON.parse(text);
          } catch (e) {
            data = {};
          }
        }
        if (!resp.ok) {
          throw new Error((data && data.error) || "Request failed: " + resp.status);
        }
        return data;
      });
    });
  }

  function toggleOverride(patientId, category, currentlyOverridden) {
    postJSON("/readiness", {
      patient_id: patientId,
      category: category,
      complete: !currentlyOverridden,
    })
      .then(load)
      .catch(function (err) {
        console.error("Mark-complete failed:", err);
      });
  }

  // ── outreach modal ───────────────────────────────────────────────────
  var outreachPatientId = null;

  function fieldValue(id) {
    var node = document.getElementById(id);
    return node ? node.value : "";
  }

  function openOutreach(patientId, patientName) {
    outreachPatientId = patientId;
    setText("drb-modal-patient", patientName || "");
    // Reset to defaults so a prior entry never carries over.
    document.getElementById("drb-o-channel").value = "Call";
    document.getElementById("drb-o-recipient-type").value = "PCP";
    document.getElementById("drb-o-recipient").value = "";
    document.getElementById("drb-o-outcome").value = "Sent";
    document.getElementById("drb-o-note").value = "";
    var err = document.getElementById("drb-o-error");
    if (err) {
      err.hidden = true;
    }
    document.getElementById("drb-outreach-modal").hidden = false;
  }

  function closeOutreach() {
    document.getElementById("drb-outreach-modal").hidden = true;
    outreachPatientId = null;
  }

  function saveOutreach() {
    if (!outreachPatientId) {
      return;
    }
    postJSON("/outreach", {
      patient_id: outreachPatientId,
      channel: fieldValue("drb-o-channel"),
      recipient_type: fieldValue("drb-o-recipient-type"),
      recipient: fieldValue("drb-o-recipient"),
      outcome: fieldValue("drb-o-outcome"),
      note: fieldValue("drb-o-note"),
    })
      .then(function () {
        closeOutreach();
        load();
      })
      .catch(function (err) {
        var el = document.getElementById("drb-o-error");
        if (el) {
          el.textContent = "" + err;
          el.hidden = false;
        }
      });
  }

  // ── create-task modal ────────────────────────────────────────────────
  var taskPatientId = null;

  function openTaskModal(row) {
    taskPatientId = row.patient_id;
    setText("drb-task-patient", row.patient_name || "");
    document.getElementById("drb-t-title").value = "";
    document.getElementById("drb-t-due").value = "";
    fillEditSelect("drb-t-assignee", staffOptions, "", "Unassigned");
    fillEditSelect("drb-t-team", teamOptions, "", "No team");
    fillEditSelect(
      "drb-t-priority",
      taskPriorities.map(function (p) {
        return { id: p, name: p.charAt(0).toUpperCase() + p.slice(1) };
      }),
      "",
      "No priority"
    );
    var err = document.getElementById("drb-t-error");
    if (err) {
      err.hidden = true;
    }
    document.getElementById("drb-task-modal").hidden = false;
  }

  function closeTask() {
    document.getElementById("drb-task-modal").hidden = true;
    taskPatientId = null;
  }

  function saveTask() {
    if (!taskPatientId) {
      return;
    }
    var title = fieldValue("drb-t-title").trim();
    var err = document.getElementById("drb-t-error");
    if (!title) {
      if (err) {
        err.textContent = "Enter a task title.";
        err.hidden = false;
      }
      return;
    }
    postJSON("/task", {
      patient_id: taskPatientId,
      title: title,
      assignee_id: fieldValue("drb-t-assignee"),
      team_id: fieldValue("drb-t-team"),
      due: fieldValue("drb-t-due"),
      priority: fieldValue("drb-t-priority"),
    })
      .then(function () {
        closeTask();
        load();
      })
      .catch(function (e) {
        if (err) {
          err.textContent = "" + e;
          err.hidden = false;
        }
      });
  }

  // ── edit-task modal ──────────────────────────────────────────────────
  var editTaskId = null;

  function fillEditSelect(id, options, selectedValue, defaultLabel) {
    var sel = document.getElementById(id);
    if (!sel) {
      return;
    }
    sel.textContent = "";
    var first = document.createElement("option");
    first.value = "";
    first.textContent = defaultLabel;
    sel.appendChild(first);
    options.forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.id !== undefined ? opt.id : opt;
      o.textContent = opt.name !== undefined ? opt.name : String(opt);
      if (o.value === (selectedValue || "")) {
        o.selected = true;
      }
      sel.appendChild(o);
    });
  }

  function openTaskEditModal(item) {
    editTaskId = item.id;
    setText("drb-edit-patient", item.patient_name || "");
    document.getElementById("drb-e-title").value = item.title || "";
    document.getElementById("drb-e-status").value = item.status || "OPEN";
    fillEditSelect("drb-e-assignee", staffOptions, item.assignee_id, "Unassigned");
    fillEditSelect("drb-e-team", teamOptions, item.team_id, "No team");
    document.getElementById("drb-e-due").value = item.due_iso || "";
    var prioOpts = taskPriorities.map(function (p) {
      return { id: p, name: p.charAt(0).toUpperCase() + p.slice(1) };
    });
    fillEditSelect("drb-e-priority", prioOpts, item.priority, "No priority");
    document.getElementById("drb-e-comment").value = "";

    var chartLink = document.getElementById("drb-e-chart");
    if (chartLink && item.patient_id && chartBase) {
      chartLink.href = chartBase + "/patient/" + item.patient_id + "/";
      chartLink.style.display = "";
    } else if (chartLink) {
      chartLink.style.display = "none";
    }

    var err = document.getElementById("drb-e-error");
    if (err) {
      err.hidden = true;
    }
    document.getElementById("drb-edit-modal").hidden = false;
  }

  function closeEdit() {
    document.getElementById("drb-edit-modal").hidden = true;
    editTaskId = null;
  }

  function saveTaskEdit() {
    if (!editTaskId) {
      return;
    }
    postJSON("/task-action", {
      task_id: editTaskId,
      title: fieldValue("drb-e-title"),
      status: fieldValue("drb-e-status"),
      assignee_id: fieldValue("drb-e-assignee"),
      team_id: fieldValue("drb-e-team"),
      due: fieldValue("drb-e-due"),
      priority: fieldValue("drb-e-priority"),
      comment: fieldValue("drb-e-comment"),
    })
      .then(function () {
        closeEdit();
        load();
      })
      .catch(function (e) {
        var err = document.getElementById("drb-e-error");
        if (err) {
          err.textContent = "" + e;
          err.hidden = false;
        }
      });
  }

  function load() {
    var tz = "";
    try {
      tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (e) {
      tz = "";
    }
    var url =
      BASE +
      "/data?scope=" +
      encodeURIComponent(state.scope) +
      "&day=" +
      encodeURIComponent(state.day) +
      "&tz=" +
      encodeURIComponent(tz) +
      "&provider=" +
      encodeURIComponent(state.provider) +
      "&location=" +
      encodeURIComponent(state.location);

    fetch(url, { credentials: "same-origin" })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("Request failed: " + resp.status);
        }
        return resp.json();
      })
      .then(function (board) {
        chartBase = board.chart_base || "";
        // Chart deep-links need CUSTOMER_IDENTIFIER; hint when it's unconfigured.
        var chartHint = document.getElementById("drb-chart-hint");
        if (chartHint) {
          chartHint.hidden = !!chartBase;
        }
        messagingApp = board.messaging_app || "";
        staffOptions = board.staff_options || [];
        teamOptions = board.team_options || [];
        taskPriorities = board.priorities || [];
        panelLinks = board.panel_links || {};
        assistantPanelApp = board.assistant_panel_app || "";
        // Default the provider filter to the signed-in user on first load,
        // when they're actually one of the providers.
        currentStaffId = board.current_staff_id || "";
        var provs = board.providers || [];
        currentStaffIsProvider = provs.some(function (p) {
          return String(p.id) === String(currentStaffId);
        });
        if (!didDefaultProvider) {
          didDefaultProvider = true;
          if (state.scope === "mine" && currentStaffIsProvider) {
            state.provider = currentStaffId;
          }
        }
        wirePanelHeaders();
        setText("drb-date", board.date_display || "");
        fillOptions(
          document.getElementById("drb-provider"),
          provs,
          state.provider,
          "Provider"
        );
        fillOptions(
          document.getElementById("drb-location"),
          board.locations || [],
          state.location,
          "Location"
        );
        renderRows(board.rows || []);
        renderPanels(board.panels);
      })
      .catch(function (err) {
        setText("drb-date", "Unable to load schedule");
        var tbody = document.getElementById("drb-rows");
        if (tbody) {
          tbody.textContent = "";
          var tr = document.createElement("tr");
          var cell = document.createElement("td");
          cell.colSpan = 8;
          var msg = document.createElement("div");
          msg.className = "drb-empty";
          msg.textContent = "" + err;
          cell.appendChild(msg);
          tr.appendChild(cell);
          tbody.appendChild(tr);
        }
      });
  }

  function wireControls() {
    var scopeButtons = document.querySelectorAll(".drb-scope .button");
    scopeButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        scopeButtons.forEach(function (b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");
        state.scope = btn.getAttribute("data-scope") || "all";
        state.day = btn.getAttribute("data-day") || "today";
        // "My day" follows the signed-in user; "All"/"Tomorrow" show everyone.
        state.provider =
          state.scope === "mine" && currentStaffIsProvider ? currentStaffId : "";
        load();
      });
    });

    var providerSel = document.getElementById("drb-provider");
    if (providerSel) {
      providerSel.addEventListener("change", function () {
        state.provider = providerSel.value;
        // Explicitly choosing "Provider: All" means everyone — drop mine scope.
        if (!state.provider) {
          state.scope = "all";
        }
        load();
      });
    }

    var locationSel = document.getElementById("drb-location");
    if (locationSel) {
      locationSel.addEventListener("change", function () {
        state.location = locationSel.value;
        load();
      });
    }

    var refresh = document.getElementById("drb-refresh");
    if (refresh) {
      refresh.addEventListener("click", load);
    }
  }

  function wireModal() {
    var cancel = document.getElementById("drb-o-cancel");
    var save = document.getElementById("drb-o-save");
    var overlay = document.getElementById("drb-outreach-modal");
    if (cancel) {
      cancel.addEventListener("click", closeOutreach);
    }
    if (save) {
      save.addEventListener("click", saveOutreach);
    }
    if (overlay) {
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) {
          closeOutreach();
        }
      });
    }

    var tCancel = document.getElementById("drb-t-cancel");
    var tSave = document.getElementById("drb-t-save");
    var tOverlay = document.getElementById("drb-task-modal");
    if (tCancel) {
      tCancel.addEventListener("click", closeTask);
    }
    if (tSave) {
      tSave.addEventListener("click", saveTask);
    }
    if (tOverlay) {
      tOverlay.addEventListener("click", function (e) {
        if (e.target === tOverlay) {
          closeTask();
        }
      });
    }

    var eCancel = document.getElementById("drb-e-cancel");
    var eSave = document.getElementById("drb-e-save");
    var eOverlay = document.getElementById("drb-edit-modal");
    if (eCancel) {
      eCancel.addEventListener("click", closeEdit);
    }
    if (eSave) {
      eSave.addEventListener("click", saveTaskEdit);
    }
    if (eOverlay) {
      eOverlay.addEventListener("click", function (e) {
        if (e.target === eOverlay) {
          closeEdit();
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireControls();
    wireModal();
    load();
  });
})();
