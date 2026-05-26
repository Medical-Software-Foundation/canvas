/* Pre-Visit Brief – vanilla JS, no framework. */

(function () {
  "use strict";

  /**
   * Compute the start-of-day and end-of-day in the local timezone,
   * returning ISO-8601 strings suitable for the /data endpoint.
   */
  function todayWindow() {
    var now = new Date();
    var start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
    var end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    return {
      start: start.toISOString(),
      end: end.toISOString(),
    };
  }

  /**
   * Format an ISO-8601 datetime string to a readable time (e.g. "10:30 AM").
   */
  function formatTime(isoString) {
    if (!isoString) return "";
    try {
      var d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (_) {
      return isoString;
    }
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
   * Build a list HTML fragment from an array of strings.
   */
  function buildList(items) {
    if (!items || items.length === 0) return "<p class='pvb-none'>None on record</p>";
    return (
      "<ul class='pvb-list'>" +
      items.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") +
      "</ul>"
    );
  }

  /**
   * Build HTML for a single prep card.
   */
  function buildCard(appt) {
    var chartUrl = "/companion/patient/" + encodeURIComponent(appt.patient_id);
    var lastVisitDate = (appt.last_visit && appt.last_visit.date) ? esc(appt.last_visit.date) : "No prior visit";
    var snippet = (appt.last_visit && appt.last_visit.snippet) ? esc(appt.last_visit.snippet) : "No summary available";

    return (
      "<article class='pvb-card'>" +
        "<header class='pvb-card-header'>" +
          "<h2 class='pvb-patient-name'>" +
            "<a href='" + esc(chartUrl) + "'>" + esc(appt.patient_name) + "</a>" +
          "</h2>" +
          "<span class='pvb-appt-meta'>" +
            esc(formatTime(appt.start_time)) +
            (appt.note_type ? " &bull; " + esc(appt.note_type) : "") +
          "</span>" +
        "</header>" +

        "<section class='pvb-section'>" +
          "<h3 class='pvb-section-title'>Last Visit</h3>" +
          "<p class='pvb-last-visit-date'>" + lastVisitDate + "</p>" +
          "<p class='pvb-snippet'>" + snippet + "</p>" +
        "</section>" +

        "<section class='pvb-section'>" +
          "<h3 class='pvb-section-title'>Active Problems</h3>" +
          buildList(appt.conditions) +
        "</section>" +

        "<section class='pvb-section pvb-safety-block'>" +
          "<div class='pvb-safety-row'>" +
            "<span class='pvb-safety-label'>Allergies</span>" +
            "<span class='pvb-safety-value'>" + esc((appt.allergies || []).join(" • ")) + "</span>" +
          "</div>" +
          "<div class='pvb-safety-row'>" +
            "<span class='pvb-safety-label'>Medications</span>" +
            "<span class='pvb-safety-value'>" + esc((appt.medications || []).join(" • ")) + "</span>" +
          "</div>" +
          "<div class='pvb-safety-row'>" +
            "<span class='pvb-safety-label'>Vitals</span>" +
            "<span class='pvb-safety-value'>" + esc((appt.vitals || []).join(" • ")) + "</span>" +
          "</div>" +
        "</section>" +
      "</article>"
    );
  }

  /**
   * Render the full card list or an empty-state message.
   */
  function render(data) {
    var container = document.getElementById("pvb-cards");
    if (!container) return;

    var appointments = (data && data.appointments) ? data.appointments : [];

    if (appointments.length === 0) {
      container.innerHTML = "<p class='pvb-empty'>No upcoming appointments today.</p>";
      return;
    }

    container.innerHTML = appointments.map(buildCard).join("");
  }

  /**
   * Render an error message.
   */
  function renderError(message) {
    var container = document.getElementById("pvb-cards");
    if (container) {
      container.innerHTML = "<p class='pvb-error'>" + esc(message) + "</p>";
    }
  }

  /**
   * Fetch prep-card data from the server and render.
   */
  function loadData() {
    var win = todayWindow();
    var url =
      "/plugin-io/api/pre_visit_brief/app/data" +
      "?start=" + encodeURIComponent(win.start) +
      "&end=" + encodeURIComponent(win.end);

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
        renderError("Unable to load appointments. Please close and reopen the brief.");
        console.error("[pre-visit-brief]", err);
      });
  }

  // Kick off on DOM ready.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadData);
  } else {
    loadData();
  }
})();
