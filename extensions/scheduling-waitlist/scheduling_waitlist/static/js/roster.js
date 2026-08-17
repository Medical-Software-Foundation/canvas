/* Scheduling Waitlist roster.
 *
 * Vanilla, no build step, no CDN. Kept deliberately thin: anything that counts
 * as a decision (sort order, expiry, priority rank, display names) is computed
 * server-side in a Python service where the test suite can reach it. This file
 * fetches, renders, and dispatches.
 */
(function () {
  "use strict";

  // ---- config ------------------------------------------------------------

  var configEl = document.getElementById("wl-config");
  var config = {};
  try {
    config = JSON.parse(configEl ? configEl.textContent : "{}") || {};
  } catch (err) {
    config = {};
  }

  var els = {
    status: document.getElementById("wl-status-line"),
    rows: document.getElementById("wl-rows"),
    filters: document.getElementById("wl-filters"),
    q: document.getElementById("wl-q"),
    statusFilter: document.getElementById("wl-status"),
    appointmentType: document.getElementById("wl-appointment-type"),
    provider: document.getElementById("wl-provider"),
    location: document.getElementById("wl-location"),
    priority: document.getElementById("wl-priority"),
    reset: document.getElementById("wl-reset"),
    add: document.getElementById("wl-add"),
    pager: document.getElementById("wl-pager"),
    prev: document.getElementById("wl-prev"),
    next: document.getElementById("wl-next"),
    range: document.getElementById("wl-range"),
    toast: document.getElementById("wl-toast")
  };

  var COLUMN_COUNT = 9;
  var SEARCH_DEBOUNCE_MS = 250;

  var state = {
    apiBase: config.apiBase || "",
    filters: {
      q: "",
      status: "",
      appointment_type_id: "",
      provider_id: "",
      location_id: "",
      priority: ""
    },
    sort: "priority",
    limit: 100,
    offset: 0,
    options: null,
    entries: [],
    total: 0,
    canManageAll: false,
    currentStaffDbid: null,
    // Set when the chart button opened this page for one patient. The key comes
    // from the page config; the name is fetched over the API so the document
    // itself carries nothing identifiable.
    addForPatientId: config.addForPatientId || "",
    // Bumped on every request; a response whose sequence is stale is dropped.
    // Without this, typing quickly can leave an earlier, slower response
    // painting over a later one.
    requestSeq: 0,
    searchTimer: null
  };

  // ---- small helpers -----------------------------------------------------

  function setStatus(message, tone) {
    if (!els.status) return;
    els.status.textContent = message;
    if (tone) {
      els.status.setAttribute("data-tone", tone);
    } else {
      els.status.removeAttribute("data-tone");
    }
  }

  var toastTimer = null;
  function toast(message, tone) {
    if (!els.toast) return;
    els.toast.textContent = message;
    if (tone) {
      els.toast.setAttribute("data-tone", tone);
    } else {
      els.toast.removeAttribute("data-tone");
    }
    els.toast.hidden = false;
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      els.toast.hidden = true;
    }, 4000);
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "text") {
          // textContent, never innerHTML: entry values are staff-entered and
          // patient-derived, and must never be parsed as markup.
          node.textContent = attrs[key];
        } else if (key === "class") {
          node.className = attrs[key];
        } else if (attrs[key] !== null && attrs[key] !== undefined) {
          node.setAttribute(key, attrs[key]);
        }
      });
    }
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function request(path, options) {
    var opts = options || {};
    return window
      .fetch(state.apiBase + path, {
        method: opts.method || "GET",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: opts.body ? JSON.stringify(opts.body) : undefined
      })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return {};
          })
          .then(function (data) {
            if (!response.ok) {
              var message = (data && data.error) || "Request failed (" + response.status + ").";
              var error = new Error(message);
              error.fieldErrors = data && data.field_errors;
              error.status = response.status;
              throw error;
            }
            return data;
          });
      });
  }

  // ---- filter controls ---------------------------------------------------

  function fillSelect(select, items, placeholder) {
    if (!select) return;
    select.textContent = "";
    select.appendChild(el("option", { value: "", text: placeholder }));
    items.forEach(function (item) {
      select.appendChild(el("option", { value: String(item.value), text: item.label }));
    });
  }

  function populateFilters(options) {
    fillSelect(
      els.statusFilter,
      (options.statuses || []).map(function (s) {
        return { value: s.value, label: s.label };
      }),
      "Waiting and offered"
    );
    fillSelect(
      els.appointmentType,
      (options.appointment_types || []).map(function (t) {
        return { value: t.dbid, label: t.name };
      }),
      "Any service"
    );

    var providers = (options.providers || []).map(function (p) {
      return { value: p.dbid, label: p.name };
    });
    providers.unshift({ value: options.any_preference || "any", label: "Any provider" });
    fillSelect(els.provider, providers, "All providers");

    var locations = (options.locations || []).map(function (l) {
      return { value: l.dbid, label: l.name };
    });
    locations.unshift({ value: options.any_preference || "any", label: "Any location" });
    fillSelect(els.location, locations, "All locations");

    fillSelect(
      els.priority,
      (options.priorities || []).map(function (p) {
        return { value: p.label, label: p.label };
      }),
      "Any priority"
    );
  }

  // ---- rendering ---------------------------------------------------------

  function priorityCell(entry) {
    var rank = entry.priority.rank;
    var pill = el("span", {
      class: "wl-pill",
      "data-rank": rank <= 2 ? String(rank) : "other",
      text: entry.priority.label || "Unset"
    });
    if (!entry.priority.is_known && entry.priority.label) {
      pill.setAttribute("title", "This priority is no longer configured.");
    }
    return el("td", null, [pill]);
  }

  function prefersText(entry) {
    var preferred = entry.preferred_window || {};
    if (preferred.note) return preferred.note;
    if (!preferred.windows || !preferred.windows.length) return "Any time";
    var names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    return preferred.windows
      .map(function (window) {
        var days = (window.days || [])
          .map(function (d) {
            return names[d] || "";
          })
          .filter(Boolean)
          .join(", ");
        var span = window.start && window.end ? window.start + "–" + window.end : "";
        return [days, span].filter(Boolean).join(" ");
      })
      .filter(Boolean)
      .join("; ");
  }

  function waitingCell(entry) {
    var children = [
      el("span", {
        text: entry.days_waiting === 1 ? "1 day" : entry.days_waiting + " days"
      })
    ];
    if (entry.is_past_shelf_life) {
      children.push(el("span", { class: "wl-secondary wl-expired", text: "Past shelf life" }));
    }
    return el("td", null, children);
  }

  function actionsCell(entry) {
    var chartLink = el("a", {
      class: "wl-link wl-btn wl-btn-sm",
      href: "/patient/" + entry.patient.id,
      target: "_top",
      text: "Chart"
    });

    var buttons = [chartLink];
    if (entry.can_edit) {
      buttons.push(
        el("button", {
          type: "button",
          class: "wl-btn wl-btn-sm",
          "data-action": "edit",
          "data-dbid": entry.dbid,
          text: "Edit"
        })
      );
      buttons.push(
        el("button", {
          type: "button",
          class: "wl-btn wl-btn-sm",
          "data-action": "scheduled",
          "data-dbid": entry.dbid,
          text: "Mark scheduled"
        })
      );
    }
    if (entry.can_remove) {
      buttons.push(
        el("button", {
          type: "button",
          class: "wl-btn wl-btn-sm wl-btn-danger",
          "data-action": "remove",
          "data-dbid": entry.dbid,
          text: "Remove"
        })
      );
    }
    return el("td", null, [el("div", { class: "wl-row-actions" }, buttons)]);
  }

  function renderRow(entry) {
    var patientCell = el("td", null, [
      el("span", { class: "wl-patient-name", text: entry.patient.name }),
      entry.note ? el("span", { class: "wl-secondary", text: entry.note }) : null
    ]);

    return el("tr", { "data-dbid": entry.dbid }, [
      patientCell,
      el("td", { text: entry.appointment_type.name }),
      el("td", { text: entry.provider.name }),
      el("td", { text: entry.location.name }),
      priorityCell(entry),
      el("td", { text: prefersText(entry) }),
      waitingCell(entry),
      el("td", null, [el("span", { class: "wl-badge", text: entry.status })]),
      actionsCell(entry)
    ]);
  }

  function renderEmpty(message) {
    return el("tr", null, [
      el("td", { colspan: String(COLUMN_COUNT), class: "wl-empty", text: message })
    ]);
  }

  function anyFilterApplied() {
    return Object.keys(state.filters).some(function (key) {
      return state.filters[key] !== "";
    });
  }

  function render() {
    if (!els.rows) return;
    els.rows.textContent = "";

    if (!state.entries.length) {
      els.rows.appendChild(
        renderEmpty(
          anyFilterApplied()
            ? "No entries match these filters."
            : "Nobody is on the waitlist yet."
        )
      );
    } else {
      state.entries.forEach(function (entry) {
        els.rows.appendChild(renderRow(entry));
      });
    }

    renderPager();
  }

  function renderPager() {
    if (!els.pager) return;
    var showing = state.entries.length;
    var hasMore = state.offset + showing < state.total;
    var hasPrev = state.offset > 0;

    els.pager.hidden = !hasMore && !hasPrev;
    if (els.range) {
      var from = state.total === 0 ? 0 : state.offset + 1;
      els.range.textContent = from + "–" + (state.offset + showing) + " of " + state.total;
    }
    if (els.prev) els.prev.disabled = !hasPrev;
    if (els.next) els.next.disabled = !hasMore;
  }

  // ---- loading -----------------------------------------------------------

  function queryString() {
    var params = new URLSearchParams();
    Object.keys(state.filters).forEach(function (key) {
      if (state.filters[key]) params.set(key, state.filters[key]);
    });
    params.set("sort", state.sort);
    params.set("limit", String(state.limit));
    params.set("offset", String(state.offset));
    return params.toString();
  }

  function reload() {
    state.requestSeq += 1;
    var seq = state.requestSeq;
    setStatus("Loading…");

    return request("/waitlist/entries?" + queryString())
      .then(function (data) {
        if (seq !== state.requestSeq) return; // a newer request already answered
        state.entries = data.entries || [];
        state.total = data.total || 0;
        state.canManageAll = !!data.can_manage_all;
        state.currentStaffDbid = data.current_staff_dbid;
        render();
        setStatus(
          state.total === 1 ? "1 patient waiting." : state.total + " patients waiting."
        );
      })
      .catch(function (error) {
        if (seq !== state.requestSeq) return;
        setStatus(error.message, "error");
      });
  }

  function loadOptions() {
    return request("/waitlist/options").then(function (data) {
      state.options = data;
      populateFilters(data);
      if (!data.is_configured) {
        toast(
          "No appointment types are configured yet, so entries cannot be added.",
          "error"
        );
      }
    });
  }

  // ---- events ------------------------------------------------------------

  function onFilterChange(key, value) {
    state.filters[key] = value;
    state.offset = 0;
    reload();
  }

  function bind() {
    if (els.q) {
      els.q.addEventListener("input", function (event) {
        var value = event.target.value.trim();
        if (state.searchTimer) window.clearTimeout(state.searchTimer);
        state.searchTimer = window.setTimeout(function () {
          onFilterChange("q", value);
        }, SEARCH_DEBOUNCE_MS);
      });
    }

    [
      [els.statusFilter, "status"],
      [els.appointmentType, "appointment_type_id"],
      [els.provider, "provider_id"],
      [els.location, "location_id"],
      [els.priority, "priority"]
    ].forEach(function (pair) {
      if (!pair[0]) return;
      pair[0].addEventListener("change", function (event) {
        onFilterChange(pair[1], event.target.value);
      });
    });

    if (els.filters) {
      els.filters.addEventListener("submit", function (event) {
        event.preventDefault();
      });
    }

    if (els.reset) {
      els.reset.addEventListener("click", function () {
        Object.keys(state.filters).forEach(function (key) {
          state.filters[key] = "";
        });
        if (els.q) els.q.value = "";
        [els.statusFilter, els.appointmentType, els.provider, els.location, els.priority].forEach(
          function (select) {
            if (select) select.value = "";
          }
        );
        state.offset = 0;
        reload();
      });
    }

    if (els.prev) {
      els.prev.addEventListener("click", function () {
        state.offset = Math.max(state.offset - state.limit, 0);
        reload();
      });
    }
    if (els.next) {
      els.next.addEventListener("click", function () {
        state.offset = state.offset + state.limit;
        reload();
      });
    }

    // One delegated listener rather than one per row, so re-rendering the
    // table never leaves stale handlers behind.
    if (els.rows) {
      els.rows.addEventListener("click", function (event) {
        var button = event.target.closest("button[data-action]");
        if (!button) return;
        var entry = findEntry(button.getAttribute("data-dbid"));
        if (!entry) return;

        var action = button.getAttribute("data-action");
        if (action === "edit") openEditDialog(entry);
        else if (action === "scheduled") markScheduled(entry);
        else if (action === "remove") removeEntry(entry);
      });
    }

    if (els.add) {
      els.add.addEventListener("click", function () {
        openAddDialog();
      });
    }
  }

  function findEntry(dbid) {
    for (var i = 0; i < state.entries.length; i += 1) {
      if (String(state.entries[i].dbid) === String(dbid)) return state.entries[i];
    }
    return null;
  }

  // ---- row actions -------------------------------------------------------

  function afterWrite(message) {
    toast(message);
    // A full reload rather than patching the row: the change may move the
    // entry out of the current filter or page.
    reload();
  }

  function markScheduled(entry) {
    request("/waitlist/entries/" + entry.dbid + "/status", {
      method: "POST",
      body: { status: "scheduled", reason: "" }
    })
      .then(function () {
        afterWrite(entry.patient.name + " marked scheduled.");
      })
      .catch(function (error) {
        toast(error.message, "error");
      });
  }

  function removeEntry(entry) {
    // Deliberately a confirm step: removal is a write other people can see.
    if (!window.confirm("Remove " + entry.patient.name + " from the waitlist?")) return;

    request("/waitlist/entries/" + entry.dbid, { method: "DELETE" })
      .then(function () {
        afterWrite(entry.patient.name + " removed from the waitlist.");
      })
      .catch(function (error) {
        toast(error.message, "error");
      });
  }

  // ---- edit dialog -------------------------------------------------------

  var dialog = document.getElementById("wl-edit-dialog");

  function field(labelText, control, errorFor, fullWidth) {
    return el("div", { class: "wl-field" + (fullWidth ? " wl-field-full" : "") }, [
      el("label", { for: control.id, text: labelText }),
      control,
      el("span", { class: "wl-field-error", "data-error-for": errorFor })
    ]);
  }

  function select(id, items, selected) {
    var node = el("select", { id: id });
    items.forEach(function (item) {
      var option = el("option", { value: String(item.value), text: item.label });
      if (String(item.value) === String(selected)) option.setAttribute("selected", "selected");
      node.appendChild(option);
    });
    return node;
  }

  // The server stores a window structurally (days plus a time span) rather
  // than by name, so the dialog matches it back to the named option it came
  // from. An unrecognised shape falls back to "any", which is also what an
  // entry with no stored window means.
  function currentWindowValue(entry, options) {
    var stored = (entry.preferred_window && entry.preferred_window.windows) || [];
    if (!stored.length) return "any";
    var first = stored[0] || {};
    var days = (first.days || []).join(",");
    var match = (options.time_windows || []).filter(function (w) {
      return w.value !== "any" && (WINDOW_SHAPES[w.value] || "") === days + "|" + (first.start || "");
    })[0];
    return match ? match.value : "any";
  }

  var WINDOW_SHAPES = {
    weekday_am: "0,1,2,3,4|08:00",
    weekday_pm: "0,1,2,3,4|12:00",
    weekend: "5,6|08:00"
  };

  function openEditDialog(entry) {
    if (!dialog || !state.options) return;
    var options = state.options;
    var ANY = options.any_preference || "any";

    var typeSelect = select(
      "wl-edit-type",
      (options.appointment_types || []).map(function (t) {
        return { value: t.dbid, label: t.name };
      }),
      entry.appointment_type.dbid
    );
    var providerSelect = select(
      "wl-edit-provider",
      [{ value: ANY, label: "Any provider" }].concat(
        (options.providers || []).map(function (p) {
          return { value: p.dbid, label: p.name };
        })
      ),
      entry.provider.is_any ? ANY : entry.provider.dbid
    );
    var locationSelect = select(
      "wl-edit-location",
      [{ value: ANY, label: "Any location" }].concat(
        (options.locations || []).map(function (l) {
          return { value: l.dbid, label: l.name };
        })
      ),
      entry.location.is_any ? ANY : entry.location.dbid
    );
    var prioritySelect = select(
      "wl-edit-priority",
      (options.priorities || []).map(function (p) {
        return { value: p.label, label: p.label };
      }),
      entry.priority.label
    );
    // Reconstruct which named window the stored days/time correspond to, so an
    // edit does not silently clear a preference the patient gave.
    var windowSelect = select(
      "wl-edit-window",
      (options.time_windows || []).map(function (w) {
        return { value: w.value, label: w.label };
      }),
      currentWindowValue(entry, options)
    );

    var noteInput = el("textarea", { id: "wl-edit-note", maxlength: "500" });
    noteInput.value = entry.note || "";

    var formError = el("p", { class: "wl-field-error", id: "wl-edit-error" });
    var save = el("button", {
      type: "submit",
      class: "wl-btn wl-btn-primary",
      text: "Save changes"
    });
    var cancel = el("button", { type: "button", class: "wl-btn", text: "Cancel" });

    var form = el("form", { id: "wl-edit-form" }, [
      el("div", { class: "wl-dialog-body" }, [
        el("h2", { id: "wl-edit-title", text: "Edit waitlist entry" }),
        el("p", { class: "wl-dialog-sub", text: entry.patient.name }),
        el("div", { class: "wl-form-grid" }, [
          field("Service", typeSelect, "appointment_type_id"),
          field("Provider", providerSelect, "provider_id"),
          field("Location", locationSelect, "location_id"),
          field("Priority", prioritySelect, "priority"),
          field("Preferred time", windowSelect, "preferred_window"),
          field("Note", noteInput, "note", true)
        ]),
        formError
      ]),
      el("div", { class: "wl-dialog-actions" }, [cancel, save])
    ]);

    dialog.textContent = "";
    dialog.appendChild(form);

    cancel.addEventListener("click", function () {
      dialog.close();
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      formError.textContent = "";
      Array.prototype.forEach.call(form.querySelectorAll("[data-error-for]"), function (n) {
        n.textContent = "";
      });

      var providerValue = providerSelect.value;
      var locationValue = locationSelect.value;
      save.disabled = true;

      request("/waitlist/entries/" + entry.dbid, {
        method: "PUT",
        body: {
          appointment_type_id: typeSelect.value,
          provider_preference: providerValue === ANY ? ANY : "specific",
          provider_id: providerValue === ANY ? "" : providerValue,
          location_preference: locationValue === ANY ? ANY : "specific",
          location_id: locationValue === ANY ? "" : locationValue,
          priority: prioritySelect.value,
          preferred_window: windowSelect.value,
          note: noteInput.value
        }
      })
        .then(function () {
          dialog.close();
          afterWrite("Entry updated.");
        })
        .catch(function (error) {
          save.disabled = false;
          formError.textContent = error.message;
          Object.keys(error.fieldErrors || {}).forEach(function (name) {
            var node = form.querySelector('[data-error-for="' + name + '"]');
            if (node) node.textContent = error.fieldErrors[name];
          });
        });
    });

    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "open");
    }
  }

  // ---- add dialog --------------------------------------------------------

  var addDialog = document.getElementById("wl-add-dialog");

  /* The patient picker.
   *
   * A patient is named rather than inferred: the waitlist is practice-wide and
   * is opened from the app drawer, so there is no chart context to read a
   * patient off. Search runs server-side for the same reason the roster's does
   * -- matching names in the browser would mean shipping the patient index.
   */
  function patientPicker(onPick) {
    var input = el("input", {
      id: "wl-add-patient",
      type: "search",
      placeholder: "Search by name",
      autocomplete: "off"
    });
    var results = el("ul", { class: "wl-picker-results", role: "listbox" });
    var chosen = el("p", { class: "wl-picker-chosen" });
    var timer = null;
    var seq = 0;

    function clearResults() {
      results.textContent = "";
      results.hidden = true;
    }

    function choose(patient) {
      onPick(patient);
      chosen.textContent = patient.name + (patient.birth_date ? " · " + patient.birth_date : "");
      input.value = "";
      clearResults();
    }

    function render(patients) {
      results.textContent = "";
      if (!patients.length) {
        results.appendChild(
          el("li", { class: "wl-picker-empty", text: "No matching patients." })
        );
        results.hidden = false;
        return;
      }
      patients.forEach(function (patient) {
        var button = el("button", {
          type: "button",
          class: "wl-picker-option",
          text: patient.name + (patient.birth_date ? " · " + patient.birth_date : "")
        });
        button.addEventListener("click", function () {
          choose(patient);
        });
        results.appendChild(el("li", { role: "option" }, [button]));
      });
      results.hidden = false;
    }

    input.addEventListener("input", function (event) {
      var term = event.target.value.trim();
      if (timer) window.clearTimeout(timer);
      if (!term) {
        clearResults();
        return;
      }
      timer = window.setTimeout(function () {
        // Same stale-response guard as the roster: typing quickly must not let
        // an earlier, slower response paint over a later one.
        seq += 1;
        var mine = seq;
        request("/waitlist/patients?q=" + window.encodeURIComponent(term))
          .then(function (data) {
            if (mine !== seq) return;
            render((data && data.patients) || []);
          })
          .catch(function () {
            if (mine !== seq) return;
            clearResults();
          });
      }, SEARCH_DEBOUNCE_MS);
    });

    clearResults();
    return { input: input, results: results, chosen: chosen };
  }

  function openAddDialog(preselected) {
    if (!addDialog || !state.options) return;

    // Guarded here rather than at each call site. Without configured services
    // every submission is refused, and the dropdown is populated from the
    // instance regardless -- so an unguarded entry point offers a form whose
    // Service choices can never be saved. Both the header button and the
    // arrive-from-a-chart path come through here, so neither can skip it.
    if (!state.options.is_configured) {
      toast(
        "No appointment types are configured for the waitlist yet, so entries "
          + "cannot be added.",
        "error"
      );
      return;
    }

    var options = state.options;
    var ANY = options.any_preference || "any";
    var picked = { patient: preselected || null };

    var picker = patientPicker(function (patient) {
      picked.patient = patient;
    });

    // Arriving from a chart, the patient is already known. Showing them as
    // chosen keeps one add form for both entry points rather than a second
    // form with its own validation.
    if (picked.patient) {
      picker.chosen.textContent =
        picked.patient.name +
        (picked.patient.birth_date ? " \u00b7 " + picked.patient.birth_date : "");
    }

    var typeSelect = select(
      "wl-add-type",
      (options.appointment_types || []).map(function (t) {
        return { value: t.dbid, label: t.name };
      })
    );
    var providerSelect = select(
      "wl-add-provider",
      [{ value: ANY, label: "Any provider" }].concat(
        (options.providers || []).map(function (p) {
          return { value: p.dbid, label: p.name };
        })
      )
    );
    var locationSelect = select(
      "wl-add-location",
      [{ value: ANY, label: "Any location" }].concat(
        (options.locations || []).map(function (l) {
          return { value: l.dbid, label: l.name };
        })
      )
    );
    var prioritySelect = select(
      "wl-add-priority",
      (options.priorities || []).map(function (p) {
        return { value: p.label, label: p.label };
      })
    );
    var windowSelect = select(
      "wl-add-window",
      (options.time_windows || []).map(function (w) {
        return { value: w.value, label: w.label };
      })
    );

    var noteInput = el("textarea", { id: "wl-add-note", maxlength: "500" });

    var formError = el("p", { class: "wl-field-error", id: "wl-add-error" });
    var save = el("button", {
      type: "submit",
      class: "wl-btn wl-btn-primary",
      text: "Add to waitlist"
    });
    var cancel = el("button", { type: "button", class: "wl-btn", text: "Cancel" });

    var form = el("form", { id: "wl-add-form" }, [
      el("div", { class: "wl-dialog-body" }, [
        el("h2", { id: "wl-add-title", text: "Add to waitlist" }),
        el("div", { class: "wl-form-grid" }, [
          el("div", { class: "wl-field wl-field-full" }, [
            el("label", { for: picker.input.id, text: "Patient" }),
            picker.input,
            picker.results,
            picker.chosen,
            el("span", { class: "wl-field-error", "data-error-for": "patient_id" })
          ]),
          field("Service", typeSelect, "appointment_type_id"),
          field("Provider", providerSelect, "provider_id"),
          field("Location", locationSelect, "location_id"),
          field("Priority", prioritySelect, "priority"),
          field("Preferred time", windowSelect, "preferred_window"),
          field("Note", noteInput, "note", true)
        ]),
        formError
      ]),
      el("div", { class: "wl-dialog-actions" }, [cancel, save])
    ]);

    addDialog.textContent = "";
    addDialog.appendChild(form);

    cancel.addEventListener("click", function () {
      addDialog.close();
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      formError.textContent = "";
      Array.prototype.forEach.call(form.querySelectorAll("[data-error-for]"), function (n) {
        n.textContent = "";
      });

      // Checked here as well as server-side: the server refuses a missing
      // patient anyway, but naming the field is friendlier than a round trip.
      if (!picked.patient) {
        var target = form.querySelector('[data-error-for="patient_id"]');
        if (target) target.textContent = "Choose a patient.";
        return;
      }

      var providerValue = providerSelect.value;
      var locationValue = locationSelect.value;
      save.disabled = true;

      request("/waitlist/entries", {
        method: "POST",
        body: {
          patient_id: picked.patient.id,
          appointment_type_id: typeSelect.value,
          provider_preference: providerValue === ANY ? ANY : "specific",
          provider_id: providerValue === ANY ? "" : providerValue,
          location_preference: locationValue === ANY ? ANY : "specific",
          location_id: locationValue === ANY ? "" : locationValue,
          priority: prioritySelect.value,
          preferred_window: windowSelect.value,
          note: noteInput.value
        }
      })
        .then(function () {
          addDialog.close();
          afterWrite(picked.patient.name + " added to the waitlist.");
        })
        .catch(function (error) {
          save.disabled = false;
          formError.textContent = error.message;
          Object.keys(error.fieldErrors || {}).forEach(function (name) {
            var node = form.querySelector('[data-error-for="' + name + '"]');
            if (node) node.textContent = error.fieldErrors[name];
          });
        });
    });

    if (typeof addDialog.showModal === "function") {
      addDialog.showModal();
    } else {
      addDialog.setAttribute("open", "open");
    }
    // With the patient already chosen, the service is the first thing left to
    // decide, so focus goes there rather than to a picker nobody needs.
    if (picked.patient) {
      typeSelect.focus();
    } else {
      picker.input.focus();
    }
  }

  // ---- start -------------------------------------------------------------

  function openAddForRequestedPatient() {
    // The chart button sent us here to add one patient. Resolve their name over
    // the API, then open the same add dialog the roster's own button opens.
    if (!state.addForPatientId) return;

    request("/waitlist/patients/" + window.encodeURIComponent(state.addForPatientId))
      .then(function (data) {
        if (data && data.patient) {
          openAddDialog(data.patient);
        } else {
          openAddDialog();
        }
      })
      .catch(function () {
        // An unresolvable patient is not worth an error banner over the whole
        // roster: fall back to the picker so the scheduler can still act.
        openAddDialog();
      });
  }

  if (!state.apiBase) {
    setStatus("The waitlist could not start: its configuration is missing.", "error");
    return;
  }

  bind();
  loadOptions()
    .then(reload)
    .then(openAddForRequestedPatient)
    .catch(function (error) {
      setStatus(error.message, "error");
    });
})();
