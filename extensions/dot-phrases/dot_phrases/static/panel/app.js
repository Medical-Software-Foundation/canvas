{% verbatim %}
/* Dot Phrases chart panel: browse, insert, copy, and manage phrases for the open note. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var API = document.body.getAttribute("data-api-base");
  var NOTE_ID = document.body.getAttribute("data-note-id") || "";

  var state = {
    phrases: [], isAdmin: false, allowCopy: true, rxTargets: [],
    commands: [], labels: {}, limits: {}, rxFields: {}, practiceNames: [], patientNames: {}, menu: [], values: {}
  };
  var filter = "all", openId = null, answers = [], target = null, mArch = "active", selecting = false, selected = {};

  var SHORT = { plan: "Plan", hpi: "HPI", instruct: "Instruct", perform: "Perform" };
  var INSERTABLE = ["plan", "hpi", "instruct", "perform"];
  var PLACEHOLDER = /\{(pick|blank)\s+([a-z_ ]*?)\s*(?::\s*([^}]*))?\}|\{([a-z_]+)\}|\*\*\*/gi;

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  // Bold the checkbox names in a prescription warning, already escaped: "uncheck <b>Sig</b> under <b>Use in</b>".
  function boldUi(html) { return html.replace(/uncheck (Sig|Note to pharmacist) under Use in/g, "uncheck <b>$1</b> under <b>Use in</b>"); }
  function toast(m) { var t = $("#toast"); t.textContent = m; t.style.pointerEvents = "none"; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove("on"); }, 2200); }
  // A toast with an Undo button, for hiding.
  function toastUndo(m, undo) {
    var t = $("#toast"); t.innerHTML = esc(m) + ' <button class="toast-undo">Undo</button>'; t.style.pointerEvents = "auto"; t.classList.add("on");
    t.querySelector(".toast-undo").addEventListener("click", function () { t.classList.remove("on"); t.style.pointerEvents = "none"; undo(); });
    clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove("on"); t.style.pointerEvents = "none"; }, 5000);
  }

  // The browser's time zone, so {today} and {age} match the clock the provider sees.
  function browserZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (err) { return ""; }
  }
  function api(method, path, body) {
    return fetch(API + path, {
      method: method, credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { throw new Error(data.error || "Something went wrong. Try again."); }
        return data;
      });
    });
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(fallback);
    }
    return Promise.resolve(fallback());
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } finally { document.body.removeChild(ta); }
    }
  }

  // ---- placeholders (mirrors dot_phrases/text.py) ----
  function bracket(kind, label, options) {
    if (kind.toLowerCase() === "pick") {
      var opts = (options || "").split("|").map(function (o) { return o.trim(); }).filter(Boolean);
      return "[" + (opts.length ? opts.join(" / ") : (label.trim() || "choose")) + "]";
    }
    return "[" + (label.trim() || "details") + "]";
  }
  function fillIns(text) {
    var out = [], blanks = 0, m; PLACEHOLDER.lastIndex = 0;
    while ((m = PLACEHOLDER.exec(text))) {
      if (m[1] && m[1].toLowerCase() === "pick") {
        out.push({ kind: "pick", label: (m[2] || "").trim() || "choose", options: (m[3] || "").split("|").map(function (o) { return o.trim(); }).filter(Boolean) });
      } else if (m[1]) {
        out.push({ kind: "blank", label: (m[2] || "").trim() || "details", options: [] });
      } else if (m[4] == null) {
        blanks += 1; out.push({ kind: "blank", label: "Blank " + blanks, options: [] });
      }
    }
    return out;
  }
  // Fill for display. html=true highlights filled values and what's left to fill in.
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
  function fill(text, ans, html) {
    var i = 0;
    return (html ? replaceAsHtml.bind(null, text, PLACEHOLDER) : text.replace.bind(text, PLACEHOLDER))(function (all, kind, label, options, name, offset) {
      var wrapVal = function (v) { return html ? '<span class="val">' + esc(v) + "</span>" : v; };
      var wrapGap = function (v) { return html ? '<span class="gap">' + esc(v) + "</span>" : v; };
      if (name != null) {
        var v = state.values[name.toLowerCase()];
        if (!v) { return wrapGap(all); }
        var before = text.slice(0, offset).replace(/\s+$/, "");
        if (!before || /[.!?]$/.test(before)) { v = v.charAt(0).toUpperCase() + v.slice(1); }
        return wrapVal(v);
      }
      var a = ans && ans[i] ? String(ans[i]).trim() : ""; i += 1;
      if (a) { return wrapVal(a); }
      if (kind == null) { return wrapGap("***"); }
      return wrapGap(bracket(kind, label || "", options));
    });
  }
  function previewHtml(text) { return fill(text, [], true).replace(/<span class="gap">/g, '<span class="fi">'); }
  function hasPlaceholders(text) { PLACEHOLDER.lastIndex = 0; return PLACEHOLDER.test(text); }
  function unknownPlaceholders(text) {
    var out = [], m; PLACEHOLDER.lastIndex = 0;
    while ((m = PLACEHOLDER.exec(text))) {
      if (m[4] != null) {
        var n = m[4].toLowerCase();
        if (!(n in state.patientNames) && state.practiceNames.indexOf(n) < 0) { out.push(m[0]); }
      }
    }
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
  function rxProblems(field, text) {
    var max = state.rxFields[field].max, p = [];
    if (text.length > max) { p.push("over " + max.toLocaleString() + " characters"); }
    if (/[\r\n]/.test(text)) { p.push("has a line break"); } else if (/[^ -~]/.test(text)) { p.push("has special characters"); }
    return p;
  }

  // ---- labels ----
  function shortLabel(k) { return SHORT[k] || state.labels[k] || k; }
  function chipsHtml(p) {
    var tags = [];
    (p.use_in || []).forEach(function (k) { tags.push('<span class="tag ' + (SHORT[k] || "any") + '">' + esc(shortLabel(k)) + "</span>"); });
    if (p.rx_sig) { tags.push('<span class="tag Sig">Sig</span>'); }
    if (p.rx_note_to_pharmacist) { tags.push('<span class="tag NTP">Note to pharmacist</span>'); }
    return tags.length ? '<div class="pc-uses">' + tags.join("") + "</div>" : "";
  }
  function ago(iso) {
    if (!iso) { return "Not used yet"; }
    var days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    return days <= 0 ? "Used today" : days === 1 ? "Used yesterday" : "Used " + days + " days ago";
  }

  // ---- where Insert can put a phrase ----
  function targetsFor(p) {
    var t = INSERTABLE.filter(function (k) { return p.use_in === null || p.use_in.indexOf(k) >= 0; });
    if (state.rxTargets.indexOf("sig") >= 0 && p.rx_sig) { t.push("sig"); }
    if (state.rxTargets.indexOf("note_to_pharmacist") >= 0 && p.rx_note_to_pharmacist) { t.push("note_to_pharmacist"); }
    return t;
  }
  function targetLabel(k) { return state.rxFields[k] ? state.rxFields[k].label : SHORT[k]; }
  function noTargetMsg(p) {
    if (p.rx_sig) { return "Sig phrase. Open a prescription in this note to insert it, or type ." + p.code + " in the Sig."; }
    if (p.rx_note_to_pharmacist) { return "Note to pharmacist phrase. Open a prescription in this note to insert it, or type ." + p.code + " there."; }
    var where = (p.use_in || []).map(function (k) { return state.labels[k] || k; }).join(", ");
    return "Works in " + where + ". Type ." + p.code + " in one of those.";
  }

  var HIDE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c5 0 9 4.5 10 7a13 13 0 0 1-3.1 4.1"/><path d="M6.6 6.6C4.3 8 2.7 10.2 2 12c1 2.5 5 7 10 7a9.8 9.8 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  var COPY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>';

  // ---- hiding practice phrases (per person; typing the code still works) ----
  function hiddenCount() { return state.phrases.filter(function (p) { return p.hidden; }).length; }
  function setHidden(ids, on) {
    return api("POST", "/phrases/hide", { phrase_ids: ids, hidden: on }).then(function () {
      state.phrases.forEach(function (p) { if (ids.indexOf(p.id) >= 0) { p.hidden = on; } });
      renderList(); if (!$("#ppManage").hidden) { renderManage(); }
    });
  }
  function hideWithUndo(ids, label) {
    return setHidden(ids, true).then(function () {
      toastUndo(label, function () { setHidden(ids, false).catch(function (er) { toast(er.message); }); });
    }).catch(function (er) { toast(er.message); });
  }

  // ---- list ----
  function card(p) {
    var open = openId === p.id, ts = targetsFor(p), fs = p.fill_ins || [], edge = p.mine ? "pc-mine" : "pc-team";
    var t = open && target && ts.indexOf(target) >= 0 ? target : ts[0];
    var top = '<div class="pc-top"><button type="button" class="pc-code pc-codebtn" data-copycode title="Copy .' + esc(p.code) + '">.' + esc(p.code) + "</button>" +
      '<button class="pc-star' + (p.favorite ? " on" : "") + '" data-star title="' + (p.favorite ? "Unstar" : "Star") + '" aria-label="' + (p.favorite ? "Unstar" : "Star") + " ." + esc(p.code) + '">' + (p.favorite ? "★" : "☆") + "</button>" +
      '<span class="pc-grow"></span>' +
      (open && p.scope === "practice" ? '<button class="pc-hide" data-hide title="Hide from my list" aria-label="Hide .' + esc(p.code) + ' from my list">' + HIDE_ICON + "</button>" : "") +
      (open ? '<button class="pc-chev" title="Close" aria-label="Close">⌃</button>' : "") + "</div>";
    var plus = ts.length ? '<button class="pc-plus" data-insert title="Insert into ' + esc(targetLabel(ts[0])) + '" aria-label="Insert .' + esc(p.code) + " into " + esc(targetLabel(ts[0])) + '">+</button>' : "";
    if (!open) {
      return '<div class="pc ' + edge + '" data-id="' + p.id + '"><div class="pc-main">' + top + '<div class="pc-prev">' + previewHtml(p.text) + "</div>" + chipsHtml(p) + "</div>" + plus + "</div>";
    }
    var asks = fs;
    var askHtml = asks.map(function (f, i) {
      if (f.kind === "pick") {
        return '<div class="pc-label">' + esc(f.label) + '</div><div class="pc-choices" data-pick="' + i + '">' +
          f.options.map(function (o) { return '<button class="' + (answers[i] === o ? "on" : "") + '" data-v="' + esc(o) + '">' + esc(o.charAt(0).toUpperCase() + o.slice(1)) + "</button>"; }).join("") + "</div>";
      }
      return '<div class="pc-label">' + esc(f.label) + '</div><input class="pc-input" data-blank="' + i + '" value="' + esc(answers[i] || "") + '" placeholder="' + esc(f.label) + '">';
    }).join("");
    var targetHtml = ts.length > 1 ? '<div class="pc-label">Add as</div><div class="pc-choices" data-target>' +
      ts.map(function (k) { return '<button class="' + (k === t ? "on" : "") + '" data-t="' + k + '">' + esc(targetLabel(k)) + "</button>"; }).join("") + "</div>" : "";
    var go = ts.length ? '<button class="pp-btn pp-primary" data-insert data-to="' + t + '">Insert into ' + esc(targetLabel(t)) + "</button>" :
      '<span style="font-size:12.5px;color:#5e7a8a;flex:1">' + esc(noTargetMsg(p)) + "</span>";
    var copy = state.allowCopy ? '<button class="pc-copytext" data-copy title="Copy the full text">' + COPY_ICON + "Copy</button>" : "";
    var meta = ago(p.last_used_at) + (p.mine ? ' · <a data-edit href="#">Edit</a>' : "");
    return '<div class="pc open ' + edge + '" data-id="' + p.id + '"><div class="pc-main">' + top + '<div class="pc-body">' +
      '<div class="pc-preview" id="pv">' + fill(p.text, answers, true) + "</div>" + chipsHtml(p) + askHtml + targetHtml +
      '<div class="pc-go">' + go + copy + "</div>" + '<div class="pc-meta">' + meta + "</div></div></div></div>";
  }

  function renderList() {
    var q = $("#q").value.trim().toLowerCase().replace(/^\./, "");
    var list = state.phrases.filter(function (p) {
      if (p.hidden) { return false; }
      if (filter === "mine" && !p.mine) { return false; }
      if (filter === "practice" && p.scope !== "practice") { return false; }
      return !q || p.code.indexOf(q) >= 0 || p.text.toLowerCase().indexOf(q) >= 0;
    });
    var byRecent = function (a, b) { return (b.last_used_at || "").localeCompare(a.last_used_at || "") || a.code.localeCompare(b.code); };
    var starred = list.filter(function (p) { return p.favorite; }).sort(byRecent);
    var rest = list.filter(function (p) { return !p.favorite; }).sort(byRecent);
    var html = "";
    if (!state.phrases.length) {
      html = '<p class="empty">No phrases yet. Use the settings button to make your first one.</p>';
    } else if (!list.length) {
      html = '<p class="empty">No phrases match.</p>';
    } else {
      if (starred.length) { html += '<div class="pp-sec">Starred</div>' + starred.map(card).join(""); }
      if (rest.length) { html += '<div class="pp-sec">Recent</div>' + rest.map(card).join(""); }
    }
    var nh = hiddenCount();
    if (nh && state.phrases.length) {
      html += '<p class="ml-foot">' + nh + " practice phrase" + (nh === 1 ? " is" : "s are") + ' hidden from your list. <a href="#" class="linkish" data-gohidden>See hidden</a></p>';
    }
    $("#plist").innerHTML = html;
  }

  function find(id) { return state.phrases.filter(function (p) { return p.id === id; })[0]; }

  // Where Insert goes: the note the panel was opened from.
  function renderAddingTo(note) {
    var box = $("#addingTo");
    if (!note) { box.hidden = true; return; }
    // "Oct 15, 2026 at 12:23 PM EDT with Canvas Support", in the browser's time zone.
    var when = note.when ? new Date(note.when) : null, at = "";
    if (when && !isNaN(when)) {
      at = when.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) + " at " +
        when.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    }
    var line = at && note.provider ? at + " with " + note.provider : at || (note.provider ? "With " + note.provider : "");
    box.innerHTML = '<span class="lbl">Adding to</span><div class="target">' + esc(note.title) + "<span>" + esc(line) + "</span></div>";
    box.hidden = false;
  }
  function load() {
    return api("GET", "/phrases?note_id=" + encodeURIComponent(NOTE_ID) + "&tz=" + encodeURIComponent(browserZone())).then(function (d) {
      state.phrases = d.phrases || []; renderAddingTo(d.note);
      state.isAdmin = !!d.is_admin; state.adminTeam = d.admin_team || ""; state.allowCopy = !!d.allow_copy_text; state.rxTargets = d.rx_targets || [];
      state.commands = d.commands || []; state.labels = {};
      state.commands.forEach(function (c) { state.labels[c.key] = c.label; });
      state.limits = d.field_limits || {}; state.rxFields = d.rx_fields || {};
      state.practiceNames = d.practice_names || []; state.patientNames = d.patient_placeholders || {}; state.menu = d.menu_placeholders || []; state.values = d.values || {};
      renderList();
      if (!$("#ppManage").hidden) { renderManage(); }
    }).catch(function (e) { $("#plist").innerHTML = '<p class="empty">' + esc(e.message) + "</p>"; });
  }

  $$("#chips button").forEach(function (c) {
    c.addEventListener("click", function () { filter = c.getAttribute("data-f"); $$("#chips button").forEach(function (x) { x.classList.toggle("on", x === c); }); renderList(); });
  });
  $("#q").addEventListener("input", renderList);

  function insert(p, to) {
    var ans = openId === p.id ? answers : [];
    return api("POST", "/notes/" + encodeURIComponent(NOTE_ID) + "/insert", { phrase_id: p.id, target: to, answers: ans, tz: browserZone() }).then(function () {
      toast(state.rxFields[to] ? "Filled the prescription's " + targetLabel(to).toLowerCase() : "Added as a new " + targetLabel(to));
      openId = null; return load();
    }).catch(function (e) { toast(e.message); });
  }

  $("#plist").addEventListener("click", function (e) {
    var t = e.target;
    if (t.closest("[data-gohidden]")) { e.preventDefault(); openManage(); selectMSeg("hidden"); return; }
    var c = t.closest(".pc"); if (!c) { return; }
    var p = find(Number(c.getAttribute("data-id"))); if (!p) { return; }
    if (t.closest("[data-star]")) {
      api("POST", "/phrases/" + p.id + "/favorite").then(function (d) { p.favorite = !!d.favorite; renderList(); }).catch(function (er) { toast(er.message); });
      return;
    }
    if (t.closest("[data-copycode]")) { copyText("." + p.code).then(function () { toast("Copied ." + p.code + ". Paste it into a note field and it fills in after saving."); }); return; }
    var tg = t.closest("[data-target] button"); if (tg) { target = tg.getAttribute("data-t"); renderList(); return; }
    var pk = t.closest("[data-pick] button");
    if (pk) { answers[Number(pk.parentElement.getAttribute("data-pick"))] = pk.getAttribute("data-v"); renderList(); return; }
    if (t.closest("[data-edit]")) { e.preventDefault(); openEditor(p, "list"); return; }
    if (t.closest("[data-hide]")) { openId = null; hideWithUndo([p.id], "Hid ." + p.code + " from your list. Typing it still works."); return; }
    if (t.closest("[data-copy]")) {
      var txt = fill(p.text, answers, false);
      copyText(txt).then(function () {
        toast(/\[[^\]]+\]|\*\*\*/.test(txt) ? "Copied the text of ." + p.code + ". Fill in the [brackets] after pasting." : "Copied the text of ." + p.code);
        api("POST", "/phrases/" + p.id + "/used").catch(function () {});
      });
      return;
    }
    var ins = t.closest("[data-insert]");
    if (ins) {
      var ts = targetsFor(p); if (!ts.length) { return; }
      var to = ins.getAttribute("data-to") || ts[0];
      var needsAsk = (p.fill_ins || []).length;
      if (openId !== p.id && (needsAsk || ts.length > 1)) { openId = p.id; answers = []; target = ts[0]; renderList(); return; }
      insert(p, to); return;
    }
    if (t.closest(".pc-chev")) { openId = null; renderList(); return; }
    if (t.closest(".pc-body")) { return; }
    openId = openId === p.id ? null : p.id; answers = []; target = null; renderList();
  });
  $("#plist").addEventListener("input", function (e) {
    var b = e.target.closest("[data-blank]"); if (!b) { return; }
    var p = find(openId); answers[Number(b.getAttribute("data-blank"))] = b.value;
    $("#pv").innerHTML = fill(p.text, answers, true);
  });

  // ---- screens: the list, Manage phrases, and the edit screen ----
  var editReturn = "manage", editDirty = null;
  function showView(v) {
    $("#ppList").hidden = v !== "list"; $("#ppManage").hidden = v !== "manage"; $("#ppEdit").hidden = v !== "edit";
    if (v !== "edit") { $("#editorSlot").innerHTML = ""; }
    if (v === "list") { renderList(); }
    if (v === "manage") { renderManage(); }
    window.scrollTo(0, 0);
  }
  function openEditScreen(title, from) { editReturn = from || "manage"; $("#edTitle").textContent = title; showView("edit"); }
  function leaveEdit() { editDirty = null; showView(editReturn); }
  // The back arrow asks before dropping unsaved edits. Cancel is a deliberate discard, so it doesn't ask.
  function askDiscard(title) {
    if ($("#edDiscard")) { return; }
    var box = document.createElement("div");
    box.className = "ed ed-discard"; box.id = "edDiscard"; box.setAttribute("role", "alertdialog"); box.setAttribute("aria-labelledby", "dsTitle");
    box.innerHTML = '<div class="cf-title" id="dsTitle">' + esc(title) + "</div><p>Your edits haven't been saved.</p>" +
      '<div class="row"><button class="pp-btn" id="dsKeep">Keep editing</button><button class="pp-btn pp-primary" id="dsDrop" style="flex:1">Discard changes</button></div>';
    $("#editorSlot").insertBefore(box, $("#editorSlot").firstChild);
    $("#dsKeep").addEventListener("click", function () { box.parentNode.removeChild(box); });
    $("#dsDrop").addEventListener("click", leaveEdit);
    window.scrollTo(0, 0); $("#dsKeep").focus();
  }
  // If Canvas closes the panel or the page reloads mid-edit, the browser asks too (where it allows it).
  window.addEventListener("beforeunload", function (e) { if (editDirty && editDirty()) { e.preventDefault(); e.returnValue = ""; } });
  $("#edBack").addEventListener("click", function () {
    var d = editDirty && editDirty();
    if (d) { askDiscard(d); } else { leaveEdit(); }
  });

  // ---- manage ----
  function openManage() { showView("manage"); }
  $("#gear").addEventListener("click", openManage);
  $("#back").addEventListener("click", function () { showView("list"); });
  function selectMSeg(a) {
    mArch = a; selecting = false; selected = {};
    $$("#mArchSeg button").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-a") === a); });
    renderManage();
  }
  $$("#mArchSeg button").forEach(function (b) { b.addEventListener("click", function () { selectMSeg(b.getAttribute("data-a")); }); });
  function selectedIds() { return Object.keys(selected).map(Number); }
  var EDIT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
  var TRASH_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';
  var DUP_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';
  var OPEN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';
  var LOCK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
  // Who manages practice phrases: the team named in the plugin's ADMIN_TEAM setting.
  function admins() { return state.adminTeam || "your practice's admins"; }
  function icon(attr, id, label, svg) { return '<button class="ml-icon" ' + attr + '="' + id + '" title="' + label + '" aria-label="' + label + '">' + svg + "</button>"; }
  function mrow(p, kind) {
    var pickable = selecting && (kind === "practice" || kind === "hidden"), on = pickable && selected[p.id], c = " ." + esc(p.code);
    var attr = pickable ? 'data-toggle="' + p.id + '"' : kind === "mine" ? 'data-medit="' + p.id + '"' : kind === "practice" ? 'data-mview="' + p.id + '"' : "";
    var pick = pickable ? '<input type="checkbox" class="ml-pick" data-pickid="' + p.id + '"' + (on ? " checked" : "") + ' aria-label="Select' + c + '" tabindex="-1">' : "";
    var tail = kind === "mine" ? icon("data-medit", p.id, "Edit" + c, EDIT_ICON) + icon("data-mdel", p.id, "Delete" + c, TRASH_ICON) :
      kind === "hidden" ? (selecting ? "" : '<button class="ml-restore" data-mshow="' + p.id + '">Show again</button>') :
      (selecting ? "" : (state.isAdmin ? icon("data-madmin", p.id, "Edit" + c + " in the Dot Phrases app", OPEN_ICON) : "") + icon("data-mcopy", p.id, "Make my own copy of" + c, DUP_ICON) + icon("data-mhide", p.id, "Hide" + c + " from my list", HIDE_ICON));
    var verb = pickable ? "Select" : kind === "mine" ? "Edit" : "View";
    var click = attr ? ' role="button" tabindex="0" aria-label="' + verb + c + '"' : "";
    return '<div class="ml-row' + (attr ? " ml-click" : "") + (on ? " ml-on" : "") + '" ' + attr + click + ">" + pick + '<div class="ml-main"><div class="ml-top"><span class="ml-code">.' + esc(p.code) + "</span></div>" +
      '<div class="ml-text">' + previewHtml(p.text) + "</div>" + chipsHtml(p) + "</div>" + tail + "</div>";
  }
  // Select mode for hiding or showing several practice phrases at once.
  function selectBar(list, verb) {
    if (!list.length) { return ""; }
    if (!selecting) { return '<button class="ml-selbtn linkish" data-selstart>Select</button>'; }
    var n = selectedIds().length, all = list.every(function (p) { return selected[p.id]; });
    return '<div class="ml-selbar"><label class="ml-all"><input type="checkbox" data-selall' + (all ? " checked" : "") + "> Select all</label>" +
      '<span class="grow"></span><button class="pp-btn pp-sm" data-selcancel>Cancel</button>' +
      '<button class="pp-btn pp-primary pp-sm" data-seldo="' + verb + '"' + (n ? "" : " disabled") + ">" + (verb === "hide" ? "Hide" : "Show") + " " + (n || "") + " selected</button></div>";
  }
  function group(title, list, kind, empty, bar, note) {
    bar = bar || "";
    return '<div class="ml-sec">' + esc(title) + " <span>" + list.length + "</span>" + (bar && !selecting ? bar : "") + "</div>" + (bar && selecting ? bar : "") + (selecting ? "" : note || "") +
      (list.length ? '<div class="ml-group">' + list.map(function (p) { return mrow(p, kind); }).join("") + "</div>" : '<p class="ml-empty">' + empty + "</p>");
  }
  function byCode(a, b) { return a.code.localeCompare(b.code); }
  function renderManage() {
    if (mArch === "hidden") {
      var hid = state.phrases.filter(function (p) { return p.hidden; }).sort(byCode);
      $("#mlist").innerHTML = hid.length ? group("Hidden practice phrases", hid, "hidden", "", selectBar(hid, "show")) +
        '<p class="ml-foot hd-note">Typing a hidden phrase in a command still works.</p>' :
        '<div class="hd-empty">' + HIDE_ICON + "<div><b>No hidden phrases</b><p>Hide practice phrases you don't need, so your list shows only the ones you use. Typing a hidden phrase in a command still works.</p></div></div>";
      return;
    }
    var own = state.phrases.filter(function (p) { return p.mine; }).sort(byCode);
    var practice = state.phrases.filter(function (p) { return p.scope === "practice" && !p.hidden; }).sort(byCode);
    var lock = practice.length ? '<div class="ml-note">' + LOCK_ICON + "<span>" + (state.isAdmin ? "Edit these on the <b>Practice phrases</b> tab of the Dot Phrases app." : "Only " + esc(admins()) + " can change these.") + " Copy one to make your own version.</span></div>" : "";
    $("#mlist").innerHTML = (selecting ? "" : group("My phrases", own, "mine", "No personal phrases yet. Use New to make one.")) +
      group("Practice phrases", practice, "practice", "No practice phrases yet.", selectBar(practice, "hide"), lock);
  }
  function anyPhrase(id) { return find(id); }
  $("#mlist").addEventListener("click", function (e) {
    var t = e.target;
    if (t.closest("[data-selstart]")) { selecting = true; selected = {}; renderManage(); return; }
    if (t.closest("[data-selcancel]")) { selecting = false; selected = {}; renderManage(); return; }
    var all = t.closest("[data-selall]");
    if (all) {
      $$("#mlist [data-pickid]").forEach(function (x) { var id = x.getAttribute("data-pickid"); if (all.checked) { selected[id] = true; } else { delete selected[id]; } });
      renderManage(); return;
    }
    var tog = t.closest("[data-toggle]");
    if (tog) { var tid = tog.getAttribute("data-toggle"); if (selected[tid]) { delete selected[tid]; } else { selected[tid] = true; } renderManage(); return; }
    var doSel = t.closest("[data-seldo]");
    if (doSel) {
      var ids = selectedIds(), hide = doSel.getAttribute("data-seldo") === "hide", n = ids.length;
      if (!n) { return; }
      selecting = false; selected = {};
      var plural = n + " practice phrase" + (n === 1 ? "" : "s");
      if (hide) { hideWithUndo(ids, "Hid " + plural + ". Typing their codes still works."); return; }
      setHidden(ids, false).then(function () {
        toastUndo("Showing " + plural + " again.", function () { setHidden(ids, true).catch(function (er) { toast(er.message); }); });
      }).catch(function (er) { toast(er.message); });
      return;
    }
    var hb = t.closest("[data-mhide]");
    if (hb) {
      e.stopPropagation(); var ph = anyPhrase(Number(hb.getAttribute("data-mhide")));
      hideWithUndo([ph.id], "Hid ." + ph.code + " from your list. Typing it still works."); return;
    }
    var sb = t.closest("[data-mshow]");
    if (sb) {
      var ps = anyPhrase(Number(sb.getAttribute("data-mshow")));
      setHidden([ps.id], false).then(function () { toast("." + ps.code + " is back on your list"); }).catch(function (er) { toast(er.message); });
      return;
    }
    var del = t.closest("[data-mdel]");
    if (del) { e.stopPropagation(); openConfirm(anyPhrase(Number(del.getAttribute("data-mdel"))), "manage"); return; }
    var adm = t.closest("[data-madmin]");
    if (adm) {
      e.stopPropagation();
      var win = window.open(API + "/admin/?phrase=" + encodeURIComponent(adm.getAttribute("data-madmin")), "_blank");
      if (win) { win.opener = null; } else { toast("Canvas blocked the new tab. Open Dot Phrases from the app drawer instead."); }
      return;
    }
    var cp = t.closest("[data-mcopy]");
    if (cp) { e.stopPropagation(); copyAsMine(anyPhrase(Number(cp.getAttribute("data-mcopy")))); return; }
    var ed = t.closest("[data-medit]");
    if (ed) { openEditor(anyPhrase(Number(ed.getAttribute("data-medit"))), "manage"); return; }
    var vw = t.closest("[data-mview]");
    if (vw) { openViewer(anyPhrase(Number(vw.getAttribute("data-mview")))); }
  });
  $("#mlist").addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("ml-click")) { e.preventDefault(); e.target.click(); }
  });
  $("#newBtn").addEventListener("click", function () { openEditor(null, "manage"); });

  // ---- editor ----
  // ---- insert toolbar and guide (same as the Dot Phrases app, fitted to the panel) ----
  var ICONS = {
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 4-5.2 7-5.2s5.8 1.6 7 5.2"/></svg>',
    practice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V9l8-5 8 5v11"/><path d="M9 20v-6h6v6"/></svg>',
    ask: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/><path d="M10 9.5a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9v.2"/><path d="M12 14.6v.1"/></svg>'
  };
  function prettyName(n) { return n.replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function insertBar() {
    var item = function (ins, name, note, hl) { return '<button type="button" class="ax-pi" data-ins="' + esc(ins) + '"' + (hl ? ' data-hl="' + esc(hl) + '"' : "") + '><span class="n">' + esc(name) + '</span><span class="e">' + esc(note) + "</span></button>"; };
    var menu = function (key, label, head, items) { return '<div class="ax-menu"><button type="button" class="ax-tbtn" data-menu="' + key + '" aria-expanded="false" aria-haspopup="true">' + ICONS[key] + label + '</button><div class="ax-pop" role="menu" hidden><div class="ax-pop-head">' + head + "</div>" + items + "</div></div>"; };
    var chart = state.menu.map(function (p) { return item("{" + p.name + "}", p.label, state.values[p.name] ? "This patient: " + state.values[p.name] : "Empty for this patient"); }).join("");
    var practice = state.practiceNames.map(function (n) { return item("{" + n + "}", prettyName(n), state.values[n] || "No value yet"); }).join("") || '<div class="ax-pop-foot">Your practice has no practice info yet.</div>';
    var ask = item("{blank instructions}", "Blank with instructions", "Tells the provider what goes here. Example: [duration]", "instructions") +
      item("***", "Plain blank", "Marks a spot to fill in, without instructions: ***", "") +
      item("{pick label: option | option}", "Choice", "The provider picks one option. Example: [right / left]", "label: option | option");
    return '<div class="ax-tools" role="toolbar" aria-label="Insert a placeholder">' + menu("chart", "Patient", "From the patient's chart", chart) +
      menu("practice", "Practice", "Practice info, same for every patient", practice) + menu("ask", "Fill-ins", "The provider fills these in when they use the phrase", ask) +
      '<div class="ax-info"><button type="button" class="ax-ibtn" data-guide aria-expanded="false" aria-controls="fGuide" aria-label="How placeholders work" title="How placeholders work"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.6v.1"/></svg></button></div></div>';
  }
  function guideHtml() {
    var ins = function (k) { return '<button class="tok" data-ins="' + esc(k) + '" title="Add to the phrase">' + esc(k) + "</button>"; };
    var chartRows = state.menu.map(function (p) { return "<tr><td>" + ins("{" + p.name + "}") + "</td><td>" + (state.values[p.name] ? "<b>" + esc(state.values[p.name]) + "</b>" : '<span class="gd-empty">Nothing in this chart, so it stays as typed</span>') + "</td></tr>"; }).join("");
    var pracRows = state.practiceNames.map(function (n) { return "<tr><td>" + ins("{" + n + "}") + "</td><td>" + (state.values[n] ? "<b>" + esc(state.values[n]) + "</b>" : '<span class="gd-empty">No value yet</span>') + "</td></tr>"; }).join("");
    return '<div class="gd-head"><div><div class="gd-title">How placeholders work</div><p>Placeholders go in curly brackets and get swapped for real information when the phrase is used. Click one below to add it where your cursor is.</p></div>' +
      '<button type="button" class="gd-close" data-guide aria-label="Close the guide" title="Close">✕</button></div><div class="gd-cols">' +
      '<section class="gd-sec"><h4>' + ICONS.chart + "Patient</h4><p>From the open chart. Shown here for this patient.</p>" +
      '<table class="gd-tbl"><thead><tr><th>You type</th><th>It becomes</th></tr></thead><tbody>' + chartRows + "</tbody></table>" +
      '<p class="gd-note">If the chart has nothing for one, it stays as typed and is filled in before recording.</p></section>' +
      '<section class="gd-sec"><h4>' + ICONS.practice + "Practice</h4><p>Same for every patient. Set by your practice's admins.</p>" +
      '<table class="gd-tbl"><thead><tr><th>You type</th><th>It becomes</th></tr></thead><tbody>' + (pracRows || '<tr><td colspan="2" class="gd-empty">None yet</td></tr>') + "</tbody></table></section>" +
      '<section class="gd-sec"><h4>' + ICONS.ask + "Fill-ins</h4><p>Filled in when the phrase is used. Written right in the phrase.</p>" +
      '<table class="gd-tbl gd-fill"><thead><tr><th>You type</th><th>In the chart panel</th><th>Typed in a note</th></tr></thead><tbody>' +
      "<tr><td>" + ins("{blank duration}") + '</td><td>A box labeled "duration"</td><td><code class="gd-out">[duration]</code></td></tr>' +
      "<tr><td>" + ins("***") + '</td><td>A box with no label</td><td><code class="gd-out">***</code></td></tr>' +
      "<tr><td>" + ins("{pick side: right | left}") + '</td><td>Buttons: Right, Left</td><td><code class="gd-out">[right / left]</code></td></tr></tbody></table>' +
      '<p class="gd-note">Add instructions when the sentence doesn\'t make clear what goes in the blank. Every blank must be filled in before the command can be recorded. For a choice, the word before the colon is the heading, and options are separated by |.</p></section></div>' +
      '<section class="gd-ex"><h4>Example</h4>' +
      '<div class="gd-ex-row"><div class="gd-ex-k">You write</div><div><span class="gd-src">{first_name} is a {age}-year-old seen today for {pick side: right | left | both} knee pain for {blank duration}.</span></div></div>' +
      '<div class="gd-ex-row"><div class="gd-ex-k">You pick</div><div>Left, and type 2 weeks</div></div>' +
      '<div class="gd-ex-row"><div class="gd-ex-k">Note gets</div><div><b>Connie is a 67-year-old seen today for left knee pain for 2 weeks.</b></div></div></section>';
  }
  // ---- Use in: one checklist. Every note command starts checked; the Sig and note to pharmacist ----
  // ---- start unchecked, so text only reaches a pharmacy when someone picks it. ----
  var USE_COMMON = ["plan", "hpi", "instruct", "perform", "assess", "diagnose"];
  var USE_GROUPS = [
    ["Common commands", USE_COMMON],
    ["Visit, orders, and tasks", ["rfv", "followup", "task", "refer", "imaging", "laborder", "poclab", "vitals"]],
    ["History", ["pmh", "removepmh", "psh", "fhx", "allergy", "removeallergy", "immstmt", "medstmt"]],
    ["Conditions and medications", ["updatedx", "resolve", "stopmed"]],
    ["Goals", ["goal", "updategoal", "closegoal"]],
    ["Reviews", ["labreview", "imgreview", "refreview", "docreview"]]
  ];
  var USE_ALL = USE_GROUPS.reduce(function (a, g) { return a.concat(g[1]); }, []);
  var USE_REVIEWS = USE_GROUPS[USE_GROUPS.length - 1][1];
  function useLabel(k) { return k === "hpi" ? "HPI" : (state.labels[k] || k); }
  function useChecked(d) { return d.use_in === null ? USE_ALL.slice() : d.use_in.slice(); }
  // Every note command checked is saved as "all note commands", so commands added later are included.
  function useSet(d, list) {
    var keep = USE_ALL.filter(function (k) { return list.indexOf(k) >= 0; });
    d.use_in = keep.length === USE_ALL.length ? null : keep;
  }
  function useSummary(d) {
    var rx = [];
    if (d.rx.sig) { rx.push("Sig"); }
    if (d.rx.note_to_pharmacist) { rx.push("note to pharmacist"); }
    var notes = d.use_in === null ? "all note commands" : d.use_in.length > 3 ? d.use_in.length + " note commands" : d.use_in.map(useLabel).join(", ");
    if (notes) { return [notes].concat(rx).join(", "); }
    if (rx.length === 2) { return "Sig and note to pharmacist"; }
    return rx.length ? rx[0] + " only" : "nothing yet";
  }
  function useNeedsReminder(d, text) {
    // Any placeholder can be left incomplete: chart values the chart doesn't have, blanks, and choices.
    if (!/\{\s*[a-z]|\*\*\*/i.test(text || "")) { return false; }
    return d.use_in === null || USE_REVIEWS.some(function (k) { return d.use_in.indexOf(k) >= 0; });
  }
  function useListHtml(d) {
    var on = useChecked(d);
    var box = function (k) { return '<label class="pk-ck"><input type="checkbox" data-cmdck="' + k + '"' + (on.indexOf(k) >= 0 ? " checked" : "") + "> " + esc(useLabel(k)) + "</label>"; };
    var rxBox = function (k, label) { return '<label class="pk-ck"><input type="checkbox" data-rx="' + k + '"' + (d.rx[k] ? " checked" : "") + "> " + label + ' <span class="use-cnt" id="useC_' + k + '"></span></label>'; };
    return '<div class="pk-gh"><span>Prescriptions</span><button type="button" class="pk-all" data-rxall>Select all</button></div>' +
      '<div class="pk-cols use-rx">' + rxBox("sig", "Sig") + rxBox("note_to_pharmacist", "Note to pharmacist") + "</div>" +
      '<div class="use-rxhint">Used in Prescribe, Refill, and Adjust prescription. Sent to the pharmacy as a single line of standard characters. Limits: Sig 1,000 characters, note to pharmacist 210. Prescriptions with unfilled placeholders cannot be sent.</div>' +
      '<div class="pk-gh use-bulk"><span>Note commands</span><button type="button" class="pk-all" data-useall>Select all</button><button type="button" class="pk-all" data-useclear>Clear all</button></div>' +
      USE_GROUPS.map(function (g, i) {
        return '<div class="pk-grp"><div class="pk-gh"><span>' + esc(g[0]) + '</span><button type="button" class="pk-all" data-grpall="' + i + '">Select all</button></div><div class="pk-cols">' + g[1].map(box).join("") + "</div></div>";
      }).join("");
  }
  function useBlockHtml(d) {
    return '<div class="wi"><span class="wi-t">Works in: <b class="use-sum"></b></span><button type="button" class="wi-link" data-usetoggle aria-expanded="false">Change</button></div>' +
      '<div class="use-rem" hidden>Review commands cannot flag incomplete placeholders.</div>' +
      '<div class="pk use-list" hidden>' + useListHtml(d) + "</div>";
  }
  // Bring the checklist, summary, and reminder in line with the draft.
  function useSync(scope, d, text) {
    var on = useChecked(d);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-cmdck]"), function (b) { b.checked = on.indexOf(b.getAttribute("data-cmdck")) >= 0; });
    Array.prototype.forEach.call(scope.querySelectorAll("[data-rx]"), function (b) { b.checked = !!d.rx[b.getAttribute("data-rx")]; });
    Array.prototype.forEach.call(scope.querySelectorAll("[data-grpall]"), function (b) {
      var keys = USE_GROUPS[Number(b.getAttribute("data-grpall"))][1];
      b.textContent = keys.every(function (k) { return on.indexOf(k) >= 0; }) ? "Clear all" : "Select all";
    });
    var rxAll = scope.querySelector("[data-rxall]"); if (rxAll) { rxAll.textContent = d.rx.sig && d.rx.note_to_pharmacist ? "Clear all" : "Select all"; }
    var sum = scope.querySelector(".use-sum"); if (sum) { sum.textContent = useSummary(d); }
    var rem = scope.querySelector(".use-rem"); if (rem) { rem.hidden = !useNeedsReminder(d, text); }
  }
  // Clicks and changes inside the Use in block. Returns true when it handled the event.
  function useHandle(e, scope, d) {
    var t = e.target;
    var tog = t.closest && t.closest("[data-usetoggle]");
    if (tog && e.type === "click") {
      var list = scope.querySelector(".use-list"), open = list.hidden;
      list.hidden = !open; tog.textContent = open ? "Done" : "Change"; tog.setAttribute("aria-expanded", String(open)); return true;
    }
    var grp = t.closest && t.closest("[data-grpall]");
    if (grp && e.type === "click") {
      var keys = USE_GROUPS[Number(grp.getAttribute("data-grpall"))][1], cur = useChecked(d);
      var full = keys.every(function (k) { return cur.indexOf(k) >= 0; });
      useSet(d, full ? cur.filter(function (k) { return keys.indexOf(k) < 0; }) : cur.concat(keys)); return true;
    }
    // Every note command at once. Sig and Note to pharmacist have their own row, since those reach a pharmacy.
    if (t.closest && t.closest("[data-useall]") && e.type === "click") { useSet(d, USE_ALL); return true; }
    if (t.closest && t.closest("[data-useclear]") && e.type === "click") { d.use_in = []; return true; }
    if (t.closest && t.closest("[data-rxall]") && e.type === "click") {
      var both = d.rx.sig && d.rx.note_to_pharmacist; d.rx.sig = !both; d.rx.note_to_pharmacist = !both; return true;
    }
    var changed = e.type === "change" || e.type === "input";
    if (changed && t.getAttribute && t.getAttribute("data-cmdck")) {
      var k = t.getAttribute("data-cmdck"), set = useChecked(d), i = set.indexOf(k);
      if (t.checked && i < 0) { set.push(k); } else if (!t.checked && i >= 0) { set.splice(i, 1); }
      useSet(d, set); return true;
    }
    if (changed && t.getAttribute && t.getAttribute("data-rx")) { d.rx[t.getAttribute("data-rx")] = t.checked; return true; }
    return false;
  }
  function useIsEmpty(d) { return d.use_in !== null && !d.use_in.length && !d.rx.sig && !d.rx.note_to_pharmacist; }
  function openEditor(p, from) {
    var editing = !!(p && p.mine);
    if (from) { openEditScreen(editing ? "Edit phrase" : "New phrase", from); } else { $("#edTitle").textContent = editing ? "Edit phrase" : "New phrase"; }
    // The draft behind the Use in checklist. A new phrase works in every note command and no prescription field.
    var draft = { use_in: p && p.use_in ? p.use_in.slice() : null, rx: { sig: !!(p && p.rx_sig), note_to_pharmacist: !!(p && p.rx_note_to_pharmacist) } };
    $("#editorSlot").innerHTML = '<div class="ed">' +
      '<label for="fCode">Code</label><input id="fCode" value="' + esc(p ? p.code : "") + '" maxlength="64" placeholder="e.g. kneehpi"><div class="hint">Starts with a letter. Letters and numbers only.</div>' +
      '<label for="fText">Text</label><div class="ax-editor"><textarea class="ax-ta ax-ta-flat" id="fText" rows="4">' + esc(p ? p.text : "") + "</textarea>" + insertBar() + "</div>" +
      '<div class="hint">Placeholders go in curly brackets. Use the menus above, or type them.</div>' +
      '<div class="ax-guide pp-guide" id="fGuide" hidden>' + guideHtml() + "</div>" +
      '<label>Use in</label><div id="fUseBlock" class="panel-pk">' + useBlockHtml(draft) + "</div>" +
      '<div class="warn" id="fLim"></div>' +
      '<div class="err" id="fRx"></div>' +
      '<div class="note">Personal phrases are only for you.' + (state.isAdmin ? " To share one with everyone, add it on the <b>Practice phrases</b> tab of the Dot Phrases app." : " Practice phrases are made by your practice's admins.") + "</div>" +
      '<div class="err" id="fErr"></div>' +
      '<div class="row ed-acts">' + (editing ? '<button class="pp-btn pp-del-out" id="fDelete" title="Delete .' + esc(p.code) + '" aria-label="Delete .' + esc(p.code) + '">' + TRASH_ICON + "</button>" : "") +
      '<span class="grow"></span><button class="pp-btn" id="fCancel">Cancel</button><button class="pp-btn pp-primary" id="fSave">Save</button></div></div>';
    var root = $("#editorSlot .ed");
    function upd() {
      var text = $("#fText").value;
      var len = fill(text, [], false).length;
      var keys = Object.keys(state.limits);
      var over = keys.filter(function (k) { return len > state.limits[k]; });
      $("#fLim").textContent = over.length ? "Too long for " + over.map(function (k) { return state.labels[k] + " (" + state.limits[k] + ")"; }).join(", ") + ". It won't expand there." : "";
      var errs = [];
      ["sig", "note_to_pharmacist"].forEach(function (k) {
        var on = !!draft.rx[k], c = $("#useC_" + k);
        var pr = on ? rxProblems(k, text) : [];
        c.textContent = on ? text.length + " / " + state.rxFields[k].max.toLocaleString() : "";
        c.classList.toggle("bad", pr.length > 0);
        if (pr.length) { errs.push(rxMessage(k, text, state.rxFields[k].label, state.rxFields[k].max)); }
      });
      useSync($("#fUseBlock"), draft, text);
      $("#fRx").innerHTML = errs.map(function (m) { return "<div>" + boldUi(esc(m)) + "</div>"; }).join("");
      return { errs: errs };
    }
    // A checkbox fires "input" before "change"; record it first so the redraw doesn't undo it.
    root.addEventListener("input", function (e) {
      if (e.target.closest && e.target.closest("#fUseBlock")) { useHandle(e, $("#fUseBlock"), draft); }
      upd();
    });
    root.addEventListener("change", function (e) {
      if (e.target.closest && e.target.closest("#fUseBlock")) { useHandle(e, $("#fUseBlock"), draft); }
      upd();
    });
    var ta = $("#fText"), caret = null;
    ["click", "keyup", "select", "input"].forEach(function (ev) { ta.addEventListener(ev, function () { caret = ta.selectionEnd; }); });
    function closeMenus(except) {
      Array.prototype.forEach.call(root.querySelectorAll(".ax-menu"), function (m) {
        if (m !== except) { m.querySelector(".ax-pop").hidden = true; m.querySelector("[data-menu]").setAttribute("aria-expanded", "false"); }
      });
    }
    document.addEventListener("click", function (e) { if (root.isConnected && !e.target.closest("#editorSlot .ax-menu")) { closeMenus(); } });
    root.addEventListener("keydown", function (e) { if (e.key === "Escape") { closeMenus(); } });
    root.addEventListener("click", function (e) {
      var menuBtn = e.target.closest("[data-menu]");
      if (menuBtn) {
        var m = menuBtn.closest(".ax-menu"), pop = m.querySelector(".ax-pop"), open = pop.hidden;
        closeMenus(m); pop.hidden = !open; menuBtn.setAttribute("aria-expanded", String(open)); return;
      }
      var ins = e.target.closest("[data-ins]");
      if (ins) {
        closeMenus();
        var text = ins.getAttribute("data-ins"), hl = ins.getAttribute("data-hl"), v = ta.value, at = caret == null ? v.length : Math.min(caret, v.length);
        var before = v.slice(0, at), after = v.slice(at);
        var pre = before && !/\s$/.test(before) ? " " : "", post = after && !/^[\s.,;:!?)]/.test(after) ? " " : "";
        ta.value = before + pre + text + post + after;
        var start = at + pre.length, a = start + text.length, b = a;
        if (hl) { var k = text.indexOf(hl); if (k >= 0) { a = start + k; b = a + hl.length; } }
        ta.focus(); ta.setSelectionRange(a, b); caret = b; upd(); return;
      }
      if (e.target.closest("#fUseBlock") && useHandle(e, $("#fUseBlock"), draft)) { upd(); return; }
      if (e.target.closest("[data-guide]")) {
        closeMenus();
        var g = $("#fGuide"); g.hidden = !g.hidden;
        Array.prototype.forEach.call(root.querySelectorAll("[data-guide]"), function (x) { x.setAttribute("aria-expanded", String(!g.hidden)); });
        if (!g.hidden) { g.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
      }
    });
    $("#fCode").addEventListener("input", function (e) { e.target.value = e.target.value.toLowerCase().replace(/[^a-z0-9]/g, ""); });
    $("#fCancel").addEventListener("click", leaveEdit);
    var snap = function () { return [$("#fCode").value, $("#fText").value, JSON.stringify(draft.use_in), draft.rx.sig, draft.rx.note_to_pharmacist].join("\u0000"); };
    var start = snap();
    editDirty = function () {
      if (!$("#fCode") || snap() === start) { return ""; }
      return editing ? "Discard your changes to ." + p.code + "?" : "Discard this new phrase?";
    };
    if (editing) { $("#fDelete").addEventListener("click", function () { openConfirm(p, null); }); }
    $("#fSave").addEventListener("click", function () {
      var s = upd(), code = $("#fCode").value, text = $("#fText").value.trim(), err = function (m) { $("#fErr").textContent = m; };
      if (!/^[a-z][a-z0-9]*$/.test(code) || !text) { return err("Enter a code that starts with a letter, and the text it inserts."); }
      var u = unknownPlaceholders(text); if (u.length) { return err("Unknown placeholder: " + u.join(", ") + "."); }
      var rx = { sig: draft.rx.sig, ntp: draft.rx.note_to_pharmacist };
      if (useIsEmpty(draft)) { return err("Pick at least one place to use this phrase."); }
      if (s.errs.length) { err(""); $("#fRx").scrollIntoView({ block: "nearest" }); return; }
      var body = { code: code, text: text, use_in: draft.use_in, rx_sig: rx.sig, rx_note_to_pharmacist: rx.ntp, scope: "personal" };
      // One save at a time, so a double click can't create the same phrase twice.
      var saveBtn = $("#fSave"); if (saveBtn.disabled) { return; } saveBtn.disabled = true;
      var req = p && p.mine ? api("PATCH", "/phrases/" + p.id, body) : api("POST", "/phrases", body);
      req.then(function () { toast("Saved ." + code); return load().then(leaveEdit); }).catch(function (er) { saveBtn.disabled = false; err(er.message); });
    });
    upd(); $("#fCode").focus();
  }
  // Confirm before deleting. Shown on the edit screen; Cancel goes back to the editor, or to the list it came from.
  function openConfirm(p, from) {
    var fromEditor = !from;
    editDirty = null;
    if (from) { openEditScreen("Delete phrase", from); }
    $("#editorSlot").innerHTML = '<div class="ed ed-confirm" role="alertdialog" aria-labelledby="cfTitle" aria-describedby="cfBody">' +
      '<div class="cf-title" id="cfTitle">Delete .' + esc(p.code) + "?</div>" +
      '<p id="cfBody">Deleting .' + esc(p.code) + " won't affect existing notes. This action can't be undone.</p>" +
      '<div class="row"><button class="pp-btn" id="cfNo">Cancel</button><button class="pp-btn pp-danger" id="cfYes">Delete</button></div></div>';
    $("#cfNo").addEventListener("click", function () { if (fromEditor) { openEditor(p); } else { leaveEdit(); } });
    $("#cfYes").addEventListener("click", function () {
      $("#cfYes").disabled = true;
      api("DELETE", "/phrases/" + p.id).then(function () { toast("Deleted ." + p.code); if (openId === p.id) { openId = null; } return load().then(leaveEdit); })
        .catch(function (er) { $("#cfYes").disabled = false; toast(er.message); });
    });
    $("#cfNo").focus();
  }
  function copyAsMine(p) {
    openEditor({ code: p.code, text: p.text, use_in: p.use_in, rx_sig: p.rx_sig, rx_note_to_pharmacist: p.rx_note_to_pharmacist, mine: false }, "manage");
  }
  // Practice phrases are read-only here; admins edit them in the Dot Phrases app.
  function openViewer(p) {
    var where = [p.use_in === null ? "All commands" : p.use_in.map(function (k) { return state.labels[k] || k; }).join(", ")];
    if (p.rx_sig) { where.push("Sig"); }
    if (p.rx_note_to_pharmacist) { where.push("Note to pharmacist"); }
    openEditScreen("Practice phrase", "manage"); editDirty = null;
    $("#editorSlot").innerHTML = '<div class="ed"><label>Code</label><div class="ro">.' + esc(p.code) + "</div>" +
      '<label>Text</label><div class="ro">' + esc(p.text) + "</div>" +
      '<label>Use in</label><div class="ro">' + esc(where.join(", ")) + "</div>" +
      '<div class="note">' + (state.isAdmin ? "Edit it on the <b>Practice phrases</b> tab of the Dot Phrases app." : "Only " + esc(admins()) + " can change it.") +
      " To use your own wording, make a personal copy: yours is used instead, for you only.</div>" +
      '<div class="row"><button class="pp-btn" id="vClose">Close</button><button class="pp-btn pp-primary" id="vCopy" style="flex:1">Make my own copy</button></div></div>';
    $("#vClose").addEventListener("click", leaveEdit);
    $("#vCopy").addEventListener("click", function () { copyAsMine(p); });
  }

  // ---- Chart tab only ----
  // Canvas keeps this side panel open when you switch to Profile or another page, where an inserted
  // phrase wouldn't show until the chart reloads. Off the Chart tab the panel closes itself, or, mid-edit
  // (or if Canvas won't let it close), covers itself until you're back on the Chart.
  var port = null, askedToClose = false;
  window.addEventListener("message", function (e) {
    if (e.data && e.data.type === "INIT_CHANNEL" && e.ports && e.ports[0]) { port = e.ports[0]; }
  });
  function hostPath() {
    try { return window.top.location.pathname; } catch (err) { return null; }
  }
  function onChartTab(path) { return /^\/patient\/[^/]+\/?$/.test(path); }
  // Work that would be lost if the panel closed: an edit not saved, fill-ins started on an open card,
  // or practice phrases checked in Select mode.
  function hasUnsavedWork() {
    if (editDirty && editDirty()) { return true; }
    if (openId !== null && answers.some(function (v) { return v != null && String(v).trim() !== ""; })) { return true; }
    return selecting && selectedIds().length > 0;
  }
  function checkTab() {
    var path = hostPath();
    if (path === null) { return; }
    var off = !onChartTab(path);
    $("#offChart").hidden = !off;
    if (!off) { askedToClose = false; return; }
    if (port && !askedToClose && !hasUnsavedWork()) { askedToClose = true; port.postMessage({ type: "CLOSE_MODAL" }); }
  }
  setInterval(checkTab, 700);

  load();
})();
{% endverbatim %}
