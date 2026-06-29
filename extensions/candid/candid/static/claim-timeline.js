const CLAIM_ID = document.body.dataset.claimId;
const API_BASE = "/plugin-io/api/candid/claim-detail";

async function loadTimeline() {
  try {
    const resp = await fetch(`${API_BASE}?claim_id=${CLAIM_ID}`, {credentials: "same-origin"});
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    render(data);
  } catch (e) {
    document.getElementById("timeline-content").innerHTML =
      `<div class="status-bar warning">Failed to load: ${e.message}</div>`;
  }
}

function render(d) {
  // Status bar
  const bar = document.getElementById("status-bar");
  if (d.submission_error && d.submission_error.error) {
    bar.className = "status-bar warning";
    bar.textContent = "Candid: Submission failed " + (d.submission_error.date || "");
  } else if (d.banner) {
    const isDenied = (d.candid_claim_status || "").toLowerCase().includes("denied");
    bar.className = "status-bar " + (isDenied ? "warning" : "info");
    bar.textContent = d.banner;
  } else if (!d.submitted_at) {
    bar.className = "status-bar empty";
    bar.textContent = "Not yet submitted to Candid";
  } else {
    bar.className = "status-bar info";
    bar.textContent = "Submitted, awaiting sync data";
  }

  // Build timeline events
  const events = [];

  if (d.submission_error && d.submission_error.error) {
    events.push({
      type: "error",
      title: "Submission Failed",
      detail: d.submission_error.error,
      time: d.submission_error.date,
    });
  }

  if (d.submitted_at) {
    const enc = (d.encounters || []);
    const encIds = enc.map(e => e.candid_encounter_id).filter(Boolean);
    events.push({
      type: "submit",
      title: "Submitted to Candid",
      detail: enc.length > 1 ? `${enc.length} encounters` : "1 encounter",
      ids: encIds,
      time: d.submitted_at,
    });
  }

  // Build a lookup of ERA amounts from sync_history detail strings
  // Detail format: "era-test-1: $70.00 | era-test-2: $30.00"
  const eraAmounts = {};
  (d.sync_history || []).forEach(s => {
    if (s.detail) {
      s.detail.split(" | ").forEach(part => {
        const [id, amt] = part.split(": ");
        if (id && amt) eraAmounts[id.trim()] = amt.trim();
      });
    }
  });

  // Synced ERAs (timestamp from actual posting created date)
  (d.synced_era_ids || []).forEach(era => {
    const amount = eraAmounts[era.id] || "";
    events.push({
      type: "era",
      title: "ERA Synced",
      detail: amount ? `${era.id} (${amount})` : era.id,
      time: era.posted_at || d.last_sync_at,
    });
  });

  // Synced payments (inbound — timestamp from actual posting created date)
  (d.synced_payment_ids || []).forEach(pmt => {
    const parts = [];
    if (pmt.paid_amount) parts.push(`$${pmt.paid_amount}`);
    parts.push(`payment_id=${pmt.id}`);
    events.push({
      type: "payment",
      title: "Patient Payment Synced from Candid",
      detail: parts.join(" | "),
      time: pmt.posted_at || d.last_sync_at,
    });
  });

  // Comments (skip failure comments — already shown via submission_error metadata)
  (d.comments || []).forEach(c => {
    const isFailure = c.comment.toLowerCase().includes("failed") || c.comment.toLowerCase().includes("rejected");
    if (isFailure && d.submission_error && d.submission_error.error) return;
    events.push({
      type: isFailure ? "error" : "comment",
      title: isFailure ? "Submission Failed" : "Claim Comment",
      detail: c.comment,
      time: c.created,
    });
  });

  // Activity history (syncs + payment reports)
  (d.sync_history || []).forEach(s => {
    if (s.log_type === "payment_reported") {
      events.push({
        type: "payment",
        title: "Patient Payment Reported to Candid",
        detail: s.detail,
        time: s.synced_at,
      });
    } else {
      const eraNote = s.era_ids.length ? ` | ERAs: ${s.era_ids.join(", ")}` : "";
      events.push({
        type: "sync",
        title: `Sync (${s.effects} effect${s.effects !== 1 ? "s" : ""})`,
        detail: `Status: ${(s.status || "unknown").replace(/_/g, " ")}${eraNote}`,
        time: s.synced_at,
      });
    }
  });

  // Sort by time descending (newest first), nulls last
  events.sort((a, b) => {
    if (!a.time && !b.time) return 0;
    if (!a.time) return 1;
    if (!b.time) return -1;
    return b.time.localeCompare(a.time);
  });

  // Render
  const container = document.getElementById("timeline-content");
  if (events.length === 0) {
    container.innerHTML = `<div class="status-bar empty">No Candid activity yet.</div>`;
    return;
  }

  let html = '<div class="section"><div class="section-title">Activity</div><div class="timeline">';
  events.forEach(ev => {
    const timeStr = ev.time ? formatTime(ev.time) : "";
    let extra = "";
    if (ev.ids) {
      extra = ev.ids.map(id => `<div class="encounter-id">${id}</div>`).join("");
    }
    html += `
      <div class="event ${ev.type}">
        <div class="event-title">${ev.title}</div>
        <div class="event-detail">${ev.detail}</div>
        ${extra}
        ${timeStr ? `<div class="event-time">${timeStr}</div>` : ""}
      </div>`;
  });
  html += "</div></div>";

  // Summary pills
  const eraCount = (d.synced_era_ids || []).length;
  const pmtCount = (d.synced_payment_ids || []).length + (d.reported_payment_ids || []).length;
  if (eraCount || pmtCount) {
    html += '<div class="section"><div class="section-title">Totals</div>';
    if (eraCount) html += `<span class="pill era">${eraCount} ERA${eraCount > 1 ? "s" : ""}</span>`;
    if (pmtCount) html += `<span class="pill pmt">${pmtCount} payment${pmtCount > 1 ? "s" : ""}</span>`;
    html += "</div>";
  }

  container.innerHTML = html;
}

function formatTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", {month: "short", day: "numeric"})
      + " " + d.toLocaleTimeString("en-US", {hour: "2-digit", minute: "2-digit"});
  } catch { return iso ? iso.slice(0, 16) : ""; }
}

async function triggerSync() {
  const btn = document.getElementById("sync-btn");
  btn.disabled = true;
  btn.textContent = "Syncing...";
  try {
    const resp = await fetch(API_BASE, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({claim_id: CLAIM_ID}),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    showToast(`Sync complete — ${data.effects_count} effects`, "success");
  } catch (e) {
    showToast(`Sync failed: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Sync Now";
  }
}

function showToast(msg, type) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show " + type;
  setTimeout(() => { t.className = "toast " + type; }, 3000);
}

loadTimeline();

// Real-time updates via WebSocket (falls back to polling if WS fails)
// The app is iframed (same origin as the parent Canvas page); prefer the
// parent window's host and fall back to this frame's own location.
let _wsHost;
try { _wsHost = window.parent.location.host; } catch { _wsHost = ""; }
const _wsProto = (window.parent.location?.protocol ?? location.protocol) === "https:" ? "wss:" : "ws:";
const wsUrl = _wsHost
  ? `${_wsProto}//${_wsHost}/plugin-io/ws/candid/claim-${CLAIM_ID}/`
  : null;
let ws;
let pollInterval;
let reconnectTimer;

function connectWs() {
  reconnectTimer = null;
  if (!wsUrl) { startPolling(); return; }
  ws = new WebSocket(wsUrl);
  ws.onmessage = () => loadTimeline();
  ws.onopen = () => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  };
  ws.onclose = () => {
    if (!pollInterval) {
      pollInterval = setInterval(() => {
        if (document.visibilityState === "visible") loadTimeline();
      }, 10000);
    }
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(connectWs, 5000);
    }
  };
}
connectWs();
