function escapeHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

var currentPermalinkMap = {};

function renderAISummary(text) {
  var normalized = text.replace(/\\n/g, '\n');
  var escaped = escapeHtml(normalized);
  escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  escaped = escaped.replace(/\n{2,}/g, '\n');
  escaped = escaped.replace(/\n/g, '<br>');
  escaped = escaped.replace(/(^|<br>)- (.+?)(?=<br>|$)/g, '$1<span class="ai-bullet">$2</span>');
  escaped = escaped.replace(/(^|<br>)(\d+)\. (.+?)(?=<br>|$)/g, function(m, pre, num, content) {
    return pre + '<span class="ai-num"><span class="ai-num-marker">' + num + '</span><span>' + content + '</span></span>';
  });
  escaped = escaped.replace(/\[#\d+(?:,\s*#\d+)*\]/g, "");
  return escaped;
}

function formatDate(s) {
  if (!s) return "";
  if (s.indexOf("T") !== -1) {
    try {
      var d = new Date(s);
      if (isNaN(d.getTime())) return s;
      return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
        + " " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    } catch(e) { return s; }
  }
  return s;
}

/* Multiselect component */
function initMultiselect(container, options, onChange) {
  var placeholder = container.getAttribute("data-placeholder") || "Select...";
  var selected = new Set();

  var toggle = document.createElement("button");
  toggle.className = "multiselect-toggle";
  toggle.type = "button";
  toggle.innerHTML = '<span class="label-text">' + escapeHtml(placeholder) + '</span><span class="arrow">&#9662;</span>';

  var panel = document.createElement("div");
  panel.className = "multiselect-panel";

  container.appendChild(toggle);
  container.appendChild(panel);

  function render() {
    panel.innerHTML = "";
    if (options.length > 1) {
      var actions = document.createElement("div");
      actions.className = "multiselect-actions";
      var selAll = document.createElement("button");
      selAll.type = "button";
      selAll.textContent = "Select all";
      selAll.addEventListener("click", function(e) {
        e.stopPropagation();
        options.forEach(function(o) { selected.add(o.v); });
        updateLabel(); render(); if (onChange) onChange();
      });
      var clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.textContent = "Clear";
      clearBtn.addEventListener("click", function(e) {
        e.stopPropagation();
        selected.clear();
        updateLabel(); render(); if (onChange) onChange();
      });
      actions.appendChild(selAll);
      actions.appendChild(clearBtn);
      panel.appendChild(actions);
    }
    options.forEach(function(opt) {
      var label = document.createElement("label");
      label.className = "multiselect-option";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selected.has(opt.v);
      cb.addEventListener("change", function() {
        if (cb.checked) { selected.add(opt.v); } else { selected.delete(opt.v); }
        updateLabel();
        if (onChange) onChange();
      });
      var span = document.createElement("span");
      span.textContent = opt.l;
      label.appendChild(cb);
      label.appendChild(span);
      panel.appendChild(label);
    });
  }

  function updateLabel() {
    var labelEl = toggle.querySelector(".label-text");
    if (selected.size === 0 || selected.size === options.length) {
      labelEl.textContent = placeholder;
    } else {
      var names = options.filter(function(o) { return selected.has(o.v); }).map(function(o) { return o.l; });
      labelEl.textContent = names.join(", ");
    }
  }

  toggle.addEventListener("click", function(e) {
    e.stopPropagation();
    document.querySelectorAll(".multiselect-panel.open").forEach(function(p) {
      if (p !== panel) p.classList.remove("open");
    });
    panel.classList.toggle("open");
  });

  panel.addEventListener("click", function(e) { e.stopPropagation(); });

  render();

  return {
    getValues: function() { return Array.from(selected); },
    setValues: function(vals) {
      selected.clear();
      vals.forEach(function(v) { selected.add(v); });
      updateLabel();
      render();
    },
    setOptions: function(newOpts) {
      options = newOpts;
      selected.clear();
      updateLabel();
      render();
    },
    replaceOptions: function(newOpts) {
      options = newOpts;
      var valid = new Set(newOpts.map(function(o) { return o.v; }));
      selected.forEach(function(v) { if (!valid.has(v)) selected.delete(v); });
      updateLabel();
      render();
    }
  };
}

document.addEventListener("click", function() {
  document.querySelectorAll(".multiselect-panel.open").forEach(function(p) {
    p.classList.remove("open");
  });
});

/* Initialize multiselects */
var categoryMs = initMultiselect(
  document.getElementById("category-ms"), CATEGORY_OPTIONS,
  function() { rebuildStatusOptions(); runSearch(); }
);

var statusMs = initMultiselect(
  document.getElementById("status-ms"), [], function() { runSearch(); }
);

var providerMs = initMultiselect(
  document.getElementById("provider-ms"), PROVIDER_OPTIONS, function() { runSearch(); }
);

function rebuildStatusOptions() {
  var cats = categoryMs.getValues();
  var merged = [];
  var seen = new Set();
  var sources = cats.length > 0 ? cats : Object.keys(STATUS_OPTIONS);
  sources.forEach(function(cat) {
    (STATUS_OPTIONS[cat] || []).forEach(function(opt) {
      if (!seen.has(opt.v)) { seen.add(opt.v); merged.push(opt); }
    });
  });
  statusMs.replaceOptions(merged);
}
rebuildStatusOptions();

function buildPermalink(rawLink) {
  if (!rawLink) return "";
  var hashIdx = rawLink.indexOf("#");
  if (hashIdx >= 0) {
    var path = rawLink.substring(0, hashIdx);
    var hashParams = rawLink.substring(hashIdx + 1);
    return path + "#" + hashParams + "&application=" + APP_ID;
  }
  return rawLink + "#application=" + APP_ID;
}

function navigateToResult(rawLink) {
  if (!rawLink) return;
  saveClickedPermalink(rawLink);
  var hashIdx = rawLink.indexOf("#");
  if (hashIdx >= 0) {
    window.open(rawLink + "&application=" + APP_ID, "_blank");
  } else {
    window.open(rawLink + "#application=" + APP_ID, "_blank");
  }
}

document.getElementById("date-from").addEventListener("change", function() { runSearch(); });
document.getElementById("date-to").addEventListener("change", function() { runSearch(); });

document.getElementById("clear-all-filters").addEventListener("click", function() {
  document.getElementById("q").value = "";
  document.getElementById("date-from").value = "";
  document.getElementById("date-to").value = "";
  categoryMs.setValues([]);
  rebuildStatusOptions();
  statusMs.setValues([]);
  providerMs.setValues([]);
  runSearch();
});

/* Collapsible filters toggle */
var FILTERS_STATE_KEY = "chartSearch_filtersOpen_" + PATIENT_ID;
var filterToggle = document.getElementById("filter-toggle");
var collapsibleFilters = document.getElementById("collapsible-filters");

function setFiltersOpen(open) {
  if (open) {
    collapsibleFilters.classList.remove("collapsed");
    filterToggle.classList.add("expanded");
  } else {
    collapsibleFilters.classList.add("collapsed");
    filterToggle.classList.remove("expanded");
  }
  try { localStorage.setItem(FILTERS_STATE_KEY, open ? "open" : "closed"); } catch(e) {}
}

filterToggle.addEventListener("click", function() {
  var isOpen = !collapsibleFilters.classList.contains("collapsed");
  setFiltersOpen(!isOpen);
});

try {
  var savedState = localStorage.getItem(FILTERS_STATE_KEY);
  if (savedState === "open") setFiltersOpen(true);
} catch(e) {}

/* Tab switching */
var TAB_STATE_KEY = "chartSearch_tab_" + PATIENT_ID;
var searchPanel = document.querySelector(".search-panel");
var tabs = document.querySelectorAll(".tab-bar .tab");

function toggleChatEntries(toggleId, cardsId) {
  var toggle = document.getElementById(toggleId);
  var cards = document.getElementById(cardsId);
  if (!toggle || !cards) return;
  toggle.classList.toggle("expanded");
  cards.classList.toggle("visible");
}

function setActiveTab(tabName) {
  searchPanel.setAttribute("data-mode", tabName);
  tabs.forEach(function(t) {
    t.classList.toggle("active", t.getAttribute("data-tab") === tabName);
  });
  try { localStorage.setItem(TAB_STATE_KEY, tabName); } catch(e) {}
}

tabs.forEach(function(t) {
  t.addEventListener("click", function() {
    setActiveTab(t.getAttribute("data-tab"));
  });
});
