(function() {
  var INTAKE_CONFIG = (function () {
    var el = document.getElementById("intake-config");
    if (!el) return { note_uuid: "", api_base: "/plugin-io/api/intake_chart_app" };
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      console.warn("ic: failed to parse intake-config", e);
      return { note_uuid: "", api_base: "/plugin-io/api/intake_chart_app" };
    }
  })();
  var NOTE_UUID = INTAKE_CONFIG.note_uuid;
  var API = INTAKE_CONFIG.api_base;

  // Iframe-stretch: Canvas embeds the modal in a srcdoc iframe whose host
  // container constrains height by default. Reach into the parent and
  // stretch the iframe + a few ancestors so the form fills the note body.
  // Called immediately AND on `load` AND once more on a short retry to
  // beat the host's post-render restyling — without it the user has to
  // toggle the tab two or three times before the iframe expands.
  function expandHostIframe() {
    try {
      var parentDoc = window.parent && window.parent.document;
      if (!parentDoc) return false;
      var iframes = parentDoc.querySelectorAll('iframe');
      for (var i = 0; i < iframes.length; i++) {
        if (iframes[i].contentWindow === window) {
          var iframe = iframes[i];
          iframe.style.minHeight = '80vh';
          iframe.style.height = '80vh';
          iframe.style.width = '100%';
          var node = iframe.parentElement;
          for (var depth = 0; node && depth < 4; depth++) {
            node.style.minHeight = '80vh';
            node = node.parentElement;
          }
          return true;
        }
      }
      return false;
    } catch (e) {
      console.warn('ic: host iframe expand failed', e && e.message);
      return false;
    }
  }
  expandHostIframe();
  window.addEventListener('load', expandHostIframe);
  setTimeout(expandHostIframe, 150);

  var FLAT_SECTIONS = ["vitals", "social_history"];
  var MULTI_SECTIONS = [
    "problems", "allergies", "medications",
    "medical_history", "surgical_history", "family_history",
  ];
  // Debounced auto-save replaces an explicit Save Draft button.
  var AUTO_SAVE_DEBOUNCE_MS = 600;

  function uuidv4() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {
      var r = Math.random() * 16 | 0, v = c === "x" ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  function $(id) { return document.getElementById(id); }

  function setStatus(sectionId, message, kind) {
    var el = $("save-status-" + sectionId);
    if (el) {
      el.textContent = message || "";
      el.className = "ic-status" + (kind ? " ic-status--" + kind : "");
    }
    var hdr = $("status-" + sectionId);
    if (hdr) {
      hdr.textContent = message || "";
      hdr.className = "ic-section-status" + (kind ? " ic-section-status--" + kind : "");
    }
  }

  function setCommitStatus(message, kind) {
    var el = $("commit-status");
    if (!el) return;
    el.textContent = message || "";
    el.className = "ic-commit-status" + (kind ? " ic-commit-status--" + kind : "");
  }

  function collectSection(sectionId) {
    var form = $("form-" + sectionId);
    if (!form) return {};
    var data = {};
    var inputs = form.querySelectorAll("input, textarea, select");
    for (var i = 0; i < inputs.length; i++) {
      var el = inputs[i];
      if (!el.name) continue;
      if (el.type === "checkbox") {
        data[el.name] = el.checked;
      } else if (el.type === "radio") {
        // Radio inputs share a name across all options in the group; only
        // record the checked one's value, otherwise the last-radio-wins loop
        // clobbers the user's pick with the last DOM-order option.
        if (el.checked) data[el.name] = el.value;
      } else {
        data[el.name] = el.value;
      }
    }
    return data;
  }

  function applySection(sectionId, data) {
    if (!data || typeof data !== "object") return;
    var form = $("form-" + sectionId);
    if (!form) return;
    var inputs = form.querySelectorAll("input, textarea, select");
    for (var i = 0; i < inputs.length; i++) {
      var el = inputs[i];
      if (!el.name || !(el.name in data)) continue;
      var v = data[el.name];
      if (el.type === "checkbox") {
        el.checked = v === true || v === "true" || v === "on";
      } else if (el.type === "radio") {
        // Restore the saved pick by checking the option whose value matches.
        // Other radios in the same group stay unchecked. Setting .value on a
        // radio is a no-op for the visual checked state, which is why the
        // pre-fix reload showed an empty form.
        el.checked = (v != null && String(el.value) === String(v));
      } else {
        el.value = v == null ? "" : v;
      }
    }
    // Re-evaluate the Vitals Save Draft gate after a draft loads — without
    // this, a saved-and-reloaded vitals row would keep the button disabled
    // even though the inputs now have values.
    if (sectionId === "vitals") refreshVitalsGate();
  }

  function refreshVitalsGate() {
    var form = $("form-vitals");
    if (!form) return;
    var inputs = form.querySelectorAll("input[type=number]");
    var hasValue = false;
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].value && inputs[i].value.trim() !== "") {
        hasValue = true;
        break;
      }
    }
    var btn = document.querySelector('[data-save-section="vitals"]');
    var hint = document.querySelector('[data-save-hint="vitals"]');
    if (btn) btn.disabled = !hasValue;
    if (hint) hint.hidden = hasValue;
  }

  // ---- Multi-command sections (Problems / Allergies / Medications) -------

  function rowsContainer(sectionId) {
    var section = document.querySelector('[data-multi-section="' + sectionId + '"]');
    return section ? section.querySelector('.ic-rows') : null;
  }

  function rowPrefix(sectionId) {
    var section = document.querySelector('[data-multi-section="' + sectionId + '"]');
    return section ? section.getAttribute('data-row-prefix') || sectionId : sectionId;
  }

  function setRowAction(rowEl, action) {
    if (!rowEl) return;
    rowEl.setAttribute('data-action', action);
    var btns = rowEl.querySelectorAll('[data-row-action]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].setAttribute('aria-pressed', btns[i].getAttribute('data-row-action') === action ? 'true' : 'false');
    }
    var editPanel = rowEl.querySelector('[data-edit-panel]');
    var removePanel = rowEl.querySelector('[data-remove-panel]');
    if (editPanel) editPanel.classList.toggle('ic-row-collapsed', action !== 'edit');
    if (removePanel) removePanel.classList.toggle('ic-row-collapsed', action !== 'remove');
  }

  // Action-button delegation: clicking Confirm/Edit/Remove on any pre-filled
  // row sets that row's data-action and reveals the appropriate field panel.
  document.body.addEventListener('click', function(ev) {
    var btn = ev.target.closest && ev.target.closest('[data-row-action]');
    if (!btn) return;
    var rowEl = btn.closest('.ic-row');
    setRowAction(rowEl, btn.getAttribute('data-row-action'));
  });

  function collectRowFields(rowEl) {
    var values = {};
    var inputs = rowEl.querySelectorAll('[data-row-field]');
    for (var i = 0; i < inputs.length; i++) {
      var el = inputs[i];
      // Only collect from the panel that matches the current action so
      // off-screen Add/Remove fields don't pollute the Edit payload.
      var action = rowEl.getAttribute('data-action');
      var inEdit = el.closest('[data-edit-panel]');
      var inRemove = el.closest('[data-remove-panel]');
      if (action === 'edit' && inRemove) continue;
      if (action === 'remove' && inEdit) continue;
      if (action === 'confirm' && (inEdit || inRemove)) continue;
      values[el.getAttribute('data-row-field')] = el.value;
    }
    return values;
  }

  function collectMultiSection(sectionId) {
    var container = rowsContainer(sectionId);
    if (!container) return {rows: {}};
    var rows = {};
    var rowEls = container.querySelectorAll('.ic-row');
    for (var i = 0; i < rowEls.length; i++) {
      var rowEl = rowEls[i];
      var rowId = rowEl.getAttribute('data-row-id');
      if (!rowId) continue;
      rows[rowId] = {
        action: rowEl.getAttribute('data-action') || 'confirm',
        values: collectRowFields(rowEl),
      };
    }
    return {rows: rows};
  }

  function applyMultiSection(sectionId, data) {
    if (!data || typeof data !== 'object') return;
    var savedRows = data.rows || {};
    var container = rowsContainer(sectionId);
    if (!container) return;
    Object.keys(savedRows).forEach(function(rowId) {
      var saved = savedRows[rowId] || {};
      var rowEl = container.querySelector('[data-row-id="' + rowId + '"]');
      if (!rowEl) {
        // A new row that was added in a previous draft — recreate it from
        // the saved values into the rows container.
        rowEl = makeAddedRow(sectionId, rowId, saved.values || {});
        if (rowEl) container.appendChild(rowEl);
      }
      if (!rowEl) return;
      setRowAction(rowEl, saved.action || 'confirm');
      var values = saved.values || {};
      Object.keys(values).forEach(function(fieldId) {
        var input = rowEl.querySelector('[data-row-field="' + fieldId + '"]');
        if (input) input.value = values[fieldId] == null ? '' : values[fieldId];
      });
    });
  }

  // "+ Add to draft" — copy the section's add-template fields into a fresh
  // row appended at the bottom of the rows container, with action="add".
  function makeAddedRow(sectionId, rowId, values) {
    var section = document.querySelector('[data-multi-section="' + sectionId + '"]');
    if (!section) return null;
    var template = section.querySelector('[data-add-template] .ic-row-fields');
    if (!template) return null;

    var row = document.createElement('div');
    row.className = 'ic-row';
    row.setAttribute('data-row-id', rowId);
    row.setAttribute('data-action', 'add');

    var summary = document.createElement('div');
    summary.className = 'ic-row-summary';
    summary.innerHTML =
      '<span class="ic-row-label">+ New entry</span>' +
      '<button type="button" class="ic-row--remove-affordance" data-drop-row>Drop from draft</button>';
    row.appendChild(summary);

    // Clone the add-fields template; mark them as the row's fields.
    var fields = template.cloneNode(true);
    fields.querySelectorAll('.ic-search-wrap').forEach(function(wrap) {
      // Reset the widget init flag so setupAllSearchWidgets reflects the
      // saved hidden value as a picked pill (cloneNode copies dataset,
      // which would otherwise make setupSearchWidget skip the clone).
      delete wrap.dataset.icSearchInit;
      // Hide the search input + dropdown in committed added rows — the
      // picked pill IS the field's visible value; an empty "Type again to
      // change…" input below it reads like a half-finished form. The row
      // is dropped via the row's "Drop from draft" link, not by editing
      // the field, so the search controls have no role here.
      var searchInput = wrap.querySelector('.ic-search-input');
      if (searchInput) searchInput.hidden = true;
      var searchResults = wrap.querySelector('.ic-search-results');
      if (searchResults) searchResults.hidden = true;
      // Strip the "(search by name)" suffix from the field label so the
      // row reads as a finalized value, not as a search prompt.
      var field = wrap.closest('.ic-field');
      var label = field ? field.querySelector('.ic-label') : null;
      if (label) {
        label.textContent = label.textContent.replace(/\s*\(search by name\)\s*$/, '');
      }
    });
    var inputs = fields.querySelectorAll('[data-row-field]');
    for (var i = 0; i < inputs.length; i++) {
      var fieldId = inputs[i].getAttribute('data-row-field');
      if (values && fieldId in values) inputs[i].value = values[fieldId] || '';
    }
    row.appendChild(fields);

    // Drop-from-draft removes the row from the DOM (and from the next
    // collected payload). If the row had been committed before it'll get
    // re-emitted as a stale entry, but for v1 we accept that.
    row.querySelector('[data-drop-row]').addEventListener('click', function() {
      row.parentNode && row.parentNode.removeChild(row);
    });

    return row;
  }

  document.querySelectorAll('[data-add-row]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var sectionId = btn.getAttribute('data-add-row');
      var prefix = rowPrefix(sectionId);
      var rowId = 'new:' + uuidv4();
      // Pull the in-progress add-template values, mint a row, then clear the
      // template so the next add starts fresh.
      var section = document.querySelector('[data-multi-section="' + sectionId + '"]');
      var template = section ? section.querySelector('[data-add-template]') : null;
      if (!template) return;
      var values = {};
      template.querySelectorAll('[data-row-field]').forEach(function(input) {
        values[input.getAttribute('data-row-field')] = input.value;
        input.value = '';
      });
      // Don't add an empty row — at least one field must be set.
      var anyValue = Object.keys(values).some(function(k) { return (values[k] || '').toString().trim() !== ''; });
      if (!anyValue) return;
      var row = makeAddedRow(sectionId, rowId, values);
      var container = rowsContainer(sectionId);
      if (row && container) {
        // If the empty placeholder is showing, replace it.
        var empty = container.querySelector('.ic-rows-empty');
        if (empty) empty.parentNode.removeChild(empty);
        container.appendChild(row);
      }
      // Reset the add-template's visual state so it doesn't look like a
      // half-finished form after + Add. Clearing hidden field values
      // above isn't enough — the picked pill and "Picked. Type again"
      // placeholder also need to clear.
      template.querySelectorAll('.ic-search-picked').forEach(function(pill) {
        pill.hidden = true;
        pill.innerHTML = '';
      });
      template.querySelectorAll('.ic-search-input').forEach(function(searchInput) {
        searchInput.value = '';
        searchInput.placeholder = 'Type to search...';
      });
      refreshAddGate(sectionId);
    });
  });

  function saveMultiSection(sectionId) {
    if (!NOTE_UUID) {
      setStatus(sectionId, "Cannot save - no note context", "error");
      return;
    }
    var btn = document.querySelector('[data-save-multi="' + sectionId + '"]');
    if (btn) btn.disabled = true;
    setStatus(sectionId, "Saving…", "saving");

    var body = collectMultiSection(sectionId);
    var url = API + "/intake/section/save?section=" + encodeURIComponent(sectionId)
      + "&note_id=" + encodeURIComponent(NOTE_UUID);
    fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
    .then(function(arr) {
      var ok = arr[0]; var j = arr[1];
      if (ok && j && j.success) setStatus(sectionId, "Saved", "saved");
      else { setStatus(sectionId, "Save failed", "error"); console.error("ic: save error", j); }
    })
    .catch(function(err) {
      setStatus(sectionId, "Save failed", "error"); console.error("ic: save fetch failed", err);
    })
    .then(function() { if (btn) btn.disabled = false; });
  }

  // Save Draft buttons (data-save-multi) were removed in favour of
  // debounced auto-save. The handler wiring stays as a defensive no-op
  // in case any partial still emits the attribute somewhere we missed.
  document.querySelectorAll('[data-save-multi]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      saveMultiSection(btn.getAttribute('data-save-multi'));
    });
  });

  // ---- Search-as-you-type widgets (NLM Clinical Tables) -----------------

  var SEARCH_ENDPOINTS = {
    icd10: function(term) {
      // ICD-10-CM autocomplete. Response shape: [count, [code...], extras, [[code, name], ...]]
      return "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
        + "?sf=code,name&maxList=12&terms=" + encodeURIComponent(term);
    },
    rxterms: function(term) {
      // Canvas FDB grouped-medication search via server-side proxy. We need
      // the FDB med_medication_id (not an RxCUI) for MedicationStatementCommand
      // to resolve a medication name. The proxy returns NLM Clinical Tables
      // shaped JSON so the shared parser below treats it the same as ICD-10.
      // The "rxterms" kind name is a historical misnomer kept to avoid
      // sprawling renames in render_context.py — the actual source is FDB.
      return API + "/intake/search/medication?q=" + encodeURIComponent(term);
    },
    allergy: function(term) {
      // Canvas FDB allergy search via server-side proxy. AllergyCommand
      // expects an Allergen(concept_id, concept_type) — both numeric — so
      // the proxy encodes them as "<id>|<type>" compound codes in the
      // picked value. The reconciler splits them apart before construction.
      return API + "/intake/search/allergy?q=" + encodeURIComponent(term);
    },
  };

  function setupSearchWidget(wrap) {
    if (wrap.dataset.icSearchInit === "1") return;
    wrap.dataset.icSearchInit = "1";
    var kind = wrap.getAttribute("data-search-kind");
    var endpoint = SEARCH_ENDPOINTS[kind];
    if (!endpoint) return;
    var input = wrap.querySelector(".ic-search-input");
    var results = wrap.querySelector(".ic-search-results");
    var hiddens = wrap.querySelectorAll('input[type="hidden"]');
    var hidden = hiddens[0];   // code (icd10_code / allergen_code / fdb_code)
    var nameHidden = hiddens[1] || null;  // sibling __display field for the human name
    var picked = wrap.querySelector(".ic-search-picked");
    var debounce = null;
    var highlight = -1;
    var lastResults = [];

    function close() {
      results.innerHTML = "";
      results.hidden = true;
      highlight = -1;
    }

    function setHighlight(i) {
      highlight = Math.max(-1, Math.min(i, lastResults.length - 1));
      var btns = results.querySelectorAll(".ic-search-result");
      for (var j = 0; j < btns.length; j++) {
        btns[j].classList.toggle("is-highlighted", j === highlight);
      }
    }

    function pick(item) {
      hidden.value = item.code || "";
      // Mirror the human-readable name into the sibling __display field so
      // it survives save/reload — reflect-on-load below reads it back as
      // the picked pill's name instead of the previous "(saved)" stub.
      if (nameHidden) nameHidden.value = item.name || "";
      // Setting .value programmatically doesn't trigger input/change events,
      // so the + Add gate would never see the picked code. Dispatch
      // explicitly so refreshAddGate runs.
      hidden.dispatchEvent(new Event("input", { bubbles: true }));
      hidden.dispatchEvent(new Event("change", { bubbles: true }));
      // In a committed added row (inside .ic-row), the picked pill is purely
      // informational — the only way to undo the add is the row's
      // "Drop from draft" link. Suppress the × clear button there so the
      // user has a single, unambiguous drop affordance per row.
      var inAddedRow = !!wrap.closest('.ic-row');
      var clearButton = inAddedRow
        ? ''
        : '<button type="button" class="ic-search-picked-clear" title="Clear">×</button>';
      var fullLabel = item.code + ' ' + item.name;
      picked.innerHTML =
        '<span title="' + escapeHtml(fullLabel) + '"><strong>'
        + escapeHtml(item.code) + '</strong> '
        + escapeHtml(item.name) + '</span>' + clearButton;
      picked.hidden = false;
      input.value = "";
      input.placeholder = "Picked. Type again to change…";
      close();
      var clearEl = picked.querySelector(".ic-search-picked-clear");
      if (clearEl) {
        clearEl.addEventListener("click", function() {
          hidden.value = "";
          if (nameHidden) nameHidden.value = "";
          hidden.dispatchEvent(new Event("input", { bubbles: true }));
          hidden.dispatchEvent(new Event("change", { bubbles: true }));
          picked.hidden = true;
          picked.innerHTML = "";
          input.placeholder = "Type to search...";
        });
      }
    }

    function escapeHtml(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function renderResults(items) {
      lastResults = items;
      if (!items || !items.length) { close(); return; }
      results.innerHTML = "";
      items.forEach(function(item, i) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ic-search-result";
        btn.innerHTML =
          '<span class="ic-search-result-code">' + escapeHtml(item.code) + '</span>' +
          '<span class="ic-search-result-name">' + escapeHtml(item.name) + '</span>';
        btn.addEventListener("click", function() { pick(item); });
        results.appendChild(btn);
      });
      results.hidden = false;
      setHighlight(0);
    }

    function search(term) {
      if (!term || term.length < 2) { close(); return; }
      fetch(endpoint(term))
        .then(function(r) { return r.json(); })
        .then(function(data) {
          // Both endpoints return NLM Clinical Tables shape:
          //   [count, [identifier_per_row], extras_or_null, [[col1, col2?], ...]].
          // ICD-10: data[1][i] mirrors pair[0] = ICD code; pair[1] = name.
          // Medication (FDB proxy): data[1][i] = med_medication_id; pair[0] = description.
          // For both, codes[i] is the picked code (fdb_code / icd10_code).
          var pairs = data && data[3] ? data[3] : [];
          var codes = data && data[1] ? data[1] : [];
          var items = pairs.map(function(pair, i) {
            var displayName = (pair && pair[1]) ? pair[1]
              : (pair && pair[0]) ? pair[0] : "";
            return {
              code: codes[i] || (pair && pair[0]) || "",
              name: displayName,
            };
          });
          // Deduplicate identical (code,name) pairs (RxTerms returns dupes
          // when sf=DISPLAY_NAME and df=DISPLAY_NAME match).
          var seen = {};
          items = items.filter(function(it) {
            var k = it.code + "::" + it.name;
            if (seen[k]) return false;
            seen[k] = true;
            return true;
          });
          renderResults(items);
        })
        .catch(function(err) {
          console.warn("ic: search failed", kind, err);
          close();
        });
    }

    input.addEventListener("input", function() {
      var term = input.value.trim();
      clearTimeout(debounce);
      debounce = setTimeout(function() { search(term); }, 300);
    });

    input.addEventListener("keydown", function(e) {
      if (results.hidden) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setHighlight(highlight + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setHighlight(highlight - 1); }
      else if (e.key === "Enter" && highlight >= 0) {
        e.preventDefault();
        pick(lastResults[highlight]);
      } else if (e.key === "Escape") {
        close();
      }
    });

    // Click outside closes the dropdown.
    document.addEventListener("click", function(ev) {
      if (!wrap.contains(ev.target)) close();
    });

    // If the hidden field already has a value (form-state load), reflect it.
    if (hidden.value) {
      pick({
        code: hidden.value,
        name: (nameHidden && nameHidden.value) || "(saved)",
      });
    }
  }

  // Wire all existing + future search widgets.
  function setupAllSearchWidgets() {
    document.querySelectorAll(".ic-search-wrap").forEach(setupSearchWidget);
  }
  setupAllSearchWidgets();

  // After + Add clones the template, the new row may include a fresh
  // .ic-search-wrap. Re-wire after every add.
  var origMakeAddedRow = makeAddedRow;
  makeAddedRow = function(sectionId, rowId, values) {
    var row = origMakeAddedRow(sectionId, rowId, values);
    if (row) setTimeout(setupAllSearchWidgets, 0);
    return row;
  };

  function loadFormState() {
    if (!NOTE_UUID) return;
    fetch(API + "/intake/form-state?note_id=" + encodeURIComponent(NOTE_UUID), {
      credentials: "same-origin",
    })
    .then(function(r) { return r.json(); })
    .then(function(payload) {
      if (!payload || !payload.success) return;
      var saved = payload.sections || {};
      FLAT_SECTIONS.forEach(function(sectionId) {
        if (saved[sectionId]) applySection(sectionId, saved[sectionId]);
      });
      MULTI_SECTIONS.forEach(function(sectionId) {
        if (saved[sectionId]) applyMultiSection(sectionId, saved[sectionId]);
      });
      // Re-wire search widgets in case applyMultiSection injected new rows.
      setupAllSearchWidgets();
    })
    .catch(function(err) {
      console.warn("ic: form-state load failed", err);
    });
  }

  function saveSection(sectionId) {
    if (!NOTE_UUID) {
      setStatus(sectionId, "Cannot save - no note context", "error");
      return;
    }
    var btn = document.querySelector('[data-save-section="' + sectionId + '"]');
    if (btn) btn.disabled = true;
    setStatus(sectionId, "Saving…", "saving");

    var body = collectSection(sectionId);
    var url = API + "/intake/section/save?section=" + encodeURIComponent(sectionId)
      + "&note_id=" + encodeURIComponent(NOTE_UUID);
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
    .then(function(arr) {
      var ok = arr[0]; var j = arr[1];
      if (ok && j && j.success) {
        setStatus(sectionId, "Saved", "saved");
      } else {
        setStatus(sectionId, "Save failed", "error");
        console.error("ic: save error", j);
      }
    })
    .catch(function(err) {
      setStatus(sectionId, "Save failed", "error");
      console.error("ic: save fetch failed", err);
    })
    .then(function() { if (btn) btn.disabled = false; });
  }

  function saveSectionPayload(sectionId, body) {
    var url = API + "/intake/section/save?section=" + encodeURIComponent(sectionId)
      + "&note_id=" + encodeURIComponent(NOTE_UUID);
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); });
  }

  function autoSaveAllSections() {
    // Persist every flat + multi section's current DOM state before commit
    // so a section the MA never explicitly Saved still shows its rows
    // (and gets a Mark-as-Reviewed if all rows are Confirm).
    var saves = [];
    FLAT_SECTIONS.forEach(function(sectionId) {
      var data = collectSection(sectionId);
      if (data && Object.keys(data).length > 0) {
        saves.push(saveSectionPayload(sectionId, data));
      }
    });
    MULTI_SECTIONS.forEach(function(sectionId) {
      var data = collectMultiSection(sectionId);
      // POST every multi-section unconditionally at commit time, even
      // when rows is empty. The 'Drop from draft' affordance removes a
      // row via removeChild without dispatching input/change events,
      // so a debounced auto-save never fires after a Drop — meaning
      // AttributeHub can still hold a row the MA explicitly cancelled.
      // The empty-rows POST clears the stale draft so the server-side
      // commit walks an empty row set and never originates the dropped
      // row. Cost: ~6 no-op POSTs per commit for sections the MA
      // never touched and that have no pre-fill (e.g. Family History
      // on a healthy patient). Worth it to avoid silently emitting
      // commands the user dropped.
      if (data) {
        saves.push(saveSectionPayload(sectionId, data));
      }
    });
    return Promise.all(saves);
  }

  function commit() {
    if (!NOTE_UUID) {
      setCommitStatus("Cannot commit - no note context", "error");
      return;
    }
    var btn = $("commit-btn");
    if (btn) btn.disabled = true;
    setCommitStatus("Saving…", "committing");
    // Cancel any debounce timers that haven't fired yet; the
    // autoSaveAllSections flush below takes a fresh snapshot of every
    // section's DOM and supersedes them, so the pending timers would
    // otherwise re-POST the same payload after commit lands.
    Object.keys(_autoSaveTimers).forEach(function(sid) {
      clearTimeout(_autoSaveTimers[sid]);
      delete _autoSaveTimers[sid];
    });

    autoSaveAllSections()
    .then(function() {
      setCommitStatus("Committing…", "committing");
      return fetch(API + "/intake/commit?note_id=" + encodeURIComponent(NOTE_UUID), {
        method: "POST",
        credentials: "same-origin",
      });
    })
    .then(function(r) { return r.json().then(function(j) { return [r.ok, j]; }); })
    .then(function(arr) {
      var ok = arr[0]; var j = arr[1];
      if (ok && j && j.success) {
        var summary = j.effects || {};
        var n = (summary.originate || 0) + (summary.edit || 0);
        var msg = n > 0
          ? "Committed " + n + " command" + (n === 1 ? "" : "s") + " — refresh the page to see them on the Commands tab."
          : "Committed (no changes)";
        setCommitStatus(msg, "committed");
        // Note on rendering: plugin-emitted ORIGINATE_*_COMMAND effects
        // persist as staged Command rows in the DB but Canvas's home-app
        // doesn't always live-refresh the Commands tab when those rows
        // are emitted from a plugin (vs the chart sidebar's UI button,
        // which has integrated DOM injection). Auto-reloading the top
        // frame caused navigation mismatches because the patient URL
        // doesn't include a note id — Canvas could load a different
        // note. Clearer to instruct the user to refresh manually.
      } else {
        setCommitStatus("Commit failed: " + ((j && j.error) || "unknown"), "error");
        console.error("ic: commit error", j);
      }
    })
    .catch(function(err) {
      setCommitStatus("Commit failed", "error");
      console.error("ic: commit fetch failed", err);
    })
    .then(function() { if (btn) btn.disabled = false; });
  }

  document.querySelectorAll('[data-save-section]').forEach(function(btn) {
    btn.addEventListener("click", function() {
      saveSection(btn.getAttribute("data-save-section"));
    });
  });
  var commitBtn = $("commit-btn");
  if (commitBtn) commitBtn.addEventListener("click", commit);

  // Wire the Vitals Save Draft gate to each numeric input. Initial call sets
  // the disabled state from the server-rendered (empty) form.
  (function wireVitalsGate() {
    var form = $("form-vitals");
    if (!form) return;
    var inputs = form.querySelectorAll("input[type=number]");
    for (var i = 0; i < inputs.length; i++) {
      inputs[i].addEventListener("input", refreshVitalsGate);
    }
    refreshVitalsGate();
  })();

  // Per-section + Add to draft gate. Disabled until the section's required
  // field (data-required-field attr on the add-template) has a non-empty
  // value. Picked search results dispatch input/change manually in pick()
  // above so this fires for icd10_code / allergen_code / fdb_code too.
  function refreshAddGate(sectionId) {
    var section = document.querySelector('[data-multi-section="' + sectionId + '"]');
    if (!section) return;
    var template = section.querySelector('[data-add-template]');
    var btn = section.querySelector('[data-add-row="' + sectionId + '"]');
    var hint = template ? template.querySelector('[data-add-hint]') : null;
    if (!template || !btn) return;
    var requiredField = template.getAttribute("data-required-field") || "";
    if (!requiredField) {
      btn.disabled = false;
      if (hint) hint.hidden = true;
      return;
    }
    var input = template.querySelector('[data-row-field="' + requiredField + '"]');
    var hasValue = !!(input && input.value && input.value.trim() !== "");
    btn.disabled = !hasValue;
    if (hint) hint.hidden = hasValue;
  }

  (function wireAddGates() {
    var sectionIds = [
      "problems", "allergies", "medications",
      "medical_history", "surgical_history", "family_history",
    ];
    sectionIds.forEach(function(sectionId) {
      var section = document.querySelector('[data-multi-section="' + sectionId + '"]');
      if (!section) return;
      var template = section.querySelector('[data-add-template]');
      if (!template) return;
      var inputs = template.querySelectorAll('[data-row-field]');
      for (var i = 0; i < inputs.length; i++) {
        inputs[i].addEventListener("input", function() { refreshAddGate(sectionId); });
        inputs[i].addEventListener("change", function() { refreshAddGate(sectionId); });
      }
      refreshAddGate(sectionId);
    });
  })();

  // ---- Debounced auto-save ---------------------------------------------
  // Save Draft buttons were removed; every input/change event in any
  // section's form fires a debounced save (~600 ms). The same
  // ``/intake/section/save`` endpoint the old buttons hit is reused — only
  // the trigger changes. Empty payloads short-circuit so an untouched
  // section never POSTs.
  var _autoSaveTimers = {};

  function _resolveSectionId(target) {
    if (!target || !target.closest) return null;
    var multi = target.closest('[data-multi-section]');
    if (multi) return multi.getAttribute('data-multi-section');
    var flat = target.closest('[data-section]');
    if (flat) return flat.getAttribute('data-section');
    // Vitals lives in <div id="section-vitals"><form id="form-vitals">…
    // and has neither data-multi-section nor data-section.
    var vitalsRoot = target.closest('#section-vitals, #form-vitals');
    if (vitalsRoot) return 'vitals';
    return null;
  }

  function _runAutoSave(sectionId) {
    if (!NOTE_UUID || !sectionId) return;
    if (FLAT_SECTIONS.indexOf(sectionId) >= 0) {
      var data = collectSection(sectionId);
      if (!data || Object.keys(data).length === 0) return;
      setStatus(sectionId, "Saving…", "saving");
      saveSectionPayload(sectionId, data)
        .then(function(arr) {
          var ok = arr[0], j = arr[1];
          setStatus(
            sectionId,
            (ok && j && j.success) ? "Saved" : "Save failed",
            (ok && j && j.success) ? "saved" : "error",
          );
        })
        .catch(function(err) {
          setStatus(sectionId, "Save failed", "error");
          console.error("ic: auto-save failed", sectionId, err);
        });
    } else if (MULTI_SECTIONS.indexOf(sectionId) >= 0) {
      var multi = collectMultiSection(sectionId);
      if (!multi || !multi.rows || Object.keys(multi.rows).length === 0) {
        // No rows yet — skip the no-op POST so an empty saved blob doesn't
        // overwrite anything legitimate.
        return;
      }
      setStatus(sectionId, "Saving…", "saving");
      saveSectionPayload(sectionId, multi)
        .then(function(arr) {
          var ok = arr[0], j = arr[1];
          setStatus(
            sectionId,
            (ok && j && j.success) ? "Saved" : "Save failed",
            (ok && j && j.success) ? "saved" : "error",
          );
        })
        .catch(function(err) {
          setStatus(sectionId, "Save failed", "error");
          console.error("ic: auto-save failed", sectionId, err);
        });
    }
  }

  function scheduleAutoSave(sectionId) {
    if (!sectionId) return;
    if (_autoSaveTimers[sectionId]) clearTimeout(_autoSaveTimers[sectionId]);
    _autoSaveTimers[sectionId] = setTimeout(function() {
      delete _autoSaveTimers[sectionId];
      _runAutoSave(sectionId);
    }, AUTO_SAVE_DEBOUNCE_MS);
  }

  document.body.addEventListener('input', function(ev) {
    scheduleAutoSave(_resolveSectionId(ev.target));
  });
  document.body.addEventListener('change', function(ev) {
    scheduleAutoSave(_resolveSectionId(ev.target));
  });
  // ----------------------------------------------------------------------

  loadFormState();
})();
