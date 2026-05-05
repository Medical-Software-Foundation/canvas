(function () {
  "use strict";

  // ── state ──────────────────────────────────────────────────────────────────
  // Initial period and week_start are seeded into <body data-*> by the server.
  let period = document.body.dataset.period || "daily";
  let weekStart =
    localStorage.getItem("npd_week_start") ||
    document.body.dataset.weekStart ||
    "sunday";
  const cacheBust = document.body.dataset.cacheBust || "";
  let selectedProviderId = null;
  let selectedProviderName = "";
  let currentNotes = [];
  let sortKey = "datetime";  // "datetime" | "patient"
  let sortDir = "desc";       // "asc" | "desc"

  // ── boot ───────────────────────────────────────────────────────────────────
  function init() {
    syncButtons();
    fetchProviders();
  }

  // ── button state ───────────────────────────────────────────────────────────
  function syncButtons() {
    ["daily", "weekly", "monthly"].forEach(function (p) {
      document.getElementById("btn-" + p).classList.toggle("active", p === period);
    });
    ["sunday", "monday"].forEach(function (w) {
      document.getElementById("btn-" + w).classList.toggle("active", w === weekStart);
    });
  }

  // ── period / week-start changes ────────────────────────────────────────────
  window.setPeriod = function (p) {
    period = p;
    syncButtons();
    selectedProviderId = null;
    fetchProviders();
  };

  window.setWeekStart = function (w) {
    weekStart = w;
    localStorage.setItem("npd_week_start", w);
    syncButtons();
    if (period === "weekly") {
      selectedProviderId = null;
      fetchProviders();
    }
  };

  // ── fetch providers ────────────────────────────────────────────────────────
  function fetchProviders() {
    const list = document.getElementById("provider-list");
    list.innerHTML = '<li class="state-msg">Loading&hellip;</li>';
    document.getElementById("notes-header").textContent = "Notes";
    document.getElementById("notes-table-wrapper").innerHTML =
      '<p class="state-msg">Select a provider.</p>';

    const url = "/plugin-io/api/note_production_dashboard/providers" +
      "?period=" + encodeURIComponent(period) +
      "&week_start=" + encodeURIComponent(weekStart) +
      "&v=" + encodeURIComponent(cacheBust);

    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (providers) {
        if (!providers || providers.length === 0) {
          list.innerHTML = '<li class="empty-msg">No locked notes in this period.</li>';
          document.getElementById("notes-table-wrapper").innerHTML =
            '<p class="state-msg">No locked notes in this period.</p>';
          return;
        }
        list.innerHTML = "";
        providers.forEach(function (p, idx) {
          const li = document.createElement("li");
          li.className = "provider-item";
          li.dataset.id = p.provider_id;

          const nameSpan = document.createElement("span");
          nameSpan.className = "provider-name";
          nameSpan.textContent = p.name;

          const badge = document.createElement("span");
          badge.className = "count-badge";
          badge.textContent = String(p.count);

          li.appendChild(nameSpan);
          li.appendChild(badge);
          li.addEventListener("click", function () {
            selectProvider(p.provider_id, p.name);
          });
          list.appendChild(li);

          // Auto-select first provider.
          if (idx === 0) {
            selectProvider(p.provider_id, p.name);
          }
        });
      })
      .catch(function (err) {
        list.innerHTML = '<li class="state-msg">Error loading providers.</li>';
        console.error("providers fetch error", err);
      });
  }

  // ── select provider ────────────────────────────────────────────────────────
  function selectProvider(providerId, providerName) {
    selectedProviderId = providerId;
    selectedProviderName = providerName;

    // Highlight selected row.
    document.querySelectorAll(".provider-item").forEach(function (el) {
      el.classList.toggle("selected", el.dataset.id === providerId);
    });

    fetchNotes(providerId, providerName);
  }

  // ── fetch notes ────────────────────────────────────────────────────────────
  function fetchNotes(providerId, providerName) {
    const periodLabels = { daily: "Daily", weekly: "Weekly", monthly: "Monthly" };
    document.getElementById("notes-header").textContent =
      "Notes for: " + providerName + " (" + (periodLabels[period] || period) + ")";

    const wrapper = document.getElementById("notes-table-wrapper");
    wrapper.innerHTML = '<p class="state-msg">Loading&hellip;</p>';

    const url = "/plugin-io/api/note_production_dashboard/providers/" +
      encodeURIComponent(providerId) + "/notes" +
      "?period=" + encodeURIComponent(period) +
      "&week_start=" + encodeURIComponent(weekStart) +
      "&v=" + encodeURIComponent(cacheBust);

    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (notes) {
        currentNotes = Array.isArray(notes) ? notes : [];
        renderNotesTable();
      })
      .catch(function (err) {
        currentNotes = [];
        wrapper.innerHTML = '<p class="state-msg">Error loading notes.</p>';
        console.error("notes fetch error", err);
      });
  }

  // ── sort + render the notes table ──────────────────────────────────────────
  function sortedNotes() {
    const sign = sortDir === "asc" ? 1 : -1;
    return currentNotes.slice().sort(function (a, b) {
      let cmp;
      if (sortKey === "patient") {
        cmp = (a.patient || "").localeCompare(b.patient || "");
      } else {
        // datetime: ISO strings sort lexicographically across years.
        cmp = (a.sort_dt || "").localeCompare(b.sort_dt || "");
      }
      return cmp * sign;
    });
  }

  function arrowFor(key) {
    if (key !== sortKey) return "";
    return sortDir === "asc" ? "▲" : "▼";
  }

  function renderNotesTable() {
    const wrapper = document.getElementById("notes-table-wrapper");
    if (!currentNotes.length) {
      wrapper.innerHTML = '<p class="state-msg">No locked notes in this period.</p>';
      return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    function makeHeader(label, sortable, sortableKey) {
      const th = document.createElement("th");
      th.textContent = label;
      if (sortable) {
        th.className = "sortable";
        const arrow = document.createElement("span");
        arrow.className = "sort-arrow";
        arrow.textContent = arrowFor(sortableKey);
        th.appendChild(arrow);
        th.addEventListener("click", function () {
          if (sortKey === sortableKey) {
            sortDir = sortDir === "asc" ? "desc" : "asc";
          } else {
            sortKey = sortableKey;
            sortDir = sortableKey === "patient" ? "asc" : "desc";
          }
          renderNotesTable();
        });
      }
      return th;
    }

    headerRow.appendChild(makeHeader("Patient", true, "patient"));
    headerRow.appendChild(makeHeader("Date / Time", true, "datetime"));
    headerRow.appendChild(makeHeader("CPT", false));
    headerRow.appendChild(makeHeader("Type", false));
    headerRow.appendChild(makeHeader("Reason for Visit", false));
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    sortedNotes().forEach(function (note) {
      const tr = document.createElement("tr");

      function cell(text) {
        const td = document.createElement("td");
        td.textContent = text || "";
        return td;
      }

      tr.appendChild(cell(note.patient));
      tr.appendChild(cell(note.datetime_of_service));
      tr.appendChild(cell(note.cpt));
      tr.appendChild(cell(note.note_type));
      tr.appendChild(cell(note.rfv));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrapper.innerHTML = "";
    wrapper.appendChild(table);
  }

  // ── start ──────────────────────────────────────────────────────────────────
  init();
})();
