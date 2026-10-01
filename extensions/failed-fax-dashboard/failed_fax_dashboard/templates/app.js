(function () {
  "use strict";

  var BASE = document.body.getAttribute("data-base");
  var PAGE_SIZE = 25;
  var currentPage = 1;
  var taskOptionsCache = null;

  var statusEl = document.getElementById("status");
  var tableEl = document.getElementById("fax-table");
  var rowsEl = document.getElementById("fax-rows");
  var pagerEl = document.getElementById("pager");
  var pageLabelEl = document.getElementById("page-label");
  var prevBtn = document.getElementById("prev-page");
  var nextBtn = document.getElementById("next-page");
  var overlayEl = document.getElementById("overlay");
  var dialogTitleEl = document.getElementById("dialog-title");
  var dialogBodyEl = document.getElementById("dialog-body");
  var dialogErrorEl = document.getElementById("dialog-error");
  var dialogSubmitEl = document.getElementById("dialog-submit");
  var dialogCancelEl = document.getElementById("dialog-cancel");
  var onSubmit = null;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") {
        node.textContent = attrs[key];
      } else if (key === "class") {
        node.className = attrs[key];
      } else {
        node.setAttribute(key, attrs[key]);
      }
    });
    (children || []).forEach(function (child) {
      node.appendChild(child);
    });
    return node;
  }

  function setStatus(message, isError) {
    statusEl.textContent = message;
    statusEl.className = isError ? "status error" : "status";
  }

  function request(method, path, body) {
    var options = { method: method, credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(BASE + path, options).then(function (response) {
      return response.text().then(function (text) {
        var data = {};
        if (text) {
          try {
            data = JSON.parse(text);
          } catch (e) {
            data = {};
          }
        }
        if (!response.ok) {
          throw new Error(data.error || "Request failed (" + response.status + ")");
        }
        return data;
      });
    });
  }

  function formatTime(iso) {
    var date = new Date(iso);
    return isNaN(date.getTime()) ? "" : date.toLocaleString();
  }

  function textCell(value) {
    return el("td", value ? { text: value } : { text: "-", class: "muted" });
  }

  function renderRow(row) {
    var tr = el("tr");
    var typeCell = el("td");
    typeCell.appendChild(el("span", { class: "tag " + row.direction, text: row.type_label }));
    tr.appendChild(typeCell);
    tr.appendChild(textCell(row.patient_name));
    tr.appendChild(textCell(row.fax_number));
    tr.appendChild(textCell(row.sender));
    tr.appendChild(textCell(formatTime(row.occurred_at)));
    tr.appendChild(textCell(row.pages === null ? "" : String(row.pages)));
    tr.appendChild(textCell(row.reason));

    var actions = el("div", { class: "actions" });
    if (row.link_url) {
      actions.appendChild(
        el("a", {
          class: "link",
          href: row.link_url,
          target: "_blank",
          rel: "noopener",
          text: row.link_label
        })
      );
    }
    if (row.can_resend) {
      var resendBtn = el("button", { type: "button", text: "Resend" });
      resendBtn.addEventListener("click", function () { openResend(row); });
      actions.appendChild(resendBtn);
    }
    var taskBtn = el("button", { type: "button", text: "Create task" });
    taskBtn.addEventListener("click", function () { openTask(row); });
    actions.appendChild(taskBtn);
    var dismissBtn = el("button", { type: "button", text: "Dismiss" });
    dismissBtn.addEventListener("click", function () { openDismiss(row); });
    actions.appendChild(dismissBtn);

    var actionsCell = el("td");
    actionsCell.appendChild(actions);
    tr.appendChild(actionsCell);
    return tr;
  }

  function load(page) {
    setStatus("Loading...", false);
    request("GET", "/failures?page=" + page + "&page_size=" + PAGE_SIZE)
      .then(function (data) {
        // After the last row of a page is cleared, step back to the last page that still exists.
        if (data.rows.length === 0 && data.page > 1) {
          currentPage = data.total_pages;
          load(currentPage);
          return;
        }
        currentPage = data.page;
        document.getElementById("window-days").textContent = String(data.window_days);
        rowsEl.textContent = "";
        data.rows.forEach(function (row) { rowsEl.appendChild(renderRow(row)); });
        tableEl.hidden = data.rows.length === 0;
        pagerEl.hidden = data.total_pages <= 1;
        pageLabelEl.textContent = "Page " + data.page + " of " + data.total_pages + " (" + data.total + " total)";
        prevBtn.disabled = data.page <= 1;
        nextBtn.disabled = data.page >= data.total_pages;
        setStatus(data.total === 0 ? "No failed faxes in this period." : data.total + " failed fax(es).", false);
      })
      .catch(function (error) {
        setStatus(error.message, true);
      });
  }

  function field(id, labelText, input, hint) {
    var wrapper = el("div", { class: "field" });
    wrapper.appendChild(el("label", { for: id, text: labelText }));
    wrapper.appendChild(input);
    if (hint) {
      wrapper.appendChild(el("p", { class: "hint", text: hint }));
    }
    return wrapper;
  }

  function openDialog(title, bodyNodes, submitLabel, submitHandler) {
    dialogTitleEl.textContent = title;
    dialogBodyEl.textContent = "";
    bodyNodes.forEach(function (node) { dialogBodyEl.appendChild(node); });
    dialogErrorEl.textContent = "";
    dialogSubmitEl.textContent = submitLabel;
    dialogSubmitEl.disabled = false;
    onSubmit = submitHandler;
    overlayEl.hidden = false;
  }

  function closeDialog() {
    overlayEl.hidden = true;
    onSubmit = null;
  }

  dialogCancelEl.addEventListener("click", closeDialog);
  dialogSubmitEl.addEventListener("click", function () {
    if (!onSubmit) { return; }
    dialogErrorEl.textContent = "";
    dialogSubmitEl.disabled = true;
    onSubmit()
      .then(function () {
        closeDialog();
        load(currentPage);
      })
      .catch(function (error) {
        dialogErrorEl.textContent = error.message;
        dialogSubmitEl.disabled = false;
      });
  });

  function openResend(row) {
    var numberInput = el("input", { id: "resend-number", type: "text", value: row.fax_number });
    var nameInput = el("input", { id: "resend-name", type: "text", placeholder: "Recipient name" });
    openDialog(
      "Resend note fax",
      [
        field("resend-number", "Fax number", numberInput),
        field("resend-name", "Recipient name", nameInput, "Required. Filled in when the contact directory has exactly one match for this number.")
      ],
      "Resend",
      function () {
        return request("POST", "/resend", {
          event_id: row.source_id,
          recipient_name: nameInput.value,
          recipient_fax_number: numberInput.value
        });
      }
    );
    request("GET", "/resend-prefill?event_id=" + encodeURIComponent(row.source_id))
      .then(function (data) {
        if (data.recipient_name && !nameInput.value) { nameInput.value = data.recipient_name; }
        if (data.fax_number && !numberInput.value) { numberInput.value = data.fax_number; }
      })
      .catch(function (error) {
        dialogErrorEl.textContent = error.message;
      });
  }

  function getTaskOptions() {
    if (taskOptionsCache) { return Promise.resolve(taskOptionsCache); }
    return request("GET", "/task-options").then(function (data) {
      taskOptionsCache = data;
      return data;
    });
  }

  function openTask(row) {
    var assigneeSelect = el("select", { id: "task-assignee" });
    assigneeSelect.appendChild(el("option", { value: "", text: "Loading..." }));
    var titleInput = el("input", {
      id: "task-title",
      type: "text",
      value: "Failed fax: " + row.type_label + (row.fax_number ? " to " + row.fax_number : "")
    });
    var dueInput = el("input", { id: "task-due", type: "date" });
    var prioritySelect = el("select", { id: "task-priority" });
    [["", "None"], ["stat", "STAT"], ["urgent", "Urgent"], ["routine", "Routine"]].forEach(function (pair) {
      prioritySelect.appendChild(el("option", { value: pair[0], text: pair[1] }));
    });

    openDialog(
      "Create follow-up task",
      [
        field("task-assignee", "Assign to", assigneeSelect),
        field("task-title", "Title", titleInput),
        field("task-due", "Due date (optional)", dueInput),
        field("task-priority", "Priority (optional)", prioritySelect)
      ],
      "Create task",
      function () {
        var parts = assigneeSelect.value.split(":");
        return request("POST", "/task", {
          source_type: row.type,
          source_id: row.source_id,
          assignee_type: parts[0],
          assignee_id: parts.slice(1).join(":"),
          title: titleInput.value,
          due: dueInput.value,
          priority: prioritySelect.value
        });
      }
    );

    getTaskOptions()
      .then(function (options) {
        assigneeSelect.textContent = "";
        assigneeSelect.appendChild(el("option", { value: "", text: "Choose..." }));
        var staffGroup = el("optgroup", { label: "Staff" });
        options.staff.forEach(function (member) {
          staffGroup.appendChild(el("option", { value: "staff:" + member.id, text: member.name }));
        });
        var teamGroup = el("optgroup", { label: "Teams" });
        options.teams.forEach(function (team) {
          teamGroup.appendChild(el("option", { value: "team:" + team.id, text: team.name }));
        });
        assigneeSelect.appendChild(staffGroup);
        assigneeSelect.appendChild(teamGroup);
      })
      .catch(function (error) {
        dialogErrorEl.textContent = error.message;
      });
  }

  function openDismiss(row) {
    openDialog(
      "Dismiss this row?",
      [
        el("p", {
          text: "The row will no longer appear on the dashboard. The dismissal records who dismissed it and when."
        })
      ],
      "Dismiss",
      function () {
        return request("POST", "/dismiss", { source_type: row.type, source_id: row.source_id });
      }
    );
  }

  prevBtn.addEventListener("click", function () { load(currentPage - 1); });
  nextBtn.addEventListener("click", function () { load(currentPage + 1); });

  load(1);
})();
