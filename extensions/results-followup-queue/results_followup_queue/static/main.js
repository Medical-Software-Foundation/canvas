/* Results Follow-Up Queue – vanilla JS, no framework. */

(function () {
  "use strict";

  /* Aging thresholds (days) for the "days pending" highlight. */
  var AMBER_DAYS = 7;
  var RED_DAYS = 14;

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
   * Format an ISO date string (YYYY-MM-DD) to a readable date (e.g. "Jun 5, 2026").
   */
  function formatDate(isoDate) {
    if (!isoDate) return "Date unknown";
    try {
      // Parse as a local date; appending T00:00 avoids UTC-shift surprises.
      var d = new Date(isoDate + "T00:00:00");
      if (isNaN(d.getTime())) return "Date unknown";
      return d.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
    } catch (_) {
      return "Date unknown";
    }
  }

  /**
   * CSS class for the aging pill based on days pending.
   */
  function agingClass(days) {
    if (days >= RED_DAYS) return "rfq-aging rfq-aging-red";
    if (days >= AMBER_DAYS) return "rfq-aging rfq-aging-amber";
    return "rfq-aging";
  }

  /**
   * Build the inline list of result values for a lab row.
   */
  function buildValues(values) {
    if (!values || values.length === 0) return "";
    var items = values
      .map(function (v) {
        var cls = v.abnormal ? "rfq-value rfq-value-abnormal" : "rfq-value";
        var unit = v.units ? " " + esc(v.units) : "";
        var flag = v.flag
          ? " <span class='rfq-flag'>" + esc(v.flag) + "</span>"
          : "";
        var ref = v.reference_range
          ? " <span class='rfq-ref'>(ref " + esc(v.reference_range) + ")</span>"
          : "";
        return (
          "<li class='" + cls + "'>" +
            "<span class='rfq-value-name'>" + esc(v.name) + "</span>" +
            "<span class='rfq-value-num'>" + esc(v.value) + unit + "</span>" +
            flag +
            ref +
          "</li>"
        );
      })
      .join("");
    return "<ul class='rfq-values'>" + items + "</ul>";
  }

  /**
   * Build HTML for a single result row.
   */
  function buildRow(row) {
    var chartUrl = "/companion/patient/" + encodeURIComponent(row.patient_key);
    var typeLabel = row.type === "imaging" ? "Imaging" : "Lab";
    var typeClass = row.type === "imaging" ? "rfq-badge-imaging" : "rfq-badge-lab";
    var days = typeof row.days_pending === "number" ? row.days_pending : 0;
    var daysLabel = row.result_date ? days + (days === 1 ? " day" : " days") : "—";

    var badges = "";
    if (row.abnormal) {
      badges += "<span class='rfq-badge rfq-badge-abnormal'>Abnormal</span>";
    }
    if (row.requires_signature) {
      badges += "<span class='rfq-badge rfq-badge-signature'>Signature</span>";
    }

    return (
      "<article class='rfq-row" + (row.abnormal ? " rfq-row-abnormal" : "") + "'>" +
        "<div class='rfq-row-main'>" +
          "<div class='rfq-row-top'>" +
            "<span class='rfq-badge " + typeClass + "'>" + esc(typeLabel) + "</span>" +
            "<a class='rfq-patient' href='" + esc(chartUrl) + "' target='_top'>" +
              esc(row.patient_name) +
            "</a>" +
          "</div>" +
          "<p class='rfq-name'>" + esc(row.name) + "</p>" +
          "<p class='rfq-date'>" + esc(formatDate(row.result_date)) + "</p>" +
          buildValues(row.values) +
        "</div>" +
        "<div class='rfq-row-side'>" +
          "<span class='" + agingClass(days) + "'>" + esc(daysLabel) + "</span>" +
          (badges ? "<div class='rfq-badges'>" + badges + "</div>" : "") +
        "</div>" +
      "</article>"
    );
  }

  /**
   * Render the full row list or an empty-state message.
   */
  function render(data) {
    var container = document.getElementById("rfq-rows");
    if (!container) return;

    var results = (data && data.results) ? data.results : [];

    if (results.length === 0) {
      container.innerHTML = "<p class='rfq-empty'>No results awaiting your review. 🎉</p>";
      return;
    }

    container.innerHTML = results.map(buildRow).join("");
  }

  /**
   * Render an error message.
   */
  function renderError(message) {
    var container = document.getElementById("rfq-rows");
    if (container) {
      container.innerHTML = "<p class='rfq-error'>" + esc(message) + "</p>";
    }
  }

  /**
   * Fetch queue data from the server and render.
   */
  function loadData() {
    var url = "/plugin-io/api/results_followup_queue/app/data";

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
        renderError("Unable to load results. Please close and reopen the queue.");
        console.error("[results-followup-queue]", err);
      });
  }

  // Kick off on DOM ready.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadData);
  } else {
    loadData();
  }
})();
