/* Feedback bar + comment modal for AI search responses */
var feedbackDataStore = [];
var feedbackStates = {};
var _pendingFeedback = null;

var THUMB_UP_SVG = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">' +
  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" ' +
  'd="M6.633 10.25c.806 0 1.533-.446 2.031-1.08a9.041 9.041 0 0 1 2.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 0 0 .322-1.672V2.75a.75.75 0 0 1 .75-.75 2.25 2.25 0 0 1 2.25 2.25c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282m0 0h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 0 1-2.649 7.521c-.388.482-.987.729-1.605.729H13.48c-.483 0-.964-.078-1.423-.23l-3.114-1.04a4.501 4.501 0 0 0-1.423-.23H5.904m10.598-9.75H14.25M5.904 18.5c.083.205.173.405.27.602.197.4-.078.898-.523.898h-.908c-.889 0-1.713-.518-1.972-1.368a12 12 0 0 1-.521-3.507c0-1.553.295-3.036.831-4.398C3.387 9.953 4.167 9.5 5 9.5h1.053c.472 0 .745.556.5.96a8.958 8.958 0 0 0-1.302 4.665c0 1.194.232 2.333.654 3.375Z"/>' +
  '</svg>';

var THUMB_DOWN_SVG = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">' +
  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" ' +
  'd="M7.498 15.25H4.372c-1.026 0-1.945-.694-2.054-1.715A12.137 12.137 0 0 1 2.25 12.25c0-2.848.992-5.464 2.649-7.521C5.287 4.247 5.886 4 6.504 4h4.016c.483 0 .964.078 1.423.23l3.114 1.04a4.5 4.5 0 0 0 1.423.23h1.294M7.498 15.25c.618 0 .991.724.725 1.282A7.471 7.471 0 0 0 7.5 19.75 2.25 2.25 0 0 0 9.75 22a.75.75 0 0 0 .75-.75v-.633c0-.573.11-1.14.322-1.672.304-.76.93-1.33 1.653-1.715a9.04 9.04 0 0 0 2.86-2.4c.5-.634 1.226-1.08 2.032-1.08h.384m-10.253 1.5H9.7m8.075-9.75c.083-.205.173-.405.27-.602.197-.4-.078-.898-.523-.898h-.908c-.889 0-1.713.518-1.972 1.368a12 12 0 0 0-.521 3.507c0 1.553.295 3.036.831 4.398.306.774 1.086 1.227 1.918 1.227h1.053c.472 0 .745-.556.5-.96a8.958 8.958 0 0 1-1.302-4.665c0-1.194.232-2.333.654-3.375Z"/>' +
  '</svg>';

function renderFeedbackBar(msgIdx) {
  return (
    '<div class="feedback-bar" data-msg-idx="' + msgIdx + '">' +
      '<button class="feedback-btn feedback-btn-up" title="Helpful" onclick="onFeedbackClick(this,\'up\')">' +
        THUMB_UP_SVG +
      '</button>' +
      '<button class="feedback-btn feedback-btn-down" title="Not helpful" onclick="onFeedbackClick(this,\'down\')">' +
        THUMB_DOWN_SVG +
      '</button>' +
    '</div>'
  );
}

function storeFeedbackData(msgIdx, data) {
  feedbackDataStore[msgIdx] = {
    query: data.ai_query || "",
    answer_summary: data.ai_summary || "",
    answer_key_findings: data.key_findings || []
  };
}

function onFeedbackClick(btn, rating) {
  var bar = btn.closest(".feedback-bar");
  if (!bar) return;
  var msgIdx = parseInt(bar.getAttribute("data-msg-idx"), 10);
  if (feedbackStates[msgIdx]) return;

  bar.querySelectorAll(".feedback-btn").forEach(function(b) {
    b.disabled = true;
    b.classList.remove("selected-up", "selected-down");
  });
  btn.classList.add(rating === "up" ? "selected-up" : "selected-down");

  _pendingFeedback = { msgIdx: msgIdx, rating: rating, bar: bar };
  openFeedbackModal(rating);
}

function openFeedbackModal(rating) {
  var modal = document.getElementById("feedback-modal");
  var label = document.getElementById("feedback-modal-label");
  var textarea = document.getElementById("feedback-comment");
  if (!modal || !label || !textarea) return;

  label.textContent = rating === "up" ? "What was helpful?" : "What could be improved?";
  textarea.value = "";
  modal.style.display = "flex";
  textarea.focus();
}

function closeFeedbackModal() {
  var modal = document.getElementById("feedback-modal");
  if (modal) modal.style.display = "none";
  if (_pendingFeedback && _pendingFeedback.bar && !feedbackStates[_pendingFeedback.msgIdx]) {
    unlockFeedbackBar(_pendingFeedback.bar);
  }
  _pendingFeedback = null;
}

function submitFeedback(withComment) {
  if (!_pendingFeedback) return;

  var msgIdx = _pendingFeedback.msgIdx;
  var rating = _pendingFeedback.rating;
  var bar = _pendingFeedback.bar;
  var comment = "";

  if (withComment) {
    var textarea = document.getElementById("feedback-comment");
    comment = textarea ? textarea.value.trim() : "";
  }

  var storeEntry = feedbackDataStore[msgIdx];
  if (!storeEntry) {
    closeFeedbackModal();
    return;
  }

  var payload = {
    patient_id: PATIENT_ID,
    query: storeEntry.query,
    answer_summary: storeEntry.answer_summary,
    answer_key_findings: storeEntry.answer_key_findings,
    rating: rating,
    comment: comment
  };

  lockFeedbackBar(bar, rating);
  feedbackStates[msgIdx] = { rating: rating, submitted: true };
  closeFeedbackModal();
  saveChatSession();

  fetch("/plugin-io/api/chart_command_search/feedback", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify(payload)
  })
    .then(function(res) {
      if (!res.ok) {
        delete feedbackStates[msgIdx];
        unlockFeedbackBar(bar);
        saveChatSession();
      }
    })
    .catch(function() {
      delete feedbackStates[msgIdx];
      unlockFeedbackBar(bar);
      saveChatSession();
    });
}

function lockFeedbackBar(bar, rating) {
  bar.querySelectorAll(".feedback-btn").forEach(function(b) {
    b.disabled = true;
    b.classList.remove("selected-up", "selected-down");
  });
  var selectedBtn = bar.querySelector(rating === "up" ? ".feedback-btn-up" : ".feedback-btn-down");
  if (selectedBtn) selectedBtn.classList.add(rating === "up" ? "selected-up" : "selected-down");

  var conf = bar.querySelector(".feedback-confirmed");
  if (!conf) {
    bar.insertAdjacentHTML("beforeend", '<span class="feedback-confirmed">Thanks for your feedback</span>');
  }
}

function unlockFeedbackBar(bar) {
  bar.querySelectorAll(".feedback-btn").forEach(function(b) {
    b.disabled = false;
    b.classList.remove("selected-up", "selected-down");
  });
  var conf = bar.querySelector(".feedback-confirmed");
  if (conf) conf.remove();
}

function restoreFeedbackStates() {
  Object.keys(feedbackStates).forEach(function(key) {
    var msgIdx = parseInt(key, 10);
    var state = feedbackStates[msgIdx];
    if (!state || !state.submitted) return;
    var bar = document.querySelector('.feedback-bar[data-msg-idx="' + msgIdx + '"]');
    if (bar) lockFeedbackBar(bar, state.rating);
  });
}
