function renderDetails(details) {
  if (!details || details.length === 0) return "";
  var rows = details.map(function(d) {
    if (!d.label) return '<tr><td colspan="2">' + escapeHtml(d.value) + '</td></tr>';
    return '<tr><td>' + escapeHtml(d.label) + '</td><td>' + escapeHtml(d.value) + '</td></tr>';
  }).join("");
  return '<table class="details-table"><tbody>' + rows + '</tbody></table>';
}

var chatMsgCounter = 0;

function renderResults(data) {
  var statusBar = document.getElementById("status-bar");
  var isAiMode = document.querySelector(".search-panel").getAttribute("data-mode") === "ai";
  var hasAiSummary = data.ai_summary && data.ai_summary.length > 0;

  if (isAiMode && hasAiSummary) {
    var chatMessages = document.getElementById("chat-messages");

    var emptyEl = document.getElementById("chat-empty");
    if (emptyEl) emptyEl.style.display = "none";

    var loadingEl = chatMessages.querySelector(".chat-loading");
    if (loadingEl) loadingEl.remove();

    if (data.permalink_map) currentPermalinkMap = data.permalink_map;

    var cardsHtml = "";
    var toggleId = "entries-toggle-" + chatMsgCounter;
    var cardsId = "entries-cards-" + chatMsgCounter;
    if (data.results && data.results.length > 0) {
      cardsHtml =
        '<button class="chat-entries-toggle" id="' + toggleId + '" onclick="toggleChatEntries(\'' + toggleId + '\', \'' + cardsId + '\')">' +
          '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 9l-7 7-7-7"/></svg>' +
          data.results.length + ' supporting ' + (data.results.length === 1 ? 'entry' : 'entries') +
        '</button>' +
        '<div class="chat-entries-cards" id="' + cardsId + '">' +
          buildCardHtml(data) +
        '</div>';
    }

    var feedbackBarHtml = (typeof renderFeedbackBar === "function") ? renderFeedbackBar(chatMsgCounter) : "";
    if (typeof storeFeedbackData === "function") storeFeedbackData(chatMsgCounter, data);

    var aiCardHtml =
      '<div class="chat-msg-ai">' +
        '<div class="chat-ai-avatar">' +
          '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"/></svg>' +
        '</div>' +
        '<div class="chat-ai-body">' +
          '<div class="chat-ai-card">' +
            '<div class="chat-ai-text">' + renderAISummary(data.ai_summary) + '</div>' +
            renderKeyFindings(data.key_findings) +
            cardsHtml +
          '</div>' +
          feedbackBarHtml +
        '</div>' +
      '</div>';

    chatMessages.insertAdjacentHTML("beforeend", aiCardHtml);
    chatMsgCounter++;

    document.getElementById("chat-clear-btn").style.display = "inline";

    renderSuggestedQuestions(data.suggested_questions);

    statusBar.textContent = "";
    setupExpanders();

    saveChatSession();

    var lastMsg = chatMessages.lastElementChild;
    if (lastMsg) lastMsg.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }

  var container = document.getElementById("results-container");

  if (!data.results || data.results.length === 0) {
    statusBar.textContent = "No results found.";
    container.innerHTML =
      '<div class="empty-state">' +
        '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">' +
          '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"/>' +
        '</svg>' +
        '<p>No results found.</p>' +
      '</div>';
    return;
  }

  statusBar.textContent = data.count === 1 ? "1 result" : data.count + " results";

  var warningHtml = "";
  if (data.search_errors && data.search_errors.length > 0) {
    warningHtml = '<div class="search-warning">Some categories could not be searched: ' +
      escapeHtml(data.search_errors.join(", ")) + '</div>';
  }

  var cards = buildCardHtml(data);
  container.innerHTML = warningHtml + cards;
  setupExpanders();
}

