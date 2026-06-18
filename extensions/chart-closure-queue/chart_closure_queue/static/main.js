/* Chart-Closure Queue – vanilla JS, no framework. */

(function () {
  "use strict";

  /**
   * Compute the end-of-day in the local timezone as an ISO-8601 string.
   * The server uses this both to exclude future-dated notes and as the
   * reference point for the "days open" aging calculation.
   */
  function endOfToday() {
    var now = new Date();
    var end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    return end.toISOString();
  }

  /**
   * Format an ISO-8601 datetime string to a readable date (e.g. "May 26, 2026").
   */
  function formatDate(isoString) {
    if (!isoString) return "Unknown date";
    try {
      var d = new Date(isoString);
      return d.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
    } catch (_) {
      return isoString;
    }
  }

  /**
   * Render "N days open" with correct pluralization.
   */
  function daysOpenLabel(days) {
    var n = typeof days === "number" ? days : 0;
    if (n <= 0) return "Today";
    return n === 1 ? "1 day open" : n + " days open";
  }

  /**
   * Escape HTML to prevent injection from server data.
   */
  function esc(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /**
   * Build HTML for a single note row.
   */
  function buildRow(note) {
    var chartUrl = "/companion/patient/" + encodeURIComponent(note.patient_id);
    var aging = note.aging === "red" || note.aging === "amber" ? note.aging : "normal";

    return (
      "<article class='ccq-row ccq-aging-" + esc(aging) + "'>" +
        "<div class='ccq-row-main'>" +
          "<h2 class='ccq-patient-name'>" +
            "<a href='" + esc(chartUrl) + "' target='_top'>" + esc(note.patient_name) + "</a>" +
          "</h2>" +
          "<p class='ccq-note-title'>" + esc(note.note_title) + "</p>" +
          "<p class='ccq-meta'>" +
            esc(formatDate(note.date_of_service)) +
            " &bull; " +
            "<span class='ccq-state'>" + esc(note.state_label) + "</span>" +
          "</p>" +
        "</div>" +
        "<div class='ccq-row-aging'>" +
          "<span class='ccq-days'>" + esc(daysOpenLabel(note.days_open)) + "</span>" +
        "</div>" +
      "</article>"
    );
  }

  /**
   * Render the full note list or an empty-state message.
   */
  function render(data) {
    var container = document.getElementById("ccq-list");
    if (!container) return;

    var notes = (data && data.notes) ? data.notes : [];

    if (notes.length === 0) {
      container.innerHTML = "<p class='ccq-empty'>No open notes — you're all caught up.</p>";
      return;
    }

    container.innerHTML = notes.map(buildRow).join("");
  }

  /**
   * Render an error message.
   */
  function renderError(message) {
    var container = document.getElementById("ccq-list");
    if (container) {
      container.innerHTML = "<p class='ccq-error'>" + esc(message) + "</p>";
    }
  }

  /**
   * Fetch worklist data from the server and render.
   */
  function loadData() {
    var url =
      "/plugin-io/api/chart_closure_queue/app/data" +
      "?end=" + encodeURIComponent(endOfToday());

    fetch(url, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Server returned " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        render(data);
      })
      .catch(function (err) {
        renderError("Unable to load your open notes. Please close and reopen the queue.");
        console.error("[chart-closure-queue]", err);
      });
  }

  // Kick off on DOM ready.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadData);
  } else {
    loadData();
  }
})();
