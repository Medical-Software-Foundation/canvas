(function () {
  "use strict";

  const root = document.getElementById("root");
  // The iframe is loaded from /plugin-io/api/<plugin>/app/ (with trailing
  // slash). Build the API base from that so every fetch lands on the
  // plugin's own SimpleAPI mount instead of the server root.
  const apiBase = window.location.pathname.replace(/\/+$/, "");

  const state = {
    patientId: null,
    coverages: [],
    options: { relationship: [], plan_type: [], rank: [] },
    view: "list", // "list" | "edit"
    editing: null, // coverage being edited, or null for "new"
    banner: null,
    saving: false,
    uploading: false,
    cardPreviews: { front: null, back: null },
    cardFiles: { front: null, back: null }, // hold File refs so we don't lose them on re-render
    pendingKeys: { front: null, back: null },
    fieldErrors: {}, // { field_name: "message" } for inline display
    payer: { id: "", name: "", query: "", results: [], open: false }, // search box state
  };

  let payerSearchTimer = null;
  let payerSearchSeq = 0; // drop out-of-order responses
  const PAYER_DEBOUNCE_MS = 120;

  let messagePort = null;
  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "INIT_CHANNEL" && event.ports && event.ports[0]) {
      messagePort = event.ports[0];
      messagePort.start();
    }
  });

  function getPatientId() {
    return new URLSearchParams(window.location.search).get("patient_id") || "";
  }

  async function http(method, path, opts) {
    const init = { method, credentials: "include", ...(opts || {}) };
    if (init.body && typeof init.body === "object" && !(init.body instanceof FormData)) {
      init.body = JSON.stringify(init.body);
      init.headers = { ...(init.headers || {}), "Content-Type": "application/json" };
    }
    const resp = await fetch(apiBase + path, init);
    let payload;
    try {
      payload = await resp.json();
    } catch (_) {
      payload = null;
    }
    return { ok: resp.ok, status: resp.status, body: payload };
  }

  async function fetchData() {
    const r = await http("GET", "/data.json?patient_id=" + encodeURIComponent(state.patientId));
    if (!r.ok) {
      state.banner = { type: "error", text: (r.body && r.body.error) || "Could not load coverages." };
      return;
    }
    state.coverages = r.body.coverages || [];
    state.options = r.body.options || state.options;
  }

  // ---- card image upload ----

  async function uploadCards() {
    const front = state.cardFiles.front;
    const back = state.cardFiles.back;
    if (!front && !back) return { ok: true, body: { front_key: null, back_key: null } };

    const form = new FormData();
    if (front) form.append("front", front);
    if (back) form.append("back", back);

    state.uploading = true;
    const r = await http("POST", "/cards/upload", { body: form });
    state.uploading = false;
    return r;
  }

  function onCardFileSelected(side, fileInput) {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    // Hold onto the File object in state — a subsequent render would
    // rebuild the <input type="file"> element and wipe its .files list,
    // losing the user's selection.
    state.cardFiles[side] = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      state.cardPreviews[side] = e.target.result;
      updateCardPreviewOnly(side);
    };
    reader.readAsDataURL(file);
  }

  function updateCardPreviewOnly(side) {
    // Surgically swap just the preview thumbnail; don't rebuild the form
    // (which would wipe the file input's selection and break the upload).
    const container = document.querySelector('.card-photo[data-side="' + side + '"]');
    if (!container) return;
    const preview = container.querySelector(".preview");
    if (!preview) return;
    preview.innerHTML = "";
    const src = state.cardPreviews[side];
    if (src) {
      const img = document.createElement("img");
      img.src = src;
      img.alt = side + " card";
      preview.appendChild(img);
    } else {
      preview.appendChild(document.createTextNode("No photo"));
    }
  }

  // ---- payer search ----

  async function searchPayers(q, seq) {
    const r = await http("GET", "/payers/search?q=" + encodeURIComponent(q));
    if (seq !== payerSearchSeq) return; // a newer query already fired
    if (!r.ok) return;
    state.payer.results = (r.body && r.body.results) || [];
    state.payer.open = true;
    updatePayerDropdownOnly();
  }

  function onPayerQueryChange(value) {
    state.payer.query = value;
    // Typing anything invalidates a prior selection. The user has to pick
    // from the dropdown again for issuer_id to be set.
    state.payer.id = "";
    state.payer.name = "";
    if (state.fieldErrors.issuer_id) {
      state.fieldErrors.issuer_id = null;
      const fieldEl = document.querySelector(".payer-search");
      if (fieldEl) fieldEl.classList.remove("field-has-error");
      const errEl = document.querySelector(".payer-search .field-error");
      if (errEl) errEl.remove();
    }
    clearTimeout(payerSearchTimer);
    const seq = ++payerSearchSeq;
    if (value.length < 2) {
      state.payer.results = [];
      state.payer.open = false;
      updatePayerDropdownOnly();
      return;
    }
    payerSearchTimer = setTimeout(() => searchPayers(value, seq), PAYER_DEBOUNCE_MS);
  }

  function updatePayerDropdownOnly() {
    // Replace just the dropdown DOM in place, leaving the input untouched.
    // A full render() would steal focus and force the OS keyboard to redraw,
    // which on mobile manifests as a long visible lag between keystrokes
    // and the request firing.
    const container = document.querySelector(".payer-search");
    if (!container) return;
    const old = container.querySelector(".payer-results");
    if (old) old.remove();
    if (!state.payer.open || !state.payer.results.length) return;
    const dropdown = makeElement(
      "div",
      { className: "payer-results" },
      state.payer.results.map((r) =>
        makeElement(
          "div",
          { className: "payer-result", onclick: () => selectPayer(r) },
          r.payer_id ? r.name + " · " + r.payer_id : r.name
        )
      )
    );
    // Insert after the input.
    const input = container.querySelector("#payer-search-input");
    if (input && input.parentNode) {
      input.parentNode.insertBefore(dropdown, input.nextSibling);
    } else {
      container.appendChild(dropdown);
    }
  }

  function selectPayer(result) {
    state.payer.id = result.id;
    state.payer.name = result.name;
    state.payer.query = result.name;
    state.payer.results = [];
    state.payer.open = false;
    state.fieldErrors.issuer_id = null;
    render();
  }

  // ---- save flows ----

  function collectFormFields() {
    const id = (name) => document.getElementById(name);
    const v = (name) => (id(name) ? id(name).value : "");
    const fields = {
      issuer_id: state.payer.id, // from the payer search component
      coverage_rank: v("f-rank"),
      plan_type: v("f-plan-type"),
      id_number: v("f-id-number"),
      plan: v("f-plan"),
      group: v("f-group"),
      employer: v("f-employer"),
      coverage_start_date: v("f-start"),
      coverage_end_date: v("f-end"),
      patient_relationship_to_subscriber: v("f-relationship"),
      subscriber_identifier: v("f-subscriber-id"),
      comments: v("f-comments"),
    };
    if (state.pendingKeys.front) fields.card_image_front_upload_key = state.pendingKeys.front;
    if (state.pendingKeys.back) fields.card_image_back_upload_key = state.pendingKeys.back;
    return fields;
  }

  // Required only on create; on update, partial payloads are fine.
  const REQUIRED_FIELDS_FOR_CREATE = {
    issuer_id: "Payer is required.",
    id_number: "Member ID is required.",
  };

  function validateCreateFields(fields) {
    const errors = {};
    for (const [name, msg] of Object.entries(REQUIRED_FIELDS_FOR_CREATE)) {
      if (!fields[name]) errors[name] = msg;
    }
    if (
      fields.coverage_start_date &&
      fields.coverage_end_date &&
      fields.coverage_end_date < fields.coverage_start_date
    ) {
      errors.coverage_end_date = "End date must be on or after start date.";
    }
    return errors;
  }

  async function save() {
    state.banner = null;
    state.fieldErrors = {};
    const fields = collectFormFields();
    // Capture the user's typed values into state.editing so any re-render
    // during save (showing "Saving…", inline errors, etc.) doesn't blank the
    // form — text inputs are uncontrolled and would otherwise lose what the
    // user typed when the DOM is rebuilt.
    state.editing = Object.assign({}, state.editing || {}, fields);
    const isUpdate = state.editing && state.editing.id;

    // Step 1: client-side validation for create — surface required-field
    // errors inline before issuing any network requests.
    if (!isUpdate) {
      const errors = validateCreateFields(fields);
      if (Object.keys(errors).length) {
        state.fieldErrors = errors;
        state.banner = { type: "error", text: "Please fix the highlighted fields." };
        render();
        return;
      }
    }

    state.saving = true;
    render();

    // Step 2: upload card images (if any) and stash the returned keys
    const up = await uploadCards();
    if (!up.ok) {
      state.saving = false;
      state.banner = {
        type: "error",
        text: (up.body && up.body.error) || "Could not upload card images.",
      };
      render();
      return;
    }
    if (up.body) {
      state.pendingKeys.front = up.body.front_key || state.pendingKeys.front;
      state.pendingKeys.back = up.body.back_key || state.pendingKeys.back;
      if (state.pendingKeys.front) fields.card_image_front_upload_key = state.pendingKeys.front;
      if (state.pendingKeys.back) fields.card_image_back_upload_key = state.pendingKeys.back;
    }

    // Step 3: POST the coverage data
    const path = isUpdate ? "/coverage/" + encodeURIComponent(state.editing.id) : "/coverage";
    const body = isUpdate ? fields : { patient_id: state.patientId, ...fields };
    const r = await http("POST", path, { body });
    state.saving = false;
    if (!r.ok) {
      // Server returned per-field errors -> show them inline. Otherwise
      // fall back to the top-level error message or a generic notice.
      if (r.body && r.body.field_errors) {
        state.fieldErrors = r.body.field_errors;
      }
      state.banner = {
        type: "error",
        text:
          (r.body && r.body.error) ||
          (r.status === 0 ? "Network error — please retry." : "Save failed."),
      };
      render();
      return;
    }
    state.banner = { type: "success", text: "Saved." };
    state.pendingKeys = { front: null, back: null };
    state.cardPreviews = { front: null, back: null };
    state.fieldErrors = {};
    state.payer = { id: "", name: "", query: "", results: [], open: false };
    await fetchData();
    state.view = "list";
    state.editing = null;
    render();
  }

  async function remove(coverage) {
    if (!confirm("Remove this coverage?")) return;
    const r = await http("POST", "/coverage/" + encodeURIComponent(coverage.id) + "/remove");
    state.banner = r.ok
      ? { type: "success", text: "Removed." }
      : { type: "error", text: (r.body && r.body.error) || "Remove failed." };
    await fetchData();
    render();
  }

  async function expire(coverage) {
    const today = new Date().toISOString().slice(0, 10);
    const date = prompt("Expire coverage on (YYYY-MM-DD):", today);
    if (!date) return;
    const r = await http("POST", "/coverage/" + encodeURIComponent(coverage.id) + "/expire", {
      body: { coverage_end_date: date },
    });
    state.banner = r.ok
      ? { type: "success", text: "Expired." }
      : { type: "error", text: (r.body && r.body.error) || "Expire failed." };
    await fetchData();
    render();
  }

  // ---- rendering ----

  function makeElement(tag, attrs, children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "className") el.className = v;
        else if (k.startsWith("on") && typeof v === "function") {
          // Any on* handler: attach as a real event listener so input/keyup/
          // focus etc. actually fire. setAttribute with a function value is a
          // silent no-op for event registration.
          el.addEventListener(k.slice(2).toLowerCase(), v);
        } else if (k === "value") el.value = v == null ? "" : v;
        else if (v != null) el.setAttribute(k, v);
      }
    }
    if (children != null) {
      for (const child of [].concat(children)) {
        if (child == null) continue;
        el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
      }
    }
    return el;
  }

  function renderBanner() {
    if (!state.banner) return null;
    return makeElement("div", { className: "banner " + state.banner.type }, state.banner.text);
  }

  function renderList() {
    if (!state.coverages.length) {
      return [
        makeElement("div", { className: "empty" }, "No coverages on file."),
        makeElement(
          "div",
          { className: "form-actions" },
          [
            makeElement(
              "button",
              { className: "primary", onclick: () => onEdit(null) },
              "Add coverage"
            ),
          ]
        ),
      ];
    }
    const list = makeElement("ul", { className: "coverage-list" });
    for (const c of state.coverages) {
      const card = makeElement("li", { className: "coverage-card" }, [
        makeElement("div", { className: "coverage-card-head" }, [
          makeElement("div", { className: "coverage-card-title" }, c.issuer_name || "(unknown payer)"),
          makeElement(
            "div",
            { className: "coverage-card-meta" },
            "Rank " + c.coverage_rank + " · " + (c.plan_type || "") + " · " + (c.id_number || "")
          ),
        ]),
        makeElement(
          "div",
          { className: "coverage-card-actions" },
          [
            makeElement("button", { onclick: () => onEdit(c) }, "Edit"),
            makeElement("button", { onclick: () => expire(c) }, "Expire"),
            makeElement("button", { className: "danger", onclick: () => remove(c) }, "Remove"),
          ]
        ),
      ]);
      list.appendChild(card);
    }
    return [
      list,
      makeElement(
        "div",
        { className: "form-actions" },
        [
          makeElement(
            "button",
            { className: "primary", onclick: () => onEdit(null) },
            "Add coverage"
          ),
        ]
      ),
    ];
  }

  function renderField(opts) {
    const id = "f-" + opts.id;
    const fieldName = opts.fieldName || opts.id.replace(/-/g, "_");
    const errorMsg = state.fieldErrors[fieldName];
    let input;
    if (opts.type === "select") {
      input = makeElement(
        "select",
        { id, value: opts.value || "" },
        (opts.options || []).map((o) =>
          makeElement(
            "option",
            { value: o.value },
            o.label
          )
        )
      );
      // <select value=...> alone isn't enough — set after children added
      input.value = opts.value || "";
    } else if (opts.type === "textarea") {
      input = makeElement("textarea", { id, rows: 3 });
      input.value = opts.value || "";
    } else {
      input = makeElement("input", { id, type: opts.type || "text", value: opts.value || "" });
    }
    return makeElement(
      "div",
      { className: errorMsg ? "field field-has-error" : "field" },
      [
        makeElement("label", { for: id }, opts.label),
        input,
        errorMsg ? makeElement("div", { className: "field-error" }, errorMsg) : null,
      ]
    );
  }

  function renderPayerSearch(editing) {
    const errorMsg = state.fieldErrors.issuer_id;

    // The visible input shows whatever the user has typed or the selected
    // payer's name. The hidden state.payer.id is what we submit.
    const visibleValue =
      state.payer.query || state.payer.name || editing.issuer_name || "";
    if (!state.payer.id && !state.payer.query && editing.issuer_id) {
      // First render after entering edit mode: seed the search from the
      // existing coverage's payer so the field shows "Aetna" not blank.
      state.payer.id = editing.issuer_id;
      state.payer.name = editing.issuer_name || "";
    }

    const input = makeElement("input", {
      id: "payer-search-input",
      type: "text",
      autocomplete: "off",
      placeholder: "Type to search payers…",
      value: visibleValue,
      // 'input' fires on every character change (more reliable than keyup
      // on mobile with IME / autocorrect); avoid re-rendering the whole form
      // on each keystroke.
      oninput: (e) => onPayerQueryChange(e.target.value),
      onfocus: () => {
        if (state.payer.results.length) {
          state.payer.open = true;
          updatePayerDropdownOnly();
        }
      },
    });

    const dropdown =
      state.payer.open && state.payer.results.length
        ? makeElement(
            "div",
            { className: "payer-results" },
            state.payer.results.map((r) =>
              makeElement(
                "div",
                {
                  className: "payer-result",
                  onclick: () => selectPayer(r),
                },
                r.payer_id ? r.name + " · " + r.payer_id : r.name
              )
            )
          )
        : null;

    const selectedTag = state.payer.id
      ? makeElement(
          "div",
          { className: "payer-selected" },
          "Selected: " + (state.payer.name || state.payer.id)
        )
      : null;

    return makeElement(
      "div",
      { className: errorMsg ? "field field-has-error payer-search" : "field payer-search" },
      [
        makeElement("label", { for: "payer-search-input" }, "Payer"),
        input,
        dropdown,
        selectedTag,
        errorMsg ? makeElement("div", { className: "field-error" }, errorMsg) : null,
      ]
    );
  }

  function renderForm() {
    const editing = state.editing || {};
    const isUpdate = !!editing.id;

    const fields = [
      renderPayerSearch(editing),
      renderField({
        id: "rank",
        fieldName: "coverage_rank",
        label: "Rank",
        type: "select",
        options: state.options.rank,
        value: editing.coverage_rank || 1,
      }),
      renderField({
        id: "plan-type",
        fieldName: "plan_type",
        label: "Plan type",
        type: "select",
        options: state.options.plan_type,
        value: editing.plan_type || "commercial",
      }),
      renderField({
        id: "id-number",
        fieldName: "id_number",
        label: "Member ID",
        value: editing.id_number || "",
      }),
      renderField({
        id: "plan",
        fieldName: "plan",
        label: "Plan name",
        value: editing.plan || "",
      }),
      renderField({
        id: "group",
        fieldName: "group",
        label: "Group",
        value: editing.group || "",
      }),
      renderField({
        id: "employer",
        fieldName: "employer",
        label: "Employer",
        value: editing.employer || "",
      }),
      renderField({
        id: "relationship",
        fieldName: "patient_relationship_to_subscriber",
        label: "Patient relationship to subscriber",
        type: "select",
        options: state.options.relationship,
        value: editing.patient_relationship_to_subscriber || "18",
      }),
      renderField({
        id: "subscriber-id",
        fieldName: "subscriber_identifier",
        label: "Subscriber identifier",
        value: editing.subscriber_identifier || "",
      }),
      renderField({
        id: "start",
        fieldName: "coverage_start_date",
        label: "Coverage start date",
        type: "date",
        value: editing.coverage_start_date || "",
      }),
      renderField({
        id: "end",
        fieldName: "coverage_end_date",
        label: "Coverage end date",
        type: "date",
        value: editing.coverage_end_date || "",
      }),
      renderField({
        id: "comments",
        fieldName: "comments",
        label: "Comments",
        type: "textarea",
        value: editing.comments || "",
      }),
    ];

    const cardPhotos = makeElement("div", { className: "card-photos" }, [
      renderCardPhoto("front", editing.card_image_front_url),
      renderCardPhoto("back", editing.card_image_back_url),
    ]);

    const actions = makeElement("div", { className: "form-actions" }, [
      makeElement("button", { onclick: cancelEdit }, "Cancel"),
      makeElement(
        "button",
        { className: "primary", onclick: save, disabled: state.saving || state.uploading || null },
        state.saving ? "Saving…" : state.uploading ? "Uploading…" : isUpdate ? "Save changes" : "Create coverage"
      ),
    ]);

    return [
      makeElement("h1", null, isUpdate ? "Edit coverage" : "New coverage"),
      makeElement("h2", null, "Card photos"),
      cardPhotos,
      makeElement("h2", null, "Coverage details"),
      makeElement("div", { className: "form-grid" }, fields),
      actions,
    ];
  }

  function renderCardPhoto(side, existingUrl) {
    const previewSrc = state.cardPreviews[side] || existingUrl || null;
    const preview = makeElement(
      "div",
      { className: "preview" },
      previewSrc ? makeElement("img", { src: previewSrc, alt: side + " card" }) : "No photo"
    );
    const input = makeElement("input", {
      id: "card-" + side + "-input",
      type: "file",
      accept: "image/*",
      capture: "environment",
      onchange: (e) => onCardFileSelected(side, e.target),
    });
    return makeElement(
      "div",
      { className: "card-photo", "data-side": side },
      [
        makeElement("label", null, side === "front" ? "Front of card" : "Back of card"),
        preview,
        input,
      ]
    );
  }

  function onEdit(coverage) {
    state.editing = coverage; // null => new
    state.view = "edit";
    state.banner = null;
    state.cardPreviews = { front: null, back: null };
    state.cardFiles = { front: null, back: null };
    state.pendingKeys = { front: null, back: null };
    state.fieldErrors = {};
    // Seed the payer search from the existing coverage (if any). The form
    // renderer fills in the visible name on its first paint.
    state.payer = {
      id: (coverage && coverage.issuer_id) || "",
      name: (coverage && coverage.issuer_name) || "",
      query: "",
      results: [],
      open: false,
    };
    render();
  }

  function cancelEdit() {
    state.view = "list";
    state.editing = null;
    state.cardPreviews = { front: null, back: null };
    state.cardFiles = { front: null, back: null };
    state.pendingKeys = { front: null, back: null };
    state.fieldErrors = {};
    state.payer = { id: "", name: "", query: "", results: [], open: false };
    render();
  }

  function render(opts) {
    opts = opts || {};
    // Capture focus + cursor state so a typing-driven re-render (payer
    // search) doesn't kick the user out of the input mid-keystroke.
    const focusedId =
      opts.preserveFocus ||
      (document.activeElement && document.activeElement.id) ||
      null;
    let cursorPos = null;
    if (focusedId && document.activeElement && "selectionStart" in document.activeElement) {
      cursorPos = document.activeElement.selectionStart;
    }

    root.innerHTML = "";
    const banner = renderBanner();
    if (banner) root.appendChild(banner);
    const body = state.view === "list" ? renderList() : renderForm();
    for (const node of [].concat(body)) root.appendChild(node);

    if (focusedId) {
      const next = document.getElementById(focusedId);
      if (next) {
        next.focus();
        if (cursorPos != null && "setSelectionRange" in next) {
          try {
            next.setSelectionRange(cursorPos, cursorPos);
          } catch (_) {
            /* not all input types support selectionRange */
          }
        }
      }
    }
  }

  // ---- boot ----

  state.patientId = getPatientId();
  if (!state.patientId) {
    state.banner = { type: "error", text: "Missing patient_id in URL." };
    render();
    return;
  }
  fetchData().then(render);
})();
