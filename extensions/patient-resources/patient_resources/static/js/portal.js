/* "My Resources": the patient's own list.
 *
 * Two rules hold throughout, and both matter more here than on the staff pages
 * because this content is rendered for a patient:
 *
 *   1. Every node is built with createElement and textContent. Never innerHTML.
 *      Resource titles and labels are staff-entered free text and must never be
 *      parsed as markup.
 *   2. An href is set only after re-checking the scheme in the browser. The
 *      server drops unsafe URLs already; this is the second of two independent
 *      checks, because a link on a patient-facing page is the highest-value
 *      thing in this plugin to get wrong.
 */

(function () {
  "use strict";

  var config = {};
  try {
    var configEl = document.getElementById("prp-config");
    config = JSON.parse(configEl ? configEl.textContent : "{}") || {};
  } catch (err) {
    config = {};
  }

  var apiBase = config.apiBase || "";

  var listEl = document.getElementById("prp-list");
  var emptyEl = document.getElementById("prp-empty");
  var withdrawnEl = document.getElementById("prp-withdrawn");
  var withdrawnHeadingEl = document.getElementById("prp-withdrawn-heading");
  var errorEl = document.getElementById("prp-error");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function isSafeUrl(value) {
    if (typeof value !== "string" || !value) {
      return false;
    }
    // Parsed rather than pattern-matched: the URL constructor resolves the
    // scheme the way the browser will when the link is clicked.
    try {
      var parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch (err) {
      return false;
    }
  }

  function formatWhen(iso) {
    if (!iso) {
      // A share with no timestamp still shows -- withholding something the care
      // team actually sent would be the wrong way to fail.
      return "";
    }
    var when = new Date(iso);
    if (isNaN(when.getTime())) {
      return "";
    }
    try {
      // The patient's own device timezone, which is the most correct display for
      // a patient-facing page and needs no configuration.
      return when.toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric"
      });
    } catch (err) {
      return iso.slice(0, 10);
    }
  }

  function renderResource(resource) {
    var item = el("li", "prp-item");
    item.appendChild(el("h2", "prp-item-title", resource.title || "Untitled"));

    var meta = el("div", "prp-meta");
    if (resource.label) {
      meta.appendChild(el("span", "prp-label", resource.label));
    }
    var when = formatWhen(resource.shared_at);
    if (when) {
      meta.appendChild(el("span", null, "Shared " + when));
    }
    if (meta.childNodes.length) {
      item.appendChild(meta);
    }

    if (isSafeUrl(resource.url)) {
      var link = el("a", "prp-open", "Open resource");
      link.setAttribute("href", resource.url);
      link.setAttribute("target", "_blank");
      // noopener stops the opened page reaching back through window.opener.
      // noreferrer also withholds this portal URL, so a third-party site cannot
      // learn that a patient viewed a resource about a given condition.
      link.setAttribute("rel", "noopener noreferrer");
      item.appendChild(link);
    } else {
      item.appendChild(
        el("p", "prp-unavailable", "This link is unavailable. Please ask your care team.")
      );
    }

    return item;
  }

  function renderWithdrawn(resource) {
    var when = formatWhen(resource.revoked_at);
    var text = resource.title || "A resource";
    text += when ? " was withdrawn by your care team on " + when + "." : " was withdrawn by your care team.";
    return el("div", "prp-withdrawn", text);
  }

  function render(payload) {
    listEl.textContent = "";
    withdrawnEl.textContent = "";

    var resources = payload.resources || [];
    resources.forEach(function (resource) {
      listEl.appendChild(renderResource(resource));
    });

    var isEmpty = resources.length === 0;
    emptyEl.hidden = !isEmpty;
    if (isEmpty) {
      emptyEl.textContent = "Your care team has not shared any resources with you yet.";
    }

    var withdrawn = payload.withdrawn || [];
    withdrawnHeadingEl.hidden = withdrawn.length === 0;
    withdrawn.forEach(function (resource) {
      withdrawnEl.appendChild(renderWithdrawn(resource));
    });
  }

  function load() {
    errorEl.textContent = "";
    window
      .fetch(apiBase + "/my-resources/", {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin"
      })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("unavailable");
        }
        return response.json();
      })
      .then(render)
      .catch(function () {
        errorEl.textContent =
          "We could not load your resources just now. Please try again in a moment.";
      });
  }

  load();
})();