function buildCardHtml(data) {
  if (!data.results || data.results.length === 0) return "";
  return data.results.map(function(r, i) {
    var catLabel = CATEGORY_LABELS[r.category] || r.category.toUpperCase();
    var catClass = "cat-" + r.category;
    var stateHtml = r.state
      ? '<span class="state-badge state-' + (r.state_class || "") + '">' + escapeHtml(r.state) + '</span>'
      : "";
    var summaryHtml = (r.summary && r.summary !== r.type_label)
      ? '<div class="card-summary">' + escapeHtml(r.summary.replace(/&nbsp;/g, ' ')) + '</div>'
      : "";
    var detailsHtml = renderDetails(r.details);
    var date = formatDate(r.date || "");
    var source = r.source || "";

    var linkHtml = r.permalink
      ? '<button class="open-link" onclick="navigateToResult(\'' + escapeHtml(r.permalink).replace(/'/g, "\\'") + '\')">Open <span class="arrow-icon"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M4.5 2.5L8.5 6L4.5 9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button>'
      : "";

    var permalinkAttr = r.permalink ? ' data-permalink="' + escapeHtml(r.permalink) + '"' : '';

    var aiExplHtml = r.ai_explanation
      ? '<div class="ai-explanation">' + escapeHtml(r.ai_explanation) + '</div>'
      : "";

    return (
      '<div class="result-card card-' + r.category + '"' + permalinkAttr + '>' +
        '<div class="card-top">' +
          '<span class="category-badge ' + catClass + '">' + catLabel + '</span>' +
          '<span class="type-label">' + escapeHtml(r.type_label) + '</span>' +
          stateHtml +
        '</div>' +
        '<div class="card-body" id="card-body-' + i + '">' +
          summaryHtml +
          detailsHtml +
        '</div>' +
        aiExplHtml +
        '<button class="show-more-btn" onclick="toggleExpand(' + i + ')">Show more</button>' +
        '<div class="card-footer">' +
          '<span class="meta">' + (date ? '<span>' + escapeHtml(date) + '</span>' : "") + (source ? '<span>' + escapeHtml(source) + '</span>' : "") + '</span>' +
          linkHtml +
        '</div>' +
      '</div>'
    );
  }).join("");
}

function setupExpanders() {
  document.querySelectorAll(".card-body").forEach(function(el) {
    var btn = el.nextElementSibling;
    if (el.scrollHeight > 100) {
      el.classList.add("collapsed");
      if (btn && btn.classList.contains("show-more-btn")) btn.classList.add("visible");
    }
  });
}

function toggleExpand(i) {
  var body = document.getElementById("card-body-" + i);
  if (!body) return;
  var btn = body.nextElementSibling;
  if (body.classList.contains("collapsed")) {
    body.classList.remove("collapsed");
    if (btn) btn.textContent = "Show less";
  } else {
    body.classList.add("collapsed");
    if (btn) btn.textContent = "Show more";
  }
}

/* localStorage state persistence */
var STORAGE_KEY = "chartSearch_" + PATIENT_ID;
var CLICKED_KEY = "chartSearch_clicked_" + PATIENT_ID;
var STATE_MAX_AGE_MS = 60 * 60 * 1000;

function saveSearchState() {
  try {
    var state = {
      q: document.getElementById("q").value,
      categories: categoryMs.getValues(),
      statuses: statusMs.getValues(),
      dateFrom: document.getElementById("date-from").value,
      dateTo: document.getElementById("date-to").value,
      providers: providerMs.getValues(),
      timestamp: Date.now()
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch(e) {}
}

function saveClickedPermalink(permalink) {
  try {
    localStorage.setItem(CLICKED_KEY, permalink);
    saveSearchState();
  } catch(e) {}
}

function restoreSearchState() {
  try {
    var raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    var state = JSON.parse(raw);
    if (Date.now() - state.timestamp > STATE_MAX_AGE_MS) {
      localStorage.removeItem(STORAGE_KEY);
      return false;
    }
    document.getElementById("q").value = state.q || "";

    if (state.categories) categoryMs.setValues(state.categories);
    rebuildStatusOptions();
    if (state.statuses) statusMs.setValues(state.statuses);
    if (state.providers) providerMs.setValues(state.providers);

    document.getElementById("date-from").value = state.dateFrom || "";
    document.getElementById("date-to").value = state.dateTo || "";
    return true;
  } catch(e) { return false; }
}

function highlightClickedResult() {
  try {
    var clicked = localStorage.getItem(CLICKED_KEY);
    if (!clicked) return;
    localStorage.removeItem(CLICKED_KEY);
    var cards = document.querySelectorAll(".result-card[data-permalink]");
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].getAttribute("data-permalink") === clicked) {
        cards[i].classList.add("highlighted");
        cards[i].scrollIntoView({ behavior: "smooth", block: "center" });
        break;
      }
    }
  } catch(e) {}
}

function runSearch() {
  var q = document.getElementById("q").value.trim();
  var categories = categoryMs.getValues();
  var statuses = statusMs.getValues();
  var dateFrom = document.getElementById("date-from").value;
  var dateTo = document.getElementById("date-to").value;
  var providers = providerMs.getValues();

  var params = new URLSearchParams({ patient_id: PATIENT_ID });
  params.set("category", categories.length > 0 ? categories.join(",") : "all");
  if (q) params.set("q", q);
  if (statuses.length > 0) params.set("status", statuses.join(","));
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (providers.length > 0) params.set("provider_id", providers.join(","));

  var spinner = document.getElementById("spinner");
  var statusBar = document.getElementById("status-bar");
  var container = document.getElementById("results-container");

  spinner.classList.add("visible");
  container.innerHTML = "";
  statusBar.textContent = "";

  fetch("/plugin-io/api/chart_command_search/search?" + params.toString(), {
    method: "GET",
    credentials: "include",
    headers: { "Accept": "application/json" }
  })
    .then(function(res) {
      if (!res.ok) throw new Error("Request failed: " + res.status);
      return res.json();
    })
    .then(function(data) { renderResults(data); saveSearchState(); highlightClickedResult(); })
    .catch(function(err) {
      statusBar.textContent = "Search failed.";
      container.innerHTML = '<div class="empty-state"><p>' + escapeHtml(err.message) + '</p></div>';
    })
    .finally(function() {
      spinner.classList.remove("visible");
    });
}

document.getElementById("q").addEventListener("keydown", function(e) {
  if (e.key === "Enter") runSearch();
});

var debounceTimer = null;
document.getElementById("q").addEventListener("input", function() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(runSearch, 400);
});
