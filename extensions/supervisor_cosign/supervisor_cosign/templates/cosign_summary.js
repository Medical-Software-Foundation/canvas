// Co-sign summary page.
//
// Two views over one table: the co-sign records, or every note the supervisee
// wrote. Co-signing happens inline, in a row that expands under the note being
// attested, and posts to the same endpoint the note-header modal uses.

(function () {
  "use strict";

  var API = "/plugin-io/api/supervisor_cosign/summary";
  var COSIGN_API = "/plugin-io/api/supervisor_cosign/cosign/";
  var CONFIG = window.COSIGN_CONFIG || {templates: [], oversight: false, supervisee_token: "__SUPERVISEE__"};

  var STATE_LABELS = {
    NEW: "Draft", PSH: "Pushed", LKD: "Locked", ULK: "Unlocked", RLK: "Relocked",
    RST: "Restored", RCL: "Recalled", UND: "Undeleted", DSC: "Discharged",
    SGN: "Signed", SCH: "Scheduling", BKD: "Booked", CVD: "Checked in",
    CLD: "Cancelled", NSW: "No show", RVT: "Reverted", CNF: "Confirmed"
  };

  var el = {};
  var openRow = null;
  var openAnchor = null;
  var PAGE_SIZE = 50;
  var offset = 0;
  // Consumed on the first render only: a task comment links here, and
  // re-expanding the row on every later filter change would fight the user.
  var pendingNote = new URLSearchParams(window.location.search).get("note") || "";

  function $(id) { return document.getElementById(id); }

  function init() {
    ["mode", "start", "end", "supervisor", "supervisee", "status", "rows",
     "emptyMsg", "pager", "pagerCount", "prevPage", "nextPage", "summaryStrip",
     "supervisorControl", "statusControl", "noteChecks", "noteScopeHint",
     "dateLabel", "includeCancelled", "includeNonClinical", "eligibleOnly",
     "attestTemplate"].forEach(function (id) {
      el[id] = $(id);
    });

    el.mode.addEventListener("change", onModeChange);
    // Any change to what is being asked for resets to the first page --
    // staying on page 4 of a result set that just shrank to one page shows an
    // empty table and looks like a bug.
    ["start", "end", "supervisor", "supervisee", "status", "includeCancelled",
     "includeNonClinical", "eligibleOnly"].forEach(function (id) {
      el[id].addEventListener("change", reload);
    });
    el.prevPage.addEventListener("click", function () { turnPage(-1); });
    el.nextPage.addEventListener("click", function () { turnPage(1); });

    loadFilters();
    onModeChange();
  }

  function isNotesMode() { return el.mode.value === "notes"; }

  function onModeChange() {
    var notes = isNotesMode();
    el.noteChecks.hidden = !notes;
    el.noteScopeHint.hidden = !notes;
    el.statusControl.hidden = notes;
    // The two views range over different date fields, so the label says which.
    el.dateLabel.textContent = notes ? "Service date from" : "Selected from";
    reload();
  }

  function reload() {
    offset = 0;
    load();
  }

  function turnPage(direction) {
    var next = offset + direction * PAGE_SIZE;
    if (next < 0) { next = 0; }
    offset = next;
    load();
    window.scrollTo({top: 0});
  }

  function loadFilters() {
    fetch(API + "/filters", {credentials: "same-origin"})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) { return; }
        if (data.oversight && data.supervisors.length) {
          el.supervisorControl.hidden = false;
          fillSelect(el.supervisor, data.supervisors, "All supervisors");
        }
        fillSelect(el.supervisee, data.supervisees, "All supervisees");
      })
      .catch(function () { /* filters are a convenience; the table still loads */ });
  }

  function fillSelect(select, options, allLabel) {
    select.innerHTML = "";
    var first = document.createElement("option");
    first.value = "";
    first.textContent = allLabel;
    select.appendChild(first);
    options.forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.id;
      o.textContent = opt.name || opt.id;
      select.appendChild(o);
    });
  }

  function query() {
    var params = new URLSearchParams();
    params.set("mode", el.mode.value);
    params.set("start", el.start.value);
    params.set("end", el.end.value);
    if (el.supervisor.value) { params.set("supervisor", el.supervisor.value); }
    if (el.supervisee.value) { params.set("supervisee", el.supervisee.value); }
    if (isNotesMode()) {
      if (el.includeCancelled.checked) { params.set("include_cancelled", "1"); }
      if (el.includeNonClinical.checked) { params.set("include_non_clinical", "1"); }
      if (el.eligibleOnly.checked) { params.set("eligible_only", "1"); }
    } else if (el.status.value) {
      params.set("status", el.status.value);
    }
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    return params.toString();
  }

  function load() {
    closeAttest();
    fetch(API + "/data?" + query(), {credentials: "same-origin"})
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(render)
      .catch(function (err) {
        el.rows.innerHTML = "";
        el.emptyMsg.hidden = false;
        el.emptyMsg.textContent = "Could not load: " + err.message;
      });
  }

  function render(data) {
    el.rows.innerHTML = "";
    el.emptyMsg.hidden = data.rows.length > 0;
    el.emptyMsg.textContent = "No notes in this range.";
    renderPager(data);
    renderSummary(data.summary, data.summary_partial, data.total);
    var target = null;
    data.rows.forEach(function (row) {
      var tr = buildRow(row);
      el.rows.appendChild(tr);
      if (pendingNote && row.note_id === pendingNote && row.can_cosign) {
        target = {tr: tr, row: row};
      }
    });
    if (pendingNote) {
      openPendingNote(target, data.rows);
    }
  }

  function openPendingNote(target, rows) {
    var wanted = pendingNote;
    pendingNote = "";
    if (target) {
      toggleAttest(target.tr, target.row);
      target.tr.scrollIntoView({block: "center"});
      return;
    }
    // Say why rather than showing a list that quietly does not contain it:
    // the link came from a task, so the note is real, but the default 30-day
    // window or an active filter can easily exclude it.
    var already = rows.some(function (r) { return r.note_id === wanted; });
    el.emptyMsg.hidden = false;
    el.emptyMsg.textContent = already
      ? "That note is in the list below, but it is not awaiting your co-signature."
      : "The note from that link is not on this page. Widen the date range, "
        + "clear the filters, or page forward to find it.";
  }

  function renderPager(data) {
    var shown = data.rows.length;
    var total = typeof data.total === "number" ? data.total : shown;
    el.pager.hidden = total <= PAGE_SIZE && offset === 0;
    if (el.pager.hidden) { return; }
    var first = shown ? offset + 1 : 0;
    el.pagerCount.textContent =
      "Showing " + first + "\u2013" + (offset + shown) + " of " + total;
    el.prevPage.disabled = offset <= 0;
    el.nextPage.disabled = !data.has_more;
  }

  function renderSummary(summary, partial, total) {
    el.summaryStrip.innerHTML = "";
    Object.keys(summary).forEach(function (key) {
      var s = summary[key];
      var box = document.createElement("div");
      box.className = "stat";
      box.innerHTML =
        '<div class="who"></div><div class="pct"></div><div class="counts"></div>';
      box.querySelector(".who").textContent = s.name || "Unknown";
      box.querySelector(".pct").textContent = s.pct_cosigned + "%";
      box.querySelector(".counts").textContent =
        s.approved + " of " + s.total + " co-signed";
      el.summaryStrip.appendChild(box);
    });
    if (partial) {
      // Says so rather than letting a capped count read as the real one.
      var note = document.createElement("div");
      note.className = "stat";
      note.innerHTML = '<div class="who">Coverage</div>' +
        '<div class="scope">Based on the first 2,000 notes of ' + total + '.</div>';
      el.summaryStrip.appendChild(note);
    }
  }

  function buildRow(row) {
    var tr = document.createElement("tr");
    tr.appendChild(noteCell(row));
    tr.appendChild(cell(row.patient_name || "—"));
    tr.appendChild(cell(row.note_type || "—"));

    var state = document.createElement("td");
    state.className = "state";
    state.textContent = STATE_LABELS[row.note_state] || row.note_state || "—";
    tr.appendChild(state);

    tr.appendChild(cell(row.supervisee_name || "—"));
    var sup = cell(row.supervisor_name || "—");
    sup.className = "supervisor-col";
    tr.appendChild(sup);
    tr.appendChild(statusCell(row));

    var actions = document.createElement("td");
    actions.className = "actions-col";
    if (row.can_cosign) {
      var btn = document.createElement("button");
      btn.className = "primary";
      btn.textContent = "Co-sign";
      btn.addEventListener("click", function () { toggleAttest(tr, row); });
      actions.appendChild(btn);
    }
    tr.appendChild(actions);
    return tr;
  }

  function statusCell(row) {
    var td = document.createElement("td");
    var pill = document.createElement("span");
    if (row.status === "approved") {
      pill.className = "pill approved";
      pill.textContent = "Co-signed";
      pill.title = row.cosigned_at ? "Co-signed " + formatDate(row.cosigned_at) : "";
    } else if (row.status === "pending") {
      var overdue = row.due_date && row.due_date < today();
      pill.className = overdue ? "pill overdue" : "pill pending";
      pill.textContent = overdue ? "Overdue" : "Pending";
      pill.title = row.due_date ? "Due " + row.due_date : "";
    } else {
      pill.className = "pill none";
      pill.textContent = "Not selected";
      pill.title = "This note never entered the co-sign flow.";
    }
    td.appendChild(pill);
    return td;
  }

  // The date doubles as the way into the note. Opens in a new tab so a
  // supervisor working down a queue does not lose the list.
  function noteCell(row) {
    var td = document.createElement("td");
    if (!row.note_url) {
      td.textContent = formatDate(row.note_date);
      return td;
    }
    var a = document.createElement("a");
    a.href = row.note_url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = formatDate(row.note_date);
    a.title = "Open this note in the chart";
    td.appendChild(a);
    return td;
  }

  function cell(text) {
    var td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  function today() { return new Date().toISOString().slice(0, 10); }

  function formatDate(iso) {
    if (!iso) { return "—"; }
    return String(iso).slice(0, 10);
  }

  function closeAttest() {
    if (openRow && openRow.parentNode) { openRow.parentNode.removeChild(openRow); }
    openRow = null;
    openAnchor = null;
  }

  function toggleAttest(tr, row) {
    var wasOpenHere = openAnchor === tr;
    closeAttest();
    if (wasOpenHere) { return; }

    var frag = el.attestTemplate.content.cloneNode(true);
    var attestRow = frag.querySelector(".attest-row");
    var select = attestRow.querySelector(".tpl");
    var body = attestRow.querySelector(".body");
    var comments = attestRow.querySelector(".comments");
    var submit = attestRow.querySelector(".submit");
    var cancel = attestRow.querySelector(".cancel");
    var msg = attestRow.querySelector(".msg");

    // Name the chart being signed, inside the form. The effect chain writes to
    // this note id, not to whatever chart is open elsewhere, so the supervisor
    // should be able to confirm which patient they are attesting for without
    // looking away from the button they are about to press.
    attestRow.querySelector(".attest-for").textContent =
      "Attesting to " + (row.supervisee_name || "the provider") + "'s note for " +
      (row.patient_name || "this patient") + " on " + formatDate(row.note_date) + ".";

    var texts = {};
    CONFIG.templates.forEach(function (tpl) {
      var option = document.createElement("option");
      option.value = tpl.key;
      option.textContent = tpl.label;
      // Reviewed & agree is the ordinary case; the teaching-physician wording
      // claims more and should be chosen, not defaulted into.
      if (tpl.key === CONFIG.default_template) { option.selected = true; }
      select.appendChild(option);
      texts[tpl.key] = (tpl.text || "").split(CONFIG.supervisee_token)
        .join(row.supervisee_name || "the provider");
    });

    function applyTemplate() { body.value = texts[select.value] || ""; }
    select.addEventListener("change", applyTemplate);
    applyTemplate();

    cancel.addEventListener("click", closeAttest);
    submit.addEventListener("click", function () {
      submitCosign(row, select, body, comments, submit, msg, tr);
    });

    // Hold the element itself, never tr.nextSibling. The <template> source
    // has a newline before <tr class="attest-row">, so the cloned fragment
    // leads with a whitespace text node and nextSibling is that text node --
    // which is what made Cancel remove nothing and leave the form on screen.
    // Same reason the anchor is tracked rather than derived from
    // previousSibling.
    tr.parentNode.insertBefore(frag, tr.nextSibling);
    openRow = attestRow;
    openAnchor = tr;
    body.focus();
  }

  function submitCosign(row, select, body, comments, submit, msg, tr) {
    var text = body.value.trim();
    if (!text) {
      msg.textContent = "Attestation text is required.";
      msg.className = "msg err";
      return;
    }
    submit.disabled = true;
    msg.textContent = "Submitting...";
    msg.className = "msg";

    fetch(COSIGN_API + encodeURIComponent(row.note_id) + "/", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        template: select.value,
        attestation_text: text,
        additional_comments: comments.value.trim()
      })
    }).then(function (resp) {
      if (resp.ok) {
        msg.textContent = "Co-signed.";
        msg.className = "msg ok";
        markApproved(tr);
        window.setTimeout(closeAttest, 800);
        return;
      }
      return resp.json().catch(function () { return null; }).then(function (data) {
        msg.textContent = (data && data.error) || ("Error (HTTP " + resp.status + ")");
        msg.className = "msg err";
        submit.disabled = false;
      });
    }).catch(function (err) {
      msg.textContent = "Request failed: " + (err && err.message ? err.message : err);
      msg.className = "msg err";
      submit.disabled = false;
    });
  }

  function markApproved(tr) {
    // Update in place rather than refetching: the supervisor is working down a
    // list and a reload would lose their position in it.
    var pill = tr.cells[6].querySelector(".pill");
    pill.className = "pill approved";
    pill.textContent = "Co-signed";
    tr.cells[7].innerHTML = "";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
