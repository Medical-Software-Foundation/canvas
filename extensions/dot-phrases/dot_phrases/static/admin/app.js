{% verbatim %}
/* Dot Phrases app: My phrases and Practice phrases for everyone; editable practice phrases, practice settings, and import for admins. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var API = document.body.getAttribute("data-api-base");

  // Preview values for a made-up patient; the admin app has no chart open.
  var SAMPLE = { first_name: "Connie", preferred_name: "Con", last_name: "Canvas", age: "67", dob: "03/14/1959", mrn: "A1B2C3D4E",
    subject_pronoun: "she", object_pronoun: "her", possessive_pronoun: "her", business_line: "Demo Health", facility: "Sunrise Assisted Living", room_number: "12",
    today: new Date().toLocaleDateString("en-US"), provider: "Dr. Canvas", practice_location: "Demo Clinic", last_visit: "09/02/2026 at 10:00 AM", next_visit: "11/05/2026 at 9:30 AM",
    insurance: "Blue Cross Blue Shield", plan: "PPO Gold", member_id: "XYZ123456789", group_number: "G-55012" };
  // Extra notes on how some chart placeholders are picked, shown in Practice settings.
  var CHART_RULE = { facility: "With more than one, all are listed: A and B", last_visit: "Skips cancelled and no-show appointments",
    next_visit: "Skips cancelled and no-show appointments", insurance: "Primary coverage in use on the visit date, as Canvas picks it" };
  var SHORT = { plan: "Plan", hpi: "HPI", instruct: "Instruct", perform: "Perform" };
  var ICONS = {
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 4-5.2 7-5.2s5.8 1.6 7 5.2"/></svg>',
    practice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V9l8-5 8 5v11"/><path d="M9 20v-6h6v6"/></svg>',
    ask: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/><path d="M10 9.5a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9v.2"/><path d="M12 14.6v.1"/></svg>'
  };
  var PLACEHOLDER = /\{(pick|blank)\s+([a-z_ ]*?)\s*(?::\s*([^}]*))?\}|\{([a-z_]+)\}|\*\*\*/gi;

  var data = { mine: [], phrases: [], values: [], allowCopy: true, labels: {}, limits: {}, rxFields: {}, isAdmin: false, adminTeam: "",
    chartGroups: [], chartEnabled: [], custom: [], metadataKeys: [], menu: [] };
  var adTab = "mine", adConfirm = false, adPending = null, adSel = null, adDraft = null, adQ = "", guideOpen = false, adCaret = null;
  var impStep = 1, impRows = [], impText = null, impDone = 0;

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  // Bold the checkbox names in a prescription warning, already escaped: "uncheck <b>Sig</b> under <b>Use in</b>".
  function boldUi(html) { return html.replace(/uncheck (Sig|Note to pharmacist) under Use in/g, "uncheck <b>$1</b> under <b>Use in</b>"); }
  function toast(m) { var t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove("on"); }, 2200); }
  function api(method, path, body) {
    return fetch(API + path, { method: method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) { throw new Error(d.error || "Something went wrong. Try again."); } return d; }); });
  }
  function valuesMap() {
    var m = {}; Object.keys(SAMPLE).forEach(function (k) { m[k] = SAMPLE[k]; });
    data.values.forEach(function (v) { m[v.name] = v.value; });
    data.custom.forEach(function (c) { m[c.name] = "Sample " + c.key.replace(/_/g, " "); });
    return m;
  }
  function practiceNames() { return data.values.map(function (v) { return v.name; }); }
  function chartNames() { var out = []; data.chartGroups.forEach(function (g) { g.items.forEach(function (i) { out.push(i.name); }); }); return out; }

  // ---- placeholders (mirrors dot_phrases/text.py) ----
  function bracket(kind, label, options) {
    if (kind.toLowerCase() === "pick") { var o = (options || "").split("|").map(function (x) { return x.trim(); }).filter(Boolean); return "[" + (o.length ? o.join(" / ") : (label.trim() || "choose")) + "]"; }
    return "[" + (label.trim() || "details") + "]";
  }
  // Like text.replace(re, fn), but escapes the text between matches, for output that goes into innerHTML.
  // fn's own output is trusted, so it must escape whatever it adds.
  function replaceAsHtml(text, re, fn) {
    var out = "", last = 0, m; re.lastIndex = 0;
    while ((m = re.exec(text))) {
      out += esc(text.slice(last, m.index)) + fn.apply(null, m.concat([m.index]));
      last = m.index + m[0].length;
      if (!m[0].length) { re.lastIndex += 1; }
    }
    return out + esc(text.slice(last));
  }
  function fill(text, html) {
    var vals = valuesMap();
    return (html ? replaceAsHtml.bind(null, text, PLACEHOLDER) : text.replace.bind(text, PLACEHOLDER))(function (all, kind, label, options, name, offset) {
      if (name != null) {
        var v = vals[name.toLowerCase()];
        if (!v) { return html ? '<span class="gap">' + esc(all) + "</span>" : all; }
        var before = text.slice(0, offset).replace(/\s+$/, "");
        if (!before || /[.!?]$/.test(before)) { v = v.charAt(0).toUpperCase() + v.slice(1); }
        return html ? '<span class="val">' + esc(v) + "</span>" : v;
      }
      var gap = kind == null ? "***" : bracket(kind, label || "", options);
      return html ? '<span class="gap">' + esc(gap) + "</span>" : gap;
    });
  }
  function fields(text) {
    var out = [], n = 0, m; PLACEHOLDER.lastIndex = 0;
    while ((m = PLACEHOLDER.exec(text))) {
      if (m[1] && m[1].toLowerCase() === "pick") { out.push({ kind: "pick", label: (m[2] || "").trim() || "choose", options: (m[3] || "").split("|").map(function (x) { return x.trim(); }).filter(Boolean) }); }
      else if (m[1]) { out.push({ kind: "blank", label: (m[2] || "").trim() || "details" }); }
      else if (m[4] == null) { n += 1; out.push({ kind: "blank", label: "Blank " + n, quick: true }); }
    }
    return out;
  }
  function unknownPlaceholders(text) {
    var out = [], m, names = practiceNames(); PLACEHOLDER.lastIndex = 0;
    names = names.concat(chartNames(), data.custom.map(function (c) { return c.name; }));
    while ((m = PLACEHOLDER.exec(text))) { if (m[4] != null && names.indexOf(m[4].toLowerCase()) < 0) { out.push(m[0]); } }
    return out;
  }
  // The editor's message for a phrase that can't go in a prescription field (mirrors rx_message in text.py).
  function rxMessage(field, text, label, max) {
    var parts = [], fixes = [], bad = [];
    if (text.length > max) { parts.push("it's over " + max.toLocaleString() + " characters (" + text.length.toLocaleString() + ")"); fixes.push("Shorten it"); }
    if (/[\r\n]/.test(text)) { parts.push("it has a line break"); fixes.push("Remove it"); }
    else {
      Array.prototype.forEach.call(text, function (ch) { if (!/[ -~]/.test(ch) && bad.indexOf(ch) < 0) { bad.push(ch); } });
      if (bad.length) { parts.push("it has special characters (" + bad.slice(0, 5).join(", ") + (bad.length > 5 ? ", …" : "") + ")"); fixes.push("Replace them"); }
    }
    if (!parts.length) { return ""; }
    var name = label === "Sig" ? label : label.charAt(0).toLowerCase() + label.slice(1);
    return "Can't use in the " + name + ": " + parts.join(" and ") + ". " + (fixes.length === 1 ? fixes[0] : "Fix these") + ", or uncheck " + label + " under Use in.";
  }
  function rxMessages(d) {
    return ["sig", "note_to_pharmacist"].filter(function (k) { return d.rx[k]; })
      .map(function (k) { return rxMessage(k, d.text, data.rxFields[k].label, data.rxFields[k].max); }).filter(Boolean);
  }
  function rxProblems(field, text) {
    var max = data.rxFields[field].max, p = [];
    if (text.length > max) { p.push("over " + max.toLocaleString() + " characters"); }
    if (/[\r\n]/.test(text)) { p.push("has a line break"); } else if (/[^ -~]/.test(text)) { p.push("has special characters"); }
    return p;
  }
  function chips(p) {
    var t = [];
    (p.use_in || []).forEach(function (k) { t.push('<span class="tag ' + (SHORT[k] || "any") + '">' + esc(SHORT[k] || data.labels[k] || k) + "</span>"); });
    if (p.rx_sig) { t.push('<span class="tag Sig">Sig</span>'); }
    if (p.rx_note_to_pharmacist) { t.push('<span class="tag NTP">Note to pharmacist</span>'); }
    return t.length ? '<span class="pc-uses">' + t.join("") + "</span>" : "";
  }

  // ---- tabs ----
  // Everyone has My phrases and Practice phrases. Admins also have Practice settings.
  function renderTabs() {
    var tabs = [["mine", "My phrases"], ["phrases", "Practice phrases"]];
    if (data.isAdmin) { tabs.push(["settings", "Practice settings"]); }
    if (!data.isAdmin && adTab === "settings") { adTab = "mine"; }
    $("#axTabs").innerHTML = tabs.map(function (t) { return '<button class="' + (t[0] === adTab ? "on" : "") + '" data-t="' + t[0] + '">' + t[1] + "</button>"; }).join("");
    $("#axSub").textContent = data.isAdmin ? "Your personal phrases, practice phrases everyone can use, and practice settings. Practice phrases and settings are limited to the plugin's admin team."
      : "Your personal phrases, and the practice phrases everyone can use.";
  }
  // The practice tab is read-only for anyone who isn't an admin.
  function readOnly() { return adTab === "phrases" && !data.isAdmin; }
  function pool() { return adTab === "mine" ? data.mine : data.phrases; }
  function selectTab() { $$("#axTabs [data-t]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-t") === adTab); }); render(); }
  $("#axTabs").addEventListener("click", function (e) { var b = e.target.closest("[data-t]"); if (b) { var t = b.getAttribute("data-t"); if (t === adTab) { return; } guard(function () { adTab = t; adSel = null; adDraft = null; adQ = ""; adConfirm = false; selectTab(); }); } });
  // Keep the note preview the same height as the text box (not counting the placeholder bar), including after a resize.
  var previewObserver = null;
  var openPhraseId = Number(new URLSearchParams(window.location.search).get("phrase")) || null;
  // Opened on a tab from the chart panel: ?tab=phrases (also mine or settings).
  var openTab = new URLSearchParams(window.location.search).get("tab");
  function syncPreview() {
    if (previewObserver) { previewObserver.disconnect(); previewObserver = null; }
    var ta = $("#axText"), out = $("#axResult");
    if (!ta || !out) { return; }
    var fit = function () {
      var ed = ta.closest(".ax-editor"), bar = ed && ed.querySelector(".ax-tools");
      if (!ed || !bar) { return; }
      out.style.height = Math.round(bar.getBoundingClientRect().top - ed.getBoundingClientRect().top) + "px";
    };
    fit();
    if (window.ResizeObserver) { previewObserver = new ResizeObserver(fit); previewObserver.observe(ta); }
  }
  function render() {
    $("#axMain").innerHTML = adTab === "settings" ? settingsHtml() : phrasesHtml();
    $("#axMain").classList.toggle("ax-settings", adTab === "settings");
    if (adTab !== "settings" && !readOnly()) { updDetail(); syncPreview(); }
  }
  function load() {
    return api("GET", "/admin/data").then(function (d) {
      data.mine = d.mine || []; data.phrases = d.phrases || []; data.values = d.values || []; data.allowCopy = !!d.allow_copy_text;
      data.isAdmin = !!d.is_admin; data.adminTeam = d.admin_team || "";
      data.chartGroups = d.chart_groups || []; data.chartEnabled = d.chart_enabled || []; data.custom = d.custom || [];
      data.metadataKeys = d.metadata_keys || []; data.metadataCapped = !!d.metadata_keys_capped; data.menu = d.menu_placeholders || [];
      data.labels = {}; (d.commands || []).forEach(function (c) { data.labels[c.key] = c.label; });
      data.limits = d.field_limits || {}; data.rxFields = d.rx_fields || {};
      // Opened from the chart panel's open-in-admin icon: go straight to that practice phrase.
      var want = openPhraseId; openPhraseId = null;
      var hit = want ? data.phrases.filter(function (p) { return p.id === want; })[0] : null;
      if (hit) { adTab = "phrases"; }
      else if (["mine", "phrases", "settings"].indexOf(openTab) >= 0) { adTab = openTab; }
      openTab = null;
      renderTabs();
      if (hit) { select(hit); return; }
      if (adSel && adSel !== "new") { adSel = pool().filter(function (p) { return p.id === adSel.id; })[0] || null; }
      if (adSel && adSel !== "new") { select(adSel); return; }
      render();
    }).catch(function (e) { $("#axMain").innerHTML = '<p class="ax-sub">' + esc(e.message) + "</p>"; });
  }

  var TRASH_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';

  // ---- phrase lists: My phrases and Practice phrases ----
  function rows() {
    var q = adQ.trim().toLowerCase().replace(/^\./, "");
    return pool().filter(function (p) { return (!q || p.code.indexOf(q) >= 0 || p.text.toLowerCase().indexOf(q) >= 0); })
      .sort(function (a, b) { return a.code.localeCompare(b.code); });
  }
  function phrasesHtml() {
    var list = rows();
    if (adSel && adSel !== "new" && list.indexOf(adSel) < 0) { adSel = null; adDraft = null; }
    var items = list.map(function (p) {
      var hid = readOnly() && p.hidden ? '<span class="tag any">Hidden</span>' : "";
      return '<button class="ax-row' + (adSel === p ? " on" : "") + '" data-sel="' + p.id + '"><span class="c"><span class="code">.' + esc(p.code) + "</span>" + hid + '<span class="n">' + (p.uses || 0) + (p.uses === 1 ? " use" : " uses") + "</span></span>" +
        '<span class="t">' + esc(fill(p.text, false)) + "</span>" + chips(p) + "</button>";
    }).join("");
    var mineTab = adTab === "mine", what = mineTab ? "my phrases" : "practice phrases";
    var empty = adQ ? (mineTab ? "None of your phrases match." : "No practice phrases match.") :
      mineTab ? "No phrases of your own yet. Make one with <b>+ New</b>, or copy a practice phrase." :
      data.isAdmin ? "No practice phrases yet. Make one, or import a list." : "Your practice has no practice phrases yet.";
    return '<div class="ax-split"><aside class="ax-list"><div class="ax-list-top">' +
      '<input class="ax-in" id="axQ" placeholder="Search ' + what + '" value="' + esc(adQ) + '" autocomplete="off" aria-label="Search ' + what + '">' +
      (readOnly() ? "" : '<button class="ax-btn primary ax-new" data-new>+ New</button>') + "</div>" +
      '<div class="ax-rows">' + (items || '<div class="ax-list-empty">' + empty + "</div>") + "</div></aside>" +
      '<section class="ax-detail" id="axDetail">' + (readOnly() ? roDetailHtml() : detailHtml()) + "</section></div>";
  }
  function insertBar() {
    var item = function (ins, name, note, sel) { return '<button type="button" class="ax-pi" data-ins="' + esc(ins) + '"' + (sel ? ' data-hl="' + esc(sel) + '"' : "") + '><span class="n">' + esc(name) + '</span><span class="e">' + esc(note) + "</span></button>"; };
    var menu = function (key, label, head, items) { return '<div class="ax-menu"><button type="button" class="ax-tbtn" data-menu="' + key + '" aria-expanded="false" aria-haspopup="true">' + ICONS[key] + label + '<span class="caret">▾</span></button><div class="ax-pop" role="menu" hidden><div class="ax-pop-head">' + head + "</div>" + items + "</div></div>"; };
    var vals = valuesMap();
    var chart = data.menu.map(function (p) { return item("{" + p.name + "}", p.label, vals[p.name] ? "Sample patient: " + vals[p.name] : "Empty for the sample patient"); }).join("") +
      (data.isAdmin ? '<div class="ax-pop-foot">Choose which show here on the <b>Practice settings</b> tab.</div>' : "");
    var practice = data.values.map(function (v) { return item("{" + v.name + "}", v.name.replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }), v.value || "No value yet"); }).join("") +
      '<div class="ax-pop-foot">' + (data.isAdmin ? "Add more on the <b>Practice settings</b> tab." : "Your practice's Dot Phrases admins set these.") + "</div>";
    var ask = item("{blank instructions}", "Blank with instructions", "Tells the provider what goes here. Example: [duration]", "instructions") +
      item("***", "Plain blank", "Marks a spot to fill in, without instructions: ***", "") +
      item("{pick label: option | option}", "Choice", "The provider picks one option. Example: [right / left]", "label: option | option");
    return '<div class="ax-tools" role="toolbar" aria-label="Insert a placeholder">' + menu("chart", "Patient", "From the patient's chart", chart) +
      menu("practice", "Practice", "Practice info, same for every patient", practice) + menu("ask", "Fill-ins", "The provider fills these in when they use the phrase", ask) +
      '<div class="ax-info"><button type="button" class="ax-ibtn" data-guide aria-expanded="' + guideOpen + '" aria-controls="axGuide" aria-label="How placeholders work" title="How placeholders work"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.6v.1"/></svg></button></div></div>';
  }
  // ---- Use in checklist: shared with the other screen, in static/shared/use_in.js ----
  var useIn = window.DotPhrasesUseIn(function () { return data.labels; }, esc);
  var useBlockHtml = useIn.useBlockHtml, useSync = useIn.useSync, useHandle = useIn.useHandle, useIsEmpty = useIn.useIsEmpty, useSummary = useIn.useSummary;
  function guideHtml() {
    var ins = function (k) { return '<button class="tok" data-ins="' + esc(k) + '" title="Add to the phrase">' + esc(k) + "</button>"; };
    var vals = valuesMap();
    var chartRows = data.menu.map(function (p) { return "<tr><td>" + ins("{" + p.name + "}") + "</td><td>" + (vals[p.name] ? "<b>" + esc(vals[p.name]) + "</b>" : '<span class="gd-empty">Nothing in this chart, so it stays as typed</span>') + "</td></tr>"; }).join("");
    var pracRows = data.values.map(function (v) { return "<tr><td>" + ins("{" + v.name + "}") + "</td><td>" + (v.value ? "<b>" + esc(v.value) + "</b>" : '<span class="gd-empty">No value yet</span>') + "</td></tr>"; }).join("");
    return '<div class="gd-head"><div><div class="gd-title">How placeholders work</div><p>Placeholders go in curly brackets and get swapped for real information when the phrase is used. Click one below to add it where your cursor is.</p></div>' +
      '<button type="button" class="gd-close" data-guide aria-label="Close the guide" title="Close">✕</button></div><div class="gd-cols">' +
      '<section class="gd-sec"><h4>' + ICONS.chart + "Patient</h4><p>From the open chart. Shown here for a sample patient.</p>" +
      '<table class="gd-tbl"><thead><tr><th>You type</th><th>It becomes</th></tr></thead><tbody>' + chartRows + "</tbody></table>" +
      '<p class="gd-note">If the chart has nothing for one, it stays as typed and the provider fills it in before recording.</p></section><div>' +
      '<section class="gd-sec"><h4>' + ICONS.practice + "Practice</h4><p>Same for every patient. " + (data.isAdmin ? "Change them on the <b>Practice settings</b> tab." : "Your practice's Dot Phrases admins set them.") + "</p>" +
      '<table class="gd-tbl"><thead><tr><th>You type</th><th>It becomes</th></tr></thead><tbody>' + (pracRows || '<tr><td colspan="2" class="gd-empty">None yet</td></tr>') + "</tbody></table></section>" +
      '<section class="gd-sec"><h4>' + ICONS.ask + "Fill-ins</h4><p>The provider fills these in when they use the phrase. Written right in the phrase.</p>" +
      '<table class="gd-tbl gd-fill"><thead><tr><th>You type</th><th>In the chart panel</th><th>Typed in a note</th></tr></thead><tbody>' +
      "<tr><td>" + ins("{blank duration}") + '</td><td>A box labeled "duration"</td><td><code class="gd-out">[duration]</code></td></tr>' +
      "<tr><td>" + ins("***") + '</td><td>A box with no label</td><td><code class="gd-out">***</code></td></tr>' +
      "<tr><td>" + ins("{pick side: right | left}") + '</td><td>Buttons: Right, Left</td><td><code class="gd-out">[right / left]</code></td></tr></tbody></table>' +
      '<p class="gd-note">Add instructions when the sentence doesn\'t make clear what goes in the blank. Every blank must be filled in before the command can be recorded. For a choice, the word before the colon is the heading, and options are separated by |.</p></section></div></div>' +
      '<section class="gd-ex"><h4>Example</h4>' +
      '<div class="gd-ex-row"><div class="gd-ex-k">You write</div><div><span class="gd-src">{first_name} is a {age}-year-old seen today for {pick side: right | left | both} knee pain for {blank duration}.</span></div></div>' +
      '<div class="gd-ex-row"><div class="gd-ex-k">Provider picks</div><div>Left, and types 2 weeks</div></div>' +
      '<div class="gd-ex-row"><div class="gd-ex-k">Note gets</div><div><b>Connie is a 67-year-old seen today for left knee pain for 2 weeks.</b></div></div></section>';
  }
  function detailHtml() {
    if (!adSel) {
      return guideOpen ? '<div class="ax-dmeta" style="margin-bottom:10px">Pick a phrase on the left to edit it, or make a new one.</div><div class="ax-guide">' + guideHtml() + "</div>"
        : adTab === "mine" ? '<div class="ax-blank"><div><b>Pick a phrase to edit</b>Or make a new one. Only you can use your phrases.</div></div>'
        : '<div class="ax-blank"><div><b>Pick a phrase to edit</b>Or make a new one. Changes reach everyone the next time they use it.</div></div>';
    }
    var p = adSel === "new" ? null : adSel, d = adDraft, ro = false, mineTab = adTab === "mine";
    var meta = mineTab ? (p ? "Your phrase. Only you can use it. Used " + (p.uses || 0) + (p.uses === 1 ? " time." : " times.") : "New phrase. Only you can use it.")
      : p ? "Made by " + esc(p.owner) + ". Used " + (p.uses || 0) + " times." : "New practice phrase. Everyone can use it once you save.";
    // Buttons sit in a bar at the bottom of the editor: Delete on the left, Cancel and Save on the right.
    var foot = adPending ? '<div class="ax-foot ax-discard" role="alertdialog" aria-labelledby="axDsT"><div><div class="ax-cf-title" id="axDsT">' + (p ? "Discard your changes to ." + esc(p.code) + "?" : "Discard this new phrase?") + "</div>" +
      "<p>Your edits haven't been saved.</p></div>" +
      '<div class="ax-dacts"><button class="ax-btn" data-keep>Keep editing</button><button class="ax-btn primary" data-discard>Discard changes</button></div></div>' : p && adConfirm ? '<div class="ax-foot ax-confirm" role="alertdialog" aria-labelledby="axCfT"><div><div class="ax-cf-title" id="axCfT">Delete .' + esc(p.code) + "?</div>" +
      "<p>Deleting ." + esc(p.code) + " won't affect existing notes. This action can't be undone.</p></div>" +
      '<div class="ax-dacts"><button class="ax-btn" data-delno>Cancel</button><button class="ax-btn danger-solid" data-delyes>Delete</button></div></div>' :
      '<div class="ax-foot">' + (p ? '<button class="ax-btn danger" data-delete>' + TRASH_ICON + "Delete</button>" : "") +
      '<div class="ax-dacts"><button class="ax-btn" data-cancel>Cancel</button><button class="ax-btn primary" data-save>' + (p ? "Save changes" : "Save phrase") + "</button></div></div>";
    return '<div class="ax-dhead"><div><div class="ax-dcode" id="axDcode">.' + esc(d.code || "new phrase") + '</div><div class="ax-dmeta">' + meta + "</div></div></div>" +
      '<label class="ax-lbl" for="axCode">Code</label><div class="ax-codein"><span>.</span><input class="ax-in" id="axCode" maxlength="64" value="' + esc(d.code) + '"' + (ro ? " disabled" : "") + "></div>" +
      '<div class="ax-help">' + (mineTab ? "What you type." : "What providers type.") + ' Starts with a letter, then letters and numbers.</div><div class="ax-warn" id="axRename"></div>' +
      '<div class="ax-pair"><div><label class="ax-lbl" for="axText">What you write</label><div class="ax-editor' + (ro ? " ro" : "") + '">' +
      '<textarea class="ax-ta ax-ta-flat" id="axText" rows="7"' + (ro ? " disabled" : "") + ">" + esc(d.text) + "</textarea>" + (ro ? "" : insertBar()) + "</div>" +
      (ro ? "" : '<div class="ax-help">Placeholders go in curly brackets. Use the menus above, or type them.</div>') + "</div>" +
      '<div><div class="ax-lbl">What lands in the note, for a sample patient</div><div class="ax-result" id="axResult"></div><div class="ax-help" id="axAsks"></div></div></div>' +
      '<div class="ax-guide" id="axGuide"' + (guideOpen ? "" : " hidden") + ">" + guideHtml() + "</div>" +
      '<div class="ax-lbl">Use in</div><div id="axUseBlock" class="ax-pk">' + useBlockHtml(d) + "</div>" +
      '<div class="ax-warn" id="axLim"></div><div class="ax-err" id="axRx"></div><div class="ax-err" id="axErr"></div>' + foot;
  }
  // A practice phrase, for someone who isn't an admin: read it, copy it, or hide it from their chart panel list.
  var LOCK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
  function myCopy(p) { return data.mine.filter(function (m) { return m.code === p.code; })[0] || null; }
  function roDetailHtml() {
    if (!adSel || adSel === "new") {
      return '<div class="ax-blank"><div><b>Pick a practice phrase</b>Make your own copy to change the wording, or hide ones you don\'t use from your chart panel list.</div></div>';
    }
    var p = adSel, copy = myCopy(p), who = data.adminTeam || "your practice's Dot Phrases admins";
    var d = { use_in: p.use_in, rx: { sig: p.rx_sig, note_to_pharmacist: p.rx_note_to_pharmacist } };
    var note = copy ? "You have your own ." + esc(p.code) + ", which is used instead of this one when you type the code." :
      "To use different wording, make your own copy. Yours is used instead of this one, for you only.";
    return '<div class="ax-dhead"><div><div class="ax-dcode">.' + esc(p.code) + '</div><div class="ax-dmeta">Practice phrase. Only ' + esc(who) + " can change it. Used " + (p.uses || 0) + (p.uses === 1 ? " time." : " times.") + "</div></div></div>" +
      '<div class="ax-note-ro">' + LOCK_ICON + "<span>" + note + "</span></div>" +
      '<div class="ax-pair"><div><div class="ax-lbl">Text</div><div class="ax-ro">' + esc(p.text) + "</div></div>" +
      '<div><div class="ax-lbl">What lands in the note, for a sample patient</div><div class="ax-result ax-result-ro">' + fill(p.text, true) + '</div><div class="ax-help">' + esc(asksSentence(p.text)) + "</div></div></div>" +
      '<div class="ax-lbl">Use in</div><div class="wi"><span class="wi-t">Works in: <b>' + esc(useSummary(d)) + "</b></span></div>" +
      '<div class="ax-foot"><button class="ax-btn" data-hide>' + (p.hidden ? "Show in my list" : "Hide from my list") + "</button>" +
      '<div class="ax-dacts">' + (copy ? '<button class="ax-btn primary" data-opencopy>Open my copy</button>' : '<button class="ax-btn primary" data-copy>Make my own copy</button>') + "</div></div>";
  }
  function asksSentence(t) {
    var f = fields(t); if (!f.length) { return "Nothing to fill in. It goes in exactly as shown."; }
    // "right or left" / "right, left, or bilateral". Two items get a comma too when the first has one.
    var listOf = function (items, word) {
      if (items.length < 2) { return items.join(""); }
      var sep = items.length > 2 || items[0].indexOf(",") >= 0 ? ", " : " ";
      return items.slice(0, -1).join(", ") + sep + word + " " + items[items.length - 1];
    };
    // "selects right, left, or both, and enters duration"
    var blanks = 0, parts = [], entered = [];
    f.forEach(function (x) {
      if (x.kind === "pick") { parts.push("selects " + (x.options.length ? listOf(x.options, "or") : x.label)); }
      else if (x.quick || x.label === "details") { blanks += 1; }
      else { entered.push(x.label); }
    });
    if (blanks) { entered.push(blanks === 1 ? "a blank" : blanks + " blanks"); }
    if (entered.length) { parts.push("enters " + listOf(entered, "and")); }
    // A comma before the last "and" keeps "selects … and enters …" readable.
    var joined = parts.length === 2 ? parts[0] + ", and " + parts[1] : listOf(parts, "and");
    return "Before recording, the provider " + joined + ".";
  }
  function updDetail() {
    if (!adSel || !$("#axDetail") || !$("#axResult")) { return; }
    var d = adDraft;
    var saved = adSel === "new" ? null : adSel;
    $("#axDcode").textContent = "." + ((saved ? saved.code : d.code) || "new phrase");
    var rn = $("#axRename");
    if (rn) {
      rn.innerHTML = !saved || d.code === saved.code ? "" : d.code ? esc("Saving renames ." + saved.code + " to ." + d.code + ". Typing ." + saved.code + " will stop working.") :
        esc("This is still ." + saved.code + ".") + " To make a new phrase instead, use <b>+ New</b>.";
    }
    $("#axResult").innerHTML = d.text ? fill(d.text, true) : '<span style="color:#8ea8b5">Start writing on the left.</span>';
    $("#axAsks").textContent = d.text ? asksSentence(d.text) : "";
    useSync($("#axUseBlock"), d, d.text);
    var len = fill(d.text, false).length, keys = d.use_in === null ? Object.keys(data.limits) : d.use_in.filter(function (k) { return data.limits[k]; });
    var over = keys.filter(function (k) { return len > data.limits[k]; });
    $("#axLim").textContent = over.length ? "Too long for " + over.map(function (k) { return data.labels[k] + " (" + data.limits[k] + " characters)"; }).join(" and ") + ", so it won't expand there." : "";
    ["sig", "note_to_pharmacist"].forEach(function (k) {
      var c = $("#useC_" + k), on = !!d.rx[k], pr = on ? rxProblems(k, d.text) : [];
      c.textContent = on ? d.text.length.toLocaleString() + " of " + data.rxFields[k].max.toLocaleString() : "";
      c.classList.toggle("bad", pr.length > 0);
    });
    $("#axRx").innerHTML = rxMessages(d).map(function (m) { return "<div>" + boldUi(esc(m)) + "</div>"; }).join("");
  }
  // Unsaved edits: leaving a phrase with changes asks first, so work isn't lost.
  function isDirty() {
    var importPending = impStep === 2 || (impStep === 1 && !!(($("#axImport") || {}).value || "").trim());
    if (adTab === "settings") {
      var changed = data.values.some(function (v) { var i = $('[data-fv="' + v.name + '"]'); return i && i.value !== v.value; });
      var keyChanged = data.custom.some(function (c) { var s = $('[data-ckey="' + c.name + '"]'); return s && s.value !== c.key; });
      return changed || keyChanged || importPending || !!(($("#axNewName") || {}).value || "").trim() || !!(($("#axNewVal") || {}).value || "").trim() ||
        !!(($("#axCName") || {}).value || "").trim();
    }
    if (!adSel || !adDraft) { return false; }
    var d = adDraft, p = adSel === "new" ? null : adSel;
    if (!p) { return !!(d.code || d.text.trim() || d.use_in !== null || d.rx.sig || d.rx.note_to_pharmacist); }
    return d.code !== p.code || d.text !== p.text || JSON.stringify(d.use_in) !== JSON.stringify(p.use_in) || !!d.rx.sig !== !!p.rx_sig || !!d.rx.note_to_pharmacist !== !!p.rx_note_to_pharmacist;
  }
  function guard(action) {
    if (!isDirty()) { adPending = null; action(); return; }
    if (adTab !== "settings") {
      adPending = action; adConfirm = false; render();
      var f = $(".ax-discard"); if (f) { f.querySelector("[data-keep]").focus(); }
      return;
    }
    // Practice settings and Import keep their typing in the page itself, so ask in a bar over it instead of redrawing.
    closeFloatBar();
    var bar = document.createElement("div");
    bar.className = "ax-floatbar ax-discard"; bar.setAttribute("role", "alertdialog"); bar.setAttribute("aria-labelledby", "axFbT");
    bar.innerHTML = '<div><div class="ax-cf-title" id="axFbT">' + "Discard your changes?" + "</div>" +
      "<p>" + "Your edits haven't been saved, and any list you added hasn't been imported." + "</p></div>" +
      '<div class="ax-dacts"><button class="ax-btn" data-fbkeep>Keep editing</button><button class="ax-btn primary" data-fbdiscard>Discard changes</button></div>';
    document.body.appendChild(bar);
    bar.querySelector("[data-fbkeep]").addEventListener("click", closeFloatBar);
    bar.querySelector("[data-fbdiscard]").addEventListener("click", function () {
      closeFloatBar();
      impStep = 1; impText = ""; impRows = [];
      action();
    });
    bar.querySelector("[data-fbkeep]").focus();
  }
  function closeFloatBar() { var b = $(".ax-floatbar"); if (b) { b.parentNode.removeChild(b); } }
  window.addEventListener("beforeunload", function (e) { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });
  function select(p) {
    adCaret = null; adSel = p; adConfirm = false; adPending = null;
    adDraft = p === "new" ? { code: "", text: "", use_in: null, rx: {} } : { code: p.code, text: p.text, use_in: p.use_in === null ? null : p.use_in.slice(), rx: { sig: p.rx_sig, note_to_pharmacist: p.rx_note_to_pharmacist } };
    render();
  }
  function closeMenus(except) {
    $$("#axMain .ax-menu").forEach(function (m) { if (m !== except) { m.querySelector(".ax-pop").hidden = true; m.querySelector("[data-menu]").setAttribute("aria-expanded", "false"); } });
  }
  function insertAtCaret(ins, selPart) {
    var ta = $("#axText"); if (!ta) { return; }
    var v = ta.value, at = adCaret == null ? v.length : Math.min(adCaret, v.length);
    var before = v.slice(0, at), after = v.slice(at);
    var pre = before && !/\s$/.test(before) ? " " : "", post = after && !/^[\s.,;:!?)]/.test(after) ? " " : "";
    ta.value = before + pre + ins + post + after;
    var start = at + pre.length, a = start + ins.length, b = a;
    if (selPart) { var i = ins.indexOf(selPart); if (i >= 0) { a = start + i; b = a + selPart.length; } }
    ta.focus(); ta.setSelectionRange(a, b); adCaret = b; adDraft.text = ta.value; updDetail();
  }
  function save() {
    var p = adSel === "new" ? null : adSel, d = adDraft, err = function (m) { $("#axErr").textContent = m; };
    if (!/^[a-z][a-z0-9]*$/.test(d.code)) { return err("Give it a code that starts with a letter and uses only letters and numbers."); }
    if (!d.text.trim()) { return err("Write the text this phrase puts in the note."); }
    var u = unknownPlaceholders(d.text);
    if (u.length) { $("#axErr").innerHTML = esc(u.join(", ") + " isn't a placeholder.") + " " + (data.isAdmin ? "Add it on the <b>Practice settings</b> tab, or fix the spelling." : "Fix the spelling, or ask your Dot Phrases admins to add it as practice info."); return; }
    if (useIsEmpty(d)) { return err("Pick at least one place to use this phrase."); }
    if (rxMessages(d).length) { err(""); $("#axRx").scrollIntoView({ block: "nearest" }); return; }
    var body = { code: d.code, text: d.text.trim(), use_in: d.use_in, rx_sig: !!d.rx.sig, rx_note_to_pharmacist: !!d.rx.note_to_pharmacist, scope: adTab === "mine" ? "personal" : "practice" };
    // One save at a time, so a double click can't create the same phrase twice.
    var btn = $("[data-save]"); if (btn) { if (btn.disabled) { return; } btn.disabled = true; }
    (p ? api("PATCH", "/phrases/" + p.id, body) : api("POST", "/phrases", body)).then(function (r) {
      toast(p || adTab === "mine" ? "Saved ." + d.code : "Saved ." + d.code + ". Everyone can use it now.");
      d.text = d.text.trim(); adSel = { id: r.phrase.id }; return load();
    }).catch(function (e) { err(e.message); if (btn) { btn.disabled = false; } });
  }

  // ---- practice settings ----
  function settingsHtml() {
    var rowsHtml = data.values.map(function (v) {
      return '<tr><td><span class="tok">{' + esc(v.name) + '}</span></td><td><input class="ax-in" data-fv="' + esc(v.name) + '" value="' + esc(v.value) + '" aria-label="Value for ' + esc(v.name) + '"></td>' +
        '<td class="used">' + v.used_in + " phrase" + (v.used_in === 1 ? "" : "s") + '</td><td><button class="ax-btn quiet" data-fsave="' + esc(v.name) + '">Save</button><button class="ax-btn quiet" data-fdel="' + esc(v.name) + '">Remove</button></td></tr>';
    }).join("");
    return '<section class="ax-sec"><h3>Settings</h3><p>Apply to everyone in the practice.</p>' +
      '<label class="ax-switchrow"><span class="ax-sw-text"><b>Allow copying phrase text</b><span class="ax-help" style="display:block">Adds a Copy button to each phrase card in the chart panel. Copied text doesn\'t follow the phrase\'s command limits, so it can be pasted into any command.</span></span>' +
      '<span class="ax-sw"><input type="checkbox" role="switch" data-setting="allow_copy_text"' + (data.allowCopy ? " checked" : "") + ' aria-label="Allow copying phrase text"><span class="ax-sw-track" aria-hidden="true"></span></span></label></section>' +
      chartPlaceholdersHtml() +
      '<section class="ax-sec"><h3>Practice info</h3><p>Information that\'s the same for every patient, like your after-hours number. Set it once here and every phrase that uses it stays up to date. Use it in a phrase by writing its name in curly brackets.</p>' +
      '<table class="ax-tbl"><thead><tr><th style="width:30%">Name</th><th>Value</th><th style="width:100px">Used in</th><th style="width:140px"></th></tr></thead><tbody>' + rowsHtml +
      '<tr class="add"><td><input class="ax-in" id="axNewName" placeholder="clinic_fax" aria-label="New name"></td><td><input class="ax-in" id="axNewVal" placeholder="(555) 010-3000" aria-label="New value"></td><td colspan="2"><button class="ax-btn" data-fadd>Add</button></td></tr></tbody></table>' +
      '<div class="ax-help">Names use lowercase letters and underscores, no spaces. Then write <span class="tok">{clinic_fax}</span> in any phrase.</div><div class="ax-err" id="axFillErr"></div></section>' +
      customPlaceholdersHtml() +
      '<section class="ax-sec ax-sec-import"><h3>Import</h3><p>Add many practice phrases at once, from a pasted list or a CSV file.</p><div id="axImportSec">' + importHtml() + "</div></section>";
  }

  // ---- placeholders in Practice settings ----
  function chartPlaceholdersHtml() {
    var vals = valuesMap();
    var groups = data.chartGroups.map(function (g, gi) {
      var on = g.items.filter(function (i) { return data.chartEnabled.indexOf(i.name) >= 0; }).length, all = on === g.items.length;
      var rows = g.items.map(function (i) {
        var checked = data.chartEnabled.indexOf(i.name) >= 0;
        return '<tr class="' + (checked ? "" : "off") + '"><td class="ck"><input type="checkbox" data-chartck="' + esc(i.name) + '"' + (checked ? " checked" : "") + ' aria-label="Show {' + esc(i.name) + '} in the menus"></td>' +
          '<td class="tk"><span class="tok">{' + esc(i.name) + '}</span></td><td class="lb">' + esc(i.label) + (CHART_RULE[i.name] ? '<span class="ph-rule">' + esc(CHART_RULE[i.name]) + "</span>" : "") + "</td>" +
          '<td class="ex">' + esc(vals[i.name] || "") + "</td></tr>";
      }).join("");
      return '<div class="ph-grp"><div class="pk-gh"><span>' + esc(g.name) + '</span><span class="cnt">' + on + " of " + g.items.length + ' on</span><button type="button" class="pk-all" data-chartgrp="' + gi + '">' + (all ? "Clear all" : "Select all") + "</button></div>" +
        '<table class="ph-tbl"><thead><tr><th class="ck"><span class="sr">Show in menus</span></th><th class="tk">Placeholder</th><th class="lb">What it fills in</th><th class="ex">Example</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
    }).join("");
    return '<section class="ax-sec"><h3>Chart placeholders</h3><p>Filled from the patient\'s chart and the note when a phrase is used. Check the ones your practice uses; they appear in the phrase editor\'s Patient menu and the placeholder guide. Unchecked ones still fill in if someone types them.</p><p class="ph-note">Examples are for a made-up patient, Connie Canvas.</p>' + groups + "</section>";
  }
  function customPlaceholdersHtml() {
    var keyOptions = function (current) {
      var keys = data.metadataKeys.slice(); if (current && keys.indexOf(current) < 0) { keys.unshift(current); }
      return '<option value="">Pick a patient detail</option>' + keys.map(function (k) { return '<option value="' + esc(k) + '"' + (k === current ? " selected" : "") + ">" + esc(k) + "</option>"; }).join("");
    };
    var rowsHtml = data.custom.map(function (c) {
      return '<tr><td><span class="tok">{' + esc(c.name) + '}</span></td><td><select class="ax-sel" data-ckey="' + esc(c.name) + '" aria-label="Patient detail for ' + esc(c.name) + '">' + keyOptions(c.key) + "</select></td>" +
        '<td class="used">' + c.used_in + " phrase" + (c.used_in === 1 ? "" : "s") + '</td><td><button class="ax-btn quiet" data-csave="' + esc(c.name) + '">Save</button><button class="ax-btn quiet" data-cdel="' + esc(c.name) + '">Remove</button></td></tr>';
    }).join("");
    return '<section class="ax-sec"><h3>Custom patient placeholders</h3><p>Filled from a patient detail your practice or its plugins store on the patient (patient metadata), such as a program or care coordinator. Pick the detail each one reads from.</p>' +
      '<table class="ax-tbl"><thead><tr><th style="width:30%">Name</th><th>Reads from</th><th style="width:100px">Used in</th><th style="width:140px"></th></tr></thead><tbody>' + rowsHtml +
      '<tr class="add"><td><input class="ax-in" id="axCName" placeholder="care_coordinator" aria-label="New placeholder name"></td><td><select class="ax-sel" id="axCKey" aria-label="Patient detail it reads from">' + keyOptions("") + "</select></td>" +
      '<td colspan="2"><button class="ax-btn" data-cadd>Add</button></td></tr></tbody></table>' +
      '<div class="ax-help">The list shows details already stored on patients in this instance' + (data.metadataCapped ? ", showing the first " + data.metadataKeys.length + "." : ".") + ' A patient with nothing stored for it keeps the placeholder as typed, to fill in before recording.</div><div class="ax-err" id="axCErr"></div></section>';
  }
  function saveChartChoices(list, msg) {
    api("POST", "/admin/settings", { chart_placeholders: list }).then(function (r) { data.chartEnabled = r.chart_enabled || list; toast(msg); return load(); })
      .catch(function (er) { toast(er.message); render(); });
  }

  // ---- import ----
  var SAMPLE_IMPORT = "ckdplan, Plan, Recheck kidney function in 3 months.\nacpdiscuss, Any, Discussed advance care planning with {first_name}.";
  function renderImport() { var box = $("#axImportSec"); if (box) { box.innerHTML = importHtml(); } }
  function importHtml() {
    var steps = ["Add your list", "Check it", "Import"].map(function (s, i) { return '<li class="' + (impStep === i + 1 ? "on" : impStep > i + 1 ? "done" : "") + '">' + s + "</li>"; }).join("");
    var body = "";
    if (impStep === 1) {
      body = '<p class="ax-sub" style="margin:0 0 12px">One phrase per line: <span class="tok">code, use in, text</span>. Use in is All, or commands separated by / such as Plan / Instruct. Sig and Note to pharmacist work too.</p>' +
        '<textarea class="ax-ta" id="axImport" rows="8" placeholder="' + esc(SAMPLE_IMPORT) + '">' + esc(impText || "") + "</textarea>" +
        '<div class="ax-imp-row"><label class="ax-btn" style="cursor:pointer">Upload a CSV<input type="file" accept=".csv,text/csv" id="axFile" hidden></label><button class="ax-btn quiet" data-template>Download the CSV template</button><span class="grow"></span><button class="ax-btn primary" data-check>Check the list</button></div>';
    } else if (impStep === 2) {
      var ok = impRows.filter(function (r) { return !r.why; }).length, bad = impRows.length - ok;
      body = '<p class="ax-sum">' + ok + " ready to import." + (bad ? ' <span class="bad">' + bad + " need fixing and will be skipped.</span>" : "") + "</p>" +
        '<table class="ax-check-tbl"><tbody>' + impRows.map(function (r) {
          return '<tr><td class="st ' + (r.why ? "bad" : "ok") + '">' + (r.why ? "✕" : "✓") + '</td><td class="code">.' + esc(r.code || "?") + "</td><td>" + (r.why ? "" : (chips(r) || '<span class="tag any">All commands</span>')) + "</td><td>" + esc(r.text) + (r.why ? '<span class="why">' + esc(r.why) + "</span>" : "") + "</td></tr>";
        }).join("") + "</tbody></table>" +
        '<div class="ax-imp-row"><button class="ax-btn" data-back1>Back to the list</button><span class="grow"></span><button class="ax-btn primary" data-import' + (ok ? "" : " disabled") + ">Import " + ok + " phrase" + (ok === 1 ? "" : "s") + "</button></div>";
    } else {
      body = '<div class="ax-done"><b>Imported ' + impDone + " practice phrase" + (impDone === 1 ? "" : "s") + '</b><p class="ax-sub" style="margin:0 auto 16px">They\'re in Practice phrases now, and everyone can use them.</p>' +
        '<button class="ax-btn primary" data-seephr>See practice phrases</button> <button class="ax-btn" data-again>Import another list</button></div>';
    }
    return '<div class="ax-imp"><ol class="ax-steps">' + steps + "</ol>" + body + "</div>";
  }
  function csvToLines(csv) {
    // Accepts a CSV with code, use in, text columns; quoted text may contain commas.
    return csv.split(/\r?\n/).filter(function (l) { return l.trim(); }).map(function (line) {
      var cells = [], cur = "", q = false;
      for (var i = 0; i < line.length; i++) {
        var ch = line[i];
        if (ch === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else { q = !q; } }
        else if (ch === "," && !q && cells.length < 2) { cells.push(cur); cur = ""; }
        else { cur += ch; }
      }
      cells.push(cur);
      return cells.map(function (c) { return c.trim(); }).join(", ");
    }).filter(function (l, i) { return !(i === 0 && /^code\s*,/i.test(l)); }).join("\n");
  }

  // ---- events ----
  document.addEventListener("click", function (e) { if (!e.target.closest(".ax-menu")) { closeMenus(); } });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { closeMenus(); } });
  ["click", "keyup", "select"].forEach(function (ev) { document.addEventListener(ev, function (e) { if (e.target && e.target.id === "axText") { adCaret = e.target.selectionEnd; } }); });
  $("#axMain").addEventListener("click", function (e) {
    var t = e.target, el = function (s) { return t.closest(s); };
    if (el("[data-sel]")) {
      var id = Number(el("[data-sel]").getAttribute("data-sel")), target = pool().filter(function (p) { return p.id === id; })[0];
      if (target === adSel) { return; }
      guard(function () { select(target); }); return;
    }
    if (el("[data-new]")) { guard(function () { select("new"); setTimeout(function () { var c = $("#axCode"); if (c) { c.focus(); } }); }); return; }
    if (el("[data-keep]")) { adPending = null; render(); return; }
    if (el("[data-hide]")) {
      var hp = adSel, hb = el("[data-hide]"); if (hb.disabled) { return; } hb.disabled = true;
      api("POST", "/phrases/hide", { phrase_ids: [hp.id], hidden: !hp.hidden })
        .then(function (r) { toast(r.hidden ? "Hid ." + hp.code + " from your chart panel list. Typing it still works." : "." + hp.code + " is back in your chart panel list."); adSel = { id: hp.id }; return load(); })
        .catch(function (er) { hb.disabled = false; toast(er.message); });
      return;
    }
    if (el("[data-opencopy]")) { var oc = myCopy(adSel); adTab = "mine"; adQ = ""; renderTabs(); select(oc); return; }
    if (el("[data-copy]")) {
      var cp = adSel, cb = el("[data-copy]"); if (cb.disabled) { return; } cb.disabled = true;
      api("POST", "/phrases", { code: cp.code, text: cp.text, use_in: cp.use_in, rx_sig: cp.rx_sig, rx_note_to_pharmacist: cp.rx_note_to_pharmacist, scope: "personal" })
        .then(function (r) { toast("Made your own ." + cp.code + ". Change it here; only you use it."); adTab = "mine"; adQ = ""; adSel = { id: r.phrase.id }; return load(); })
        .catch(function (er) { cb.disabled = false; toast(er.message); });
      return;
    }
    if (el("[data-discard]")) { var go = adPending; adPending = null; adDraft = null; go(); return; }
    if (el("[data-cancel]")) { adSel = null; adDraft = null; render(); return; }
    if (el("[data-save]")) { save(); return; }
    if (el("[data-delete]")) { adConfirm = true; render(); var cf = $(".ax-confirm"); if (cf) { cf.scrollIntoView({ block: "nearest" }); cf.querySelector("[data-delno]").focus(); } return; }
    if (el("[data-delno]")) { adConfirm = false; render(); return; }
    if (el("[data-delyes]")) {
      var pd = adSel;
      api("DELETE", "/phrases/" + pd.id).then(function () { toast("Deleted ." + pd.code); adConfirm = false; adSel = null; adDraft = null; return load(); })
        .catch(function (er) { adConfirm = false; render(); toast(er.message); });
      return;
    }
    if (el("[data-menu]")) { var m = el(".ax-menu"), pop = m.querySelector(".ax-pop"), open = pop.hidden; closeMenus(m); pop.hidden = !open; el("[data-menu]").setAttribute("aria-expanded", String(open)); return; }
    if (el("[data-ins]")) { var b = el("[data-ins]"); closeMenus(); insertAtCaret(b.getAttribute("data-ins"), b.getAttribute("data-hl")); return; }
    if (el("#axUseBlock") && adDraft && useHandle(e, $("#axUseBlock"), adDraft)) { updDetail(); return; }
    if (el("[data-guide]")) {
      closeMenus(); guideOpen = !guideOpen;
      if (!adSel) { render(); return; }
      var g = $("#axGuide"); g.hidden = !guideOpen; $$("#axMain [data-guide]").forEach(function (x) { x.setAttribute("aria-expanded", String(guideOpen)); });
      if (guideOpen) { g.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
      return;
    }
    if (el("[data-fsave]")) {
      var name = el("[data-fsave]").getAttribute("data-fsave"), input = $('[data-fv="' + name + '"]');
      api("POST", "/admin/values", { name: name, value: input.value }).then(function () { toast("Saved {" + name + "}"); return load(); }).catch(function (er) { $("#axFillErr").textContent = er.message; });
      return;
    }
    if (el("[data-fdel]")) { var dn = el("[data-fdel]").getAttribute("data-fdel"); api("DELETE", "/admin/values/" + encodeURIComponent(dn)).then(function () { toast("Removed {" + dn + "}"); return load(); }).catch(function (er) { toast(er.message); }); return; }
    if (el("[data-fadd]")) {
      api("POST", "/admin/values", { name: $("#axNewName").value.trim(), value: $("#axNewVal").value.trim() })
        .then(function (r) { toast("Added {" + r.name + "}"); return load(); }).catch(function (er) { $("#axFillErr").textContent = er.message; });
      return;
    }
    if (el("[data-chartgrp]")) {
      var g = data.chartGroups[Number(el("[data-chartgrp]").getAttribute("data-chartgrp"))], names = g.items.map(function (i) { return i.name; });
      var allOn = names.every(function (n) { return data.chartEnabled.indexOf(n) >= 0; });
      var next = allOn ? data.chartEnabled.filter(function (n) { return names.indexOf(n) < 0; }) : data.chartEnabled.concat(names.filter(function (n) { return data.chartEnabled.indexOf(n) < 0; }));
      saveChartChoices(next, (allOn ? "Hid " : "Showing ") + g.name.toLowerCase() + " placeholders in the menus");
      return;
    }
    if (el("[data-cadd]") || el("[data-csave]")) {
      var adding = !!el("[data-cadd]"), cname = adding ? $("#axCName").value.trim() : el("[data-csave]").getAttribute("data-csave");
      var ckey = adding ? $("#axCKey").value : $('[data-ckey="' + cname + '"]').value;
      api("POST", "/admin/custom-placeholders", { name: cname, key: ckey }).then(function (r) { toast((adding ? "Added {" : "Saved {") + r.name + "}"); return load(); })
        .catch(function (er) { $("#axCErr").textContent = er.message; });
      return;
    }
    if (el("[data-cdel]")) {
      var cd = el("[data-cdel]").getAttribute("data-cdel");
      api("DELETE", "/admin/custom-placeholders/" + encodeURIComponent(cd)).then(function () { toast("Removed {" + cd + "}"); return load(); }).catch(function (er) { toast(er.message); });
      return;
    }
    if (el("[data-template]")) {
      var csv = "code,use in,text\nfu2w,Plan,Follow up in 2 weeks.\nmetf500,Sig,Take 1 tablet by mouth twice daily with meals\n";
      var a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "dot-phrases-template.csv"; a.click(); URL.revokeObjectURL(a.href);
      return;
    }
    if (el("[data-check]")) {
      impText = $("#axImport").value;
      api("POST", "/admin/import/check", { text: impText }).then(function (r) { impRows = r.rows || []; impStep = 2; renderImport(); }).catch(function (er) { toast(er.message); });
      return;
    }
    if (el("[data-back1]")) { impStep = 1; renderImport(); return; }
    if (el("[data-import]")) { var ib = el("[data-import]"); if (ib.disabled) { return; } ib.disabled = true; api("POST", "/admin/import", { text: impText }).then(function (r) { impDone = r.imported || 0; impStep = 3; impText = ""; return load(); }).catch(function (er) { ib.disabled = false; toast(er.message); }); return; }
    if (el("[data-seephr]")) { impStep = 1; adTab = "phrases"; adSel = null; selectTab(); return; }
    if (el("[data-again]")) { impStep = 1; impText = ""; renderImport(); }
  });
  $("#axMain").addEventListener("input", function (e) {
    var t = e.target;
    if (t.id === "axQ") { adQ = t.value; var pos = t.selectionStart; render(); var q = $("#axQ"); q.focus(); q.setSelectionRange(pos, pos); return; }
    if (t.id === "axCode") { t.value = t.value.toLowerCase().replace(/[^a-z0-9]/g, ""); adDraft.code = t.value; updDetail(); return; }
    if (t.id === "axText") { adDraft.text = t.value; adCaret = t.selectionEnd; updDetail(); }
  });
  $("#axMain").addEventListener("change", function (e) {
    var t = e.target;
    if (t.getAttribute("data-chartck")) {
      var n = t.getAttribute("data-chartck");
      var list = t.checked ? data.chartEnabled.concat([n]) : data.chartEnabled.filter(function (x) { return x !== n; });
      saveChartChoices(list, (t.checked ? "Showing {" : "Hid {") + n + "}" + (t.checked ? " in the menus" : " from the menus"));
      return;
    }
    if (t.getAttribute("data-setting")) {
      api("POST", "/admin/settings", { allow_copy_text: t.checked }).then(function (r) { data.allowCopy = !!r.allow_copy_text; toast(data.allowCopy ? "Copying is on for everyone" : "Copying is off for everyone"); })
        .catch(function (er) { t.checked = !t.checked; toast(er.message); });
      return;
    }
    if (t.closest("#axUseBlock") && adDraft && useHandle(e, $("#axUseBlock"), adDraft)) { updDetail(); return; }
    if (t.id === "axFile" && t.files && t.files[0]) {
      var reader = new FileReader();
      reader.onload = function () { impText = csvToLines(String(reader.result || "")); renderImport(); };
      reader.readAsText(t.files[0]);
    }
  });

  load();
})();
{% endverbatim %}
