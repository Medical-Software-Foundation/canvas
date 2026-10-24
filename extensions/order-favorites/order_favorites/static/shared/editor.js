{% verbatim %}
/* Shared by the chart panel and the admin app: API calls, icons, and the favorite editor form. */
(function () {
  "use strict";
  var API = document.body.getAttribute("data-api-base");

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  function api(method, path, body) {
    return fetch(API + path, {
      method: method, credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        // 401 means the Canvas sign-in ended (support logins time out); say so instead of the raw server text.
        var message = r.status === 401 ? "Your Canvas session ended. Sign in to Canvas again, then reopen Order Favorites." : (data.error || "Something went wrong. Try again.");
        if (!r.ok) { var e = new Error(message); e.status = r.status; throw e; }
        return data;
      });
    });
  }

  // E119 -> E11.9
  function icd(code) { code = String(code || "").replace(".", "").toUpperCase(); return code.length <= 3 ? code : code.slice(0, 3) + "." + code.slice(3); }

  var I = {
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    rx: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2.5" y="8" width="19" height="8" rx="4" transform="rotate(-45 12 12)"/><path d="M8.5 8.5l7 7"/></svg>',
    lab: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6"/><path d="M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/><path d="M7 15h10"/></svg>',
    sliders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="17" x2="20" y2="17"/><circle cx="9" cy="7" r="2.2" fill="#fff"/><circle cx="15" cy="17" r="2.2" fill="#fff"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 18l-6-6 6-6"/></svg>',
    open: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/></svg>',
    edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>',
    hide: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17.9 17.9A10 10 0 0 1 12 20C5 20 1 12 1 12a18 18 0 0 1 5.1-5.9M9.9 4.2A9 9 0 0 1 12 4c7 0 11 8 11 8a18 18 0 0 1-2.2 3.2"/><path d="M1 1l22 22"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
    lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
    chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    set: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>',
    all: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>'
  };

  // Order sets point to other favorites; the page registers the favorites it loaded so sets can name them.
  var known = {};
  function useFavorites(list) { known = {}; (list || []).forEach(function (f) { known[f.id] = f; }); }
  function setMembers(f) { return (f.items || []).map(function (id) { return known[id]; }).filter(Boolean); }
  function setCounts(f) {
    var m = setMembers(f), rx = m.filter(function (x) { return x.kind === "rx"; }).length, lab = m.length - rx;
    return [rx ? plural(rx, "prescription", "prescriptions") : "", lab ? plural(lab, "lab", "labs") : ""].filter(Boolean).join(" · ") || "No orders available";
  }

  // Shared lookups, loaded once per page.
  var cache = {};
  function once(key, path) { if (!cache[key]) { cache[key] = api("GET", path).then(function (d) { return d.results || []; }).catch(function (e) { delete cache[key]; throw e; }); } return cache[key]; }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  // ---------- favorite summaries (cards and lists) ----------
  // Prescription fields other than the medication may be blank; blanks are left out of summaries.
  function has(v) { return v !== null && v !== undefined && String(v) !== ""; }
  function rxSupply(f) {
    var bits = [];
    if (has(f.days_supply)) { bits.push(esc(f.days_supply) + " days"); }
    if (has(f.quantity)) { bits.push(esc(f.quantity) + (f.unit ? " " + esc(f.unit) : "")); }
    return bits;
  }
  function compact(f) {
    if (f.kind === "set") { return '<div class="cs"><div class="cs-2">' + setCounts(f) + "</div></div>"; }
    if (f.kind === "rx") {
      var rxBits = rxSupply(f);
      if (has(f.refills)) { rxBits.push(plural(+f.refills, "refill", "refills")); }
      return '<div class="cs"><div class="cs-1">' + esc(f.sig || f.medication) + '</div><div class="cs-2">' + (rxBits.length ? rxBits.join(" · ") : esc(f.sig ? f.medication : "Sig and amounts filled in on the order")) + "</div></div>";
    }
    var bits = [esc(f.lab_partner_name), plural(f.tests.length, "test", "tests")];
    if (f.fasting) { bits.push("Fasting"); }
    if (f.diagnoses.length) { bits.push(plural(f.diagnoses.length, "diagnosis", "diagnoses")); }
    return '<div class="cs"><div class="cs-2">' + bits.join(" · ") + "</div></div>";
  }
  function details(f) {
    if (f.kind === "set") {
      var m = setMembers(f);
      return '<ul class="set-list">' + (m.map(function (x) { return '<li class="' + x.kind + '">' + I[x.kind] + esc(x.name) + "</li>"; }).join("") || '<li class="gone">None of its favorites are available.</li>') + "</ul>";
    }
    var row = function (k, v) { return "<dt>" + k + "</dt><dd>" + v + "</dd>"; };
    var r = "";
    if (f.kind === "rx") {
      r += row("Drug", esc(f.medication));
      if (f.sig) { r += row("Sig", esc(f.sig)); }
      if (rxSupply(f).length) { r += row("Supply", rxSupply(f).join(" · ")); }
      if (has(f.refills)) { r += row("Refills", esc(f.refills)); }
      if (f.pharmacy_name) { r += row("Pharmacy", esc(f.pharmacy_name)); }
    } else {
      var stale = f.stale || [];
      r += row("Lab", esc(f.lab_partner_name));
      r += row("Tests", '<ul class="fd-list">' + f.tests.map(function (t) { return "<li" + (stale.indexOf(t.code) >= 0 ? ' class="bad"' : "") + ">" + esc(t.name || t.code) + (stale.indexOf(t.code) >= 0 ? " · no longer offered" : "") + "</li>"; }).join("") + "</ul>");
      r += row("Fasting", f.fasting ? "Yes" : "No");
      if (f.diagnoses.length) { r += row("Diagnosis", '<ul class="fd-list">' + f.diagnoses.map(function (d) { return '<li><b class="code">' + esc(icd(d.code)) + "</b> " + esc(d.text) + "</li>"; }).join("") + "</ul>"); }
      if (f.ordering_provider_name) { r += row("Provider", esc(f.ordering_provider_name)); }
      if (f.comment) { r += row("Comment", esc(f.comment)); }
    }
    return '<dl class="fd">' + r + "</dl>";
  }
  function searchText(f) {
    var parts = [f.name];
    if (f.kind === "set") { setMembers(f).forEach(function (x) { parts.push(x.name); }); return parts.join(" ").toLowerCase(); }
    if (f.kind === "rx") { parts.push(f.medication, f.sig, f.pharmacy_name); }
    else { parts.push(f.lab_partner_name); f.tests.forEach(function (t) { parts.push(t.name, t.code); }); f.diagnoses.forEach(function (d) { parts.push(d.code, icd(d.code), d.text); }); }
    return parts.join(" ").toLowerCase();
  }

  // ---------- search picker ----------
  // A text box with a pop-up list. multi: check several, the list stays open; single: pick one, it closes.
  function Picker(root, opts) {
    var self = this, timer = null, seq = 0;
    self.root = root; self.opts = opts;
    root.innerHTML = (opts.multi ? '<div class="cb-sel"></div>' : "") +
      '<div class="cb-box">' + I.search + '<input autocomplete="off" placeholder="' + esc(opts.placeholder) + '"></div>';
    self.input = root.querySelector("input");
    self.sel = root.querySelector(".cb-sel");
    self.pop = null;
    self.results = [];
    if (!opts.multi && opts.shown) { self.input.value = opts.shown(); }
    self.input.addEventListener("focus", function () { if (opts.multi || !self.input.value) { self.search(self.input.value); } });
    self.input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = self.input.value;
      timer = setTimeout(function () { self.search(q); }, 220);
    });
    self.input.addEventListener("keydown", function (e) { if (e.key === "Escape") { self.close(); } });
    self.search = function (q) {
      var mine = ++seq;
      self.open('<div class="cb-empty">Searching…</div>');
      Promise.resolve(opts.find(q)).then(function (rows) {
        if (mine !== seq) { return; }
        self.results = rows || [];
        self.renderPop(q);
      }).catch(function (e) { if (mine === seq) { self.open('<div class="cb-empty">' + esc(e.message) + "</div>"); } });
    };
    self.renderPop = function (q) {
      if (!self.results.length) { self.open('<div class="cb-empty">' + esc(q && q.length < (opts.min || 0) ? "Type at least " + opts.min + " letters" : "No matches") + "</div>"); return; }
      var chosen = opts.selected().map(opts.key);
      self.open(self.results.map(function (r, i) {
        var on = chosen.indexOf(opts.key(r)) >= 0;
        return '<button type="button" class="cb-opt' + (on ? " on" : "") + '" data-i="' + i + '">' + (opts.multi ? '<span class="cb-ck">' + (on ? "✓" : "") + "</span>" : "") + "<span>" + opts.row(r) + "</span></button>";
      }).join("") + (opts.foot ? '<div class="cb-foot">' + esc(opts.foot) + "</div>" : ""));
    };
    self.open = function (html) {
      if (!self.pop) {
        self.pop = document.createElement("div"); self.pop.className = "cb-pop"; root.appendChild(self.pop);
        self.pop.addEventListener("mousedown", function (e) { e.preventDefault(); });
        self.pop.addEventListener("click", function (e) {
          var b = e.target.closest("[data-i]"); if (!b) { return; }
          opts.pick(self.results[+b.getAttribute("data-i")]);
          self.drawSelected();
          if (opts.multi) { self.renderPop(self.input.value); self.input.focus(); }
          else { self.input.value = opts.shown ? opts.shown() : ""; self.close(); }
        });
      }
      self.pop.innerHTML = html;
    };
    self.close = function () { if (self.pop) { self.pop.remove(); self.pop = null; } };
    self.input.addEventListener("blur", function () { setTimeout(function () { self.close(); if (!opts.multi && opts.shown) { self.input.value = opts.shown(); } }, 120); });
    self.drawSelected = function () {
      if (!self.sel) { return; }
      self.sel.innerHTML = opts.selected().map(function (v, i) {
        var bad = opts.bad && opts.bad(v);
        return '<div class="cb-row' + (bad ? " bad" : "") + '"><span class="t">' + opts.row(v) + (bad ? " · no longer offered" : "") + '</span><button type="button" class="rm" data-rm="' + i + '" title="Remove" aria-label="Remove">✕</button></div>';
      }).join("");
    };
    if (self.sel) {
      self.sel.addEventListener("click", function (e) { var b = e.target.closest("[data-rm]"); if (b) { opts.remove(+b.getAttribute("data-rm")); self.drawSelected(); } });
      self.drawSelected();
    }
  }

  // ---------- the editor form ----------
  // value: a favorite (or a blank one). Returns {payload(), dirty(), el}. onChange is called on every edit.
  function blank(kind) {
    if (kind === "set") { return { kind: "set", name: "", items: [] }; }
    return kind === "rx"
      ? { kind: "rx", name: "", fdb_code: "", medication: "", sig: "", days_supply: "", quantity: "", unit: "", representative_ndc: "", ncpdp_quantity_qualifier_code: "", refills: "", pharmacy_ncpdp_id: "", pharmacy_name: "" }
      : { kind: "lab", name: "", lab_partner_id: "", lab_partner_name: "", tests: [], diagnoses: [], ordering_provider_id: "", ordering_provider_name: "", comment: "", fasting: false, stale: [] };
  }

  function snapshot(f) {
    var keys = f.kind === "rx"
      ? ["name", "fdb_code", "sig", "days_supply", "quantity", "representative_ndc", "refills", "pharmacy_ncpdp_id"]
      : ["name", "lab_partner_id", "tests", "diagnoses", "ordering_provider_id", "comment", "fasting"];
    var o = {};
    keys.forEach(function (k) { var v = f[k]; o[k] = Array.isArray(v) ? v.map(function (x) { return x.code; }).join("|") : String(v == null ? "" : v); });
    return JSON.stringify(o);
  }

  function Editor(container, value, opts) {
    opts = opts || {};
    var f = JSON.parse(JSON.stringify(value));
    var start = snapshot(f);
    var units = [];
    var h = "";
    if (opts.note) { h += '<div class="note">' + esc(opts.note) + "</div>"; }
    h += '<label for="fName">Name</label><input id="fName" maxlength="120">';
    if (f.kind === "rx") {
      h += '<label>Medication</label><div class="cb" id="pMed"></div>';
      h += '<label for="fSig">Sig</label><textarea id="fSig" maxlength="1000"></textarea>';
      h += '<div class="grid"><div><label for="fDays">Days supply</label><input id="fDays" type="number" min="1" max="365"></div><div><label for="fQty">Quantity</label><input id="fQty" type="number" min="0" step="any"></div></div>';
      h += '<div class="grid"><div><label for="fUnit">Unit</label><select id="fUnit"></select></div><div><label for="fRef">Refills</label><input id="fRef" type="number" min="0" max="99"></div></div>';
      h += '<label>Default pharmacy</label><div class="cb" id="pPharm"></div><div class="hint" id="phClear"></div>';
    } else {
      h += '<label for="fLab">Lab partner</label><select id="fLab"><option value="">Loading…</option></select>';
      h += '<label>Tests</label><div class="cb" id="pTests"></div><div class="warn" id="staleWarn" hidden></div>';
      h += '<label>Diagnosis</label><div class="cb" id="pDx"></div>';
      h += '<label for="fProv">Ordering provider</label><select id="fProv"><option value="">The note\'s provider, or whoever adds it</option></select>';
      h += '<label for="fComment">Comment</label><input id="fComment" maxlength="500">';
      h += '<label class="ck"><input type="checkbox" id="fFast"> Fasting required</label>';
    }
    container.innerHTML = h;
    var $ = function (s) { return container.querySelector(s); };
    var changed = function () { if (opts.onChange) { opts.onChange(); } };
    $("#fName").value = f.name;
    $("#fName").addEventListener("input", function () { f.name = this.value; changed(); });

    if (f.kind === "rx") {
      var fillUnits = function () {
        var sel = $("#fUnit");
        var list = units.length ? units : (f.representative_ndc ? [{ description: f.unit, representative_ndc: f.representative_ndc, ncpdp_quantity_qualifier_code: f.ncpdp_quantity_qualifier_code }] : []);
        // Unit is optional: the first choice leaves it for the prescriber to pick on the order.
        sel.innerHTML = '<option value="">' + (list.length ? "Pick on the order" : "Pick a medication first") + "</option>" +
          list.map(function (u, i) { return '<option value="' + i + '"' + (f.representative_ndc && u.representative_ndc === f.representative_ndc ? " selected" : "") + ">" + esc(u.description) + "</option>"; }).join("");
        var setUnit = function () {
          var u = sel.value === "" ? null : list[+sel.value];
          f.unit = u ? u.description : ""; f.representative_ndc = u ? u.representative_ndc : ""; f.ncpdp_quantity_qualifier_code = u ? u.ncpdp_quantity_qualifier_code : "";
        };
        setUnit();
        sel.onchange = function () { setUnit(); changed(); };
      };
      new Picker($("#pMed"), {
        placeholder: "Search medications", min: 2,
        find: function (q) { return q.length < 2 ? [] : api("GET", "/lookup/medications?q=" + encodeURIComponent(q)).then(function (d) { return d.results; }); },
        key: function (m) { return m.fdb_code; }, row: function (m) { return esc(m.name); },
        selected: function () { return f.fdb_code ? [{ fdb_code: f.fdb_code, name: f.medication }] : []; },
        shown: function () { return f.medication; },
        pick: function (m) { f.fdb_code = m.fdb_code; f.medication = m.name; units = m.units; f.representative_ndc = ""; fillUnits(); changed(); }
      });
      $("#fSig").value = f.sig; $("#fDays").value = f.days_supply; $("#fQty").value = f.quantity; $("#fRef").value = f.refills;
      [["#fSig", "sig"], ["#fDays", "days_supply"], ["#fQty", "quantity"], ["#fRef", "refills"]].forEach(function (p) { $(p[0]).addEventListener("input", function () { f[p[1]] = this.value; changed(); }); });
      fillUnits();
      var drawPharmClear = function () { $("#phClear").innerHTML = f.pharmacy_ncpdp_id ? '<a class="linkish" id="phX">Remove default pharmacy</a>' : "Optional. Without one, the prescription uses the patient's preferred pharmacy."; };
      new Picker($("#pPharm"), {
        placeholder: "Search pharmacies (optional)", min: 2,
        find: function (q) { return q.length < 2 ? [] : api("GET", "/lookup/pharmacies?q=" + encodeURIComponent(q)).then(function (d) { return d.results; }); },
        key: function (p) { return p.ncpdp_id; }, row: function (p) { return "<b>" + esc(p.name) + "</b> · " + esc(p.address); },
        selected: function () { return f.pharmacy_ncpdp_id ? [{ ncpdp_id: f.pharmacy_ncpdp_id }] : []; },
        shown: function () { return f.pharmacy_name; },
        pick: function (p) { f.pharmacy_ncpdp_id = p.ncpdp_id; f.pharmacy_name = p.name; drawPharmClear(); changed(); }
      });
      drawPharmClear();
      $("#phClear").addEventListener("click", function (e) { if (e.target.id === "phX") { f.pharmacy_ncpdp_id = ""; f.pharmacy_name = ""; $("#pPharm input").value = ""; drawPharmClear(); changed(); } });
    } else {
      var stale = (f.stale || []).slice();
      var drawStale = function () {
        var left = f.tests.filter(function (t) { return stale.indexOf(t.code) >= 0; });
        $("#staleWarn").hidden = !left.length;
        $("#staleWarn").textContent = left.length ? left.map(function (t) { return t.name || t.code; }).join(", ") + (left.length === 1 ? " is" : " are") + " no longer offered by " + (f.lab_partner_name || "this lab") + ". Remove it and add its replacement." : "";
      };
      var tests = new Picker($("#pTests"), {
        multi: true, placeholder: "Search tests to add", foot: "Check as many as you need",
        find: function (q) { return f.lab_partner_id ? api("GET", "/lookup/lab-tests?partner_id=" + encodeURIComponent(f.lab_partner_id) + "&q=" + encodeURIComponent(q)).then(function (d) { return d.results; }) : Promise.reject(new Error("Pick a lab partner first")); },
        key: function (t) { return t.code; }, row: function (t) { return esc(t.name || t.code) + (t.name ? ' <span class="muted">' + esc(t.code) + "</span>" : ""); },
        selected: function () { return f.tests; },
        bad: function (t) { return stale.indexOf(t.code) >= 0; },
        pick: function (t) { var i = f.tests.map(function (x) { return x.code; }).indexOf(t.code); if (i >= 0) { f.tests.splice(i, 1); } else { f.tests.push({ code: t.code, name: t.name }); } drawStale(); changed(); },
        remove: function (i) { f.tests.splice(i, 1); drawStale(); changed(); }
      });
      drawStale();
      new Picker($("#pDx"), {
        multi: true, min: 2, placeholder: "Search ICD-10 code or name", foot: "Check as many as you need",
        find: function (q) { return q.length < 2 ? [] : api("GET", "/lookup/diagnoses?q=" + encodeURIComponent(q)).then(function (d) { return d.results; }); },
        key: function (d) { return d.code; }, row: function (d) { return '<span class="code">' + esc(icd(d.code)) + "</span>" + esc(d.text); },
        selected: function () { return f.diagnoses; },
        pick: function (d) { var i = f.diagnoses.map(function (x) { return x.code; }).indexOf(d.code); if (i >= 0) { f.diagnoses.splice(i, 1); } else { f.diagnoses.push({ code: d.code, text: d.text }); } changed(); },
        remove: function (i) { f.diagnoses.splice(i, 1); changed(); }
      });
      once("partners", "/lookup/lab-partners").then(function (partners) {
        var sel = $("#fLab");
        var opts2 = partners.slice();
        if (f.lab_partner_id && !opts2.some(function (p) { return p.id === f.lab_partner_id; })) { opts2.unshift({ id: f.lab_partner_id, name: (f.lab_partner_name || "This lab") + " (not active)" }); }
        sel.innerHTML = '<option value="">Pick a lab partner</option>' + opts2.map(function (p) { return '<option value="' + esc(p.id) + '"' + (p.id === f.lab_partner_id ? " selected" : "") + ">" + esc(p.name) + "</option>"; }).join("");
        sel.onchange = function () {
          var p = opts2[sel.selectedIndex - 1];
          f.lab_partner_id = p ? p.id : ""; f.lab_partner_name = p ? p.name : "";
          // Tests belong to one lab, so changing the lab clears them.
          f.tests = []; stale = []; tests.drawSelected(); drawStale(); changed();
        };
      }).catch(function () { $("#fLab").innerHTML = '<option value="">Couldn\'t load lab partners</option>'; });
      once("providers", "/lookup/providers").then(function (list) {
        var sel = $("#fProv");
        var all = list.slice();
        if (f.ordering_provider_id && !all.some(function (p) { return p.id === f.ordering_provider_id; })) { all.unshift({ id: f.ordering_provider_id, name: (f.ordering_provider_name || "Saved provider") + " (no longer available)" }); }
        // Several staff can share a name, so the NPI tells them apart.
        sel.innerHTML += all.map(function (p) { return '<option value="' + esc(p.id) + '"' + (p.id === f.ordering_provider_id ? " selected" : "") + ">" + esc(p.name) + (p.npi ? " · NPI " + esc(p.npi) : "") + "</option>"; }).join("");
        sel.onchange = function () { f.ordering_provider_id = sel.value; changed(); };
      }).catch(function () { /* the provider stays as saved */ });
      $("#fComment").value = f.comment; $("#fComment").addEventListener("input", function () { f.comment = this.value; changed(); });
      $("#fFast").checked = !!f.fasting; $("#fFast").addEventListener("change", function () { f.fasting = this.checked; changed(); });
    }
    return {
      payload: function () { var p = JSON.parse(JSON.stringify(f)); delete p.stale; return p; },
      dirty: function () { return snapshot(f) !== start; },
      name: function () { return f.name; },
      saved: function () { start = snapshot(f); }
    };
  }

  // ---------- the order set editor ----------
  // favorites: everything the person can see. practice: a practice set, which may only hold practice favorites.
  // onNew(kind): show "+ New" on each group to create a favorite from here. baseline: the set as it was before a
  // trip to that form, so unsaved changes are still caught. justAdded: the favorite just created, marked "new".
  function SetEditor(container, value, opts) {
    opts = opts || {};
    var f = { kind: "set", name: value.name || "", items: (value.items || []).slice() };
    var base = opts.baseline || value;
    var start = JSON.stringify({ kind: "set", name: base.name || "", items: (base.items || []).slice() });
    var pool = (opts.favorites || []).filter(function (x) { return (x.kind === "rx" || x.kind === "lab") && (!opts.practice || x.shared) && (!x.hidden || f.items.indexOf(x.id) >= 0); });
    if (opts.practice) { f.items = f.items.filter(function (id) { return pool.some(function (x) { return x.id === id; }); }); }
    var groups = [["rx", "Prescriptions"], ["lab", "Labs"]].filter(function (g) { return !opts.kinds || opts.kinds.indexOf(g[0]) >= 0; });
    var h = "";
    if (opts.note) { h += '<div class="note">' + esc(opts.note) + "</div>"; }
    h += '<label for="fName">Name</label><input id="fName" maxlength="120" placeholder="e.g. Diabetes visit">';
    h += '<label>Favorites in this set</label><div class="picklist">' + groups.map(function (g) {
      var list = pool.filter(function (x) { return x.kind === g[0]; });
      var addNew = opts.onNew ? '<button type="button" class="linkbtn pk-new" data-pknew="' + g[0] + '">+ New</button>' : "";
      return '<div class="pkh"><span>' + g[1] + "</span>" + addNew + "</div>" + (list.map(function (x) {
        var just = x.id === opts.justAdded;
        return '<label class="pk' + (just ? " just" : "") + '"><input type="checkbox" data-pk="' + x.id + '"' + (f.items.indexOf(x.id) >= 0 ? " checked" : "") + "><span>" + esc(x.name) + "<small>" + (x.shared ? "Practice" : "Mine") + (just ? " · <b>new</b>" : "") + "</small></span></label>";
      }).join("") || '<div class="pk-empty">None yet.</div>');
    }).join("") + '</div><div class="hint" id="pkCount"></div>';
    container.innerHTML = h;
    var $ = function (s) { return container.querySelector(s); };
    var changed = function () { $("#pkCount").textContent = plural(f.items.length, "favorite", "favorites") + " picked. Editing a favorite later changes it in every set that uses it."; if (opts.onChange) { opts.onChange(); } };
    $("#fName").value = f.name;
    $("#fName").addEventListener("input", function () { f.name = this.value; changed(); });
    container.querySelector(".picklist").addEventListener("click", function (e) {
      var b = e.target.closest("[data-pknew]"); if (b && opts.onNew) { opts.onNew(b.getAttribute("data-pknew")); }
    });
    var justRow = container.querySelector(".pk.just");
    if (justRow) { justRow.scrollIntoView({ block: "nearest" }); setTimeout(function () { justRow.classList.remove("just"); }, 1600); }
    container.querySelector(".picklist").addEventListener("change", function (e) {
      var id = +e.target.getAttribute("data-pk"); if (!id) { return; }
      var i = f.items.indexOf(id);
      if (e.target.checked && i < 0) { f.items.push(id); } else if (!e.target.checked && i >= 0) { f.items.splice(i, 1); }
      changed();
    });
    $("#pkCount").textContent = plural(f.items.length, "favorite", "favorites") + " picked. Editing a favorite later changes it in every set that uses it.";
    return {
      payload: function () { return JSON.parse(JSON.stringify(f)); },
      dirty: function () { return JSON.stringify(f) !== start; },
      name: function () { return f.name; },
      saved: function () { start = JSON.stringify(f); }
    };
  }

  // An unsaved-changes warning: run go() now, or hold it behind a Keep editing / Discard banner.
  function Guard(slot, isDirty, label) {
    var pending = null;
    function hide() { slot.innerHTML = ""; slot.hidden = true; pending = null; }
    slot.addEventListener("click", function (e) {
      var b = e.target.closest("[data-guard]"); if (!b) { return; }
      var go = pending; hide();
      if (b.getAttribute("data-guard") === "discard" && go) { go(); }
    });
    return {
      run: function (go) {
        if (!isDirty()) { go(); return; }
        pending = go; slot.hidden = false;
        slot.innerHTML = '<div class="unsaved"><span class="grow"><b>Unsaved changes.</b> Your edits to ' + esc(label() || "this favorite") + " haven't been saved.</span>" +
          '<button type="button" class="btn sm" data-guard="keep">Keep editing</button><button type="button" class="btn sm danger" data-guard="discard">Discard changes</button></div>';
        slot.scrollIntoView({ block: "nearest" });
      },
      clear: hide
    };
  }

  window.OF = { API: API, api: api, esc: esc, icd: icd, I: I, compact: compact, details: details, searchText: searchText, blank: blank, Editor: Editor, SetEditor: SetEditor, Guard: Guard, plural: plural, useFavorites: useFavorites, setMembers: setMembers };
})();
{% endverbatim %}
