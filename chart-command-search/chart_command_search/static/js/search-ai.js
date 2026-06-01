function renderKeyFindings(findings) {
  if (!findings || findings.length === 0) return "";
  var KF_ICONS = {
    info: "&#8505;&#65039;",
    warning: "&#9888;",
    action: "&#10132;"
  };
  var items = findings.map(function(f) {
    var typeClass = "kf-" + (f.type || "info");
    var icon = KF_ICONS[f.type] || KF_ICONS.info;
    return '<div class="kf-item ' + typeClass + '"><span class="kf-icon">' + icon + '</span><span>' + escapeHtml(f.text || "") + '</span></div>';
  }).join("");
  return (
    '<div class="key-findings">' +
      '<div class="key-findings-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">' +
        'Key Findings <span class="kf-chevron">&#9662;</span>' +
      '</div>' +
      '<div class="key-findings-list">' + items + '</div>' +
    '</div>'
  );
}

function renderSourceChips(results) {
  if (!results || results.length === 0) return "";
  var cats = {};
  results.forEach(function(r) { if (r.category) cats[r.category] = true; });
  var catNames = Object.keys(cats);
  if (catNames.length === 0) return "";
  var CAT_LABELS = { command: "Command", note: "Note", appointment: "Appointment", letter: "Letter", message: "Message" };
  var chips = catNames.map(function(c) {
    return '<span class="source-chip source-chip-' + c + '">' + (CAT_LABELS[c] || c) + '</span>';
  }).join("");
  return '<div class="chat-sources"><span class="source-label">Sources</span>' + chips + '</div>';
}

function renderSuggestedQuestions(questions) {
  var container = document.getElementById("suggested-questions");
  if (!questions || questions.length === 0) {
    container.style.display = "none";
    return;
  }
  container.innerHTML =
    '<span class="suggested-label">Suggested questions</span>' +
    questions.map(function(q) {
      return '<button class="suggested-chip" onclick="askSuggested(this.textContent)">' + escapeHtml(q) + '</button>';
    }).join("");
  container.style.display = "flex";
}

function askSuggested(question) {
  var aiQueryEl = document.getElementById("ai-query");
  aiQueryEl.value = question;
  runAISearch();
}

function showChatEmptyState() {
  var chatMessages = document.getElementById("chat-messages");
  var statusBar = document.getElementById("status-bar");
  statusBar.textContent = "";
  chatMessages.innerHTML =
    '<div class="chat-empty" id="chat-empty">' +
      '<div class="chat-empty-icon">' +
        '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">' +
          '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"/>' +
        '</svg>' +
      '</div>' +
      '<h3>AI Chart Search</h3>' +
      '<p>Ask a question about this patient\'s chart to get AI-powered insights.</p>' +
      '<div id="prompt-chips-container"></div>' +
    '</div>';
  document.getElementById("suggested-questions").style.display = "none";
  document.getElementById("chat-clear-btn").style.display = "none";
  renderPromptChips();
}

/* AI search with conversation history */
var aiSearchInFlight = false;
var aiConversationHistory = [];
var chatSessionMessages = [];
var _restoringSession = false;
var aiQueryEl = document.getElementById("ai-query");
var aiSendBtn = document.getElementById("ai-send-btn");

function showChatLoading() {
  var chatMessages = document.getElementById("chat-messages");
  chatMessages.insertAdjacentHTML("beforeend",
    '<div class="chat-loading">' +
      '<div class="chat-ai-avatar">' +
        '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"/></svg>' +
      '</div>' +
      '<div class="chat-loading-dots"><span></span><span></span><span></span></div>' +
    '</div>'
  );
  var lastEl = chatMessages.lastElementChild;
  if (lastEl) lastEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function removeChatLoading() {
  var chatMessages = document.getElementById("chat-messages");
  var loadingEl = chatMessages.querySelector(".chat-loading");
  if (loadingEl) loadingEl.remove();
}

function renderUserBubble(text) {
  return '<div class="chat-msg-user"><div class="chat-bubble-user">' + escapeHtml(text) + '</div></div>';
}

var AI_AVATAR_SVG = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"/></svg>';

function renderErrorBubble(text) {
  return (
    '<div class="chat-msg-ai">' +
      '<div class="chat-ai-avatar">' + AI_AVATAR_SVG + '</div>' +
      '<div class="chat-ai-body"><div class="chat-ai-card"><div class="chat-ai-text" style="color:var(--text-secondary)">' +
        escapeHtml(text) +
      '</div></div></div>' +
    '</div>'
  );
}

function runAISearch() {
  var query = aiQueryEl.value.trim();
  if (!query || aiSearchInFlight) return;

  var statusBar = document.getElementById("status-bar");

  aiSearchInFlight = true;
  aiSendBtn.disabled = true;
  statusBar.textContent = "";

  var emptyEl = document.getElementById("chat-empty");
  if (emptyEl) emptyEl.style.display = "none";

  document.getElementById("suggested-questions").style.display = "none";

  var chatMessages = document.getElementById("chat-messages");
  chatMessages.insertAdjacentHTML("beforeend", renderUserBubble(query));
  chatSessionMessages.push({type: "user", text: query});
  showChatLoading();

  var sentQuery = query;
  aiQueryEl.value = "";
  aiQueryEl.placeholder = "Ask a follow-up question...";

  fetch("/plugin-io/api/chart_command_search/ai-search", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify({
      patient_id: PATIENT_ID,
      query: sentQuery,
      history: aiConversationHistory
    })
  })
    .then(function(res) {
      if (!res.ok) {
        return res.text().then(function(text) {
          var msg = "Request failed: " + res.status;
          try {
            var data = JSON.parse(text);
            if (data.error) msg = data.error;
          } catch(e) {
            if (text) msg += " — " + text.substring(0, 200);
          }
          throw new Error(msg);
        });
      }
      return res.json();
    })
    .then(function(data) {
      removeChatLoading();
      renderResults(data);
      chatSessionMessages.push({type: "ai", data: data});
      aiConversationHistory.push({
        query: sentQuery,
        summary: data.ai_summary || ""
      });
    })
    .catch(function(err) {
      removeChatLoading();
      chatMessages.insertAdjacentHTML("beforeend", renderErrorBubble(err.message));
      chatSessionMessages.push({type: "error", text: err.message});
      saveChatSession();
    })
    .finally(function() {
      aiSearchInFlight = false;
      aiSendBtn.disabled = false;
    });
}

