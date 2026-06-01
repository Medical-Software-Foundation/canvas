var DEFAULT_PROMPTS = [
  "Summarize the most recent visit",
  "What medications is this patient currently taking?",
  "Are there any abnormal lab results?"
];
var PROMPTS_STORAGE_KEY = "chartSearch_prompts";

function getPromptData() {
  try {
    var raw = localStorage.getItem(PROMPTS_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch(e) {}
  return { defaults: DEFAULT_PROMPTS, custom: [], hidden: [] };
}

function savePromptData(data) {
  try { localStorage.setItem(PROMPTS_STORAGE_KEY, JSON.stringify(data)); } catch(e) {}
}

function buildPromptChip(text, opts) {
  opts = opts || {};
  var iconSvg = opts.icon || '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z"/>';
  var deleteHtml = opts.deleteIndex !== undefined
    ? '<span class="prompt-chip-delete" onclick="event.stopPropagation(); removeCustomPrompt(' + opts.deleteIndex + ')">&times;</span>'
    : '';
  return '<button class="prompt-chip" onclick="usePrompt(this.querySelector(\'.prompt-chip-text\').textContent)">' +
    '<span class="prompt-chip-icon"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">' + iconSvg + '</svg></span>' +
    '<span class="prompt-chip-text">' + escapeHtml(text) + '</span>' +
    deleteHtml +
  '</button>';
}

var STAR_ICON = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z"/>';

function renderPromptChips() {
  var container = document.getElementById("prompt-chips-container");
  if (!container) return;
  var data = getPromptData();
  var html = "";

  var suggestedPrompts = PRACTICE_PROMPTS.length > 0 ? PRACTICE_PROMPTS.slice(0, 5) : data.defaults;
  var suggestedLabel = PRACTICE_PROMPTS.length > 0 ? "Practice Prompts" : "Suggested";
  html += '<div class="prompt-section">';
  html += '<div class="prompt-section-header"><span class="prompt-section-title">' + suggestedLabel + '</span></div>';
  html += '<div class="prompt-chips">';
  suggestedPrompts.forEach(function(p, i) {
    if (PRACTICE_PROMPTS.length > 0 || (data.hidden || []).indexOf(i) === -1) {
      html += buildPromptChip(p);
    }
  });
  html += '</div></div>';

  html += '<div class="prompt-section">';
  var addBtnHtml = (data.custom || []).length < 5
    ? '<button class="prompt-add-btn" onclick="showAddPromptInput()">+ Add</button>'
    : '';
  html += '<div class="prompt-section-header"><span class="prompt-section-title">My Prompts</span>' + addBtnHtml + '</div>';
  html += '<div class="prompt-chips" id="custom-prompt-chips">';
  (data.custom || []).slice(0, 5).forEach(function(p, i) {
    html += buildPromptChip(p, { icon: STAR_ICON, deleteIndex: i });
  });
  html += '</div>';
  html += '<div id="add-prompt-area"></div>';
  html += '</div>';

  container.innerHTML = html;
}

function usePrompt(text) {
  aiQueryEl.value = text;
  runAISearch();
}

function showAddPromptInput() {
  var area = document.getElementById("add-prompt-area");
  if (!area) return;
  area.innerHTML =
    '<div class="prompt-add-input">' +
      '<input type="text" id="new-prompt-input" placeholder="Type your custom prompt..." />' +
      '<button onclick="saveNewPrompt()">Save</button>' +
    '</div>';
  var input = document.getElementById("new-prompt-input");
  input.focus();
  input.addEventListener("keydown", function(e) {
    if (e.key === "Enter") saveNewPrompt();
    if (e.key === "Escape") { area.innerHTML = ""; }
  });
}

function saveNewPrompt() {
  var input = document.getElementById("new-prompt-input");
  if (!input) return;
  var text = input.value.trim();
  if (!text) return;
  var data = getPromptData();
  data.custom = data.custom || [];
  data.custom.push(text);
  savePromptData(data);
  renderPromptChips();
}

function removeCustomPrompt(index) {
  var data = getPromptData();
  if (data.custom && index >= 0 && index < data.custom.length) {
    data.custom.splice(index, 1);
    savePromptData(data);
    renderPromptChips();
  }
}
