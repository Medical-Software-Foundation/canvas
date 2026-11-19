(function () {
  "use strict";
  var API = document.body.dataset.api;
  var AVAILABLE = document.body.dataset.available === "true";
  // Shown in the patient's own zone, and says which zone that is.
  var WHEN = { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" };
  var POLL_MS = 3000, POLL_FOR_MS = 10 * 60 * 1000;
  var state = { status: null, waitingUntil: 0, timer: null };

  function $(id) { return document.getElementById(id); }
  function notice(text, kind) {
    var n = $("notice");
    if (!text) { n.hidden = true; return; }
    n.textContent = text;
    n.className = "notice" + (kind ? " " + kind : "");
    n.hidden = false;
  }
  function showConfirm(on) {
    $("stop").hidden = on;
    $("stop-confirm").hidden = !on;
    $("stop-cancel").hidden = !on;
  }

  function render(body) {
    var previous = state.status;
    state.status = body.status;
    var pill = $("pill");
    var connected = body.status === "connected";
    pill.textContent = connected ? "Connected" : body.status === "reconnect" ? "Reconnect needed" : "Not connected";
    pill.className = "pill " + (connected ? "connected" : body.status === "reconnect" ? "reconnect" : "");
    $("connected").hidden = !connected;
    $("not-connected").hidden = connected || !AVAILABLE;
    $("unavailable").hidden = connected || AVAILABLE;
    $("connect").textContent = body.status === "reconnect" ? "Reconnect Oura Ring" : "Connect Oura Ring";
    $("lead").textContent = connected
      ? "You are sharing your Oura Ring summaries with your care team. They can see:"
      : "Share your Oura Ring summaries with your care team. They will see:";
    if (connected && body.connected_at) {
      $("since").textContent = "Sharing since " + new Date(body.connected_at).toLocaleString(undefined, WHEN) + ".";
    }
    if (connected && previous && previous !== "connected") {
      state.waitingUntil = 0;
      notice("You're connected. Your care team can now see your Oura summaries.");
    } else if (body.status === "reconnect" && !previous) {
      notice("Your Oura connection has expired. Reconnect to keep sharing.");
    }
    schedule();
  }

  function schedule() {
    clearTimeout(state.timer);
    if (state.status === "connected" || Date.now() > state.waitingUntil) return;
    state.timer = setTimeout(refresh, POLL_MS);
  }

  function refresh() {
    return fetch(API + "/status", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () { notice("Could not reach your health record. Check your connection.", "error"); });
  }

  $("connect").addEventListener("click", function () {
    state.waitingUntil = Date.now() + POLL_FOR_MS;
    notice("Finish in the Oura tab. This page will update when you are done.");
    schedule();
  });
  $("stop").addEventListener("click", function () { showConfirm(true); });
  $("stop-cancel").addEventListener("click", function () { showConfirm(false); });
  $("stop-confirm").addEventListener("click", function () {
    $("stop-confirm").disabled = true;
    fetch(API + "/disconnect", { method: "POST", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        return r.json();
      })
      .then(function (body) {
        showConfirm(false);
        notice(body.revoked_at_oura
          ? "Sharing stopped. Your care team can no longer see your Oura data, and Oura has ended this app's access."
          : "Sharing stopped. Your care team can no longer see your Oura data. To finish, remove this app in your Oura account settings.");
        return refresh();
      })
      .catch(function () { notice("Could not stop sharing. Please try again.", "error"); })
      .then(function () { $("stop-confirm").disabled = false; });
  });
  // Coming back from the Oura tab is the moment the answer is most likely new.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && state.status !== "connected") refresh();
  });

  refresh();
})();
