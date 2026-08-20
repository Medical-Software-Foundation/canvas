/* The chart picker: search the library, select several, send to the portal.
 *
 * The patient key comes only from the injected config block. Nothing else on
 * this page can name a patient, and the send endpoint resolves the key
 * server-side, so a tampered value fails with a 404 rather than reaching
 * somebody else's chart.
 *
 * Same conventions as the other bundles: createElement plus textContent, never
 * innerHTML; hrefs only after re-checking the scheme; <dialog> rather than
 * window.confirm; a monotonic request sequence so a slow response cannot paint
 * over a newer one.
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
  var patientId = config.patientId || "";

  var state = {
    selected: {},
    alreadyShared: {},
    requestSeq: 0,
    patientResolved: false
  };

  var els = {
    patient: document.getElementById("pr-patient"),
    search: document.getElementById("pr-search"),
    labelFilter: document.getElementById("pr-label-filter"),
    list: document.getElementById("pr-list"),
    empty: document.getElementById("pr-empty"),
    error: document.getElementById("pr-error"),
    selection: document.getElementById("pr-selection"),
    send: document.getElementById("pr-send"),
    resultDialog: document.getElementById("pr-result-dialog"),
    resultMessage: document.getElementById("pr-result-message")
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
  var MODAL_WIDTH = 760;
  var MODAL_MIN_HEIGHT = 300;
  var MODAL_MAX_HEIGHT = 620;
  var lastRequestedHeight = 0;

  function requestResize() {
    if (!messagePort) {
      return;
    }
    var app = document.getElementById("pr-app");
    var content = app ? app.scrollHeight : 0;
    var desired = Math.max(MODAL_MIN_HEIGHT, Math.min(MODAL_MAX_HEIGHT, content + 32));
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

  function selectedIds() {
    return Object.keys(state.selected)
      .filter(function (id) {
        return state.selected[id];
      })
      .map(Number);
  }

  function refreshFooter() {
    var count = selectedIds().length;
    els.selection.textContent =
      count === 0
        ? "Nothing selected"
        : count === 1
          ? "1 resource selected"
          : count + " resources selected";
    els.send.disabled = count === 0 || !state.patientResolved;
  }

  function renderItem(resource) {
    var item = el("li", "pr-item");
    var row = el("div", "pr-check-row");

    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = "pr-resource-" + resource.id;
    checkbox.checked = Boolean(state.selected[resource.id]);
    var shared = Boolean(state.alreadyShared[resource.id]);
    checkbox.disabled = shared;
    checkbox.addEventListener("change", function () {
      state.selected[resource.id] = checkbox.checked;
      refreshFooter();
    });
    row.appendChild(checkbox);

    var body = el("div", "pr-item-body");

    var label = document.createElement("label");
    label.setAttribute("for", checkbox.id);
    label.className = "pr-item-title";
    label.textContent = resource.title || "Untitled";
    body.appendChild(label);

    if (isSafeUrl(resource.url)) {
      var link = el("a", "pr-item-link", resource.url);
      link.setAttribute("href", resource.url);
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
      body.appendChild(link);
    }

    var meta = el("p");
    if (resource.label) {
      meta.appendChild(el("span", "pr-label", resource.label));
    }
    if (shared) {
      meta.appendChild(el("span", "pr-shared-flag", " Already shared"));
    }
    if (meta.childNodes.length) {
      body.appendChild(meta);
    }

    row.appendChild(body);
    item.appendChild(row);
    return item;
  }

  function render(payload) {
    els.list.textContent = "";
    var resources = payload.resources || [];
    resources.forEach(function (resource) {
      els.list.appendChild(renderItem(resource));
    });

    var isEmpty = resources.length === 0;
    els.empty.hidden = !isEmpty;
    if (isEmpty) {
      els.empty.textContent = hasFilters()
        ? "No resources match that search."
        : "The resource library is empty. An administrator can add resources from the Patient Resources app.";
    }
    refreshFooter();
    requestResize();
  }

  function hasFilters() {
    return Boolean(els.search.value.trim() || els.labelFilter.value);
  }

  function query() {
    var parts = [];
    var term = els.search.value.trim();
    if (term) {
      parts.push("q=" + encodeURIComponent(term));
    }
    if (els.labelFilter.value) {
      parts.push("label=" + encodeURIComponent(els.labelFilter.value));
    }
    return parts.length ? "?" + parts.join("&") : "";
  }

  function load() {
    var seq = ++state.requestSeq;
    els.error.textContent = "";
    request("/library/resources" + query())
      .then(function (payload) {
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
        (payload.labels || []).forEach(function (label) {
          var option = el("option", null, label);
          option.value = label;
          els.labelFilter.appendChild(option);
        });
      })
      .catch(function () {
        /* The filter is optional; the list still works without it. */
      });
  }

  function loadPatient() {
    if (!patientId) {
      els.patient.textContent = "This patient could not be found.";
      els.send.disabled = true;
      return;
    }
    request("/shares/patients/" + encodeURIComponent(patientId))
      .then(function (payload) {
        state.patientResolved = true;
        var name = (payload.patient && payload.patient.name) || "";
        els.patient.textContent = name ? "Sharing with " + name : "Sharing with this patient";
        (payload.shared || []).forEach(function (share) {
          state.alreadyShared[share.resource_id] = true;
        });
        load();
      })
      .catch(function () {
        els.patient.textContent = "This patient could not be found.";
        els.send.disabled = true;
      });
  }

  function send() {
    var ids = selectedIds();
    if (!ids.length) {
      return;
    }
    els.send.disabled = true;
    els.error.textContent = "";

    request("/shares/", { method: "POST", body: { patient: patientId, resource_ids: ids } })
      .then(function (payload) {
        (payload.shared_resource_ids || []).forEach(function (id) {
          state.alreadyShared[id] = true;
        });
        state.selected = {};
        els.resultMessage.textContent = summarize(payload);
        els.resultDialog.showModal();
        load();
      })
      .catch(function (error) {
        els.error.textContent = error.message;
        refreshFooter();
      });
  }

  function summarize(payload) {
    var parts = [];
    var created = payload.created || 0;
    parts.push(
      created === 0
        ? "Nothing new was shared."
        : created === 1
          ? "Shared 1 resource."
          : "Shared " + created + " resources."
    );
    if (payload.already_shared) {
      parts.push(
        payload.already_shared === 1
          ? "1 was already shared."
          : payload.already_shared + " were already shared."
      );
    }
    if (payload.skipped_unavailable) {
      parts.push(
        payload.skipped_unavailable === 1
          ? "1 is no longer available."
          : payload.skipped_unavailable + " are no longer available."
      );
    }
    return parts.join(" ");
  }

  var searchTimer = null;
  els.search.addEventListener("input", function () {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(load, 200);
  });
  els.labelFilter.addEventListener("change", load);
  els.send.addEventListener("click", send);

  var closeButton = document.getElementById("pr-close");
  if (closeButton) {
    closeButton.addEventListener("click", closeModal);
  }

  loadLabels();
  loadPatient();
})();
