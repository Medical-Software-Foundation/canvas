(function () {
  "use strict";

  var BASE = document.body.getAttribute("data-base");
  var PAGE_SIZE = 25;
  var SAVE_DELAY = 600;
  var SEARCH_DELAY = 300;

  // ---- State -------------------------------------------------------------
  var tab = "sent";
  var views = null;            // saved settings per tab: { sent: view, received: view }
  var result = null;           // the last /failures response for the open tab
  var totals = { sent: 0, received: 0 };
  var me = { id: "", name: "", team_ids: [] };
  var people = { teams: [], staff: [] };
  var kindList = [];
  var pageNo = { sent: 1, received: 1 };
  var expanded = {};
  var threadOpen = {};
  var requestId = 0;
  var saveTimer = null, searchTimer = null;

  function defaults() {
    return {
      sent: { q: "", kinds: [], people: [], sort: { key: "when", dir: -1 }, collapsed: { mine: false, rest: false } },
      received: { q: "", people: [], sort: { key: "when", dir: -1 }, collapsed: { mine: false, rest: false } }
    };
  }

  // ---- Server calls ------------------------------------------------------
  function request(method, path, body) {
    var options = { method: method, credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(BASE + path, options).then(function (response) {
      return response.text().then(function (text) {
        var data = {};
        if (text) {
          try { data = JSON.parse(text); } catch (e) { data = {}; }
        }
        if (!response.ok) throw new Error(data.error || "Something went wrong (" + response.status + ").");
        return data;
      });
    });
  }

  function queryFor(which, saved) {
    var v = views[which];
    var parts = ["tab=" + which, "page=" + pageNo[which], "page_size=" + PAGE_SIZE];
    if (saved) {
      parts.push("saved=1");
    } else {
      parts.push("q=" + encodeURIComponent(v.q));
      if (v.kinds && v.kinds.length) parts.push("kinds=" + encodeURIComponent(v.kinds.join(",")));
      if (v.people.length) parts.push("people=" + encodeURIComponent(v.people.join(",")));
      parts.push("sort=" + v.sort.key, "dir=" + v.sort.dir);
      var folded = [];
      if (v.collapsed.mine) folded.push("mine");
      if (v.collapsed.rest) folded.push("rest");
      if (folded.length) parts.push("collapsed=" + folded.join(","));
    }
    return parts.join("&");
  }

  function load(saved) {
    var id = ++requestId;
    panelEl.setAttribute("aria-busy", "true");
    return request("GET", "/failures?" + queryFor(tab, saved)).then(function (res) {
      if (id !== requestId) return;
      panelEl.removeAttribute("aria-busy");
      result = res;
      totals = res.totals;
      me = res.me;
      kindList = res.kinds;
      pageNo[tab] = res.page;
      if (saved) { views = res.views; }
      views[tab] = res.view;
      renderRows();
    }).catch(function (err) {
      if (id !== requestId) return;
      panelEl.removeAttribute("aria-busy");
      toast(err.message);
    });
  }

  function changed(resetPage) {
    if (resetPage) pageNo[tab] = 1;
    scheduleSave();
    return load(false);
  }

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      request("POST", "/preferences", { views: views }).catch(function () { /* settings last for this visit only */ });
    }, SAVE_DELAY);
  }

  // ---- Small helpers -----------------------------------------------------
  var filtersEl = document.getElementById("filters");
  var countEl = document.getElementById("filter-count");
  var panelEl = document.getElementById("table-panel");
  var hintEl = document.getElementById("hint-line");
  var pagerEl = document.getElementById("pager");

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k === "class") n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function td(cls, kids) { return el("td", cls ? { class: cls } : {}, kids); }
  function th(text, cls) { return el("th", cls ? { class: cls, text: text, scope: "col" } : { text: text, scope: "col" }); }
  function relative(d) {
    var mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min ago";
    var hrs = Math.round(mins / 60);
    if (hrs < 24) return hrs + (hrs === 1 ? " hour ago" : " hours ago");
    var days = Math.round(hrs / 24);
    return days + (days === 1 ? " day ago" : " days ago");
  }
  function when(d) { return el("time", { datetime: d.toISOString(), title: d.toLocaleString(), text: relative(d) }); }
  function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }
  function stamp(d) { return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); }
  function btn(text, cls, onClick) {
    var b = el("button", { type: "button", class: "btn " + cls, text: text });
    b.addEventListener("click", onClick);
    return b;
  }
  function itemLink(text, url) {
    if (!url) return el("span", { text: text });
    return el("a", { href: url, class: "item", target: "_blank", rel: "noopener", text: text });
  }
  function digits(x) { return String(x || "").replace(/\D/g, ""); }

  var TEAM_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18.5 14.4c1.9.8 3 2.7 3 5.6"/></svg>';
  // A team gets a small two-person icon before its name; people get nothing extra.
  function nameNode(name, isTeam) {
    if (!isTeam) return document.createTextNode(name);
    var span = el("span", { class: "who", title: name + " is a team" }, [el("span", { class: "visually-hidden", text: "Team: " }), name]);
    span.insertAdjacentHTML("afterbegin", TEAM_ICON);
    return span;
  }
  function taskWho(row) {
    if (!row.task) return el("span", { class: "muted", text: "No task" });
    return el("span", { class: "alerted" }, [nameNode(row.task.assignee.name, row.task.assignee.kind === "team")]);
  }
  function taskLine(row, cls) {
    // Silent while the task sits with the latest sender; names whoever else now has it.
    if (!row.task_with) return null;
    return el("span", { class: "sub " + (cls || "") }, ["Task with ", nameNode(row.task_with.name, row.task_with.team)]);
  }
  function whoLabel(row) { return row.sender.label; }
  function byLine(row) {
    if (row.sender.kind === "staff") return "By " + row.sender.label;
    return row.sender.label;
  }

  var ICONS = {
    send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7z"/>',
    sent: '<path d="M20 6 9 17l-5-5"/>',
    dismiss: '<path d="M18 6 6 18"/><path d="M6 6l12 12"/>'
  };
  function iconBtn(icon, label, cls, onClick) {
    var b = el("button", { type: "button", class: "icon-btn " + cls, "aria-label": label, "data-tip": label });
    b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + ICONS[icon] + "</svg>";
    if (onClick) b.addEventListener("click", onClick);
    return b;
  }
  function acts(first, row) {
    return td("acts", [el("div", { class: "acts-grid" }, [
      first || el("span"),
      iconBtn("dismiss", "Dismiss", "quiet", function () { dismiss(row); })
    ])]);
  }

  var CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>';
  var OUTCOME_TEXT = { failed: "Failed", pending: "Waiting for delivery", delivered: "Delivered" };
  function linkify(text) {
    var span = el("span");
    text.split(/(https:\/\/\S+)/).forEach(function (part) {
      if (/^https:\/\//.test(part)) span.appendChild(el("a", { href: part, target: "_blank", rel: "noopener", text: part }));
      else if (part) span.appendChild(document.createTextNode(part));
    });
    return span;
  }
  var BOT = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="8" width="14" height="11" rx="2"/><path d="M12 8V5"/><circle cx="12" cy="4" r="1"/><path d="M9 13h.01M15 13h.01"/></svg>';
  function initials(name) {
    var bare = name.replace(/^(Dr\.|Mr\.|Ms\.|Mrs\.)\s+/, "").split(",")[0].trim().split(/\s+/);
    return ((bare[0] || "?")[0] + (bare.length > 1 ? bare[bare.length - 1][0] : "")).toUpperCase();
  }

  // ---- Who the task belongs to ------------------------------------------
  function isMineTask(t) {
    if (!t) return false;
    if (t.assignee.kind === "staff") return t.assignee.id === me.id;
    if (t.assignee.kind === "team") return me.team_ids.indexOf(t.assignee.id) > -1;
    return false;
  }
  function assigneeValue(t) { return t.assignee.kind + ":" + t.assignee.id; }

  // ---- Sorting header ----------------------------------------------------
  function sortTh(label, key, cls) {
    var S = views[tab].sort, active = S.key === key;
    var b = el("button", { type: "button", class: "sort-btn" }, [label, el("span", { class: "arrow", "aria-hidden": "true", text: active ? (S.dir === 1 ? "▲" : "▼") : "" })]);
    b.addEventListener("click", function () {
      if (S.key === key) S.dir = -S.dir; else { S.key = key; S.dir = key === "when" || key === "attempts" || key === "pages" ? -1 : 1; }
      changed(true);
    });
    var attrs = { scope: "col" };
    if (cls) attrs["class"] = cls;
    if (active) attrs["aria-sort"] = S.dir === 1 ? "ascending" : "descending";
    return el("th", attrs, [b]);
  }

  // ---- Filters -----------------------------------------------------------
  var openMulti = null;
  document.addEventListener("click", function (e) { if (openMulti && !openMulti.contains(e.target)) { closeMulti(); } });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && openMulti) { var b = openMulti.querySelector(".multi-btn"); closeMulti(); b.focus(); } });
  function closeMulti() { if (!openMulti) return; openMulti.querySelector(".multi-panel").hidden = true; openMulti.querySelector(".multi-btn").setAttribute("aria-expanded", "false"); openMulti = null; }
  var CARET = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
  function multiSelect(id, label, allText, groups, chosen, labelFor, onChange) {
    var wrap = el("div", { class: "multi" });
    var summary = el("span");
    function summarize() {
      var value = !chosen.length ? allText : chosen.length <= 2 ? chosen.map(labelFor).join(", ") : chosen.length + " selected";
      summary.textContent = "";
      summary.appendChild(el("span", { class: "k", text: label + ": " }));
      summary.appendChild(document.createTextNode(value));
      b.title = label + ": " + (!chosen.length ? allText : chosen.map(labelFor).join(", "));
      b.classList.toggle("active", chosen.length > 0);
    }
    var b = el("button", { type: "button", class: "multi-btn", id: id, "aria-haspopup": "true", "aria-expanded": "false" }, [summary]);
    summarize();
    b.insertAdjacentHTML("beforeend", CARET);
    var panel = el("div", { class: "multi-panel", hidden: "", role: "group", "aria-label": label });
    groups.forEach(function (g) {
      if (g.name) panel.appendChild(el("div", { class: "group", text: g.name }));
      g.items.forEach(function (it) {
        var box = el("input", { type: "checkbox", value: it.value });
        box.checked = chosen.indexOf(it.value) > -1;
        box.addEventListener("change", function () {
          var i = chosen.indexOf(it.value);
          if (box.checked && i === -1) chosen.push(it.value);
          if (!box.checked && i > -1) chosen.splice(i, 1);
          summarize(); onChange();
        });
        panel.appendChild(el("label", { class: "opt" }, [box, nameNode(it.label, it.team)]));
      });
    });
    var clearOpt = el("button", { type: "button", class: "clear-opt", text: "Clear selection" });
    clearOpt.addEventListener("click", function () { chosen.length = 0; panel.querySelectorAll("input").forEach(function (x) { x.checked = false; }); summarize(); onChange(); });
    panel.appendChild(clearOpt);
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      var wasOpen = openMulti === wrap;
      closeMulti();
      if (!wasOpen) { panel.hidden = false; b.setAttribute("aria-expanded", "true"); openMulti = wrap; }
    });
    wrap.appendChild(b); wrap.appendChild(panel);
    return wrap;
  }
  var SEARCH = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>';
  var barCount = null;
  function personLabel(value) {
    if (value === "__me") return "Me";
    var found = null;
    people.teams.concat(people.staff).forEach(function (p) { if (p.value === value) found = p.name; });
    return found || value;
  }
  function renderFilters() {
    var F = views[tab];
    filtersEl.textContent = "";
    var q = el("input", { type: "search", id: "f-q", value: F.q, "aria-label": "Search", placeholder: tab === "sent" ? "Search patient, recipient, or fax number" : "Search sender or fax number" });
    q.addEventListener("input", function () {
      F.q = q.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { changed(true); }, SEARCH_DELAY);
    });
    var sb = el("div", { class: "search-box" }, [q]);
    sb.insertAdjacentHTML("afterbegin", SEARCH);
    filtersEl.appendChild(sb);
    if (tab === "sent") {
      filtersEl.appendChild(multiSelect("f-kind", "Item", "All",
        [{ items: kindList.map(function (k) { return { value: k.value, label: k.label }; }) }],
        F.kinds, function (v) {
          var found = v;
          kindList.forEach(function (k) { if (k.value === v) found = k.label; });
          return found;
        }, function () { changed(true); }));
    }
    var peopleGroups = [{ items: [{ value: "__me", label: "Me" }] }];
    peopleGroups.push({ name: "Teams", items: people.teams.map(function (p) { return { value: p.value, label: p.name, team: true }; }) });
    peopleGroups.push({ name: "Staff", items: people.staff.map(function (p) { return { value: p.value, label: p.name }; }) });
    filtersEl.appendChild(multiSelect("f-person", tab === "sent" ? "Sent by or assigned to" : "Assigned to", "Anyone", peopleGroups,
      F.people, personLabel, function () { changed(true); }));
    filtersEl.appendChild(el("span", { class: "spacer" }));
    barCount = el("span", { class: "bar-count", "aria-live": "polite" });
    filtersEl.appendChild(barCount);
    var reset = el("button", { type: "button", class: "linkish reset-link", text: "Reset view" });
    reset.addEventListener("click", function () {
      clearTimeout(saveTimer);
      views = defaults();
      pageNo = { sent: 1, received: 1 };
      request("POST", "/preferences", { reset: true }).catch(function () { /* nothing saved */ });
      renderFilters();
      load(false).then(function () { toast("View reset to the defaults."); });
    });
    filtersEl.appendChild(el("span", { class: "bar-sep", "aria-hidden": "true" }));
    filtersEl.appendChild(reset);
  }

  // ---- Task card ---------------------------------------------------------
  function taskBox(row) {
    var t = row.task;
    var card = el("section", { class: "task-card", "aria-label": "Task: " + t.title });
    // The assignee's name is the control: click it to pick someone else, Escape to back out.
    var whoLine = el("p", { class: "task-who" });
    function showName() {
      whoLine.textContent = "Assigned to ";
      var isTeam = t.assignee.kind === "team";
      var nameBtn = el("button", { type: "button", class: "assignee-btn", "aria-label": "Assigned to " + (t.assignee.name ? (isTeam ? "the " + t.assignee.name + " team" : t.assignee.name) : "no one") + ". Change assignee" }, [t.assignee.name ? nameNode(t.assignee.name, isTeam) : document.createTextNode("No one")]);
      nameBtn.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>');
      nameBtn.addEventListener("click", showPicker);
      whoLine.appendChild(nameBtn);
    }
    function showPicker() {
      whoLine.textContent = "Assigned to ";
      var picker = el("select", { class: "assignee-picker", "aria-label": "Change assignee" });
      [["Teams", people.teams], ["Staff", people.staff]].forEach(function (g) {
        var og = el("optgroup", { label: g[0] });
        g[1].forEach(function (p) { og.appendChild(el("option", { value: p.value, text: p.name })); });
        picker.appendChild(og);
      });
      picker.value = assigneeValue(t);
      picker.addEventListener("change", function () {
        if (picker.value === assigneeValue(t)) { showName(); return; }
        var chosen = picker.value;
        var name = personLabel(chosen);
        picker.disabled = true;
        request("POST", "/tasks/reassign", { task_id: t.id, assignee: chosen }).then(function () {
          var kind = chosen.split(":")[0];
          var wasMine = row.mine;
          t.assignee = { kind: kind, id: chosen.substring(chosen.indexOf(":") + 1), name: name };
          t.comments.push({ author: me.name, mine: true, automatic: false, at: new Date().toISOString(), body: "Reassigned to " + name + " by " + me.name + "." });
          row.mine = isMineTask(t);
          if (row.mine !== wasMine && result) {
            result.counts.mine += row.mine ? 1 : -1;
            result.counts.rest += row.mine ? -1 : 1;
          }
          renderRows(); toast("Task reassigned to " + name + ".");
        }).catch(function (err) { toast(err.message); showName(); });
      });
      picker.addEventListener("keydown", function (e) { if (e.key === "Escape") { e.stopPropagation(); showName(); whoLine.querySelector("button").focus(); } });
      picker.addEventListener("blur", function () { setTimeout(function () { if (whoLine.contains(picker) && !picker.disabled) showName(); }, 150); });
      whoLine.appendChild(picker);
      picker.focus();
    }
    showName();
    // Title opens the task in the patient's chart. Tasks with no patient have no single-task page, so their title is plain text.
    var titleNode;
    if (!t.url) titleNode = el("h4", { text: t.title });
    else titleNode = el("h4", {}, [el("a", { href: t.url, target: "_blank", rel: "noopener", text: t.title })]);
    var open = !!threadOpen[row.key];
    var threadId = "thread-" + row.key.replace(/[^A-Za-z0-9_-]/g, "");
    function toggleThread() { threadOpen[row.key] = !open; renderRows(); var again = document.querySelector('[aria-controls="' + threadId + '"]'); if (again) again.focus(); }
    var tg = el("button", { type: "button", class: "thread-toggle", "aria-expanded": String(open), "aria-controls": threadId, "aria-label": (open ? "Hide" : "Show") + " comments" });
    tg.innerHTML = CHEVRON;
    tg.addEventListener("click", toggleThread);
    var countBtn = el("button", { type: "button", class: "count-btn", "aria-controls": threadId, text: t.comments.length ? plural(t.comments.length, "comment") : "No comments" });
    countBtn.addEventListener("click", toggleThread);
    // Due date: gray while on time, red with its age once past.
    var due = null;
    if (t.due) {
      var dueDay = new Date(t.due); dueDay.setHours(0, 0, 0, 0);
      var today = new Date(); today.setHours(0, 0, 0, 0);
      var daysLate = Math.round((today - dueDay) / 86400000);
      var dueLabel = dueDay.toLocaleDateString([], { month: "short", day: "numeric" });
      due = daysLate > 0 && t.is_open
        ? el("span", { class: "task-due overdue" }, [el("span", { class: "age", text: daysLate + " d" }), "Overdue " + dueLabel])
        : el("span", { class: "task-due" }, [daysLate === 0 ? "Due today" : (daysLate > 0 ? "Was due " : "Due ") + dueLabel]);
    } else {
      due = el("span", { class: "task-due" });
    }
    var statusText = t.status.charAt(0) + t.status.slice(1).toLowerCase();
    card.appendChild(el("div", { class: "task-bar" }, [
      tg,
      el("div", {}, [
        el("div", { class: "task-title-row" }, [titleNode, !t.is_open ? el("span", { class: "status-pill closed", text: statusText }) : null]),
        whoLine
      ]),
      el("div", { class: "task-side" }, [countBtn, due])
    ]));
    var body = el("div", { id: threadId });
    if (!open) body.hidden = true;
    card.appendChild(body);
    if (t.comments.length) {
      var thread = el("ol", { class: "thread", "aria-label": "Task comments" });
      t.comments.forEach(function (c) {
        var av = el("span", { class: "avatar" + (c.automatic ? " auto" : ""), "aria-hidden": "true" });
        if (c.automatic) av.innerHTML = BOT; else av.textContent = initials(c.author);
        thread.appendChild(el("li", {}, [
          av,
          el("div", {}, [
            el("div", { class: "c-head" }, [el("b", { text: c.mine ? c.author + " (you)" : c.author }), stamp(new Date(c.at))]),
            el("div", { class: "bubble" + (c.mine ? " mine" : "") }, [linkify(c.body)])
          ])
        ]));
      });
      body.appendChild(thread);
    }
    var textId = "comment-" + threadId;
    var text = el("textarea", { id: textId, placeholder: "Add a comment…", rows: "2" });
    var addBtn = btn("Add comment", "primary", function () {
      var value = text.value.trim();
      if (!value) { text.focus(); return; }
      addBtn.disabled = true;
      request("POST", "/tasks/comment", { task_id: t.id, body: value }).then(function () {
        t.comments.push({ author: me.name, mine: true, automatic: false, at: new Date().toISOString(), body: value });
        threadOpen[row.key] = true;
        renderRows(); toast("Comment added. It also shows on the task itself.");
      }).catch(function (err) { addBtn.disabled = false; toast(err.message); });
    });
    body.appendChild(el("div", { class: "comment-form" }, [
      el("label", { for: textId, class: "visually-hidden", text: "Add a comment" }),
      text,
      el("div", { class: "comment-actions" }, [
        btn("Cancel", "", function () { text.value = ""; }),
        addBtn
      ])
    ]));
    return card;
  }
  function historyRow(row, cols) {
    var cellKids = [];
    if (row.attempts) { cellKids.push(el("h4", { class: "section-title", text: "Fax attempts" })); cellKids.push(attemptList(row)); }
    cellKids.push(el("h4", { class: "section-title", text: "Task" }));
    cellKids.push(row.task ? taskBox(row) : el("p", { class: "no-task", text: "No task was made for this fax." }));
    return el("tr", { class: "history-row", id: "history-" + domId(row) }, [el("td", { colspan: String(cols) }, cellKids)]);
  }
  function attemptList(row) {
    var list = el("ol", { class: "attempt-list", "aria-label": "Fax attempts for " + (row.patient_name || row.fax_number) });
    row.attempts.forEach(function (a, i) {
      var at = new Date(a.at);
      list.appendChild(el("li", { class: a.outcome }, [
        el("span", { class: "a-when" }, [stamp(at), el("small", { text: (i === 0 ? "First send, " : "Attempt " + (i + 1) + ", ") + relative(at) })]),
        el("span", { class: "a-who", text: a.who }),
        el("span", { class: "outcome " + a.outcome, text: OUTCOME_TEXT[a.outcome] }),
        el("span", { class: "a-reason", text: a.reason })
      ]));
    });
    return list;
  }
  function domId(row) { return row.key.replace(/[^A-Za-z0-9_-]/g, ""); }
  function toggleBtn(row) {
    var open = !!expanded[row.key];
    var b = el("button", { type: "button", class: "expand", "aria-expanded": String(open), "aria-controls": "history-" + domId(row), "aria-label": (open ? "Hide" : "Show") + " details for " + (row.patient_name || row.fax_number) });
    b.innerHTML = CHEVRON;
    b.addEventListener("click", function () { expanded[row.key] = !open; renderRows(); var again = document.querySelector('[aria-controls="history-' + domId(row) + '"]'); if (again) again.focus(); });
    return b;
  }

  // ---- Contact card ------------------------------------------------------
  var openCard = null;
  function closeCard() { if (openCard) { openCard.card.hidden = true; openCard.btn.setAttribute("aria-expanded", "false"); openCard = null; } }
  document.addEventListener("click", function (e) { if (openCard && !openCard.wrap.contains(e.target) && !openCard.card.contains(e.target)) closeCard(); });
  window.addEventListener("resize", closeCard);
  window.addEventListener("scroll", closeCard, true);
  // The card floats above the page so the table's edges can't cut it off.
  function placeCard(card, anchor) {
    var r = anchor.getBoundingClientRect();
    var w = 300, gap = 6;
    var left = Math.max(8, Math.min(r.left - 12, window.innerWidth - w - 8));
    card.style.left = left + "px";
    card.style.top = (r.bottom + gap) + "px";
    var h = card.offsetHeight;
    if (r.bottom + gap + h > window.innerHeight - 8) card.style.top = Math.max(8, r.top - gap - h) + "px";
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && openCard) { var b = openCard.btn; closeCard(); b.focus(); } });
  function recipientCell(c, number, idBase) {
    var wrap = el("div", { class: "recipient" });
    if (!c) {
      wrap.appendChild(el("span", { text: number }));
      wrap.appendChild(el("span", { class: "unknown", text: "Not in contact directory" }));
      return td("", [wrap]);
    }
    var cardId = "card-" + idBase;
    var btnEl = el("button", { type: "button", class: "recipient-btn", "aria-expanded": "false", "aria-controls": cardId, text: c.name });
    var rows = [];
    if (c.phone) rows.push(el("dt", { text: "Phone" }), el("dd", {}, [el("a", { href: "tel:" + c.phone.replace(/[^0-9]/g, ""), text: c.phone })]));
    rows.push(el("dt", { text: "Fax" }), el("dd", { text: c.fax || number }));
    if (c.address) rows.push(el("dt", { text: "Address" }), el("dd", { text: c.address }));
    var spec = [c.specialty, c.practice].filter(function (x) { return x && x !== c.name; }).join(" · ");
    var card = el("div", { class: "contact-card", id: cardId, role: "dialog", "aria-label": c.name + " contact details", hidden: "" }, [
      el("h3", { text: c.name }),
      spec ? el("p", { class: "spec", text: spec }) : null,
      el("dl", {}, rows),
      el("p", { class: "source", text: c.source })
    ]);
    btnEl.addEventListener("click", function (e) {
      e.stopPropagation();
      var wasOpen = openCard && openCard.card === card;
      closeCard();
      if (!wasOpen) { card.hidden = false; placeCard(card, btnEl); btnEl.setAttribute("aria-expanded", "true"); openCard = { card: card, btn: btnEl, wrap: wrap }; }
    });
    wrap.appendChild(btnEl);
    wrap.appendChild(el("span", { class: "number", text: number }));
    wrap.appendChild(card);
    return td("", [wrap]);
  }

  // ---- Table -------------------------------------------------------------
  function render() { renderFilters(); renderRows(); }
  function renderRows() {
    closeCard();
    document.getElementById("count-sent").textContent = totals.sent;
    document.getElementById("count-received").textContent = totals.received;
    document.querySelectorAll(".tab").forEach(function (t) { t.setAttribute("aria-selected", String(t.dataset.tab === tab)); });
    panelEl.textContent = "";
    pagerEl.hidden = true;
    var rows = result.rows, view = views[tab];

    if (tab === "sent") {
      hintEl.textContent = "Outgoing faxes that didn't reach the recipient. Whoever sent it gets a task automatically. A row clears on its own once the same item is delivered.";
      if (!totals.sent) { if (barCount) barCount.textContent = ""; return empty("No failed sent faxes", "Everything sent in the last 90 days was delivered."); }
      filterCount(result.shown, totals.sent);
      if (!result.shown) return empty("No failed faxes match these filters", "Change the search or clear the filters to see all " + totals.sent + ".");
      var tbody = el("tbody");
      grouped(tbody, rows, 10, function (f) {
        var resend = null;
        if (f.can_resend) resend = iconBtn("send", "Resend", "primary", function () { openResend(f); });
        else if (f.resend_pending) {
          resend = iconBtn("sent", "Resent, waiting for delivery", "done", null);
          resend.setAttribute("aria-disabled", "true");
        }
        function sub(text) { return el("span", { class: "sub narrow-only", text: text }); }
        var pending = f.problem.pending;
        var n = f.attempts.length;
        var open = !!expanded[f.key];
        var at = new Date(f.occurred_at);
        tbody.appendChild(el("tr", { id: "row-" + domId(f), class: open ? "has-history" : "" }, [
          td("toggle", [toggleBtn(f)]),
          td("patient", [f.patient_name]),
          td("", [itemLink(f.type_label, f.link_url), f.pages === null ? null : sub(plural(f.pages, "page"))]),
          td(pending ? "problem pending" : "problem", [f.problem.text]),
          recipientCell(f.contact, f.fax_number, domId(f)),
          td("wide-only", [whoLabel(f), taskLine(f)]),
          td("muted", [when(at), sub(byLine(f)), taskLine(f, "narrow-only")]),
          td("num wide-only", [f.pages === null ? "" : String(f.pages)]),
          el("td", { class: "attempt-count" + (n > 1 ? " repeat" : ""), "aria-label": plural(n, "attempt") }, [String(n)]),
          acts(resend, f)
        ]));
        if (open) tbody.appendChild(historyRow(f, 10));
      });
      panelEl.appendChild(el("table", { class: "sent-table" }, [
        el("thead", {}, [el("tr", {}, [el("th", { scope: "col", "aria-label": "Details" }), sortTh("Patient", "patient"), sortTh("Item", "item"), sortTh("Problem", "problem"), sortTh("Recipient", "recipient"), sortTh("Sent by", "sender", "wide-only"), sortTh("When", "when"), sortTh("Pages", "pages", "num wide-only"), sortTh("Attempts", "attempts", "attempt-count"), el("th", { scope: "col" })])]),
        tbody
      ]));
    } else {
      hintEl.textContent = "Faxes that only partly arrived. The pages that came through are in Data Integration, and the team you choose gets a task to ask the sender to fax again.";
      if (!totals.received) { if (barCount) barCount.textContent = ""; return empty("No incomplete received faxes", "Every fax received in the last 90 days arrived in full."); }
      filterCount(result.shown, totals.received);
      if (!result.shown) return empty("No received faxes match these filters", "Change the search or clear the filters to see all " + totals.received + ".");
      var rb = el("tbody");
      grouped(rb, rows, 8, function (f) {
        var ropen = !!expanded[f.key];
        rb.appendChild(el("tr", { id: "row-" + domId(f), class: ropen ? "has-history" : "" }, [
          td("toggle", [toggleBtn(f)]),
          recipientCell(f.contact, f.fax_number, domId(f)),
          td("problem", [f.problem.text]),
          td("num", [f.pages === null ? "" : String(f.pages)]),
          td("muted", [when(new Date(f.occurred_at))]),
          td("", [itemLink("View in Data Integration", f.link_url)]),
          td("", [taskWho(f)]),
          acts(null, f)
        ]));
        if (ropen) rb.appendChild(historyRow(f, 8));
      });
      // Set widths so the spare space is shared, instead of all of it going to Problem.
      var rcols = el("colgroup", {}, ["44px", "16%", "18%", "11%", "12%", "18%", "21%", "84px"].map(function (w) { return el("col", { style: "width:" + w }); }));
      panelEl.appendChild(el("table", { class: "received-table" }, [
        rcols,
        el("thead", {}, [el("tr", {}, [el("th", { scope: "col", "aria-label": "Details" }), sortTh("Sender", "recipient"), sortTh("Problem", "problem"), sortTh("Pages arrived", "pages", "num"), sortTh("When", "when"), th("Document"), sortTh("Task assigned to", "task"), el("th", { scope: "col" })])]),
        rb
      ]));
    }
    renderPager();
  }
  // Splits rows into "Assigned to you" and "Everything else", each collapsible.
  function grouped(tbody, rows, cols, addRow) {
    var view = views[tab];
    [["mine", "Assigned to you", result.counts.mine], ["rest", "Everything else", result.counts.rest]].forEach(function (g) {
      var key = g[0], collapsed = view.collapsed[key];
      var b = el("button", { type: "button", class: "group-btn", "aria-expanded": String(!collapsed) }, [g[1], el("span", { class: "group-count", text: String(g[2]) })]);
      b.insertAdjacentHTML("afterbegin", CHEVRON);
      b.addEventListener("click", function () { view.collapsed[key] = !collapsed; changed(true); });
      tbody.appendChild(el("tr", { class: "group-row" }, [el("td", { colspan: String(cols) }, [b])]));
      if (collapsed) return;
      if (!g[2]) {
        tbody.appendChild(el("tr", { class: "group-empty" }, [el("td", { colspan: String(cols), text: key === "mine" ? "Nothing is assigned to you right now." : "Nothing else matches." })]));
        return;
      }
      rows.filter(function (r) { return (key === "mine") === !!r.mine; }).forEach(addRow);
    });
  }
  function renderPager() {
    if (!result || result.total_pages <= 1) { pagerEl.hidden = true; return; }
    pagerEl.hidden = false;
    document.getElementById("page-label").textContent = "Page " + result.page + " of " + result.total_pages;
    document.getElementById("prev-page").disabled = result.page <= 1;
    document.getElementById("next-page").disabled = result.page >= result.total_pages;
  }
  function filterCount(shown, total) {
    var F = views[tab], on = F.q || (F.kinds && F.kinds.length) || F.people.length;
    countEl.hidden = true;
    if (barCount) barCount.textContent = on ? "Showing " + shown + " of " + total : "";
  }
  function empty(title, body) { panelEl.appendChild(el("div", { class: "empty" }, [el("strong", { text: title }), body])); renderPager(); }

  document.getElementById("prev-page").addEventListener("click", function () { pageNo[tab] = Math.max(1, result.page - 1); load(false); });
  document.getElementById("next-page").addEventListener("click", function () { pageNo[tab] = result.page + 1; load(false); });

  // ---- Dialog ------------------------------------------------------------
  var scrim = document.getElementById("scrim");
  var titleEl = document.getElementById("dialog-title");
  var contextEl = document.getElementById("dialog-context");
  var bodyEl = document.getElementById("dialog-body");
  var errorEl = document.getElementById("dialog-error");
  var submitEl = document.getElementById("dialog-submit");
  var onSubmit = null, lastFocus = null;

  function openDialog(title, context, nodes, submitText, handler) {
    lastFocus = document.activeElement;
    titleEl.textContent = title; contextEl.textContent = context;
    bodyEl.textContent = ""; nodes.forEach(function (n) { bodyEl.appendChild(n); });
    errorEl.textContent = ""; submitEl.textContent = submitText; submitEl.disabled = false; onSubmit = handler;
    scrim.hidden = false;
    var first = bodyEl.querySelector("input, select"); if (first) first.focus();
  }
  function closeDialog() { scrim.hidden = true; onSubmit = null; if (lastFocus) lastFocus.focus(); }
  document.getElementById("dialog-cancel").addEventListener("click", closeDialog);
  scrim.addEventListener("click", function (e) { if (e.target === scrim) closeDialog(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !scrim.hidden) closeDialog(); });
  submitEl.addEventListener("click", function () {
    if (!onSubmit) return;
    var problem = onSubmit();
    if (typeof problem === "string") { errorEl.textContent = problem; return; }
    if (problem && problem.then) {
      errorEl.textContent = ""; submitEl.disabled = true;
      problem.then(closeDialog).catch(function (err) { submitEl.disabled = false; errorEl.textContent = err.message; });
      return;
    }
    closeDialog();
  });
  function field(id, label, input, hint, hintClass) {
    input.id = id;
    return el("div", { class: "field" }, [el("label", { for: id, text: label }), input, hint ? el("p", { class: "hint " + (hintClass || ""), text: hint }) : null]);
  }

  function openResend(f) {
    var number = el("input", { type: "tel", value: f.fax_number });
    var name = el("input", { type: "text", value: f.directory_name, placeholder: "Who should receive it" });
    var hint = f.directory_name ? "Matched in your contact directory." : "No single match in your contact directory. Type the recipient's name.";
    openDialog("Resend note", f.patient_name + ", " + plural(f.pages || 0, "page"), [
      field("resend-number", "Fax number", number),
      field("resend-name", "Recipient name", name, hint, f.directory_name ? "found" : "")
    ], "Resend fax", function () {
      if (!name.value.trim()) return "Add the recipient's name to resend.";
      if (!number.value.trim()) return "Add a fax number to resend.";
      return request("POST", "/resend", { event_id: f.source_id, recipient_name: name.value.trim(), recipient_fax_number: number.value.trim() }).then(function () {
        var now = new Date().toISOString();
        f.attempts.push({ at: now, number: f.attempts.length + 1, who: "Resent by " + me.name, outcome: "pending", reason: "" });
        f.sender = { label: "Resent by " + me.name, kind: "resent" };
        f.occurred_at = now;
        f.problem = { pending: true, text: "Resent, waiting for delivery" };
        f.task_with = null;
        f.can_resend = false; f.resend_pending = true;
        expanded[f.key] = true; renderRows();
        toast("Resent to " + name.value.trim() + ". The row clears once it's delivered.");
      });
    });
  }

  function dismiss(f) {
    var row = document.getElementById("row-" + domId(f));
    request("POST", "/dismiss", { source_type: f.source_type, source_id: f.source_id }).then(function () {
      var done = function () { load(false).then(function () { toast("Dismissed. It won't show here again."); }); };
      if (row && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) { row.classList.add("leaving"); setTimeout(done, 200); } else { done(); }
    }).catch(function (err) { toast(err.message); });
  }

  var toastEl = document.getElementById("toast"), toastTimer = null;
  function toast(msg) { toastEl.textContent = msg; toastEl.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(function () { toastEl.hidden = true; }, 3200); }

  document.querySelectorAll(".tab").forEach(function (t) {
    t.addEventListener("click", function () {
      if (t.dataset.tab === tab || !views) return;
      tab = t.dataset.tab;
      renderFilters();
      load(false);
    });
  });

  // ---- Start -------------------------------------------------------------
  panelEl.appendChild(el("div", { class: "empty" }, ["Loading failed faxes…"]));
  Promise.all([request("GET", "/people"), request("GET", "/failures?" + "tab=sent&page=1&page_size=" + PAGE_SIZE + "&saved=1")]).then(function (both) {
    people = both[0];
    result = both[1];
    totals = result.totals; me = result.me; kindList = result.kinds;
    views = result.views;
    views[tab] = result.view;
    pageNo[tab] = result.page;
    render();
  }).catch(function (err) {
    panelEl.textContent = "";
    panelEl.appendChild(el("div", { class: "empty" }, [el("strong", { text: "The dashboard couldn't load" }), err.message]));
  });
})();
