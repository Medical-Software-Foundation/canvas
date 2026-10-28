{% verbatim %}
/* Dot Phrases: the Use in checklist, shared by the app (static/admin) and the chart panel (static/panel).
   Each screen calls DotPhrasesUseIn with a function that returns its command labels and its HTML escaper. */
window.DotPhrasesUseIn = function (labels, esc) {
  "use strict";
  // ---- Use in: one checklist. Every note command except the reviews starts checked; the review ----
  // ---- commands can't block incomplete placeholders, and the Sig and note to pharmacist reach a pharmacy. ----
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
  var USE_DEFAULT = USE_ALL.filter(function (k) { return USE_REVIEWS.indexOf(k) < 0; });
  function useLabel(k) { var all = labels() || {}; return k === "hpi" ? "HPI" : (all[k] || k); }
  function useChecked(d) { return d.use_in === null ? USE_DEFAULT.slice() : d.use_in.slice(); }
  // Exactly the default commands checked is saved as the default (null), so commands added later are included.
  function useSet(d, list) {
    var keep = USE_ALL.filter(function (k) { return list.indexOf(k) >= 0; });
    var isDefault = keep.length === USE_DEFAULT.length && keep.every(function (k) { return USE_DEFAULT.indexOf(k) >= 0; });
    d.use_in = isDefault ? null : keep;
  }
  function useSummary(d) {
    var rx = [];
    if (d.rx.sig) { rx.push("Sig"); }
    if (d.rx.note_to_pharmacist) { rx.push("note to pharmacist"); }
    // The default and the full list read as "all commands except ...", naming what is left out.
    if (d.use_in === null || d.use_in.length === USE_ALL.length) {
      var left = d.use_in === null ? ["reviews"] : [];
      if (!rx.length) { left.push("prescriptions"); } else if (rx.length === 1) { left.push(d.rx.sig ? "note to pharmacist" : "Sig"); }
      return "all commands" + (left.length ? " except " + left.join(" and ") : "");
    }
    var notes = d.use_in.length > 3 ? d.use_in.length + " note commands" : d.use_in.map(useLabel).join(", ");
    if (notes) { return [notes].concat(rx).join(", "); }
    if (rx.length === 2) { return "Sig and note to pharmacist"; }
    return rx.length ? rx[0] + " only" : "nothing yet";
  }
  function useNeedsReminder(d, text) {
    // Any placeholder can be left incomplete: chart values the chart doesn't have, blanks, and choices.
    if (!/\{\s*[a-z]|\*\*\*/i.test(text || "")) { return false; }
    return d.use_in !== null && USE_REVIEWS.some(function (k) { return d.use_in.indexOf(k) >= 0; });
  }
  // Each group's commands in alphabetical order by the name people see.
  function byLabel(keys) { return keys.slice().sort(function (a, b) { return useLabel(a).localeCompare(useLabel(b)); }); }
  function useListHtml(d) {
    var on = useChecked(d);
    var box = function (k) { return '<label class="pk-ck"><input type="checkbox" data-cmdck="' + k + '"' + (on.indexOf(k) >= 0 ? " checked" : "") + "> " + esc(useLabel(k)) + "</label>"; };
    var rxBox = function (k, label) { return '<label class="pk-ck"><input type="checkbox" data-rx="' + k + '"' + (d.rx[k] ? " checked" : "") + "> " + label + ' <span class="use-cnt" id="useC_' + k + '"></span></label>'; };
    return '<div class="pk-gh"><span>Prescriptions</span><button type="button" class="pk-all" data-rxall>Select all</button></div>' +
      '<div class="pk-cols use-rx">' + rxBox("sig", "Sig") + rxBox("note_to_pharmacist", "Note to pharmacist") + "</div>" +
      '<div class="use-rxhint">Used in Prescribe, Refill, and Adjust prescription. Sent to the pharmacy as a single line of standard characters. Limits: Sig 1,000 characters, note to pharmacist 210. Prescriptions with unfilled placeholders cannot be sent.</div>' +
      '<div class="pk-gh use-bulk"><span>Note commands</span><button type="button" class="pk-all" data-useall>Select all</button><button type="button" class="pk-all" data-useclear>Clear all</button></div>' +
      USE_GROUPS.map(function (g, i) {
        var note = g[1] === USE_REVIEWS ? '<div class="use-rxhint">Off by default. Review commands cannot flag incomplete placeholders.</div>' : "";
        return '<div class="pk-grp"><div class="pk-gh"><span>' + esc(g[0]) + '</span><button type="button" class="pk-all" data-grpall="' + i + '">Select all</button></div>' + note + '<div class="pk-cols">' + byLabel(g[1]).map(box).join("") + "</div></div>";
      }).join("");
  }
  function useBlockHtml(d) {
    return '<div class="wi"><span class="wi-t">Works in: <b class="use-sum"></b></span><button type="button" class="wi-link" data-usetoggle aria-expanded="false">Change</button></div>' +
      '<div class="use-hint">Review commands and prescriptions are off by default. Review commands cannot flag incomplete placeholders, and prescription text goes to the pharmacy. Select <b>Change</b> to choose where this phrase works.</div>' +
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
      list.hidden = !open; tog.textContent = open ? "Done" : "Change"; tog.setAttribute("aria-expanded", String(open));
      var hint = scope.querySelector(".use-hint"); if (hint) { hint.hidden = open; }
      return true;
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
  return { defaultKeys: USE_DEFAULT, useBlockHtml: useBlockHtml, useSync: useSync, useHandle: useHandle, useIsEmpty: useIsEmpty, useSummary: useSummary };
};
{% endverbatim %}
