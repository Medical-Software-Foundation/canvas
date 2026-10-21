{% verbatim %}
/* Order Favorites chart panel: pick favorites and order sets and add them to a note, and manage your own.
   Opens on the note whose button was clicked; Change in the footer can pick another open visit or chart
   review note of the same patient. Layout follows mockups/order-favorites-panel-additions.html. */
(function () {
  "use strict";
  var OF = window.OF, esc = OF.esc, I = OF.I;
  var $ = function (s) { return document.querySelector(s); };
  var NOTE_ID = document.body.getAttribute("data-note-id") || "";

  var data = null;
  var tab = "all", filter = "all", q = "", view = "use", mFilter = "active", confirmDel = null, result = "";
  var selected = [], expanded = {}, showSel = false;
  var target = null, others = null, othersTotal = 0, picking = false; // the note orders go into, and the patient's other open notes
  var edit = null; // {editor, id, kind, practice}
  var newMenu = false, newFor = "mine";

  function toast(m) { var t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove("on"); }, 2200); }
  function byId(id) { for (var i = 0; i < data.favorites.length; i++) { if (data.favorites[i].id === id) { return data.favorites[i]; } } return null; }
  // "Oct 15, 2026 at 12:23 PM EDT with Canvas Support", in the browser's time zone, as Dot Phrases shows it.
  function whenLine(note) {
    var d = note.when ? new Date(note.when) : null, at = "";
    if (d && !isNaN(d)) {
      at = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) + " at " +
        d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    }
    return at && note.provider ? at + " with " + note.provider : at || (note.provider ? "With " + note.provider : "");
  }
  function adminUrl(id) { return OF.API + "/admin/" + (id ? "?favorite=" + encodeURIComponent(id) : ""); }
  // The order types and sets the practice uses, as panel tabs.
  function types() { return data.kinds.concat(data.sets_enabled ? ["set"] : []); }
  // An order set with nothing left to add (its favorites deleted or their type turned off) isn't offered.
  function usable(f) { return f.kind !== "set" || OF.setMembers(f).length > 0; }

  function load() {
    return OF.api("GET", "/panel/data?note_id=" + encodeURIComponent(NOTE_ID)).then(function (d) {
      data = d;
      OF.useFavorites(data.favorites);
      if (!target) { target = data.note ? { id: data.note.id, title: data.note.title, when: data.note.when, provider: data.note.provider, url: data.note.url, clicked: true } : null; }
      if (tab !== "all" && types().indexOf(tab) < 0) { tab = "all"; }
      selected = selected.filter(function (id) { var f = byId(id); return f && !f.hidden && usable(f); });
      render();
    }).catch(function (e) { $("#vUse").innerHTML = '<p class="loading">' + esc(e.message) + "</p>"; });
  }

  function list(kind, opts) {
    return data.favorites.filter(function (f) {
      if (kind !== "all" && f.kind !== kind) { return false; }
      if (opts.hidden ? !f.hidden : f.hidden) { return false; }
      if (opts.filter === "mine" && !f.mine) { return false; }
      if (opts.filter === "practice" && !f.shared) { return false; }
      if (opts.usableOnly && !usable(f)) { return false; }
      return !q || OF.searchText(f).indexOf(q.toLowerCase()) >= 0;
    });
  }
  function counts() {
    var n = { rx: 0, lab: 0, set: 0 };
    selected.forEach(function (id) { var f = byId(id); if (f) { n[f.kind]++; } });
    return n;
  }
  var TAB = { all: ["All", "all"], rx: ["Rx", "rx"], lab: ["Labs", "lab"], set: ["Sets", "set"] };
  function tabsHtml() {
    var t = types();
    if (t.length < 2) { return ""; }
    var n = counts();
    var shown = ["all"].concat(t);
    return '<div class="pp-seg' + (shown.length > 3 ? " four" : "") + '" id="tabs">' + shown.map(function (k) {
      var c = k === "all" ? selected.length : n[k];
      return '<button class="' + (tab === k ? "on" : "") + '" data-tab="' + k + '"><span class="ti">' + I[TAB[k][1]] + "</span>" + TAB[k][0] + (c ? '<span class="cnt">' + c + "</span>" : "") + "</button>";
    }).join("") + "</div>";
  }
  function chev(f) { var open = !!expanded[f.id]; return '<button class="pc-exp' + (open ? " open" : "") + '" data-exp="' + f.id + '" title="' + (open ? "Show less" : "Show details") + '" aria-expanded="' + open + '">' + I.chev + "</button>"; }
  function kindTag(f) { return tab === "all" ? '<span class="pc-kind ' + f.kind + '">' + I[f.kind] + (f.kind === "rx" ? "Rx" : f.kind === "lab" ? "Lab" : "Order set") + "</span>" : ""; }
  // The expand arrow at the top right, and in the All tab the Rx / Lab / Order set tag at the bottom right.
  function side(f) { return '<div class="pc-side">' + chev(f) + kindTag(f) + "</div>"; }
  function card(f) {
    var on = selected.indexOf(f.id) >= 0;
    return '<div class="pc ' + (f.shared ? "pc-team" : "pc-mine") + (on ? " sel" : "") + '" data-card="' + f.id + '">' +
      '<input type="checkbox" data-sel="' + f.id + '"' + (on ? " checked" : "") + ' aria-label="Pick ' + esc(f.name) + '">' +
      '<div class="pc-main"><div class="pc-top"><span class="pc-code">' + esc(f.name) + "</span></div>" + (expanded[f.id] ? OF.details(f) : OF.compact(f)) + "</div>" + side(f) + "</div>";
  }

  // ---------- use favorites ----------
  var GROUPS = [["set", "Order sets"], ["rx", "Prescriptions"], ["lab", "Labs"]];
  function searchWord() { return tab === "all" ? "favorites" : tab === "rx" ? "prescriptions" : tab === "lab" ? "labs" : "order sets"; }
  function renderUse() {
    var h = '<div class="pp-band"><div class="pp-head"><h2>' + esc(data.title) + '</h2><button class="pp-icon" id="gear" title="Manage favorites" aria-label="Manage favorites">' + I.sliders + "</button></div>" +
      tabsHtml() +
      '<div class="pp-search">' + I.search + '<input id="q" placeholder="Search ' + searchWord() + '" autocomplete="off" aria-label="Search" value="' + esc(q) + '"></div>' +
      '<div class="pp-seg" id="filt">' + [["all", "All"], ["mine", "Mine"], ["practice", "Practice"]].map(function (p) { return '<button class="' + (filter === p[0] ? "on" : "") + '" data-f="' + p[0] + '">' + p[1] + "</button>"; }).join("") + "</div>" +
      '</div><div class="pp-content">' + result;
    if (tab === "all") {
      var any = false;
      GROUPS.forEach(function (g) {
        if (types().indexOf(g[0]) < 0) { return; }
        var items = list(g[0], { filter: filter, usableOnly: true });
        if (items.length) { any = true; h += '<div class="grp-h">' + g[1] + "</div>" + items.map(card).join(""); }
      });
      if (!any) { h += '<div class="empty">No favorites match. Add one from Manage.</div>'; }
    } else {
      var items = list(tab, { filter: filter, usableOnly: true });
      h += items.length ? items.map(card).join("") : '<div class="empty">No favorites match. Add one from Manage.</div>';
    }
    $("#vUse").innerHTML = h + "</div>" + footer();
  }

  // ---------- footer: the target note and what's selected ----------
  // Opens the note in the chart. target="_top" moves the whole Canvas page, which closes this panel.
  // Left off the note the panel was opened from: it is already on screen, and reloading would clear what is checked.
  function noteLink(note, icon, cls) {
    if (!note.url) { return ""; }
    return '<a class="' + cls + '" target="_top" href="' + esc(note.url) + '" title="Open this note in the chart" aria-label="Open this note in the chart">' + icon + "</a>";
  }
  function footer() {
    var n = selected.length;
    var h = '<div class="pp-foot"><span class="lbl">Adding to</span>';
    if (picking) {
      if (!others) { h += '<div class="info">Loading this patient\'s open notes…</div>'; }
      else if (!others.length) { h += '<div class="info">This patient has no open visit or chart review notes.</div><button class="linkbtn" data-pickcancel="1">Back</button>'; }
      else {
        h += '<div class="notepick">' + others.map(function (x) {
          return '<div class="noterow"><button class="' + (target && x.id === target.id ? "on" : "") + '" data-note="' + esc(x.id) + '">' + esc(x.title) + (x.clicked ? " (this note)" : "") + "<span>" + esc(whenLine(x)) + "</span></button>" + (x.clicked ? "" : noteLink(x, I.open, "noteopen")) + "</div>";
        }).join("") + '<div class="warnline">Only this patient\'s open visit and chart review notes are listed.' +
          (othersTotal > others.length ? " Showing the " + others.length + " most recent of " + othersTotal + " open notes." : "") + "</div></div>";
      }
    } else if (target) {
      h += '<div class="tgt"><div class="target">' + esc(target.title) + (target.clicked ? "" : noteLink(target, I.open, "noteopen inline")) + "<span>" + esc(whenLine(target)) + '</span></div><button class="linkbtn" data-pick="1">Change</button></div>';
      if (!target.clicked) { h += '<div class="info" style="margin-top:-4px">Orders will go into this note, not the one you\'re in.</div>'; }
    } else {
      h += '<div class="info">The note you opened this from is no longer open. Pick another open note for this patient.</div><button class="linkbtn" data-pick="1" style="margin-bottom:10px">Pick a note</button>';
    }
    if (n) {
      // Order sets count as their orders, so "2 selected (3 orders)" says exactly what will be added.
      var orders = {};
      selected.forEach(function (id) { var f = byId(id); (f.kind === "set" ? OF.setMembers(f) : [f]).forEach(function (x) { orders[x.id] = 1; }); });
      var count = Object.keys(orders).length;
      h += '<div class="selbar"><button class="linkbtn" data-showsel="1">' + (showSel ? "Hide " : "Show ") + n + " selected" + (count !== n ? " (" + OF.plural(count, "order", "orders") + ")" : "") + '</button><button class="linkbtn muted-link" data-clear="1">Clear</button></div>';
      if (showSel) {
        h += '<div class="selbox">' + selected.map(function (id) {
          var f = byId(id);
          var row = '<div class="selrow">' + I[f.kind] + '<span class="nm">' + esc(f.name) + '</span><button class="x" data-unsel="' + f.id + '" title="Remove" aria-label="Remove ' + esc(f.name) + '">✕</button></div>';
          if (f.kind === "set") { row += OF.setMembers(f).map(function (x) { return '<div class="selrow ind">' + I[x.kind] + '<span class="nm">' + esc(x.name) + "</span></div>"; }).join(""); }
          return row;
        }).join("") + "</div>";
      }
    }
    h += '<button class="pp-btn pp-primary" id="add"' + (n && target && !picking ? "" : " disabled") + ">" + (n ? "Add " + n + " to note" : "Pick favorites to add") + "</button></div>";
    return h;
  }
  function openPicker() {
    picking = true; render();
    if (others) { return; }
    OF.api("GET", "/notes/" + encodeURIComponent(NOTE_ID) + "/others").then(function (d) { others = d.notes; othersTotal = d.total || d.notes.length; render(); })
      .catch(function (e) { picking = false; result = '<div class="rs bad">' + esc(e.message) + "</div>"; render(); });
  }

  // ---------- manage ----------
  function rowHtml(f) {
    if (confirmDel === f.id) {
      return '<div class="ml-row ml-confirm"><div class="ml-main"><div class="ml-code">Delete ' + esc(f.name) + '?</div><div class="ml-ask">This can\'t be undone.</div></div>' +
        '<button class="pp-btn pp-sm" data-delno="' + f.id + '">Cancel</button><button class="pp-btn pp-sm pp-danger" data-delyes="' + f.id + '">Delete</button></div>';
    }
    var a = "";
    if (f.hidden) { a += '<button class="ml-restore" data-show="' + f.id + '">Show</button>'; }
    else {
      if (f.mine) { a += '<button class="ml-icon" data-edit="' + f.id + '" title="Edit" aria-label="Edit">' + I.edit + "</button>"; }
      if (f.shared) { a += '<button class="ml-icon" data-copy="' + f.id + '" title="Make a copy" aria-label="Make a copy">' + I.copy + "</button>"; }
      if (f.shared) { a += '<button class="ml-icon" data-hide="' + f.id + '" title="Hide from my list" aria-label="Hide from my list">' + I.hide + "</button>"; }
      if (f.mine) { a += '<button class="ml-icon" data-del="' + f.id + '" title="Delete" aria-label="Delete">' + I.trash + "</button>"; }
    }
    return '<div class="ml-row"><div class="ml-main"><div class="ml-top"><span class="ml-code">' + esc(f.name) + "</span></div>" + (expanded[f.id] ? OF.details(f) : OF.compact(f)) + "</div>" + a + side(f) + "</div>";
  }
  function group(items) { return '<div class="ml-group">' + items.map(rowHtml).join("") + "</div>"; }
  function renderManage() {
    var h = '<div class="pp-band"><div class="pp-head"><button class="pp-back" id="back" title="Back" aria-label="Back">' + I.back + '</button><h2>Manage favorites</h2><button class="pp-btn pp-primary pp-sm" id="newBtn">+ New</button></div>' +
      tabsHtml() +
      '<div class="pp-seg sm" id="mseg"><button class="' + (mFilter === "active" ? "on" : "") + '" data-m="active">Active</button><button class="' + (mFilter === "hidden" ? "on" : "") + '" data-m="hidden">Hidden</button></div>' +
      '</div><div class="pp-content">' + result;
    if (newMenu) {
      h += '<div class="ed"><label>What do you want to make?</label><div class="row new-menu">' + types().map(function (k) {
        return '<button class="pp-btn' + (k === "set" ? " pp-primary" : "") + '" data-make="' + k + '">' + (k === "rx" ? "Prescription favorite" : k === "lab" ? "Lab favorite" : "Order set (several favorites at once)") + "</button>";
      }).join("") + "</div></div>";
    }
    if (mFilter === "hidden") {
      var hid = list(tab, { filter: "all", hidden: true });
      h += '<div class="ml-sec">Hidden from your list <span>' + hid.length + "</span></div>";
      h += hid.length ? group(hid) : '<p class="ml-empty">Nothing hidden. Hide a practice favorite to take it off your list; everyone else still sees it.</p>';
    } else {
      var mine = list(tab, { filter: "mine" }), prac = list(tab, { filter: "practice" });
      h += '<div class="ml-sec">My favorites <span>' + mine.length + "</span></div>";
      h += mine.length ? group(mine) : '<p class="ml-empty">None yet. Use + New, or copy a practice favorite.</p>';
      h += '<div class="ml-sec">Practice favorites <span>' + prac.length + "</span></div>";
      if (prac.length) {
        h += data.is_admin
          ? '<div class="ml-note">' + I.lock + '<span>You manage practice favorites in the Order Favorites app. <a class="linkish" href="' + esc(adminUrl()) + '" target="_blank" rel="noopener">Open it</a></span></div>'
          : '<div class="ml-note">' + I.lock + "<span>Only your practice's favorites admins can change these. Copy one to make your own version.</span></div>";
      }
      h += prac.length ? group(prac) : '<p class="ml-empty">None yet.</p>';
    }
    $("#vManage").innerHTML = h + "</div>";
  }

  // ---------- editor ----------
  var guard = OF.Guard($("#guardSlot"), function () { return !!(edit && edit.editor.dirty()); }, function () { return edit ? edit.editor.name() : ""; });
  function openEditor(value, opts) {
    var isSet = value.kind === "set";
    edit = { id: opts.id || null, kind: value.kind, practice: false, value: value, note: opts.note };
    $("#edBack").innerHTML = I.back;
    $("#edTitle").textContent = (opts.id ? "Edit " : "New ") + (isSet ? "order set" : (value.kind === "rx" ? "prescription" : "lab") + " favorite");
    $("#edErr").textContent = "";
    guard.clear();
    // Admins choose Personal or Practice for a new order set; everything else saved here is personal.
    newFor = "mine";
    drawEditor();
    view = "edit"; result = ""; render();
  }
  function drawEditor() {
    var isSet = edit.kind === "set";
    var forSeg = isSet && !edit.id && data.is_admin
      ? '<div class="save-for"><label>Save for</label><div class="pp-seg">' + [["mine", "Personal"], ["practice", "Practice"]].map(function (v) { return '<button class="' + (newFor === v[0] ? "on" : "") + '" data-for="' + v[0] + '">' + v[1] + "</button>"; }).join("") + '</div><div class="hint">' + (newFor === "practice" ? "Everyone in the practice will see this. It can only include practice favorites." : "Only you will see this in your favorites panel.") + "</div></div>"
      : "";
    $("#edFor").innerHTML = forSeg;
    $("#vEdit").classList.toggle("is-set", isSet);
    edit.practice = isSet && newFor === "practice";
    edit.editor = isSet
      ? OF.SetEditor($("#edForm"), edit.value, { favorites: data.favorites, practice: edit.practice, kinds: data.kinds, note: edit.note })
      : OF.Editor($("#edForm"), edit.value, { note: edit.note });
    $("#edHint").textContent = edit.practice ? "Saved as a practice order set." : "Saved as your personal " + (isSet ? "order set." : "favorite.") + (data.is_admin && !isSet ? " Practice favorites are added in the Order Favorites app." : "");
    $("#edSave").textContent = edit.practice ? "Save practice order set" : "Save";
  }
  function leaveEditor() { guard.run(function () { edit = null; view = "manage"; render(); }); }
  function save() {
    var body = edit.editor.payload();
    var path = edit.practice ? "/admin/favorites" : "/favorites";
    var req = edit.id ? OF.api("PATCH", path + "/" + edit.id, body) : OF.api("POST", path, body);
    $("#edSave").disabled = true;
    req.then(function (d) {
      toast('Saved "' + d.favorite.name + '"');
      edit.editor.saved(); edit = null; view = "manage"; mFilter = "active";
      return load();
    }).catch(function (e) { $("#edErr").textContent = e.message; }).then(function () { $("#edSave").disabled = false; });
  }

  // ---------- adding ----------
  function addToNote() {
    $("#add").disabled = true;
    OF.api("POST", "/notes/" + encodeURIComponent(target.id) + "/add", { favorite_ids: selected }).then(function (d) {
      result = "";
      if (d.added.length) { result += '<div class="rs ok">' + d.added.length + " added to " + esc(d.note.title) + ": " + d.added.map(function (f) { return esc(f.name); }).join(", ") + "</div>"; }
      d.skipped.forEach(function (s) {
        var why = s.reason === "partner" ? esc(s.lab || "Its lab") + " isn't an active lab partner any more." : esc(s.lab) + " no longer offers " + esc(s.stale.join(", ")) + ".";
        var fix = !s.shared ? '<a data-edit="' + s.id + '">Fix it now</a>'
          : data.is_admin ? '<a href="' + esc(adminUrl(s.id)) + '" target="_blank" rel="noopener">Fix it in the Order Favorites app</a>'
          : "Ask a favorites admin to update it, or copy it in Manage and fix your copy.";
        result += '<div class="rs warn"><b>' + esc(s.name) + "</b> wasn't added: " + why + " " + fix + "</div>";
      });
      selected = []; showSel = false;
      render();
    }).catch(function (e) {
      result = '<div class="rs bad">' + esc(e.message) + "</div>";
      render();
    });
  }

  function render() {
    if (!data) { return; }
    $("#vUse").hidden = view !== "use"; $("#vManage").hidden = view !== "manage"; $("#vEdit").hidden = view !== "edit";
    if (view === "use") { renderUse(); }
    if (view === "manage") { renderManage(); }
  }
  function keepFocus(id) { var el = document.getElementById(id); if (el) { var p = el.value.length; el.focus(); el.setSelectionRange(p, p); } }
  function toggle(id) { var i = selected.indexOf(id); if (i >= 0) { selected.splice(i, 1); } else { selected.push(id); } result = ""; }

  document.addEventListener("click", function (e) {
    var ex = e.target.closest("[data-exp]");
    if (ex) { var xid = +ex.getAttribute("data-exp"); expanded[xid] = !expanded[xid]; render(); return; }
    var cardEl = e.target.closest("[data-card]");
    if (cardEl && e.target.tagName !== "INPUT") { toggle(+cardEl.getAttribute("data-card")); render(); return; }
    var t = e.target.closest("button,a"); if (!t) { return; }
    var d = t.dataset;
    if (d.tab) { if (view === "edit") { return; } tab = d.tab; q = ""; confirmDel = null; render(); return; }
    if (d.f) { filter = d.f; render(); return; }
    if (d.m) { mFilter = d.m; confirmDel = null; render(); return; }
    if (d.pick) { openPicker(); return; }
    if (d.pickcancel) { picking = false; render(); return; }
    if (d.note) { var n = others.filter(function (x) { return x.id === d.note; })[0]; target = n; picking = false; result = ""; render(); return; }
    if (d.showsel) { showSel = !showSel; render(); return; }
    if (d.clear) { selected = []; showSel = false; render(); return; }
    if (d.unsel) { toggle(+d.unsel); render(); return; }
    if (d.make) { newMenu = false; openEditor(OF.blank(d.make), {}); return; }
    if (d.for) { newFor = d.for; var keep = edit.editor.payload(); edit.value = keep; drawEditor(); return; }
    if (d.edit) { var f = byId(+d.edit); if (f && f.mine) { openEditor(f, { id: f.id }); } return; }
    if (d.copy) {
      var src = byId(+d.copy); if (!src) { return; }
      var copy = JSON.parse(JSON.stringify(src)); copy.name = src.name + " (my copy)";
      openEditor(copy, { note: 'A personal copy of the practice ' + (src.kind === "set" ? "order set" : "favorite") + ' "' + src.name + '". Changes to the practice one won\'t reach your copy.' });
      return;
    }
    if (d.hide || d.show) {
      var hid = !!d.hide, fid = +(d.hide || d.show);
      OF.api("POST", "/favorites/" + fid + "/hide", { hidden: hid }).then(function () {
        var fv = byId(fid); if (fv) { fv.hidden = hid; }
        selected = selected.filter(function (x) { return x !== fid; });
        toast(hid ? "Hidden from your list. Everyone else still sees it." : "Back on your list"); render();
      }).catch(function (err) { toast(err.message); });
      return;
    }
    if (d.del) { confirmDel = +d.del; render(); return; }
    if (d.delno) { confirmDel = null; render(); return; }
    if (d.delyes) {
      var did = +d.delyes;
      OF.api("DELETE", "/favorites/" + did).then(function (r) { confirmDel = null; selected = selected.filter(function (x) { return x !== did; }); toast('Deleted "' + r.deleted + '"'); return load(); }).catch(function (err) { toast(err.message); });
      return;
    }
    switch (t.id) {
      case "gear": confirmDel = null; newMenu = false; view = "manage"; result = ""; mFilter = "active"; render(); break;
      case "back": newMenu = false; view = "use"; result = ""; render(); break;
      case "add": addToNote(); break;
      case "newBtn":
        if (tab === "all" && types().length > 1) { newMenu = !newMenu; render(); }
        else { openEditor(OF.blank(tab === "all" ? types()[0] : tab), {}); }
        break;
      case "edBack": case "edCancel": leaveEditor(); break;
      case "edSave": save(); break;
    }
  });
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.dataset && t.dataset.sel) { var id = +t.dataset.sel, i = selected.indexOf(id); if (t.checked && i < 0) { selected.push(id); } if (!t.checked && i >= 0) { selected.splice(i, 1); } result = ""; render(); }
  });
  document.addEventListener("input", function (e) {
    if (e.target.id === "q") { q = e.target.value; render(); keepFocus("q"); }
  });

  load();
})();
{% endverbatim %}
