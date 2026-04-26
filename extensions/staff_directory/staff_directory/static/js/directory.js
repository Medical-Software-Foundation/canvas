(function () {
  "use strict";

  // ---------- Bootstrap ----------

  const bootNode = document.getElementById("dp-boot");
  const boot = JSON.parse(bootNode.textContent);
  const state = {
    staff: boot.staff || [],
    filteredStaff: boot.staff || [],
    isAdmin: !!boot.is_admin,
    apiBase: boot.api_base,
    nuccBase: boot.nucc_base,
    selectedDbid: null,
    currentProfile: null,
    searchTerm: "",
    expiringOnly: false,
  };

  // ---------- DOM helpers ----------

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs, children) => {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k === "html") node.innerHTML = v;
        else if (k.startsWith("on") && typeof v === "function") {
          node.addEventListener(k.slice(2), v);
        } else if (v === true) node.setAttribute(k, "");
        else if (v === false || v == null) continue;
        else node.setAttribute(k, v);
      }
    }
    if (children) {
      for (const child of [].concat(children)) {
        if (child == null) continue;
        if (typeof child === "string") node.appendChild(document.createTextNode(child));
        else node.appendChild(child);
      }
    }
    return node;
  };

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

  // ---------- HTTP ----------

  async function apiRequest(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = { raw: text }; }
    if (!res.ok) {
      const msg = (data && data.error) || "Request failed (" + res.status + ")";
      throw new Error(msg);
    }
    return data;
  }

  // ---------- Toast ----------

  let toastTimer;
  function toast(message, kind) {
    const existing = document.querySelector(".dp-toast");
    if (existing) existing.remove();
    const t = el("div", { class: "dp-toast " + (kind === "error" ? "is-error" : "is-success") }, message);
    document.body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.remove(), 3500);
  }

  // ---------- List rendering ----------

  function renderList() {
    const list = $("#dp-staff-list");
    list.innerHTML = "";

    const term = state.searchTerm.toLowerCase();
    state.filteredStaff = state.staff.filter((s) => {
      if (state.expiringOnly && !s.has_expiring_certification) return false;
      if (!term) return true;
      const hay = [
        s.full_name,
        s.role,
        (s.primary_specialty && s.primary_specialty.display_name) || "",
        (s.specialty_codes || []).join(" "),
      ].join(" ").toLowerCase();
      return hay.includes(term);
    });

    $("#dp-list-count").textContent =
      state.filteredStaff.length + " of " + state.staff.length + " staff";

    for (const s of state.filteredStaff) {
      const item = el("li", {
        class: "dp-staff-item" + (state.selectedDbid === s.dbid ? " is-active" : ""),
        "data-dbid": s.dbid,
        onclick: () => selectStaff(s.dbid),
      }, [
        el("div", { class: "dp-staff-name" }, s.full_name || "(no name)"),
        el("div", { class: "dp-staff-meta" },
          [
            s.role || "Staff",
            s.primary_specialty ? " · " + s.primary_specialty.display_name : "",
            s.has_expiring_certification ? " · expiring cert" : "",
          ].join("")
        ),
      ]);
      list.appendChild(item);
    }

    if (state.filteredStaff.length === 0) {
      list.appendChild(el("li", { class: "dp-entry-empty", style: "padding: 16px;" },
        "No staff match this filter."));
    }
  }

  async function selectStaff(dbid) {
    state.selectedDbid = dbid;
    renderList();
    const pane = $("#dp-detail-pane");
    pane.innerHTML = '<div class="dp-empty-state"><p>Loading profile…</p></div>';
    try {
      const profile = await apiRequest("GET", state.apiBase + "/staff/" + dbid + "/");
      state.currentProfile = profile;
      renderDetail();
    } catch (err) {
      pane.innerHTML = '<div class="dp-empty-state"><p>Could not load profile: '
        + escapeHtml(err.message) + "</p></div>";
    }
  }

  // ---------- Detail rendering ----------

  function renderDetail() {
    const pane = $("#dp-detail-pane");
    const p = state.currentProfile;
    pane.innerHTML = "";
    pane.appendChild(el("div", { class: "dp-detail-header" }, [
      el("div", null, [
        el("h2", null, p.full_name || "(no name)"),
        el("div", { class: "dp-detail-sub" },
          [p.role || "Staff", p.email ? " · " + p.email : ""].join("")),
      ]),
    ]));

    pane.appendChild(renderEducationSection(p));
    pane.appendChild(renderTrainingSection(p));
    pane.appendChild(renderSpecialtySection(p));
    pane.appendChild(renderCertificationSection(p));
  }

  // ---------- Sections ----------

  function sectionHeader(title, addLabel, onAdd) {
    const children = [el("h3", null, title)];
    if (state.isAdmin) {
      children.push(el("button", {
        class: "dp-btn dp-btn-small",
        onclick: onAdd,
      }, addLabel));
    }
    return el("div", { class: "dp-section-header" }, children);
  }

  function renderEducationSection(p) {
    const section = el("section", { class: "dp-section", "data-section": "education" });
    section.appendChild(sectionHeader("Education", "+ Add education",
      () => showForm(section, educationFormFields(), (values) =>
        createEntry("education", values))));
    const list = el("ul", { class: "dp-entries" });
    if (!p.educations.length) {
      list.appendChild(el("li", { class: "dp-entry-empty" }, "No education recorded."));
    }
    for (const entry of p.educations) {
      const title = [entry.degree, entry.field_of_study].filter(Boolean).join(" · ")
        || entry.institution;
      const subParts = [entry.institution];
      if (entry.graduation_year) subParts.push(String(entry.graduation_year));
      list.appendChild(renderEntryRow({
        section,
        entry,
        title,
        sub: subParts.filter(Boolean).join(" · "),
        notes: entry.notes,
        formFields: educationFormFields,
        updateFn: (values) => updateEntry("education", entry.id, values),
        deleteFn: () => deleteEntry("education", entry.id),
      }));
    }
    section.appendChild(list);
    return section;
  }

  function renderTrainingSection(p) {
    const section = el("section", { class: "dp-section", "data-section": "training" });
    section.appendChild(sectionHeader("Clinical training", "+ Add training",
      () => showForm(section, trainingFormFields(), (values) =>
        createEntry("training", values))));
    const list = el("ul", { class: "dp-entries" });
    if (!p.trainings.length) {
      list.appendChild(el("li", { class: "dp-entry-empty" }, "No training recorded."));
    }
    for (const entry of p.trainings) {
      const years = [];
      if (entry.start_year) years.push(entry.start_year);
      if (entry.end_year) years.push(entry.end_year);
      const yearSpan = years.length === 2 ? years.join("–") : years.join("");
      list.appendChild(renderEntryRow({
        section,
        entry,
        title: [entry.program_type, entry.specialty_area].filter(Boolean).join(" · "),
        sub: [entry.institution, yearSpan].filter(Boolean).join(" · "),
        notes: entry.notes,
        formFields: trainingFormFields,
        updateFn: (values) => updateEntry("training", entry.id, values),
        deleteFn: () => deleteEntry("training", entry.id),
      }));
    }
    section.appendChild(list);
    return section;
  }

  function renderSpecialtySection(p) {
    const section = el("section", { class: "dp-section", "data-section": "specialty" });
    section.appendChild(sectionHeader("Specialties", "+ Add specialty",
      () => showSpecialtyForm(section)));
    const list = el("ul", { class: "dp-entries" });
    if (!p.specialties.length) {
      list.appendChild(el("li", { class: "dp-entry-empty" }, "No specialties recorded."));
    }
    for (const entry of p.specialties) {
      const titleChildren = [entry.display_name];
      if (entry.is_primary) {
        titleChildren.push(el("span", { class: "dp-pill dp-pill-primary" }, "Primary"));
      }
      const menuItems = [];
      if (state.isAdmin && !entry.is_primary) {
        menuItems.push({
          label: "Make primary",
          onClick: () => setPrimarySpecialty(entry.id),
        });
      }
      if (state.isAdmin) {
        menuItems.push({
          label: "Remove",
          danger: true,
          onClick: () => confirmAndDelete("specialty", entry.id, entry.display_name),
        });
      }
      const row = el("li", { class: "dp-entry" }, [
        el("div", null, [
          el("div", { class: "dp-entry-title" }, titleChildren),
          el("div", { class: "dp-entry-sub" },
            (entry.code ? entry.code + " · " : "") + (entry.grouping || "")),
        ]),
        menuItems.length ? renderEntryMenu(menuItems) : null,
      ]);
      list.appendChild(row);
    }
    section.appendChild(list);
    return section;
  }

  function renderCertificationSection(p) {
    const section = el("section", { class: "dp-section", "data-section": "certification" });
    section.appendChild(sectionHeader("Board certifications", "+ Add certification",
      () => showForm(section, certificationFormFields(), (values) =>
        createEntry("certification", values))));
    const list = el("ul", { class: "dp-entries" });
    if (!p.certifications.length) {
      list.appendChild(el("li", { class: "dp-entry-empty" }, "No certifications recorded."));
    }
    for (const entry of p.certifications) {
      const pillClass = {
        expired: "dp-pill-expired",
        expiring_soon: "dp-pill-expiring",
        current: "dp-pill-current",
      }[entry.status] || null;
      const pillLabel = {
        expired: "Expired",
        expiring_soon: "Expiring soon",
        current: "Current",
      }[entry.status] || "Unknown date";
      const titleChildren = [
        entry.specialty || entry.board_name,
      ];
      if (pillClass) {
        titleChildren.push(el("span", { class: "dp-pill " + pillClass }, pillLabel));
      }
      const dateSpan = entry.expiration_date
        ? "Expires " + entry.expiration_date
        : "No expiration on file";
      list.appendChild(renderEntryRow({
        section,
        entry,
        title: titleChildren,
        sub: [entry.board_name, dateSpan].filter(Boolean).join(" · "),
        notes: entry.notes,
        formFields: certificationFormFields,
        updateFn: (values) => updateEntry("certification", entry.id, values),
        deleteFn: () => deleteEntry("certification", entry.id),
      }));
    }
    section.appendChild(list);
    return section;
  }

  // ---------- Shared entry row ----------

  function renderEntryRow({ section, entry, title, sub, notes, formFields, updateFn, deleteFn }) {
    const menuItems = [];
    if (state.isAdmin) {
      menuItems.push({
        label: "Edit",
        onClick: () => showForm(section, formFields(entry), updateFn),
      });
      menuItems.push({
        label: "Remove",
        danger: true,
        onClick: () => confirmAndDeleteEntry(deleteFn,
          typeof title === "string" ? title : (entry.institution || "")),
      });
    }
    const titleNode = el("div", { class: "dp-entry-title" });
    if (Array.isArray(title)) title.forEach((c) =>
      titleNode.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    else titleNode.appendChild(document.createTextNode(title || ""));

    const body = [
      titleNode,
      el("div", { class: "dp-entry-sub" }, sub || ""),
    ];
    if (notes) body.push(el("div", { class: "dp-entry-notes" }, notes));

    return el("li", { class: "dp-entry" }, [
      el("div", null, body),
      menuItems.length ? renderEntryMenu(menuItems) : null,
    ]);
  }

  // ---------- Row action dropdown ----------

  function closeAllEntryMenus(except) {
    document.querySelectorAll(".dp-entry-menu.is-open").forEach((m) => {
      if (m !== except) m.classList.remove("is-open");
    });
  }

  function renderEntryMenu(items) {
    const menu = el("div", { class: "dp-entry-menu" });
    const button = el("button", {
      type: "button",
      class: "dp-entry-menu-button",
      "aria-label": "Actions",
      "aria-haspopup": "true",
      onclick: (e) => {
        e.stopPropagation();
        const isOpen = menu.classList.contains("is-open");
        closeAllEntryMenus(menu);
        menu.classList.toggle("is-open", !isOpen);
      },
    }, "⋯");
    const itemsBox = el("div", { class: "dp-entry-menu-items", role: "menu" });
    for (const item of items) {
      itemsBox.appendChild(el("button", {
        type: "button",
        class: "dp-entry-menu-item" + (item.danger ? " is-danger" : ""),
        role: "menuitem",
        onclick: (e) => {
          e.stopPropagation();
          closeAllEntryMenus();
          item.onClick();
        },
      }, item.label));
    }
    menu.appendChild(button);
    menu.appendChild(itemsBox);
    return menu;
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".dp-entry-menu")) closeAllEntryMenus();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllEntryMenus();
  });

  // ---------- Form definitions ----------

  function educationFormFields(entry) {
    entry = entry || {};
    return [
      { key: "institution", label: "Institution", type: "text", value: entry.institution || "", required: true },
      { key: "degree", label: "Degree", type: "text", value: entry.degree || "", placeholder: "MD, DO, PhD, etc.", required: true },
      { key: "field_of_study", label: "Field of study", type: "text", value: entry.field_of_study || "" },
      { key: "graduation_year", label: "Graduation year", type: "number", value: entry.graduation_year || "", min: 1900, max: 2100 },
      { key: "notes", label: "Notes", type: "textarea", value: entry.notes || "" },
    ];
  }

  function trainingFormFields(entry) {
    entry = entry || {};
    return [
      { key: "institution", label: "Institution", type: "text", value: entry.institution || "", required: true },
      { key: "program_type", label: "Program type", type: "select", value: entry.program_type || "residency",
        options: [
          { value: "internship", label: "Internship" },
          { value: "residency", label: "Residency" },
          { value: "fellowship", label: "Fellowship" },
          { value: "other", label: "Other" },
        ] },
      { key: "specialty_area", label: "Specialty area", type: "text", value: entry.specialty_area || "" },
      { key: "start_year", label: "Start year", type: "number", value: entry.start_year || "", min: 1900, max: 2100 },
      { key: "end_year", label: "End year", type: "number", value: entry.end_year || "", min: 1900, max: 2100 },
      { key: "notes", label: "Notes", type: "textarea", value: entry.notes || "" },
    ];
  }

  function certificationFormFields(entry) {
    entry = entry || {};
    return [
      { key: "board_name", label: "Board", type: "text", value: entry.board_name || "", required: true,
        placeholder: "American Board of Internal Medicine" },
      { key: "specialty", label: "Specialty", type: "text", value: entry.specialty || "", required: true },
      { key: "certification_number", label: "Cert number", type: "text", value: entry.certification_number || "" },
      { key: "issued_date", label: "Issued date", type: "date", value: entry.issued_date || "" },
      { key: "expiration_date", label: "Expires", type: "date", value: entry.expiration_date || "" },
      { key: "notes", label: "Notes", type: "textarea", value: entry.notes || "" },
    ];
  }

  // ---------- Form rendering ----------

  function showForm(section, fields, onSubmit) {
    section.querySelectorAll(".dp-form").forEach((n) => n.remove());
    const form = el("form", { class: "dp-form", onsubmit: (e) => {
      e.preventDefault();
      const values = {};
      for (const f of fields) {
        const input = form.querySelector('[name="' + f.key + '"]');
        let v = input.value.trim();
        if (f.type === "number" && v !== "") v = Number(v);
        if (f.type === "number" && v === "") v = 0;
        values[f.key] = v;
      }
      onSubmit(values);
    } });
    for (const f of fields) {
      const row = el("div", { class: "dp-form-row" });
      row.appendChild(el("label", null, f.label));
      let input;
      if (f.type === "textarea") {
        input = el("textarea", { name: f.key }, f.value || "");
      } else if (f.type === "select") {
        input = el("select", { name: f.key });
        for (const opt of f.options) {
          const optNode = el("option", { value: opt.value }, opt.label);
          if (String(opt.value) === String(f.value)) optNode.setAttribute("selected", "");
          input.appendChild(optNode);
        }
      } else {
        input = el("input", {
          type: f.type,
          name: f.key,
          value: f.value,
          placeholder: f.placeholder || "",
          min: f.min, max: f.max,
          required: f.required,
        });
      }
      row.appendChild(input);
      form.appendChild(row);
    }
    form.appendChild(el("div", { class: "dp-form-actions" }, [
      el("button", { type: "button", class: "dp-btn dp-btn-ghost",
        onclick: () => form.remove() }, "Cancel"),
      el("button", { type: "submit", class: "dp-btn" }, "Save"),
    ]));
    section.appendChild(form);
  }

  function showSpecialtyForm(section) {
    section.querySelectorAll(".dp-form").forEach((n) => n.remove());

    const form = el("form", { class: "dp-form" });
    const taRow = el("div", { class: "dp-form-row" });
    taRow.appendChild(el("label", null, "Search NUCC"));
    const taWrap = el("div", { class: "dp-typeahead-wrapper" });
    const input = el("input", {
      type: "search",
      placeholder: "Family Medicine, Cardio…",
      autocomplete: "off",
    });
    const results = el("div", { class: "dp-typeahead-results dp-hidden" });
    taWrap.appendChild(input);
    taWrap.appendChild(results);
    taRow.appendChild(taWrap);
    form.appendChild(taRow);

    const primaryRow = el("div", { class: "dp-form-row" });
    primaryRow.appendChild(el("label", null, "Primary?"));
    const primary = el("input", { type: "checkbox", name: "is_primary" });
    primaryRow.appendChild(primary);
    form.appendChild(primaryRow);

    const hiddenCode = el("input", { type: "hidden", name: "nucc_code" });
    form.appendChild(hiddenCode);
    const chosen = el("div", { class: "dp-entry-sub", style: "padding: 4px 0 8px 130px;" },
      "No NUCC code selected");
    form.appendChild(chosen);

    form.appendChild(el("div", { class: "dp-form-actions" }, [
      el("button", { type: "button", class: "dp-btn dp-btn-ghost",
        onclick: () => form.remove() }, "Cancel"),
      el("button", { type: "submit", class: "dp-btn" }, "Add"),
    ]));

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!hiddenCode.value) {
        toast("Pick a NUCC code from the list first.", "error");
        return;
      }
      createSpecialty({ nucc_code: hiddenCode.value, is_primary: primary.checked });
    });

    let tid;
    input.addEventListener("input", () => {
      clearTimeout(tid);
      tid = setTimeout(() => doNuccSearch(input.value, results, (row) => {
        hiddenCode.value = row.code;
        input.value = row.display_name;
        chosen.textContent = row.code + " · " + row.display_name;
        results.classList.add("dp-hidden");
      }), 200);
    });

    section.appendChild(form);
    input.focus();
  }

  async function doNuccSearch(q, container, onPick) {
    container.innerHTML = "";
    if (!q || q.length < 2) {
      container.classList.add("dp-hidden");
      return;
    }
    try {
      const data = await apiRequest("GET",
        state.nuccBase + "/search?q=" + encodeURIComponent(q) + "&limit=20");
      if (!data.results.length) {
        container.classList.remove("dp-hidden");
        container.appendChild(el("div", { class: "dp-typeahead-item" }, "No matches"));
        return;
      }
      for (const row of data.results) {
        const item = el("div", { class: "dp-typeahead-item" }, [
          el("span", null, row.display_name),
          el("span", { class: "dp-typeahead-code" }, row.code),
        ]);
        item.addEventListener("click", () => onPick(row));
        container.appendChild(item);
      }
      container.classList.remove("dp-hidden");
    } catch (err) {
      toast("Search failed: " + err.message, "error");
    }
  }

  // ---------- Mutations ----------

  async function createEntry(kind, values) {
    try {
      await apiRequest("POST",
        state.apiBase + "/staff/" + state.selectedDbid + "/" + kind + "/", values);
      toast("Added.");
      await reloadCurrent();
    } catch (err) { toast(err.message, "error"); }
  }

  async function updateEntry(kind, id, values) {
    try {
      await apiRequest("PATCH",
        state.apiBase + "/staff/" + state.selectedDbid + "/" + kind + "/" + id + "/", values);
      toast("Saved.");
      await reloadCurrent();
    } catch (err) { toast(err.message, "error"); }
  }

  async function deleteEntry(kind, id) {
    try {
      await apiRequest("DELETE",
        state.apiBase + "/staff/" + state.selectedDbid + "/" + kind + "/" + id + "/");
      toast("Removed.");
      await reloadCurrent();
    } catch (err) { toast(err.message, "error"); }
  }

  async function createSpecialty(values) {
    try {
      await apiRequest("POST",
        state.apiBase + "/staff/" + state.selectedDbid + "/specialty/", values);
      toast("Specialty added.");
      await reloadCurrent();
    } catch (err) { toast(err.message, "error"); }
  }

  async function setPrimarySpecialty(id) {
    try {
      await apiRequest("POST",
        state.apiBase + "/staff/" + state.selectedDbid + "/specialty/" + id + "/primary/");
      toast("Primary updated.");
      await reloadCurrent();
    } catch (err) { toast(err.message, "error"); }
  }

  function confirmAndDelete(kind, id, label) {
    if (!window.confirm("Remove '" + label + "'? This cannot be undone.")) return;
    deleteEntry(kind, id);
  }

  function confirmAndDeleteEntry(fn, label) {
    if (!window.confirm("Remove '" + (label || "this entry") + "'? This cannot be undone.")) return;
    fn();
  }

  async function reloadCurrent() {
    if (state.selectedDbid) await selectStaff(state.selectedDbid);
    // Also refresh the list, since primary specialties/expiring certs affect sort/filter
    try {
      const listData = await apiRequest("GET",
        state.apiBase + "/staff/"
        + (state.expiringOnly ? "?expiring_within_days=90" : ""));
      state.staff = listData.staff;
      renderList();
    } catch (_) { /* non-fatal */ }
  }

  // ---------- Filters ----------

  function wireHeader() {
    $("#dp-search").addEventListener("input", (e) => {
      state.searchTerm = e.target.value.trim();
      renderList();
    });
    $("#dp-expiring-toggle").addEventListener("change", async (e) => {
      state.expiringOnly = e.target.checked;
      try {
        const data = await apiRequest("GET",
          state.apiBase + "/staff/"
          + (state.expiringOnly ? "?expiring_within_days=90" : ""));
        state.staff = data.staff;
      } catch (err) { toast(err.message, "error"); }
      renderList();
    });
    if (state.isAdmin) $("#dp-admin-badge").removeAttribute("hidden");
  }

  // ---------- Init ----------

  wireHeader();
  renderList();
})();
