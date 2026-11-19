{% verbatim %}
/* Dot Phrases: the Use in checklist, shared by the app (static/admin) and the chart panel (static/panel).
   Each screen calls DotPhrasesUseIn with a function that returns its command labels and its HTML escaper. */
window.DotPhrasesUseIn = function (labels, esc) {
  "use strict";
  // Commands whose text stays in the chart start checked. Orders, referrals, reviews, and the Sig and
  // Note to pharmacist start unchecked, since their text is sent outside the chart. Matches
  // catalog.DEFAULT_USE_IN on the server.
  var USE_GROUPS_IN = [
    ["Visit", ["rfv", "hpi", "vitals", "plan", "instruct", "perform", "followup", "task", "poclab"]],
    ["Conditions", ["assess", "diagnose", "updatedx", "resolve"]],
    ["Medications", ["medstmt", "stopmed", "immstmt"]],
    ["Allergies", ["allergy", "removeallergy"]],
    ["History", ["pmh", "removepmh", "psh", "fhx"]],
    ["Goals", ["goal", "updategoal", "closegoal"]]
  ];
  var USE_GROUPS_OUT = [
    ["Orders and referrals", ["imaging", "laborder", "refer"]],
    ["Reviews", ["labreview", "imgreview", "refreview", "docreview"]]
  ];
  var USE_GROUPS = USE_GROUPS_IN.concat(USE_GROUPS_OUT);
  var USE_ALL = USE_GROUPS.reduce(function (a, g) { return a.concat(g[1]); }, []);
  var USE_REVIEWS = USE_GROUPS_OUT[1][1];
  var USE_DEFAULT = USE_GROUPS_IN.reduce(function (a, g) { return a.concat(g[1]); }, []);
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
    if (d.rx.note_to_pharmacist) { rx.push("Note to pharmacist"); }
    if (d.use_in === null && !rx.length) { return "Default commands"; }
    if (d.use_in !== null && d.use_in.length === USE_ALL.length && rx.length === 2) { return "All commands"; }
    if (d.use_in === null) { return ["Default commands"].concat(rx).join(", "); }
    var notes = d.use_in.length > 3 ? d.use_in.length + " note commands" : d.use_in.map(useLabel).join(", ");
    if (notes) { return [notes].concat(rx).join(", "); }
    if (rx.length === 2) { return "Sig and Note to pharmacist"; }
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
    var WHY = {
      "Medications": "Sig and Note to pharmacist are used in Prescribe, Refill, and Adjust prescription commands. Select Sig for prescription directions or Note to pharmacist for pharmacy notes. Sig has a 1,000-character limit, and Note to pharmacist has a 210-character limit.",
      "Orders and referrals": "Phrase text appears on the order or referral sent to the receiving lab, imaging center, or specialist. Select these for phrases meant for the receiving provider or facility.",
      "Reviews": "Phrase text can appear in the patient message or the internal comment. Placeholders are not flagged in these commands, so any left incomplete in the <b>Patient message</b> field can be sent to the patient when the communication method sends it to their portal. Select these for phrases meant for internal comments or patient communication."
    };
    var group = function (g, i) {
      var why = WHY[g[0]] ? '<div class="use-rxhint">' + WHY[g[0]] + "</div>" : "";
      var meds = g[0] === "Medications";
      var btn = meds ? "data-medall" : 'data-grpall="' + i + '"';
      var rx = meds ? '<div class="pk-cols use-rx">' + rxBox("sig", "Sig") + rxBox("note_to_pharmacist", "Note to pharmacist") + "</div>" : "";
      return '<div class="pk-grp"><div class="pk-gh"><span>' + esc(g[0]) + '</span><button type="button" class="pk-all" ' + btn + ">Select all</button></div>" + why + '<div class="pk-cols">' + byLabel(g[1]).map(box).join("") + "</div>" + rx + "</div>";
    };
    return USE_GROUPS.map(group).join("");
  }
  function useBlockHtml(d) {
    return '<div class="wi"><span class="wi-t">Works in: <b class="use-sum"></b></span><button type="button" class="wi-link" data-usetoggle aria-expanded="false">Change</button></div>' +
      '<div class="use-hint">Orders, Referrals, Reviews, Sig, and Note to pharmacist are off by default. Their phrase text may be shared with patients, pharmacies, or outside providers. Select them only when appropriate.</div>' +
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
    var MEDS = USE_GROUPS_IN[2][1];
    var medAll = scope.querySelector("[data-medall]"); if (medAll) { medAll.textContent = MEDS.every(function (k) { return on.indexOf(k) >= 0; }) && d.rx.sig && d.rx.note_to_pharmacist ? "Clear all" : "Select all"; }
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
    // Medications' button covers its commands and the Sig and Note to pharmacist.
    if (t.closest && t.closest("[data-medall]") && e.type === "click") {
      var meds = USE_GROUPS_IN[2][1], cur2 = useChecked(d);
      var full2 = meds.every(function (k) { return cur2.indexOf(k) >= 0; }) && d.rx.sig && d.rx.note_to_pharmacist;
      useSet(d, full2 ? cur2.filter(function (k) { return meds.indexOf(k) < 0; }) : cur2.concat(meds));
      d.rx.sig = !full2; d.rx.note_to_pharmacist = !full2; return true;
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
