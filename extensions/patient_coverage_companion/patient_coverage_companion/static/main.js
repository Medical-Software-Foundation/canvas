(function () {
  "use strict";

  const root = document.getElementById("root");
  const apiBase = ""; // same origin, served from /plugin-io/api/patient_coverage_companion/app

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
    pendingKeys: { front: null, back: null },
  };

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
    const frontInput = document.getElementById("card-front-input");
    const backInput = document.getElementById("card-back-input");
    const front = frontInput && frontInput.files && frontInput.files[0];
    const back = backInput && backInput.files && backInput.files[0];
    if (!front && !back) return { ok: true, body: { front_key: null, back_key: null } };

    const form = new FormData();
    if (front) form.append("front", front);
    if (back) form.append("back", back);

    state.uploading = true;
    render();
    const r = await http("POST", "/cards/upload", { body: form });
    state.uploading = false;
    return r;
  }

  function showLocalPreview(side, fileInput) {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      state.cardPreviews[side] = e.target.result;
      render();
    };
    reader.readAsDataURL(file);
  }

  // ---- save flows ----

  function collectFormFields() {
    const id = (name) => document.getElementById(name);
    const v = (name) => (id(name) ? id(name).value : "");
    const fields = {
      issuer_id: v("f-issuer-id"),
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

  async function save() {
    state.saving = true;
    state.banner = null;
    render();

    // Step 1: upload card images (if any) and stash the returned keys
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
    }

    // Step 2: POST the coverage data
    const fields = collectFormFields();
    const isUpdate = state.editing && state.editing.id;
    const path = isUpdate ? "/coverage/" + encodeURIComponent(state.editing.id) : "/coverage";
    const body = isUpdate ? fields : { patient_id: state.patientId, ...fields };
    const r = await http("POST", path, { body });
    state.saving = false;
    if (!r.ok) {
      state.banner = { type: "error", text: (r.body && r.body.error) || "Save failed." };
      render();
      return;
    }
    state.banner = { type: "success", text: "Saved." };
    state.pendingKeys = { front: null, back: null };
    state.cardPreviews = { front: null, back: null };
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
        else if (k === "onclick") el.addEventListener("click", v);
        else if (k === "onchange") el.addEventListener("change", v);
        else if (k === "value") el.value = v == null ? "" : v;
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
    return makeElement("div", { className: "field" }, [
      makeElement("label", { for: id }, opts.label),
      input,
    ]);
  }

  function renderForm() {
    const editing = state.editing || {};
    const isUpdate = !!editing.id;

    const fields = [
      renderField({
        id: "issuer-id",
        label: "Payer ID (Transactor UUID)",
        value: editing.issuer_id || "",
      }),
      renderField({
        id: "rank",
        label: "Rank",
        type: "select",
        options: state.options.rank,
        value: editing.coverage_rank || 1,
      }),
      renderField({
        id: "plan-type",
        label: "Plan type",
        type: "select",
        options: state.options.plan_type,
        value: editing.plan_type || "commercial",
      }),
      renderField({
        id: "id-number",
        label: "Member ID",
        value: editing.id_number || "",
      }),
      renderField({
        id: "plan",
        label: "Plan name",
        value: editing.plan || "",
      }),
      renderField({
        id: "group",
        label: "Group",
        value: editing.group || "",
      }),
      renderField({
        id: "employer",
        label: "Employer",
        value: editing.employer || "",
      }),
      renderField({
        id: "relationship",
        label: "Patient relationship to subscriber",
        type: "select",
        options: state.options.relationship,
        value: editing.patient_relationship_to_subscriber || "18",
      }),
      renderField({
        id: "subscriber-id",
        label: "Subscriber identifier",
        value: editing.subscriber_identifier || "",
      }),
      renderField({
        id: "start",
        label: "Coverage start date",
        type: "date",
        value: editing.coverage_start_date || "",
      }),
      renderField({
        id: "end",
        label: "Coverage end date",
        type: "date",
        value: editing.coverage_end_date || "",
      }),
      renderField({
        id: "comments",
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
      onchange: (e) => showLocalPreview(side, e.target),
    });
    return makeElement("div", { className: "card-photo" }, [
      makeElement("label", null, side === "front" ? "Front of card" : "Back of card"),
      preview,
      input,
    ]);
  }

  function onEdit(coverage) {
    state.editing = coverage; // null => new
    state.view = "edit";
    state.banner = null;
    state.cardPreviews = { front: null, back: null };
    state.pendingKeys = { front: null, back: null };
    render();
  }

  function cancelEdit() {
    state.view = "list";
    state.editing = null;
    state.cardPreviews = { front: null, back: null };
    state.pendingKeys = { front: null, back: null };
    render();
  }

  function render() {
    root.innerHTML = "";
    const banner = renderBanner();
    if (banner) root.appendChild(banner);
    const body = state.view === "list" ? renderList() : renderForm();
    for (const node of [].concat(body)) root.appendChild(node);
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