aiQueryEl.addEventListener("input", function() {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 100) + "px";
});

aiQueryEl.addEventListener("keydown", function(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    runAISearch();
  }
});

aiSendBtn.addEventListener("click", function() {
  runAISearch();
});

/* Chat Session Persistence */
var CHAT_SESSION_KEY = "chartSearch_aiChat_" + PATIENT_ID;
var CHAT_SESSION_TTL = 30 * 60 * 1000;

function saveChatSession() {
  if (_restoringSession) return;
  try {
    var chatMessages = document.getElementById("chat-messages");
    if (!chatMessages || chatMessages.querySelector(".chat-empty")) return;
    if (chatSessionMessages.length === 0) return;
    var session = {
      version: 3,
      messages: chatSessionMessages,
      history: aiConversationHistory,
      counter: chatMsgCounter,
      timestamp: Date.now(),
      feedbackStates: (typeof feedbackStates !== "undefined") ? feedbackStates : {},
      feedbackDataStore: (typeof feedbackDataStore !== "undefined") ? feedbackDataStore : []
    };
    sessionStorage.setItem(CHAT_SESSION_KEY, JSON.stringify(session));
  } catch(e) {}
}

function restoreChatSession() {
  try {
    var raw = sessionStorage.getItem(CHAT_SESSION_KEY);
    if (!raw) return false;
    var session = JSON.parse(raw);
    if (Date.now() - session.timestamp > CHAT_SESSION_TTL) {
      sessionStorage.removeItem(CHAT_SESSION_KEY);
      return false;
    }
    if ((!session.version || session.version < 2) || !session.messages) {
      sessionStorage.removeItem(CHAT_SESSION_KEY);
      return false;
    }

    _restoringSession = true;
    var chatMessages = document.getElementById("chat-messages");
    var emptyEl = document.getElementById("chat-empty");
    if (emptyEl) emptyEl.style.display = "none";

    session.messages.forEach(function(entry) {
      if (entry.type === "user") {
        chatMessages.insertAdjacentHTML("beforeend", renderUserBubble(entry.text));
      } else if (entry.type === "ai" && entry.data) {
        renderResults(entry.data);
      } else if (entry.type === "error") {
        chatMessages.insertAdjacentHTML("beforeend", renderErrorBubble(entry.text));
      }
    });

    chatSessionMessages = session.messages;
    aiConversationHistory = session.history || [];
    chatMsgCounter = session.counter || 0;
    if (typeof feedbackStates !== "undefined") feedbackStates = session.feedbackStates || {};
    if (typeof feedbackDataStore !== "undefined") feedbackDataStore = session.feedbackDataStore || [];
    aiQueryEl.placeholder = "Ask a follow-up question...";
    document.getElementById("chat-clear-btn").style.display = "inline";
    setupExpanders();
    if (typeof restoreFeedbackStates === "function") restoreFeedbackStates();
    _restoringSession = false;
    return true;
  } catch(e) {
    _restoringSession = false;
    return false;
  }
}

function clearChatSession() {
  try { sessionStorage.removeItem(CHAT_SESSION_KEY); } catch(e) {}
  aiConversationHistory = [];
  chatSessionMessages = [];
  chatMsgCounter = 0;
  if (typeof feedbackStates !== "undefined") feedbackStates = {};
  if (typeof feedbackDataStore !== "undefined") feedbackDataStore = [];
  aiQueryEl.placeholder = "Ask about this patient's chart...";
  showChatEmptyState();
}

