(function () {
  "use strict";
  var PATIENT_ID = document.body.dataset.patientId;
  var API = document.body.dataset.api;
  var state = { range: 14, data: null, busy: false, loading: false, poll: null, pollUntil: 0, lastStatus: null };
  // Until the patient is connected, check back so the panel fills in on its own
  // when they approve, whether from a staff link or from the portal. Checking a
  // patient who is not connected never calls Oura.
  var POLL_PENDING_MS = 10000, POLL_IDLE_MS = 30000, POLL_FOR_MS = 30 * 60 * 1000;
  // While data is on screen, check the connection (not the data) so a patient
  // who stops sharing disappears from an open chart within a minute.
  var CONSENT_CHECK_MS = 60000;

  // Times are shown in the viewer's own zone, and say which zone that is.
  var WHEN = { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" };

  var STATUS_LABELS = {
    connected: "Connected", expired: "Reconnect needed",
    link_pending: "Link sent", link_expired: "Link expired", disconnected: "Not connected"
  };
  var ERRORS = {
    not_connected: "This patient has not connected an Oura Ring yet.",
    reconnect_required: "The patient's Oura connection has expired. Send them a new connection link.",
    rate_limited: "Oura is limiting requests right now. Try again in a few minutes.",
    oura_unavailable: "Oura did not respond. Try Refresh in a minute.",
    plugin_not_configured: "This plugin is missing settings. Ask your Canvas administrator to finish setup.",
    invalid_patient_id: "This chart could not identify the patient.",
    forbidden: "You do not have access to this patient's Oura data.",
    not_staff: "Oura data is only available to signed-in staff.",
    all_forbidden: "The patient's Oura account is not sharing any data. They may have declined access, or their Oura membership may have lapsed.",
    api_error: "Oura did not respond. Try Refresh in a minute.",
    refresh_failed: "The patient's Oura connection has expired. Send them a new connection link.",
    auth_failed: "The patient's Oura connection has expired. Send them a new connection link."
  };
  var ENDPOINT_LABELS = {
    daily_sleep: "sleep score", sleep: "sleep details", daily_readiness: "readiness",
    daily_activity: "activity", daily_spo2: "blood oxygen"
  };
  var PORTAL_ERRORS = {
    no_staff_sender: "your staff account could not be identified",
    no_messageable_channel: "the patient has no consenting email or phone on file",
    invalid_sender_or_recipient: "Canvas rejected the message"
  };
  var CARDS = [
    { key: "sleep_score", label: "Sleep score", fmt: num },
    { key: "total_sleep_seconds", label: "Total sleep", fmt: duration },
    { key: "resting_hr_bpm", label: "Resting heart rate", fmt: unit(" bpm") },
    { key: "hrv_ms", label: "HRV (overnight avg)", fmt: unit(" ms") },
    { key: "readiness_score", label: "Readiness", fmt: num },
    { key: "steps", label: "Steps", fmt: steps },
    { key: "spo2_pct", label: "Blood oxygen (overnight)", fmt: unit("%") }
  ];

  function $(id) { return document.getElementById(id); }
  function num(v) { return String(Math.round(v)); }
  function unit(suffix) { return function (v) { return (Math.round(v * 10) / 10) + suffix; }; }
  function steps(v) { return Math.round(v).toLocaleString(); }
  function duration(s) {
    var m = Math.round(s / 60);
    return Math.floor(m / 60) + "h " + (m % 60) + "m";
  }
  function shortDay(iso) {
    var p = iso.split("-");
    return Number(p[1]) + "/" + Number(p[2]);
  }
  function ago(iso) {
    if (!iso) return "";
    var s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    return Math.floor(s / 86400) + " d ago";
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function notice(text, kind) {
    var n = $("notice");
    if (!text) { n.hidden = true; return; }
    n.textContent = text;
    n.className = "notice" + (kind ? " " + kind : "");
    n.hidden = false;
  }

  function call(method, path, params) {
    var q = "patient_id=" + encodeURIComponent(PATIENT_ID);
    Object.keys(params || {}).forEach(function (k) {
      q += "&" + encodeURIComponent(k) + "=" + encodeURIComponent(params[k]);
    });
    return fetch(API + path + "?" + q, { method: method, credentials: "same-origin" })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          return { ok: r.ok, body: body };
        });
      });
  }

  function setBusy(busy) {
    state.busy = busy;
    ["refresh", "disconnect", "send-portal", "send-copy", "replace"].forEach(function (id) { $(id).disabled = busy; });
  }

  function sparkline(values) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 100 40");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("role", "img");
    var nums = values.filter(function (v) { return typeof v === "number"; });
    if (!nums.length) return svg;
    var lo = Math.min.apply(null, nums), hi = Math.max.apply(null, nums);
    var span = hi - lo || 1;
    var step = values.length > 1 ? 100 / (values.length - 1) : 0;
    var d = "", pen = false;
    values.forEach(function (v, i) {
      if (typeof v !== "number") { pen = false; return; }
      var x = (i * step).toFixed(2), y = (36 - ((v - lo) / span) * 32).toFixed(2);
      var prev = values[i - 1], next = values[i + 1];
      if (typeof prev !== "number" && typeof next !== "number") {
        var dot = document.createElementNS(ns, "circle");
        dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", "1.6");
        svg.appendChild(dot);
      }
      d += (pen ? " L" : " M") + x + " " + y;
      pen = true;
    });
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", d.trim());
    path.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(path);
    return svg;
  }

  function renderCards(data) {
    var grid = $("cards");
    grid.textContent = "";
    CARDS.forEach(function (c) {
      var latest = data.latest[c.key];
      var avg = data.averages[c.key];
      var card = el("div", "card");
      card.appendChild(el("div", "label", c.label));
      card.appendChild(el("div", latest ? "value" : "value empty",
        latest ? c.fmt(latest.value) : "No data"));
      var meta = [];
      if (latest) meta.push(shortDay(latest.day));
      if (avg !== null && avg !== undefined) meta.push(data.range + " avg " + c.fmt(avg));
      card.appendChild(el("div", "meta", meta.join(" · ")));
      var svg = sparkline(data.series[c.key]);
      svg.setAttribute("aria-label", c.label + " trend, " + data.range);
      card.appendChild(svg);
      var axis = el("div", "axis");
      axis.appendChild(el("span", "", shortDay(data.days[0])));
      axis.appendChild(el("span", "", shortDay(data.days[data.days.length - 1])));
      card.appendChild(axis);
      grid.appendChild(card);
    });
    grid.hidden = false;
  }

  function render(data) {
    $("sandbox").hidden = !data.sandbox;
    state.data = data;
    var status = data.connection_status;
    var pill = $("status");
    pill.textContent = STATUS_LABELS[status] || status;
    pill.className = "pill " + status;
    var connected = status === "connected";
    $("synced").textContent = connected && data.last_synced_at ? "Updated " + ago(data.last_synced_at) : "";
    $("disclaimer").textContent = data.disclaimer;

    $("refresh").hidden = !connected;
    $("disconnect").hidden = status === "disconnected";
    $("connect").hidden = connected;
    // While a link is out, the buttons act on that link: resending or
    // copying it never cancels what the patient may already have.
    var pending = status === "link_pending";
    $("disconnect").textContent = pending ? "Cancel link" : "Disconnect";
    $("send-portal").textContent = pending ? "Resend to patient" : "Send to patient";
    $("send-copy").textContent = pending ? "Copy link" : "Copy link instead";
    $("replace").hidden = !pending;
    if (status === "expired") {
      $("connect-title").textContent = "Reconnect this patient's Oura Ring";
    } else if (pending) {
      $("connect-title").textContent = "Waiting for the patient to connect";
    } else if (status === "link_expired") {
      $("connect-title").textContent = "The link expired before the patient used it";
    } else {
      $("connect-title").textContent = "Connect this patient's Oura Ring";
    }
    if (pending && data.link_expires_at) {
      $("link-meta").textContent = "Link expires " + new Date(data.link_expires_at).toLocaleString(undefined, WHEN) + ".";
    }

    document.querySelector(".range").hidden = !connected;
    Array.prototype.forEach.call(document.querySelectorAll(".range button"), function (b) {
      b.setAttribute("aria-pressed", String(Number(b.dataset.range) === state.range));
    });

    $("cards").hidden = !data.has_data;
    $("source").hidden = !data.has_data;
    if (data.has_data) renderCards(data);

    var problem = data.fetch_error || data.last_error;
    var justConnected = connected && !!state.lastStatus && state.lastStatus !== "connected";
    state.lastStatus = status;
    if (justConnected && !problem) {
      notice("The patient connected their Oura Ring.");
    } else if (problem && ERRORS[problem]) {
      notice(ERRORS[problem], status === "expired" ? "error" : "warn");
    } else if (data.forbidden_endpoints && data.forbidden_endpoints.length) {
      var names = data.forbidden_endpoints.map(function (e) { return ENDPOINT_LABELS[e] || e; });
      notice("The patient is not sharing: " + names.join(", ") + ".", "warn");
    } else if (connected && !data.has_data) {
      notice("Oura has no data for this patient in this range.");
    } else {
      notice("");
    }
    schedulePoll(status);
  }

  function schedulePoll(status) {
    clearTimeout(state.poll);
    state.poll = null;
    if (status === "connected") {
      state.pollUntil = 0;
      state.poll = setTimeout(checkConsent, CONSENT_CHECK_MS);
      return;
    }
    if (!state.pollUntil) state.pollUntil = Date.now() + POLL_FOR_MS;
    if (Date.now() > state.pollUntil) return;
    state.poll = setTimeout(function () {
      if (document.hidden || state.busy) { schedulePoll(status); return; }
      load(true);
    }, status === "link_pending" ? POLL_PENDING_MS : POLL_IDLE_MS);
  }

  function checkConsent() {
    if (document.hidden || state.busy) { schedulePoll("connected"); return; }
    call("GET", "/status").then(function (r) {
      if (r.ok && r.body.connection_status !== "connected") {
        load(true).then(function () {
          notice("The patient stopped sharing their Oura data.", "warn");
        });
      } else {
        schedulePoll("connected");
      }
    }).catch(function () { schedulePoll("connected"); });
  }

  // A connected patient's data is read from Oura on every load, which takes a
  // moment, so say so. Background polls stay quiet.
  function load(quiet) {
    // One read at a time: overlapping reads can each try to refresh the token.
    if (state.loading) return Promise.resolve();
    state.loading = true;
    setRangeDisabled(true);
    if (!quiet) {
      notice("Loading from Oura…");
      $("refresh").disabled = true;
    }
    return call("GET", "/data", { range: state.range + "d" }).then(function (r) {
      if (!r.ok) { notice(ERRORS[r.body.error] || "Could not load Oura data.", "error"); return; }
      render(r.body);
    }).catch(function () {
      notice("Could not reach the plugin. Check your connection.", "error");
    }).then(function () {
      state.loading = false;
      setRangeDisabled(false);
      $("refresh").disabled = state.busy;
    });
  }

  function setRangeDisabled(on) {
    Array.prototype.forEach.call(document.querySelectorAll(".range button"), function (b) { b.disabled = on; });
  }

  function sendLink(viaPortal, fresh) {
    var reuse = !fresh && state.data && state.data.connection_status === "link_pending";
    setBusy(true);
    call("POST", "/send-link", { channels: viaPortal ? "portal" : "", reuse: reuse ? "1" : "0" }).then(function (r) {
      if (!r.ok) {
        var extra = r.body.settings ? " (" + r.body.settings.join("; ") + ")" : "";
        notice((ERRORS[r.body.error] || "Could not create a link.") + extra, "error");
        return;
      }
      $("link").value = r.body.connection_link;
      $("link-box").hidden = false;
      var hours = Math.max(1, Math.round(r.body.expires_in_seconds / 3600));
      var meta = "Expires in " + (hours >= 48 ? Math.round(hours / 24) + " days" : hours + " hours") + ".";
      $("link-meta").textContent = meta;
      if (!viaPortal) copyLink();
      // Reload first: a successful load replaces the notice, so the outcome
      // message has to be shown after it, not before.
      state.pollUntil = 0;
      return load(true).then(function () {
        if (r.body.portal_status === "sent") {
          notice(r.body.reused ? "Link sent to the patient again." : "Link sent to the patient's portal.");
        } else if (viaPortal) {
          notice("Portal message not sent: " + (PORTAL_ERRORS[r.body.portal_error] || r.body.portal_error) +
                 ". Copy the link and share it another way.", "warn");
        } else {
          notice("Link copied. Share it with the patient; it works once.");
        }
      });
    }).catch(function () {
      notice("Could not reach the plugin. Check your connection.", "error");
    }).then(function () { setBusy(false); });
  }

  function disconnect() {
    if (!window.confirm(state.data && state.data.connection_status === "link_pending"
        ? "Cancel the link sent to this patient? It will stop working."
        : "Disconnect this patient's Oura Ring? The care team will no longer see their Oura data.")) return;
    setBusy(true);
    call("POST", "/disconnect").then(function (r) {
      if (!r.ok) { notice("Could not disconnect.", "error"); return; }
      $("link-box").hidden = true;
      return load(true).then(function () {
        notice(r.body.revoked_at_oura
          ? "Done. The patient can connect again any time."
          : "Removed from this chart, but Oura did not confirm it ended access. The patient can remove this app in their Oura account settings.",
          r.body.revoked_at_oura ? "" : "warn");
      });
    }).catch(function () {
      notice("Could not reach the plugin. Check your connection.", "error");
    }).then(function () { setBusy(false); });
  }

  $("refresh").addEventListener("click", function () { load(); });
  $("disconnect").addEventListener("click", disconnect);
  $("send-portal").addEventListener("click", function () { sendLink(true); });
  $("send-copy").addEventListener("click", function () { sendLink(false); });
  $("replace").addEventListener("click", function () {
    if (!window.confirm("Send a new link? The link already sent will stop working.")) return;
    sendLink(true, true);
  });
  function copyLink(done) {
    var input = $("link");
    input.select();
    done = done || function () {};
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(input.value).then(done, function () { document.execCommand("copy"); done(); });
    } else {
      document.execCommand("copy");
      done();
    }
  }
  $("copy").addEventListener("click", function () { copyLink(function () { notice("Link copied."); }); });
  Array.prototype.forEach.call(document.querySelectorAll(".range button"), function (b) {
    b.addEventListener("click", function () {
      if (state.busy) return;
      state.range = Number(b.dataset.range);
      load();
    });
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden || !state.data) return;
    if (state.data.connection_status === "connected") checkConsent(); else load(true);
  });

  load();
})();
