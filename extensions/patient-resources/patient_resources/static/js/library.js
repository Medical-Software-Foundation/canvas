/* The resource library, for staff.
 *
 * Conventions shared with the other two bundles in this plugin:
 *   - Every node is built with createElement and textContent. Never innerHTML:
 *     titles and labels are staff-entered free text.
 *   - An href is set only after re-checking the scheme in the browser.
 *   - Confirmations use <dialog>, never window.confirm -- this page is itself
 *     inside a host modal, where a native confirm is unreliable.
 *   - A monotonic request sequence guards against a slow response painting over
 *     a newer one.
 */

(function () {
  "use strict";

  var config = {};
  try {
    var configEl = document.getElementById("pr-config");
    config = JSON.parse(configEl ? configEl.textContent : "{}") || {};
  } catch (err) {
    config = {};
  }

  var apiBase = config.apiBase || "";

  var state = {
    canEdit: false,
    requestSeq: 0,
    editing: null
  };

  var els = {
    add: document.getElementById("pr-add"),
    readonly: document.getElementById("pr-readonly"),
    search: document.getElementById("pr-search"),
    labelFilter: document.getElementById("pr-label-filter"),
    archivedToggle: document.getElementById("pr-archived-toggle"),
    showArchived: document.getElementById("pr-show-archived"),
    rows: document.getElementById("pr-rows"),
    empty: document.getElementById("pr-empty"),
    status: document.getElementById("pr-status"),
    error: document.getElementById("pr-error"),
    editDialog: document.getElementById("pr-edit-dialog"),
    editForm: document.getElementById("pr-edit-form"),
    editHeading: document.getElementById("pr-edit-heading"),
    editSharedNote: document.getElementById("pr-edit-shared-note"),
    editTitle: document.getElementById("pr-edit-title"),
    editUrl: document.getElementById("pr-edit-url"),
    editLabel: document.getElementById("pr-edit-label"),
    editError: document.getElementById("pr-edit-error"),
    editCancel: document.getElementById("pr-edit-cancel"),
    confirmDialog: document.getElementById("pr-confirm-dialog"),
    confirmForm: document.getElementById("pr-confirm-form"),
    confirmHeading: document.getElementById("pr-confirm-heading"),
    confirmMessage: document.getElementById("pr-confirm-message"),
    confirmTypedField: document.getElementById("pr-confirm-typed-field"),
    confirmTyped: document.getElementById("pr-confirm-typed"),
    confirmError: document.getElementById("pr-confirm-error"),
    confirmCancel: document.getElementById("pr-confirm-cancel")
  };

  // --- closing the host modal ---------------------------------------------
  // The platform hands the iframe a MessagePort in an INIT_CHANNEL message and
  // listens for CLOSE_MODAL on it. Inlined in each staff bundle rather than
  // shared: a fourth asset route and cache-busting surface costs more than
  // fifteen duplicated lines, and it keeps the patient bundle free of anything
  // that talks to the staff host.
  var messagePort = null;

  window.addEventListener("message", function (event) {
    if (event.origin !== window.location.origin) {
      return;
    }
    if (event.data && event.data.type === "INIT_CHANNEL" && event.ports && event.ports[0]) {
      messagePort = event.ports[0];
      messagePort.start();
      requestResize();
    }
  });

  function closeModal() {
    if (messagePort) {
      messagePort.postMessage({ type: "CLOSE_MODAL" });
      return;
    }
    // No port means the host did not offer one. Closing the window is the only
    // remaining option and is harmless when it is not permitted.
    window.close();
  }

  // --- sizing the host modal ----------------------------------------------
  // The host opens this iframe at its own default, which for a short list is a
  // mostly empty window. It accepts a RESIZE on the same port, so the page asks
  // for the height its content actually needs, re-measured whenever the list
  // changes. Clamped: a long library must scroll inside the modal rather than
  // request a window taller than the viewport.
  var MODAL_WIDTH = 920;
  var MODAL_MIN_HEIGHT = 340;
  var MODAL_MAX_HEIGHT = 780;
  var lastRequestedHeight = 0;

  function wantedDialogHeight(dialog) {
    // Deliberately not dialog.offsetHeight. A <dialog> is capped by the user
    // agent's own max-height, so once it is clamped offsetHeight reports the
    // clamped value -- asking the host for exactly that can never grow the
    // window back out of the clamp, and the form stays scrolled forever.
    // Summing the body's scrollHeight with the pinned actions gives the height
    // the content actually wants.
    var body = dialog.querySelector(".pr-dialog-body");
    var actions = dialog.querySelector(".pr-dialog-actions");
    var wanted = (body ? body.scrollHeight : 0) + (actions ? actions.offsetHeight : 0);
    return wanted || dialog.offsetHeight;
  }

  function measuredContentHeight() {
    var app = document.getElementById("pr-app");
    var content = app ? app.scrollHeight : 0;

    // An open <dialog> is an overlay: it is laid out on top of the page rather
    // than inside #pr-app, so it contributes nothing to the measurement above.
    // Without this the window stays sized to the list behind it and the form has
    // to be scrolled.
    var openDialog = document.querySelector("dialog[open]");
    if (openDialog) {
      content = Math.max(content, wantedDialogHeight(openDialog) + 56);
    }
    return content;
  }

  function requestResize() {
    if (!messagePort) {
      return;
    }
    var desired = Math.max(
      MODAL_MIN_HEIGHT,
      Math.min(MODAL_MAX_HEIGHT, measuredContentHeight() + 32)
    );
    // Small fluctuations are not worth a message on every keystroke.
    if (Math.abs(desired - lastRequestedHeight) < 8) {
      return;
    }
    lastRequestedHeight = desired;
    messagePort.postMessage({ type: "RESIZE", width: MODAL_WIDTH, height: desired });
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function isSafeUrl(value) {
    if (typeof value !== "string" || !value) {
      return false;
    }
    try {
      var parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch (err) {
      return false;
    }
  }

  function request(path, options) {
    var opts = options || {};
    var body = opts.body ? JSON.stringify(opts.body) : undefined;
    // Content-Type describes a body, so it is only sent when there is one. A GET
    // that advertises `application/json` and then carries nothing invites the
    // layer in front of the plugin to parse an empty string as JSON.
    var headers = { Accept: "application/json" };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    return window
      .fetch(apiBase + path, {
        method: opts.method || "GET",
        headers: headers,
        credentials: "same-origin",
        body: body
      })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            if (response.ok) {
              return data;
            }
            var error = new Error(describeFailure(response.status, data));
            error.status = response.status;
            error.fieldErrors = data.field_errors || null;
            throw error;
          });
      })
      .catch(function (error) {
        // A rejected fetch never reached Canvas at all, so there is no status
        // to report. Presented the same way as a 5xx: not the user's doing, and
        // worth retrying.
        if (error.status === undefined) {
          var wrapped = new Error(describeFailure(0, null));
          wrapped.status = 0;
          throw wrapped;
        }
        throw error;
      });
  }

  function describeFailure(status, data) {
    // A message the reader can act on. The previous version said only "That did
    // not work", which left a plugin-runner restart indistinguishable from a
    // permissions problem and read as though the plugin were broken.
    if (data && data.error) {
      return data.error;
    }
    if (!status || status >= 500) {
      return (
        "Canvas could not reach this plugin" +
        (status ? " (HTTP " + status + ")" : "") +
        ". It may be reloading \u2014 wait a few seconds and reload the page."
      );
    }
    if (status === 404) {
      return "That endpoint is not available (HTTP 404). The plugin may still be loading.";
    }
    return "The request failed (HTTP " + status + ").";
  }

  // ---------- rendering ----------

  function cell(className) {
    var td = document.createElement("td");
    if (className) {
      td.className = className;
    }
    return td;
  }

  function renderTitleCell(resource) {
    var td = cell(null);
    var title = resource.title || "Untitled";

    // An anchor so an admin can check where a resource actually points, styled
    // as body text because the design shows no blue link. A stored value that no
    // longer passes validation renders as inert text instead.
    if (isSafeUrl(resource.url)) {
      var link = el("a", "pr-row-title", title);
      link.setAttribute("href", resource.url);
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
      link.setAttribute("title", resource.url);
      td.appendChild(link);
    } else {
      td.appendChild(el("span", "pr-row-title-plain", title));
    }

    if (!resource.is_active) {
      // Why it is inactive, not just that it is. Withdrawing archives the
      // resource as part of taking it back from patients, so the two states are
      // otherwise indistinguishable in this list.
      var withdrawn = Boolean(resource.withdrawn);
      var flag = el("span", "pr-archived-flag", withdrawn ? "Withdrawn" : "Archived");
      flag.setAttribute(
        "title",
        withdrawn
          ? "Taken back from patients who had it, and no longer offered"
          : "No longer offered. Patients who received it were not affected."
      );
      td.appendChild(document.createTextNode(" "));
      td.appendChild(flag);
    }
    return td;
  }

  function renderActionsCell(resource) {
    var td = cell("pr-col-actions");
    var group = el("div", "pr-row-actions");

    var edit = el("button", null, "Edit");
    edit.type = "button";
    edit.addEventListener("click", function () {
      openEditDialog(resource);
    });
    group.appendChild(edit);

    if (resource.is_active) {
      var archive = el("button", "pr-action-secondary", "Archive");
      archive.type = "button";
      archive.addEventListener("click", function () {
        confirmArchive(resource);
      });
      group.appendChild(archive);
    } else {
      var restore = el("button", "pr-action-secondary", "Restore");
      restore.type = "button";
      restore.addEventListener("click", function () {
        act("/library/resources/" + resource.id + "/restore", "Restored.");
      });
      group.appendChild(restore);
    }

    // One destructive slot, and which control fills it says whether this
    // resource ever reached a patient. Withdraw is meaningless for a resource
    // nobody has; Delete is refused for one they do.
    if (resource.ever_shared) {
      var retract = el("button", "pr-action-secondary pr-danger", "Withdraw");
      retract.type = "button";
      retract.setAttribute("title", "Shared with patients \u2014 take it back from them");
      retract.addEventListener("click", function () {
        confirmRetract(resource);
      });
      group.appendChild(retract);
    } else {
      var remove = el("button", "pr-action-secondary pr-danger", "Delete");
      remove.type = "button";
      remove.setAttribute("title", "Never shared \u2014 safe to remove entirely");
      remove.addEventListener("click", function () {
        confirmDelete(resource);
      });
      group.appendChild(remove);
    }

    td.appendChild(group);
    return td;
  }

  function renderRow(resource) {
    var row = document.createElement("tr");
    if (!resource.is_active) {
      row.className = "pr-row-archived";
    }

    row.appendChild(renderTitleCell(resource));

    // Always LINK: the scope is links only, and a real type field arrives with
    // PDF support. A constant here rather than computed state.
    var type = cell("pr-col-type");
    type.appendChild(el("span", "pr-type-pill", "Link"));
    row.appendChild(type);

    var label = cell("pr-col-label pr-row-label");
    label.textContent = resource.label || "";
    row.appendChild(label);

    row.appendChild(state.canEdit ? renderActionsCell(resource) : cell("pr-col-actions"));
    return row;
  }

  function render(payload) {
    state.canEdit = payload.can_edit === true;
    els.add.hidden = !state.canEdit;
    els.archivedToggle.hidden = !state.canEdit;
    els.readonly.hidden = state.canEdit;
    if (!state.canEdit) {
      els.readonly.textContent =
        "Read-only. Only administrators can change the resource library.";
    }

    els.rows.textContent = "";
    var resources = payload.resources || [];
    resources.forEach(function (resource) {
      els.rows.appendChild(renderRow(resource));
    });

    var isEmpty = resources.length === 0;
    els.empty.hidden = !isEmpty;
    if (isEmpty) {
      els.empty.textContent = hasFilters()
        ? "No resources match that search."
        : "The library is empty. Add the first resource to get started.";
    }

    var total = payload.total || 0;
    els.status.textContent =
      total > resources.length
        ? "Showing " + resources.length + " of " + total + " resources."
        : "";

    requestResize();
  }

  function hasFilters() {
    return Boolean(els.search.value.trim() || els.labelFilter.value);
  }

  // ---------- loading ----------

  function query() {
    var parts = [];
    var term = els.search.value.trim();
    if (term) {
      parts.push("q=" + encodeURIComponent(term));
    }
    if (els.labelFilter.value) {
      parts.push("label=" + encodeURIComponent(els.labelFilter.value));
    }
    if (els.showArchived && els.showArchived.checked) {
      parts.push("include_archived=true");
    }
    return parts.length ? "?" + parts.join("&") : "";
  }

  function load() {
    var seq = ++state.requestSeq;
    els.error.textContent = "";
    request("/library/resources" + query())
      .then(function (payload) {
        // A slower earlier response must not paint over a newer one.
        if (seq === state.requestSeq) {
          render(payload);
        }
      })
      .catch(function (error) {
        if (seq === state.requestSeq) {
          els.error.textContent = error.message;
        }
      });
  }

  function loadLabels() {
    request("/library/labels")
      .then(function (payload) {
        var current = els.labelFilter.value;
        els.labelFilter.textContent = "";
        els.labelFilter.appendChild(el("option", null, "All labels"));
        els.labelFilter.firstChild.value = "";
        (payload.labels || []).forEach(function (label) {
          var option = el("option", null, label);
          option.value = label;
          els.labelFilter.appendChild(option);
        });
        els.labelFilter.value = current;
      })
      .catch(function () {
        /* The filter is an optional convenience; the list still works. */
      });
  }

  // ---------- editing ----------

  function clearFieldErrors() {
    ["title", "url", "label"].forEach(function (field) {
      document.getElementById("pr-edit-" + field + "-error").textContent = "";
    });
    els.editError.textContent = "";
  }

  function openEditDialog(resource) {
    state.editing = resource || null;
    clearFieldErrors();
    els.editHeading.textContent = resource ? "Edit resource" : "Add resource";
    els.editTitle.value = resource ? resource.title || "" : "";
    els.editUrl.value = resource ? resource.url || "" : "";
    els.editLabel.value = resource ? resource.label || "" : "";
    els.editSharedNote.hidden = !resource;
    els.editDialog.showModal();
    requestResize();
    els.editTitle.focus();
  }

  function submitEdit(event) {
    event.preventDefault();
    clearFieldErrors();

    var body = {
      title: els.editTitle.value,
      url: els.editUrl.value,
      label: els.editLabel.value
    };
    var editing = state.editing;
    var path = editing ? "/library/resources/" + editing.id : "/library/resources";

    request(path, { method: editing ? "PUT" : "POST", body: body })
      .then(function () {
        els.editDialog.close();
        loadLabels();
        load();
      })
      .catch(function (error) {
        if (error.fieldErrors) {
          Object.keys(error.fieldErrors).forEach(function (field) {
            var node = document.getElementById("pr-edit-" + field + "-error");
            if (node) {
              node.textContent = error.fieldErrors[field];
            }
          });
        }
        els.editError.textContent = error.message;
      });
  }

  // ---------- archive and withdraw ----------

  function act(path, message, method) {
    request(path, { method: method || "POST" })
      .then(function () {
        els.status.textContent = message;
        loadLabels();
        load();
      })
      .catch(function (error) {
        els.error.textContent = error.message;
      });
  }

  var pendingConfirm = null;

  function openConfirm(options) {
    pendingConfirm = options;
    els.confirmError.textContent = "";
    els.confirmTyped.value = "";
    els.confirmHeading.textContent = options.heading;
    els.confirmMessage.textContent = options.message;
    els.confirmTypedField.hidden = !options.requireTyped;
    els.confirmDialog.showModal();
    requestResize();
  }

  function confirmArchive(resource) {
    openConfirm({
      heading: "Archive resource",
      message:
        'Archive "' +
        (resource.title || "this resource") +
        '"? It stops appearing in the picker and in patients\' portals. Patients keep the record of having received it, and you can restore it later.',
      requireTyped: false,
      run: function () {
        act("/library/resources/" + resource.id + "/archive", "Archived.");
      }
    });
  }

  function confirmRetract(resource) {
    openConfirm({
      heading: "Withdraw from patients",
      message:
        'Withdraw "' +
        (resource.title || "this resource") +
        '" from every patient who has it? Their portal will show that it was withdrawn, and the resource is archived. Use this when a link is wrong or harmful.',
      requireTyped: true,
      run: function () {
        act("/library/resources/" + resource.id + "/retract", "Withdrawn from patients.");
      }
    });
  }

  function confirmDelete(resource) {
    openConfirm({
      heading: "Delete resource",
      message:
        'Delete "' +
        (resource.title || "this resource") +
        '" from the library? It has never been shared with a patient, so nobody \u2014 ' +
        "and no record \u2014 loses anything. This cannot be undone.",
      // No typed confirmation: unlike Withdraw, this changes nothing a patient
      // holds, so demanding a typed word would be theatre.
      requireTyped: false,
      run: function () {
        act("/library/resources/" + resource.id, "Deleted.", "DELETE");
      }
    });
  }

  function submitConfirm(event) {
    event.preventDefault();
    if (!pendingConfirm) {
      return;
    }
    if (pendingConfirm.requireTyped && els.confirmTyped.value.trim().toUpperCase() !== "WITHDRAW") {
      els.confirmError.textContent = 'Type WITHDRAW to confirm.';
      return;
    }
    var run = pendingConfirm.run;
    pendingConfirm = null;
    els.confirmDialog.close();
    run();
  }

  // ---------- wiring ----------

  var searchTimer = null;
  els.search.addEventListener("input", function () {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(load, 200);
  });
  els.labelFilter.addEventListener("change", load);
  if (els.showArchived) {
    els.showArchived.addEventListener("change", load);
  }
  els.add.addEventListener("click", function () {
    openEditDialog(null);
  });
  els.editForm.addEventListener("submit", submitEdit);
  els.editCancel.addEventListener("click", function () {
    els.editDialog.close();
  });
  els.confirmForm.addEventListener("submit", submitConfirm);
  els.confirmCancel.addEventListener("click", function () {
    pendingConfirm = null;
    els.confirmDialog.close();
  });

  // Shrink back once a dialog goes away. Listening for `close` covers Esc, the
  // cancel buttons and a programmatic close with one handler.
  [els.editDialog, els.confirmDialog].forEach(function (dialog) {
    dialog.addEventListener("close", requestResize);
  });

  var closeButton = document.getElementById("pr-close");
  if (closeButton) {
    closeButton.addEventListener("click", closeModal);
  }

  loadLabels();
  load();
})();
