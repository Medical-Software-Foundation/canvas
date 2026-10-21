{% verbatim %}
/* Order Favorites app in the app drawer. Tabs: Prescriptions, Labs, and (for favorites admins) Settings with
   import. Each order-type tab lists your own favorites and the practice's (All is grouped Mine, then Practice),
   with an eye on each practice favorite to hide or show it in your chart panel. Admins edit practice favorites
   here and choose Personal or Practice on New. Layout follows mockups/order-favorites-tab-options.html,
   option E. */
(function () {
  "use strict";
  var OF = window.OF, esc = OF.esc, I = OF.I;
  var $ = function (s) { return document.querySelector(s); };
  var app = $("#app");

  var data = null; // admin data: settings, admins, import template (admins only)
  var mine = null; // the signed-in person's view: kinds, title, is_admin, every favorite they can see
  var tab = "rx", view = "all", showHidden = false, sel = null, listQ = "", confirmDel = false;
  var edit = null; // {editor, id, kind, value, practice}
  var newFor = "mine", copyOf = null;
  var imp = { text: "", rows: null, error: "", done: "" };
  var staffQ = "", staffResults = [], removeAsk = null, staffTimer = null;
  var guard = null;
  // "+ New" in an order set opens a favorite form in the detail pane (sub), then returns to the set (back).
  var sub = null, back = null;

  var EYE_ON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = I.hide;

  function toast(m) { var t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove("on"); }, 2400); }
  function kinds() { return mine.kinds; }
  // Tabs for favorites: the enabled order types, plus order sets when they're on.
  function listTabs() { return mine.kinds.concat(mine.sets_enabled ? ["set"] : []); }
  function isAdmin() { return !!mine.is_admin; }
  function byId(id) { for (var i = 0; i < mine.favorites.length; i++) { if (mine.favorites[i].id === id) { return mine.favorites[i]; } } return null; }
  // While a favorite form is open from a set, the set's own unsaved changes count too.
  function dirty() { return !!(edit && edit.editor && edit.editor.dirty()) || !!(sub && sub.setDirty); }
  function guarded(go) { if (guard && dirty()) { guard.run(go); } else { go(); } }
  function noun() { return tab === "rx" ? "prescriptions" : tab === "lab" ? "labs" : "order sets"; }
  function kindWord() { return tab === "rx" ? "prescription" : tab === "lab" ? "lab" : "order set"; }

  function load() {
    return OF.api("GET", "/panel/data").then(function (m) {
      mine = m;
      OF.useFavorites(mine.favorites);
      if (!isAdmin()) { data = null; return null; }
      return OF.api("GET", "/admin/data").then(function (d) { data = d; });
    }).then(function () {
      if (tab !== "settings" && listTabs().indexOf(tab) < 0) { tab = kinds()[0]; sel = null; edit = null; }
      if (tab === "settings" && !isAdmin()) { tab = kinds()[0]; }
      // "Fix it in the admin app" links arrive with ?favorite=<id>.
      var want = +(document.body.getAttribute("data-favorite") || 0);
      document.body.setAttribute("data-favorite", "");
      var f = want ? byId(want) : null;
      if (f) { tab = f.kind; view = "all"; showHidden = showHidden || !!f.hidden; select(f.id); }
      render();
    }).catch(function (e) { app.innerHTML = '<p class="ax-list-empty">' + esc(e.message) + "</p>"; });
  }

  function select(id) { sel = id; confirmDel = false; edit = null; copyOf = null; sub = null; back = null; }

  // ---------- frame ----------
  function render() {
    var tabs = listTabs().map(function (k) { return '<button class="' + (tab === k ? "on" : "") + '" data-adtab="' + k + '">' + (k === "rx" ? "Prescriptions" : k === "lab" ? "Labs" : "Order sets") + "</button>"; }).join("");
    if (isAdmin()) { tabs += '<button class="' + (tab === "settings" ? "on" : "") + '" data-adtab="settings">Settings</button>'; }
    app.innerHTML = '<header class="ax-head"><div class="ax-title">' + esc(mine.title) + '</div><p class="ax-sub">Your favorites and the practice\'s. Add them to a note from the Order Favorites button in the note.</p><nav class="ax-tabs">' + tabs + '</nav></header><div class="ax-main" id="main"></div>';
    if (tab === "settings") { renderSettings(); } else { renderSplit(); }
  }

  // ---------- favorites list ----------
  function visible() {
    var ql = listQ.toLowerCase();
    return mine.favorites.filter(function (f) {
      if (f.kind !== tab) { return false; }
      if (view === "mine" && !f.mine) { return false; }
      if (view === "practice" && !f.shared) { return false; }
      if (f.hidden && !showHidden) { return false; }
      return !ql || OF.searchText(f).indexOf(ql) >= 0;
    });
  }
  function hiddenCount() { return mine.favorites.filter(function (f) { return f.kind === tab && f.shared && f.hidden; }).length; }
  function rowHtml(f) {
    var sub = f.kind === "set"
      ? (OF.setMembers(f).length ? OF.plural(OF.setMembers(f).length, "order", "orders") + " · " + OF.setMembers(f).map(function (x) { return esc(x.name); }).join(", ") : "None of its favorites are available")
      : f.kind === "rx" ? esc(f.sig || f.medication) : esc(f.lab_partner_name) + " · " + OF.plural(f.tests.length, "test", "tests");
    var flag = f.stale && f.stale.length && (f.mine || isAdmin()) ? '<span class="ax-flag">Needs fixing</span>' : "";
    // The eye only applies to practice favorites: it hides or shows them in your own chart panel.
    var eye = f.shared
      ? '<button class="eye" data-eye="' + f.id + '" title="' + (f.hidden ? "Hidden from your favorites panel. Click to show it." : "In your favorites panel. Click to hide it.") + '" aria-label="' + (f.hidden ? "Show " : "Hide ") + esc(f.name) + '">' + (f.hidden ? EYE_OFF : EYE_ON) + "</button>"
      : '<span class="eye-space"></span>';
    return '<div class="erow' + (f.hidden ? " hid" : "") + '"><button class="ax-row' + (sel === f.id ? " on" : "") + '" data-sel="' + f.id + '"><span class="c"><span class="code">' + esc(f.name) + "</span>" + flag + '</span><span class="t">' + sub + "</span></button>" + eye + "</div>";
  }
  function renderRows() {
    var items = visible();
    var h;
    if (view === "all") {
      var my = items.filter(function (f) { return f.mine; }), prac = items.filter(function (f) { return f.shared; });
      var word = tab === "set" ? "order sets" : "favorites";
      h = '<div class="grp">My ' + word + '<span>' + my.length + "</span></div>" + (my.map(rowHtml).join("") || '<div class="grp-empty">' + (listQ ? "None match." : "None yet. Use + New, or copy a practice " + (tab === "set" ? "order set." : "favorite.")) + "</div>") +
        '<div class="grp">Practice ' + word + '<span>' + prac.length + "</span></div>" + (prac.map(rowHtml).join("") || '<div class="grp-empty">' + (listQ ? "None match." : "None yet.") + "</div>");
    } else {
      h = items.map(rowHtml).join("") || '<div class="ax-list-empty">' + (listQ ? "No favorites match." : view === "mine" ? "None yet. Use + New, or copy a practice favorite." : "No practice favorites yet.") + "</div>";
    }
    $("#rows").innerHTML = h;
    var hc = hiddenCount(), box = $("#hidOpt");
    if (box) { box.innerHTML = view === "mine" || !hc ? "" : '<label><input type="checkbox" id="showHidden"' + (showHidden ? " checked" : "") + "> Show hidden (" + hc + ")</label>"; }
  }
  function canNew() { return view !== "practice" || isAdmin(); }
  function renderSplit() {
    var seg = '<div class="pp-seg">' + [["all", "All"], ["mine", "Mine"], ["practice", "Practice"]].map(function (v) { return '<button class="' + (view === v[0] ? "on" : "") + '" data-view="' + v[0] + '">' + v[1] + "</button>"; }).join("") + "</div>";
    $("#main").innerHTML = '<div class="ax-split"><div class="ax-list"><div class="ax-list-top my-top">' +
      '<div class="pp-search" style="margin:0;flex:1;min-width:0">' + I.search + '<input id="q" placeholder="Search ' + noun() + '" autocomplete="off" aria-label="Search" value="' + esc(listQ) + '"></div>' +
      (canNew() ? '<button class="ax-btn primary ax-new" data-new="1">+ New</button>' : "") + '</div><div class="my-segs">' + seg + '<div class="hid-opt" id="hidOpt"></div></div><div class="ax-rows" id="rows"></div></div><div class="ax-detail" id="detail"></div></div>';
    renderRows();
    renderDetail();
  }

  // ---------- detail ----------
  function renderDetail() {
    if (sub) { renderSub(); return; }
    var box = $("#detail");
    var f = sel ? byId(sel) : null;
    var editingNew = edit && !edit.id;
    if (!f && !editingNew) { box.innerHTML = '<div class="ax-blank"><div><b>Pick ' + (tab === "set" ? "an order set" : "a favorite") + '</b>or add a new one.</div></div>'; edit = null; guard = null; return; }

    if (f && f.shared && !isAdmin()) {
      // Practice favorites are read-only for everyone but admins: copy or hide them.
      edit = null; guard = null;
      box.innerHTML = '<div class="ax-dhead"><div><div class="ax-dcode">' + esc(f.name) + '</div><div class="ax-dmeta">Practice ' + (f.kind === "set" ? "order set" : "favorite") + ' · only your practice\'s favorites admins can change it.</div></div></div>' +
        '<div style="margin-top:14px">' + OF.details(f) + "</div>" +
        '<div class="ax-foot"><div class="ax-dacts"><button class="ax-btn" data-eye="' + f.id + '">' + (f.hidden ? "Show in my list" : "Hide from my list") + '</button><button class="ax-btn primary" data-copy="' + f.id + '">Make a copy</button></div></div>';
      return;
    }

    var practice = f ? f.shared : (isAdmin() && newFor === "practice");
    var title, meta;
    var isSet = tab === "set";
    if (!f) { title = "New " + kindWord() + (isSet ? "" : " favorite"); meta = isAdmin() ? "Choose whether it's personal or for the practice." : "Only you see your own " + (isSet ? "order sets." : "favorites."); }
    else if (practice) { title = "Edit practice " + kindWord(); meta = "Added by " + esc(f.owner || "a former admin") + " · everyone in the practice sees this in their favorites panel."; }
    else { title = "Edit " + kindWord() + " favorite"; meta = "Only you see your own favorites."; }
    var forSeg = !f && isAdmin()
      ? '<div class="save-for"><label>Save for</label><div class="pp-seg">' + [["mine", "Personal"], ["practice", "Practice"]].map(function (v) { return '<button class="' + (newFor === v[0] ? "on" : "") + '" data-for="' + v[0] + '">' + v[1] + "</button>"; }).join("") + '</div><div class="ax-help">' + (newFor === "practice" ? "Everyone in the practice will see this in their favorites panel." + (tab === "set" ? " It can only include practice favorites." : "") : "Only you will see this in your favorites panel.") + "</div></div>"
      : "";
    box.innerHTML = '<div class="ax-dhead"><div><div class="ax-dcode">' + title + '</div><div class="ax-dmeta">' + meta + "</div></div></div>" +
      '<div id="guardSlot" hidden></div>' + forSeg + '<div class="ed" style="margin-top:16px" id="form"></div><div class="ax-err" id="err" role="alert"></div><div id="foot"></div>';
    var value = back ? back.value : f || edit.value;
    var baseline = back ? back.baseline : edit && edit.baseline || null;
    edit = { id: f ? f.id : null, kind: tab, value: value, practice: practice, editor: null, baseline: baseline };
    var copyNote = !f && copyOf ? 'A personal copy of the practice ' + (isSet ? "order set" : "favorite") + ' "' + copyOf + '". Changes to the practice one won\'t reach your copy.' : "";
    edit.editor = isSet
      ? OF.SetEditor($("#form"), value, { favorites: mine.favorites, practice: practice, kinds: kinds(), note: copyNote, onNew: openSub, baseline: baseline, justAdded: back ? back.justAdded : null })
      : OF.Editor($("#form"), value, { note: copyNote });
    back = null;
    guard = OF.Guard($("#guardSlot"), dirty, function () { return edit ? edit.editor.name() : ""; });
    renderFoot();
  }
  // A favorite made from a set is personal or practice to match the set, and lands in it checked.
  function openSub(kind) {
    sub = { kind: kind, practice: edit.practice, draft: edit.editor.payload(), baseline: edit.baseline || edit.value, setDirty: edit.editor.dirty() };
    renderSub();
  }
  function renderSub() {
    var word = sub.kind === "rx" ? "prescription" : "lab";
    $("#detail").innerHTML = '<div class="ax-dhead"><div><div class="ax-dcode">New ' + word + ' favorite</div><div class="ax-dmeta">For the order set <b>' + esc(sub.draft.name || "Untitled") + "</b> · " +
      (sub.practice ? "saved as a practice favorite, since this is a practice order set, and added to the set." : "saved as your personal favorite and added to the set.") + "</div></div></div>" +
      '<div id="guardSlot" hidden></div><div class="ed" style="margin-top:16px" id="form"></div><div class="ax-err" id="err" role="alert"></div>' +
      '<div class="ax-foot"><div class="ax-dacts"><button class="ax-btn" data-subback="1">Back to set</button><button class="ax-btn primary" id="subsave">Save and add to set</button></div></div>';
    edit = { id: null, kind: sub.kind, value: OF.blank(sub.kind), practice: sub.practice, editor: null };
    edit.editor = OF.Editor($("#form"), edit.value, {});
    // Leaving the pane warns if the form or the set behind it has unsaved changes.
    guard = OF.Guard($("#guardSlot"), dirty, function () { return edit && edit.editor.name() || sub.draft.name; });
  }
  function closeSub(added) {
    var draft = sub.draft;
    if (added) { draft.items.push(added.id); }
    back = { value: draft, baseline: sub.baseline, justAdded: added ? added.id : null };
    sub = null;
    renderDetail();
  }
  function saveSub() {
    var body = edit.editor.payload();
    $("#subsave").disabled = true;
    OF.api("POST", sub.practice ? "/admin/favorites" : "/favorites", body).then(function (d) {
      mine.favorites.push(d.favorite);
      OF.useFavorites(mine.favorites);
      toast('Saved "' + d.favorite.name + '" and added it to the set');
      edit.editor.saved();
      closeSub(d.favorite);
    }).catch(function (e) { $("#err").textContent = e.message; var b = $("#subsave"); if (b) { b.disabled = false; } });
  }
  function renderFoot() {
    var f = edit && edit.id ? byId(edit.id) : null;
    var everyone = f && f.shared ? "This removes it for everyone in the practice. " : "";
    $("#foot").innerHTML = confirmDel && f
      ? '<div class="ax-foot ax-confirm" role="alertdialog"><div><div class="ax-cf-title">Delete ' + esc(f.name) + "?</div><p>" + everyone + "Orders already added to notes aren't affected. This can't be undone.</p></div>" +
        '<div class="ax-dacts"><button class="ax-btn" data-confirm="no">Cancel</button><button class="ax-btn danger-solid" data-confirm="yes">Delete</button></div></div>'
      : '<div class="ax-foot">' + (f ? '<button class="ax-btn danger" data-del="1">' + I.trash + "Delete</button>" : "") +
        '<div class="ax-dacts">' + (f && f.shared ? '<button class="ax-btn" data-eye="' + f.id + '">' + (f.hidden ? "Show in my list" : "Hide from my list") + "</button>" : "") +
        '<button class="ax-btn" data-cancel="1">Cancel</button><button class="ax-btn primary" id="save">' + (f ? "Save changes" : edit.practice ? (tab === "set" ? "Save practice order set" : "Save practice favorite") : (tab === "set" ? "Save order set" : "Save favorite")) + "</button></div></div>";
  }
  function save() {
    var body = edit.editor.payload();
    var base = edit.practice ? "/admin/favorites" : "/favorites";
    var req = edit.id ? OF.api("PATCH", base + "/" + edit.id, body) : OF.api("POST", base, body);
    $("#save").disabled = true;
    req.then(function (d) {
      toast('Saved "' + d.favorite.name + '"' + (edit.practice ? " for the practice" : ""));
      edit.editor.saved();
      select(d.favorite.id);
      return load();
    }).catch(function (e) { $("#err").textContent = e.message; var b = $("#save"); if (b) { b.disabled = false; } });
  }
  function setHidden(id, hide) {
    OF.api("POST", "/favorites/" + id + "/hide", { hidden: hide }).then(function () {
      var f = byId(id); if (f) { f.hidden = hide; }
      toast(hide ? "Hidden from your favorites panel. Everyone else still sees it." : "Back in your favorites panel");
      renderRows();
      if (sel === id && !(edit && edit.editor)) { renderDetail(); } else if (sel === id && edit) { renderFoot(); }
    }).catch(function (err) { toast(err.message); });
  }

  // ---------- import ----------
  function renderImport() {
    var checked = !!imp.rows;
    var good = checked ? imp.rows.filter(function (r) { return r.ok; }).length : 0;
    var h = (imp.done ? '<div class="rs ok">' + esc(imp.done) + "</div>" : "") + '<ol class="ax-steps"><li class="' + (checked ? "done" : "on") + '">Paste or upload</li><li class="' + (checked ? "on" : "") + '">Check rows</li><li>Import</li></ol>' +
      '<label class="ax-lbl" style="margin-top:0" for="csv">CSV</label><textarea class="ax-ta" id="csv" rows="8" style="font-family:ui-monospace,Menlo,monospace;font-size:12.5px" placeholder="type,name,details">' + esc(imp.text) + "</textarea>" +
      '<p class="ax-help">One row per favorite. Prescriptions and labs can share a file. Everything imported becomes a practice favorite. Download the template for the column format. Order sets aren\'t imported: make them on the Order sets tab after importing their favorites.</p>' +
      '<div class="ax-imp-row"><button class="ax-btn" id="tpl">Download template</button><label class="ax-btn" style="display:inline-block">Upload file<input type="file" id="file" accept=".csv,text/csv" hidden></label><span class="grow"></span><button class="ax-btn primary" id="check">Check rows</button></div>' +
      '<div class="ax-err">' + esc(imp.error) + "</div>";
    if (checked) {
      h += '<table class="ax-check-tbl" style="margin-top:16px">' + imp.rows.map(function (r) {
        return '<tr><td class="st ' + (r.ok ? "ok" : "bad") + '">' + (r.ok ? "✓" : "✕") + '</td><td class="code">Row ' + r.row + "</td><td>" + esc(r.name) + (r.ok ? " · " + esc(r.summary) : '<span class="why">' + esc(r.reason) + "</span>") + "</td></tr>";
      }).join("") + "</table>";
      h += '<div class="ax-imp-row"><span class="grow"></span><button class="ax-btn primary" id="doImport"' + (good ? "" : " disabled") + ">Import " + OF.plural(good, "good row", "good rows") + "</button></div>";
    }
    var slot = $("#impSlot"); if (slot) { slot.innerHTML = h; }
  }
  function checkRows() {
    imp.text = $("#csv").value; imp.error = ""; imp.done = "";
    $("#check").disabled = true;
    OF.api("POST", "/admin/import/check", { csv: imp.text }).then(function (d) {
      imp.rows = d.error ? null : d.rows; imp.error = d.error; renderImport();
    }).catch(function (e) { imp.error = e.message; renderImport(); });
  }
  function doImport() {
    $("#doImport").disabled = true;
    OF.api("POST", "/admin/import", { csv: imp.text }).then(function (d) {
      var msg = "Imported " + OF.plural(d.imported, "practice favorite", "practice favorites") + "." + (d.skipped ? " " + OF.plural(d.skipped, "row was", "rows were") + " skipped." : "");
      toast(msg);
      // Stay on Settings; the new favorites show on the Prescriptions and Labs tabs.
      imp = { text: "", rows: null, error: "", done: msg };
      return load();
    }).catch(function (e) { imp.error = e.message; renderImport(); });
  }

  // ---------- settings ----------
  function renderSettings() {
    var s = data.settings, only = data.admins.length === 1;
    var h = '<div class="ax-sec"><h3>Available order types</h3><p>Choose what your practice can use. Turning something off hides it for everyone, but saved favorites and sets are kept if it\'s turned back on.</p>' +
      '<label class="ax-check"><input type="checkbox" data-set="rx_enabled"' + (s.rx_enabled ? " checked" : "") + (s.rx_enabled && !s.lab_enabled ? " disabled" : "") + "> Prescriptions</label>" +
      '<label class="ax-check" style="margin-top:8px"><input type="checkbox" data-set="lab_enabled"' + (s.lab_enabled ? " checked" : "") + (s.lab_enabled && !s.rx_enabled ? " disabled" : "") + "> Labs</label>" +
      '<label class="ax-check" style="margin-top:8px"><input type="checkbox" data-set="set_enabled"' + (s.set_enabled ? " checked" : "") + '> Order sets <span class="ax-help" style="display:inline;margin-left:4px">(several favorites added together)</span></label>' +
      '<p class="ax-help ax-info">' + I.info + " At least one of prescriptions or labs must stay on. Order sets can be turned off on their own.</p>" +
      ((!s.rx_enabled || !s.lab_enabled) && s.set_enabled ? '<p class="ax-warn">With ' + (s.rx_enabled ? "labs" : "prescriptions") + " off, order sets add only their " + (s.rx_enabled ? "prescriptions" : "labs") + ". Sets with nothing left to add are hidden.</p>" : "") + "</div>";
    h += '<div class="ax-sec"><h3>Admins</h3><p>Admins manage practice favorites, practice order sets, and these settings.</p><table class="ax-tbl"><tr><th>Name</th><th>Email</th><th></th></tr>';
    data.admins.forEach(function (a) {
      if (removeAsk === a.id) {
        h += '<tr><td colspan="3"><div class="ax-del" style="margin:0"><span class="grow">Remove <b>' + esc(a.name) + "</b> as an admin?" + (a.me ? " You will lose access to this app." : "") + '</span><button class="pp-btn pp-sm" data-adrm="no">Cancel</button><button class="pp-btn pp-sm pp-danger" data-adrm="yes">Remove</button></div></td></tr>';
      } else {
        h += '<tr><td><b style="color:#0d203c">' + esc(a.name) + "</b>" + (a.me ? ' <span class="ax-help" style="display:inline">(you)</span>' : "") + '</td><td class="used">' + esc(a.email) + '</td><td style="text-align:right">' + (only ? "" : '<button class="ax-btn quiet" data-adrmask="' + esc(a.id) + '">Remove</button>') + "</td></tr>";
      }
    });
    if (!data.admins.length) { h += '<tr><td colspan="3" class="used">No practice admins yet. Add one below.</td></tr>'; }
    h += '</table><label class="ax-lbl" for="adStaff">Add an admin</label><div class="cb"><div class="pp-search" style="margin:0">' + I.search + '<input id="adStaff" placeholder="Search staff by name or email" autocomplete="off" value="' + esc(staffQ) + '"></div>';
    if (staffQ.length >= 2) {
      h += '<div class="cb-pop">' + (staffResults.map(function (x) { return '<button class="cb-opt" data-adadd="' + esc(x.id) + '"><span><b style="color:#0d203c">' + esc(x.name) + "</b>" + (x.email ? " · " + esc(x.email) : "") + "</span></button>"; }).join("") || "<div class=\"cb-empty\">No matching active staff who aren't admins already</div>") + "</div>";
    }
    h += '</div><p class="ax-help ax-info">' + I.info + " There must always be at least one admin.</p></div>";
    h += '<div class="ax-sec"><h3>Import practice favorites</h3><p>Add many practice favorites at once from a CSV file.</p><div id="impSlot"></div></div>';
    $("#main").innerHTML = h;
    renderImport();
  }
  function searchStaff() {
    clearTimeout(staffTimer);
    if (staffQ.length < 2) { staffResults = []; renderSettings(); focusEnd("adStaff"); return; }
    staffTimer = setTimeout(function () {
      var asked = staffQ;
      OF.api("GET", "/admin/staff?q=" + encodeURIComponent(asked)).then(function (d) {
        if (asked !== staffQ) { return; }
        staffResults = d.results; renderSettings(); focusEnd("adStaff");
      }).catch(function (e) { toast(e.message); });
    }, 220);
  }
  function focusEnd(id) { var el = document.getElementById(id); if (el) { var p = el.value.length; el.focus(); el.setSelectionRange(p, p); } }

  // ---------- events ----------
  app.addEventListener("click", function (e) {
    var t = e.target.closest("button,a"); if (!t) { return; }
    var d = t.dataset;
    if (d.adtab) { var to = d.adtab; if (to === tab) { return; } guarded(function () { tab = to; select(null); listQ = ""; render(); }); return; }
    if (d.view) { var v = d.view; if (v === view) { return; } guarded(function () { view = v; select(null); renderSplit(); }); return; }
    if (d.eye) { setHidden(+d.eye, !byId(+d.eye).hidden); return; }
    if (d.sel) { var id = +d.sel; if (id === sel) { return; } guarded(function () { select(id); renderRows(); renderDetail(); }); return; }
    if (d.new) {
      guarded(function () {
        select(null);
        newFor = isAdmin() && view === "practice" ? "practice" : "mine";
        edit = { id: null, kind: tab, value: OF.blank(tab) };
        renderRows(); renderDetail();
      });
      return;
    }
    if (d.for) {
      // Switching who a new favorite is for keeps what was typed.
      newFor = d.for; var keep = edit.editor.payload(); keep.stale = []; edit.value = keep;
      var wasDirty = edit.editor.dirty(); renderDetail(); if (!wasDirty) { edit.editor.saved(); }
      return;
    }
    if (d.copy) {
      var src = byId(+d.copy); if (!src) { return; }
      var copy = JSON.parse(JSON.stringify(src)); copy.name = src.name + " (my copy)";
      select(null); copyOf = src.name; newFor = "mine";
      edit = { id: null, kind: src.kind, value: copy }; renderRows(); renderDetail();
      return;
    }
    // Back to the set only needs a warning when the form itself has changes; the set is kept either way.
    if (d.subback) { if (edit.editor.dirty()) { guard.run(function () { closeSub(null); }); } else { closeSub(null); } return; }
    if (d.cancel) { guarded(function () { select(null); renderRows(); renderDetail(); }); return; }
    if (d.del) { confirmDel = true; renderFoot(); return; }
    if (d.confirm) {
      if (d.confirm === "no") { confirmDel = false; renderFoot(); return; }
      var gone = byId(edit.id);
      var path = (gone.shared ? "/admin/favorites/" : "/favorites/") + gone.id;
      OF.api("DELETE", path).then(function (r) { toast('Deleted "' + r.deleted + '"' + (gone.shared ? " for the practice" : "")); select(null); return load(); })
        .catch(function (err) { toast(err.message); confirmDel = false; renderFoot(); });
      return;
    }
    if (d.adadd) {
      OF.api("POST", "/admin/admins", { staff_id: d.adadd }).then(function (r) { data.admins = r.admins; staffQ = ""; staffResults = []; toast("Added as an admin"); renderSettings(); }).catch(function (err) { toast(err.message); });
      return;
    }
    if (d.adrmask) { removeAsk = d.adrmask; renderSettings(); return; }
    if (d.adrm) {
      var who = removeAsk; removeAsk = null;
      if (d.adrm === "no") { renderSettings(); return; }
      OF.api("DELETE", "/admin/admins/" + encodeURIComponent(who)).then(function (r) {
        if (r.removed_self) { toast("You are no longer a favorites admin."); tab = kinds()[0]; select(null); return load(); }
        data.admins = r.admins; toast("Removed as an admin"); renderSettings();
      }).catch(function (err) { toast(err.message); renderSettings(); });
      return;
    }
    switch (t.id) {
      case "save": save(); break;
      case "subsave": saveSub(); break;
      case "check": checkRows(); break;
      case "doImport": doImport(); break;
      case "tpl": {
        var a = document.createElement("a");
        a.href = "data:text/csv;charset=utf-8," + encodeURIComponent(data.template);
        a.download = "order-favorites-template.csv"; document.body.appendChild(a); a.click(); a.remove();
        break;
      }
    }
  });
  app.addEventListener("change", function (e) {
    var t = e.target;
    if (t.id === "showHidden") { showHidden = t.checked; renderRows(); return; }
    if (t.id === "file" && t.files && t.files[0]) {
      var reader = new FileReader();
      reader.onload = function () { imp.text = String(reader.result || ""); imp.rows = null; imp.done = ""; renderImport(); };
      reader.readAsText(t.files[0]);
      return;
    }
    if (t.dataset && t.dataset.set) {
      var body = {}; body[t.dataset.set] = t.checked;
      OF.api("POST", "/admin/settings", body).then(function () { toast("Setting saved"); return load(); }).catch(function (err) { toast(err.message); render(); });
    }
  });
  app.addEventListener("input", function (e) {
    if (e.target.id === "q") { listQ = e.target.value; renderRows(); }
    if (e.target.id === "adStaff") { staffQ = e.target.value.trim(); searchStaff(); }
    if (e.target.id === "csv") { imp.text = e.target.value; }
  });

  load();
})();
{% endverbatim %}
