"""Candid claim timeline application.

Shows on /revenue/claims/<id> pages. Displays a timeline of all Candid
activity (submission, syncs, ERA postings, patient payments) and provides
a button to trigger a manual adjudication sync.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class CandidClaimTimeline(Application):
    """Claim-level Candid activity timeline with manual sync trigger."""

    def on_open(self) -> Effect:
        """Load timeline if already on a claim page, otherwise show placeholder."""
        claim = self.event.context.get("claim")
        claim_id = claim["id"] if claim else None
        return LaunchModalEffect(
            content=_html(claim_id=claim_id),
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Candid Activity",
        ).apply()

    def on_context_change(self) -> Effect | list[Effect] | None:
        """Update the timeline when the user navigates to a claim."""
        claim = self.event.context.get("claim")
        if not claim:
            return None

        claim_id = claim["id"]
        return LaunchModalEffect(
            content=_html(claim_id=claim_id),
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Candid Activity",
        ).apply()


def _html(claim_id: str | None) -> str:
    """Generate the application HTML with embedded JavaScript."""
    if not claim_id:
        return """
        <html><body style="font-family: sans-serif; padding: 20px; color: #666;">
        <p>Navigate to a claim to see Candid activity.</p>
        </body></html>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 16px; color: #333; font-size: 13px; }}

  .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }}
  .header h2 {{ font-size: 15px; font-weight: 600; }}

  .sync-btn {{
    padding: 6px 14px; font-size: 12px; font-weight: 600;
    background: #2563eb; color: white; border: none; border-radius: 6px;
    cursor: pointer; transition: background 0.15s;
  }}
  .sync-btn:hover {{ background: #1d4ed8; }}
  .sync-btn:disabled {{ background: #94a3b8; cursor: not-allowed; }}

  .status-bar {{
    padding: 10px 12px; border-radius: 6px; margin-bottom: 16px;
    font-size: 12px; font-weight: 500;
  }}
  .status-bar.info {{ background: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }}
  .status-bar.warning {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
  .status-bar.empty {{ background: #f3f4f6; color: #6b7280; border: 1px solid #e5e7eb; }}

  .section {{ margin-bottom: 16px; }}
  .section-title {{ font-size: 11px; font-weight: 600; text-transform: uppercase; color: #6b7280; letter-spacing: 0.05em; margin-bottom: 8px; }}

  .timeline {{ position: relative; padding-left: 20px; }}
  .timeline::before {{
    content: ""; position: absolute; left: 5px; top: 4px; bottom: 4px;
    width: 2px; background: #e5e7eb; border-radius: 1px;
  }}

  .event {{
    position: relative; margin-bottom: 12px; padding: 8px 10px;
    background: #f9fafb; border-radius: 6px; border: 1px solid #f3f4f6;
  }}
  .event::before {{
    content: ""; position: absolute; left: -21px; top: 12px;
    width: 8px; height: 8px; border-radius: 50%; border: 2px solid white;
  }}
  .event.submit::before {{ background: #2563eb; }}
  .event.sync::before {{ background: #ca8a04; }}
  .event.payment::before {{ background: #7c3aed; }}
  .event.era::before {{ background: #16a34a; }}
  .event.error::before {{ background: #dc2626; }}
  .event.error {{ background: #fef2f2; border: 1px solid #fecaca; }}
  .event.error .event-title {{ color: #991b1b; }}
  .event.comment::before {{ background: #6b7280; }}

  .event-title {{ font-size: 12px; font-weight: 600; margin-bottom: 2px; }}
  .event-detail {{ font-size: 11px; color: #6b7280; }}
  .event-time {{ font-size: 10px; color: #9ca3af; margin-top: 2px; }}

  .encounter-id {{ font-family: monospace; font-size: 10px; color: #6b7280; word-break: break-all; }}

  .pill {{
    display: inline-block; padding: 1px 6px; border-radius: 4px;
    font-size: 10px; font-weight: 600; margin: 1px 2px;
  }}
  .pill.era {{ background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }}
  .pill.pmt {{ background: #f5f3ff; color: #6d28d9; border: 1px solid #ddd6fe; }}

  .toast {{
    position: fixed; bottom: 16px; left: 16px; right: 16px;
    padding: 10px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;
    opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 100;
  }}
  .toast.show {{ opacity: 1; }}
  .toast.success {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
  .toast.error {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}

  .loading {{ text-align: center; padding: 40px 0; color: #9ca3af; }}
</style>
</head>
<body>

<div class="header">
  <h2>Candid</h2>
  <button class="sync-btn" id="sync-btn" onclick="triggerSync()">Sync Now</button>
</div>
<div id="status-bar"></div>
<div id="timeline-content"><div class="loading">Loading...</div></div>
<div class="toast" id="toast"></div>

<script>
const CLAIM_ID = "{claim_id}";
const API_BASE = "/plugin-io/api/candid/claim-detail";

async function loadTimeline() {{
  try {{
    const resp = await fetch(`${{API_BASE}}?claim_id=${{CLAIM_ID}}`, {{credentials: "same-origin"}});
    if (!resp.ok) throw new Error(`HTTP ${{resp.status}}`);
    const data = await resp.json();
    render(data);
  }} catch (e) {{
    document.getElementById("timeline-content").innerHTML =
      `<div class="status-bar warning">Failed to load: ${{e.message}}</div>`;
  }}
}}

function render(d) {{
  // Status bar
  const bar = document.getElementById("status-bar");
  if (d.submission_error && d.submission_error.error) {{
    bar.className = "status-bar warning";
    bar.textContent = "Candid: Submission failed " + (d.submission_error.date || "");
  }} else if (d.banner) {{
    const isDenied = (d.candid_claim_status || "").toLowerCase().includes("denied");
    bar.className = "status-bar " + (isDenied ? "warning" : "info");
    bar.textContent = d.banner;
  }} else if (!d.submitted_at) {{
    bar.className = "status-bar empty";
    bar.textContent = "Not yet submitted to Candid";
  }} else {{
    bar.className = "status-bar info";
    bar.textContent = "Submitted, awaiting sync data";
  }}

  // Build timeline events
  const events = [];

  if (d.submission_error && d.submission_error.error) {{
    events.push({{
      type: "error",
      title: "Submission Failed",
      detail: d.submission_error.error,
      time: d.submission_error.date,
    }});
  }}

  if (d.submitted_at) {{
    const enc = (d.encounters || []);
    const encIds = enc.map(e => e.candid_encounter_id).filter(Boolean);
    events.push({{
      type: "submit",
      title: "Submitted to Candid",
      detail: enc.length > 1 ? `${{enc.length}} encounters` : "1 encounter",
      ids: encIds,
      time: d.submitted_at,
    }});
  }}

  // Build a lookup of ERA amounts from sync_history detail strings
  // Detail format: "era-test-1: $70.00 | era-test-2: $30.00"
  const eraAmounts = {{}};
  (d.sync_history || []).forEach(s => {{
    if (s.detail) {{
      s.detail.split(" | ").forEach(part => {{
        const [id, amt] = part.split(": ");
        if (id && amt) eraAmounts[id.trim()] = amt.trim();
      }});
    }}
  }});

  // Synced ERAs (timestamp from actual posting created date)
  (d.synced_era_ids || []).forEach(era => {{
    const amount = eraAmounts[era.id] || "";
    events.push({{
      type: "era",
      title: "ERA Synced",
      detail: amount ? `${{era.id}} (${{amount}})` : era.id,
      time: era.posted_at || d.last_sync_at,
    }});
  }});

  // Synced payments (inbound — timestamp from actual posting created date)
  (d.synced_payment_ids || []).forEach(pmt => {{
    const parts = [];
    if (pmt.paid_amount) parts.push(`$${{pmt.paid_amount}}`);
    parts.push(`payment_id=${{pmt.id}}`);
    events.push({{
      type: "payment",
      title: "Patient Payment Synced from Candid",
      detail: parts.join(" | "),
      time: pmt.posted_at || d.last_sync_at,
    }});
  }});

  // Comments (skip failure comments — already shown via submission_error metadata)
  (d.comments || []).forEach(c => {{
    const isFailure = c.comment.toLowerCase().includes("failed") || c.comment.toLowerCase().includes("rejected");
    if (isFailure && d.submission_error && d.submission_error.error) return;
    events.push({{
      type: isFailure ? "error" : "comment",
      title: isFailure ? "Submission Failed" : "Claim Comment",
      detail: c.comment,
      time: c.created,
    }});
  }});

  // Activity history (syncs + payment reports)
  (d.sync_history || []).forEach(s => {{
    if (s.log_type === "payment_reported") {{
      events.push({{
        type: "payment",
        title: "Patient Payment Reported to Candid",
        detail: s.detail,
        time: s.synced_at,
      }});
    }} else {{
      const eraNote = s.era_ids.length ? ` | ERAs: ${{s.era_ids.join(", ")}}` : "";
      events.push({{
        type: "sync",
        title: `Sync (${{s.effects}} effect${{s.effects !== 1 ? "s" : ""}})`,
        detail: `Status: ${{(s.status || "unknown").replace(/_/g, " ")}}${{eraNote}}`,
        time: s.synced_at,
      }});
    }}
  }});

  // Sort by time descending (newest first), nulls last
  events.sort((a, b) => {{
    if (!a.time && !b.time) return 0;
    if (!a.time) return 1;
    if (!b.time) return -1;
    return b.time.localeCompare(a.time);
  }});

  // Render
  const container = document.getElementById("timeline-content");
  if (events.length === 0) {{
    container.innerHTML = `<div class="status-bar empty">No Candid activity yet.</div>`;
    return;
  }}

  let html = '<div class="section"><div class="section-title">Activity</div><div class="timeline">';
  events.forEach(ev => {{
    const timeStr = ev.time ? formatTime(ev.time) : "";
    let extra = "";
    if (ev.ids) {{
      extra = ev.ids.map(id => `<div class="encounter-id">${{id}}</div>`).join("");
    }}
    html += `
      <div class="event ${{ev.type}}">
        <div class="event-title">${{ev.title}}</div>
        <div class="event-detail">${{ev.detail}}</div>
        ${{extra}}
        ${{timeStr ? `<div class="event-time">${{timeStr}}</div>` : ""}}
      </div>`;
  }});
  html += "</div></div>";

  // Summary pills
  const eraCount = (d.synced_era_ids || []).length;
  const pmtCount = (d.synced_payment_ids || []).length + (d.reported_payment_ids || []).length;
  if (eraCount || pmtCount) {{
    html += '<div class="section"><div class="section-title">Totals</div>';
    if (eraCount) html += `<span class="pill era">${{eraCount}} ERA${{eraCount > 1 ? "s" : ""}}</span>`;
    if (pmtCount) html += `<span class="pill pmt">${{pmtCount}} payment${{pmtCount > 1 ? "s" : ""}}</span>`;
    html += "</div>";
  }}

  container.innerHTML = html;
}}

function formatTime(iso) {{
  try {{
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", {{month: "short", day: "numeric"}})
      + " " + d.toLocaleTimeString("en-US", {{hour: "2-digit", minute: "2-digit"}});
  }} catch {{ return iso ? iso.slice(0, 16) : ""; }}
}}

async function triggerSync() {{
  const btn = document.getElementById("sync-btn");
  btn.disabled = true;
  btn.textContent = "Syncing...";
  try {{
    const resp = await fetch(API_BASE, {{
      method: "POST",
      credentials: "same-origin",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{claim_id: CLAIM_ID}}),
    }});
    if (!resp.ok) throw new Error(`HTTP ${{resp.status}}`);
    const data = await resp.json();
    showToast(`Sync complete — ${{data.effects_count}} effects`, "success");
  }} catch (e) {{
    showToast(`Sync failed: ${{e.message}}`, "error");
  }} finally {{
    btn.disabled = false;
    btn.textContent = "Sync Now";
  }}
}}

function showToast(msg, type) {{
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show " + type;
  setTimeout(() => {{ t.className = "toast " + type; }}, 3000);
}}

loadTimeline();

// Real-time updates via WebSocket (falls back to polling if WS fails)
const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${{wsProto}}//${{location.host}}/plugin-io/ws/candid/claim-${{CLAIM_ID}}/`;
let ws;
let pollInterval;
let reconnectTimer;

function connectWs() {{
  reconnectTimer = null;
  ws = new WebSocket(wsUrl);
  ws.onmessage = () => loadTimeline();
  ws.onopen = () => {{
    if (pollInterval) {{
      clearInterval(pollInterval);
      pollInterval = null;
    }}
  }};
  ws.onclose = () => {{
    if (!pollInterval) {{
      pollInterval = setInterval(() => {{
        if (document.visibilityState === "visible") loadTimeline();
      }}, 10000);
    }}
    if (!reconnectTimer) {{
      reconnectTimer = setTimeout(connectWs, 5000);
    }}
  }};
}}
connectWs();
</script>
</body>
</html>"""
