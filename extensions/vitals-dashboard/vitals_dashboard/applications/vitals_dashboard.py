"""Vitals Dashboard full-chart Application — V0.3 capture form."""

import json

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class VitalsDashboardApp(Application):
    """Cardiology vitals dashboard tab on the patient chart."""

    def on_open(self) -> Effect:
        ctx = self.event.context or {}
        patient_key = (ctx.get("patient") or {}).get("id", "") if isinstance(ctx, dict) else ""
        user_ctx = ctx.get("user") or {} if isinstance(ctx, dict) else {}
        staff_key = user_ctx.get("id", "") or user_ctx.get("staff_id", "") or ""

        bootstrap = json.dumps({
            "patient_key": patient_key,
            "staff_key": staff_key,
        })

        content = _render_page(bootstrap)

        return LaunchModalEffect(
            content=content,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Vitals",
        ).apply()


def _render_page(bootstrap_json: str) -> str:
    return (
        """
<style>
  html, body { margin: 0; height: 100%; }
  body { overflow-y: auto; }
  #vd-root { box-sizing: border-box; max-width: 960px; margin: 0 auto; padding: 1.5rem 2rem 16rem; color: #1a1a1a; font-family: system-ui, -apple-system, sans-serif; }
  .vd-charts-grid { display: grid; gap: 1rem; grid-template-columns: 1fr 1fr; }
  .vd-chart-panel { background:#fff; border:1px solid #e5e7eb; border-radius:8px; padding:.75rem 1rem 1rem; }
  .vd-chart-panel h3 { margin:0 0 .5rem; font-size:1rem; color:#374151; }
  .vd-chart-wrap { position:relative; height: 220px; }
  .vd-chart-panel.full { grid-column: 1 / -1; }
  .vd-charts-mini { display: grid; gap: 1rem; grid-template-columns: repeat(3, 1fr); }
  .vd-charts-mini .vd-chart-wrap { height: 140px; }
  .vd-charts-mini h3 { font-size: .85rem; }
  @media (max-width: 720px) { .vd-charts-grid { grid-template-columns: 1fr; } .vd-charts-mini { grid-template-columns: repeat(2, 1fr); } }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<div id="vd-root">
  <header style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:1rem;">
    <div>
      <h1 style="margin:0;font-size:1.5rem;">Vitals Dashboard</h1>
      <p style="margin:.25rem 0 0;color:#6b7280;font-size:.9rem;">Record orthostatic vitals, weight, urine output, and more for this visit.</p>
    </div>
    <span id="vd-status" style="font-size:.85rem;color:#6b7280;"></span>
  </header>

  <form id="vd-form" style="display:grid;gap:1.25rem;">

    <!-- Session timestamp -->
    <section style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;">
      <label style="display:block;font-weight:600;margin-bottom:.5rem;">Session Date & Time</label>
      <input type="datetime-local" name="session_datetime" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;font-size:.95rem;width:260px;"/>
    </section>

    <!-- Standard BP -->
    <section style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;">
      <h2 style="margin:0 0 .75rem;font-size:1.05rem;">Standard Blood Pressure</h2>
      <p style="margin:0 0 .75rem;color:#6b7280;font-size:.85rem;">Single BP reading (no orthostatic positioning).</p>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;align-items:end;">
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">Systolic (mmHg)</span>
          <input type="number" name="std_sys" min="0" max="300" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;"/></label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">Diastolic (mmHg)</span>
          <input type="number" name="std_dia" min="0" max="250" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;"/></label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">HR (bpm)</span>
          <input type="number" name="std_hr" min="0" max="300" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;"/></label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">Cuff Location</span>
          <select name="std_cuff" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;">
            <option value="">—</option>
            <option value="right_arm">Right arm</option>
            <option value="left_arm">Left arm</option>
            <option value="right_thigh">Right thigh</option>
            <option value="left_thigh">Left thigh</option>
            <option value="right_wrist">Right wrist</option>
            <option value="left_wrist">Left wrist</option>
          </select></label>
      </div>
    </section>

    <!-- Orthostatic BP -->
    <section style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:1rem;flex-wrap:wrap;margin-bottom:.5rem;">
        <h2 style="margin:0;font-size:1.05rem;">Orthostatic Blood Pressure & Heart Rate</h2>
        <label style="font-size:.85rem;color:#374151;display:flex;align-items:center;gap:.5rem;">
          Cuff Location:
          <select name="ortho_cuff" style="padding:.35rem .55rem;border:1px solid #d1d5db;border-radius:6px;font-size:.9rem;">
            <option value="">—</option>
            <option value="right_arm">Right arm</option>
            <option value="left_arm">Left arm</option>
            <option value="right_thigh">Right thigh</option>
            <option value="left_thigh">Left thigh</option>
            <option value="right_wrist">Right wrist</option>
            <option value="left_wrist">Left wrist</option>
          </select>
        </label>
      </div>
      <p style="margin:0 0 .75rem;color:#6b7280;font-size:.85rem;">Record any positions you captured. Leave blank for positions not taken. The cuff location above applies to all three.</p>
      <table style="width:100%;border-collapse:collapse;font-size:.95rem;">
        <thead>
          <tr style="text-align:left;color:#374151;">
            <th style="padding:.4rem .5rem;font-weight:600;width:25%;">Position</th>
            <th style="padding:.4rem .5rem;font-weight:600;">Systolic (mmHg)</th>
            <th style="padding:.4rem .5rem;font-weight:600;">Diastolic (mmHg)</th>
            <th style="padding:.4rem .5rem;font-weight:600;">HR (bpm)</th>
          </tr>
        </thead>
        <tbody>
""" + _ortho_row("Laying", "laying") + _ortho_row("Sitting", "sitting") + _ortho_row("Standing", "standing") + """
        </tbody>
      </table>
    </section>

    <!-- Weight -->
    <section style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;">
      <h2 style="margin:0 0 .75rem;font-size:1.05rem;">Weight</h2>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;max-width:460px;">
        <label style="display:grid;gap:.25rem;font-size:.9rem;">
          <span style="color:#374151;">Current weight (lbs)</span>
          <input type="number" step="0.1" min="0" name="weight_current" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;font-size:.95rem;"/>
        </label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;">
          <span style="color:#374151;">Dry weight (lbs)</span>
          <input type="number" step="0.1" min="0" name="weight_dry" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;font-size:.95rem;"/>
        </label>
      </div>
    </section>

    <!-- Urine output -->
    <section style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem;">
        <h2 style="margin:0;font-size:1.05rem;">Urine Output</h2>
        <button type="button" id="vd-add-urine" style="background:#2563eb;color:#fff;border:0;padding:.35rem .75rem;border-radius:6px;font-size:.85rem;cursor:pointer;">+ Add void</button>
      </div>
      <div id="vd-urine-rows" style="display:grid;gap:.5rem;"></div>
      <p style="margin:.5rem 0 0;color:#6b7280;font-size:.8rem;">Daily total is computed automatically from the entries below.</p>
    </section>

    <!-- Other vitals -->
    <section style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;">
      <h2 style="margin:0 0 .75rem;font-size:1.05rem;">Other Vitals</h2>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;">
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">O2 saturation (%)</span>
          <input type="number" step="1" min="0" max="100" name="oxygen_saturation" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;"/></label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">Respiration rate</span>
          <input type="number" step="1" min="0" name="respiration_rate" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;"/></label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">Temperature (F)</span>
          <input type="number" step="0.1" min="0" name="temperature" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;"/></label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;"><span style="color:#374151;">Pain (0-10)</span>
          <input type="number" step="1" min="0" max="10" name="pain_score" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;"/></label>
        <label style="display:grid;gap:.25rem;font-size:.9rem;grid-column:span 2;"><span style="color:#374151;">Edema</span>
          <div style="display:flex;gap:.5rem;">
            <select name="edema_grade" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;flex:0 0 140px;">
              <option value="">—</option>
              <option>None</option><option>Trace</option><option>1+</option><option>2+</option><option>3+</option><option>4+</option>
            </select>
            <input type="text" name="edema_location" placeholder="Location (e.g. bilateral LE)" style="padding:.45rem .6rem;border:1px solid #d1d5db;border-radius:6px;flex:1;"/>
          </div>
        </label>
      </div>
    </section>

    <div style="display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;margin-top:.5rem;">
      <button type="button" id="vd-save" style="background:#6b7280;color:#fff;border:0;padding:.65rem 1.25rem;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;">Save Session</button>
      <button type="button" id="vd-finish" style="background:#059669;color:#fff;border:0;padding:.65rem 1.25rem;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;">Finish Session &amp; Create Note</button>
      <button type="button" id="vd-carry" style="background:transparent;color:#2563eb;border:1px solid #bfdbfe;padding:.55rem 1rem;border-radius:8px;font-size:.9rem;cursor:pointer;">Carry Forward Last Values</button>
      <button type="button" id="vd-clear" style="background:transparent;color:#6b7280;border:1px solid #d1d5db;padding:.55rem 1rem;border-radius:8px;font-size:.9rem;cursor:pointer;">Start Fresh</button>
      <span id="vd-autosave" style="font-size:.8rem;color:#9ca3af;margin-left:auto;"></span>
      <span id="vd-message" style="font-size:.9rem;flex-basis:100%;"></span>
    </div>
  </form>

  <div style="margin-top:2rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.5rem;">
    <h2 style="margin:0;font-size:1.2rem;">Trends &amp; History</h2>
    <div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;">
      <label style="font-size:.85rem;color:#374151;display:flex;align-items:center;gap:.5rem;">
        Window:
        <select id="vd-window" style="padding:.35rem .55rem;border:1px solid #d1d5db;border-radius:6px;font-size:.9rem;">
          <option value="24h">Last 24 hours</option>
          <option value="7d" selected>Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="90d">Last 90 days</option>
          <option value="all">All time</option>
        </select>
      </label>
      <button type="button" id="vd-export-csv" style="background:#fff;color:#374151;border:1px solid #d1d5db;padding:.4rem .75rem;border-radius:6px;font-size:.85rem;cursor:pointer;">Export CSV</button>
      <button type="button" id="vd-print" style="background:#fff;color:#374151;border:1px solid #d1d5db;padding:.4rem .75rem;border-radius:6px;font-size:.85rem;cursor:pointer;">Print Report</button>
    </div>
  </div>

  <section style="margin-top:1rem;">
    <div id="vd-charts-status" style="color:#6b7280;font-size:.9rem;padding:.5rem 0;">Loading charts…</div>
    <div id="vd-charts-body" style="display:none;">
      <div class="vd-chart-panel full">
        <h3>Blood Pressure</h3>
        <div class="vd-chart-wrap"><canvas id="vd-chart-bp"></canvas></div>
      </div>
      <div class="vd-charts-grid" style="margin-top:1rem;">
        <div class="vd-chart-panel"><h3>Heart Rate (bpm)</h3><div class="vd-chart-wrap"><canvas id="vd-chart-hr"></canvas></div></div>
        <div class="vd-chart-panel"><h3>Weight (lbs)</h3><div class="vd-chart-wrap"><canvas id="vd-chart-weight"></canvas></div></div>
      </div>
      <div class="vd-chart-panel full" style="margin-top:1rem;">
        <h3>Urine Output (mL per void)</h3>
        <div class="vd-chart-wrap"><canvas id="vd-chart-urine"></canvas></div>
      </div>
      <div class="vd-charts-mini" style="margin-top:1rem;">
        <div class="vd-chart-panel"><h3>O2 Sat (%)</h3><div class="vd-chart-wrap"><canvas id="vd-chart-o2"></canvas></div></div>
        <div class="vd-chart-panel"><h3>Resp Rate</h3><div class="vd-chart-wrap"><canvas id="vd-chart-rr"></canvas></div></div>
        <div class="vd-chart-panel"><h3>Temp (F)</h3><div class="vd-chart-wrap"><canvas id="vd-chart-temp"></canvas></div></div>
      </div>
      <div class="vd-chart-panel full" style="margin-top:1rem;">
        <h3>Pain (0-10)</h3>
        <div class="vd-chart-wrap"><canvas id="vd-chart-pain"></canvas></div>
      </div>
    </div>
  </section>

  <section style="margin-top:1.5rem;background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem;flex-wrap:wrap;gap:.5rem;">
      <h2 style="margin:0;font-size:1.15rem;">Measurement History</h2>
      <label style="font-size:.85rem;color:#374151;display:flex;align-items:center;gap:.5rem;">
        Filter by:
        <select id="vd-filter" style="padding:.3rem .55rem;border:1px solid #d1d5db;border-radius:6px;font-size:.85rem;">
          <option value="">All vitals</option>
          <option value="bp">Blood Pressure</option>
          <option value="heart_rate">Heart Rate</option>
          <option value="weight">Weight (current + dry)</option>
          <option value="urine_output">Urine Output</option>
          <option value="oxygen_saturation">O2 Saturation</option>
          <option value="respiration_rate">Respiration Rate</option>
          <option value="temperature">Temperature</option>
          <option value="pain_score">Pain</option>
          <option value="edema">Edema</option>
        </select>
      </label>
    </div>
    <div id="vd-audit-status" style="color:#6b7280;font-size:.9rem;">Loading history…</div>
    <div id="vd-audit-wrap" style="overflow-x:auto;display:none;">
      <table style="width:100%;border-collapse:collapse;font-size:.9rem;">
        <thead>
          <tr style="text-align:left;color:#374151;border-bottom:1px solid #e5e7eb;">
            <th style="padding:.5rem .5rem;">Date/Time</th>
            <th style="padding:.5rem .5rem;">Vital</th>
            <th style="padding:.5rem .5rem;">Position</th>
            <th style="padding:.5rem .5rem;">Value</th>
            <th style="padding:.5rem .5rem;">Entered by</th>
            <th style="padding:.5rem .5rem;">Provider</th>
            <th style="padding:.5rem .5rem;">Note</th>
            <th style="padding:.5rem .5rem;">Actions</th>
          </tr>
        </thead>
        <tbody id="vd-audit-body"></tbody>
      </table>
    </div>
  </section>
</div>

<script>
(function() {
  const BOOT = __BOOTSTRAP__;
  const API_BASE = "/plugin-io/api/vitals_dashboard";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const msg = (text, color) => {
    const el = $("#vd-message");
    el.textContent = text;
    el.style.color = color || "#374151";
  };

  // Default session datetime = now (local)
  (function setNow() {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    $("[name=session_datetime]").value = d.toISOString().slice(0, 16);
  })();

  // Urine rows
  let urineCounter = 0;
  function addUrineRow(time) {
    const row = document.createElement("div");
    row.dataset.urine = ++urineCounter;
    row.style.cssText = "display:grid;grid-template-columns:180px 140px 1fr 36px;gap:.5rem;align-items:center;";
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    row.innerHTML = `
      <input type="time" class="u-time" value="${(time || now.toISOString().slice(11,16))}" style="padding:.4rem;border:1px solid #d1d5db;border-radius:6px;"/>
      <input type="number" class="u-vol" placeholder="mL" min="0" step="1" style="padding:.4rem;border:1px solid #d1d5db;border-radius:6px;"/>
      <input type="text" class="u-desc" placeholder="Qualitative (clear, amber, hematuria...)" style="padding:.4rem;border:1px solid #d1d5db;border-radius:6px;"/>
      <button type="button" class="u-rm" title="Remove" style="background:#fee2e2;color:#991b1b;border:0;border-radius:6px;height:32px;cursor:pointer;">&times;</button>
    `;
    row.querySelector(".u-rm").addEventListener("click", () => row.remove());
    $("#vd-urine-rows").appendChild(row);
  }
  $("#vd-add-urine").addEventListener("click", () => addUrineRow());

  // Helpers to collect form data
  function num(name) {
    const v = $(`[name=${name}]`).value;
    return v === "" ? null : parseFloat(v);
  }
  function buildMeasurements(sessionISO) {
    const ms = [];
    const orthoCuff = ($("[name=ortho_cuff]") && $("[name=ortho_cuff]").value) || "";
    ["laying","sitting","standing"].forEach(pos => {
      const s = num(`sys_${pos}`);
      const d = num(`dia_${pos}`);
      const hr = num(`hr_${pos}`);
      if (s !== null) ms.push({vital_type:"bp_systolic", position:pos, cuff_location:orthoCuff, value_numeric:s, recorded_at:sessionISO});
      if (d !== null) ms.push({vital_type:"bp_diastolic", position:pos, cuff_location:orthoCuff, value_numeric:d, recorded_at:sessionISO});
      if (hr !== null) ms.push({vital_type:"heart_rate", position:pos, cuff_location:orthoCuff, value_numeric:hr, recorded_at:sessionISO});
    });
    // Standard BP (non-orthostatic)
    const stdSys = num("std_sys");
    const stdDia = num("std_dia");
    const stdHr = num("std_hr");
    const stdCuff = ($("[name=std_cuff]") && $("[name=std_cuff]").value) || "";
    if (stdSys !== null) ms.push({vital_type:"bp_systolic", position:"", cuff_location:stdCuff, value_numeric:stdSys, recorded_at:sessionISO});
    if (stdDia !== null) ms.push({vital_type:"bp_diastolic", position:"", cuff_location:stdCuff, value_numeric:stdDia, recorded_at:sessionISO});
    if (stdHr !== null) ms.push({vital_type:"heart_rate", position:"", cuff_location:stdCuff, value_numeric:stdHr, recorded_at:sessionISO});
    const single = {
      weight_current:num("weight_current"),
      weight_dry:num("weight_dry"),
      oxygen_saturation:num("oxygen_saturation"),
      respiration_rate:num("respiration_rate"),
      temperature:num("temperature"),
      pain_score:num("pain_score"),
    };
    Object.entries(single).forEach(([k,v]) => {
      if (v !== null) ms.push({vital_type:k, value_numeric:v, recorded_at:sessionISO});
    });
    const edemaGrade = $("[name=edema_grade]").value;
    const edemaLoc = $("[name=edema_location]").value.trim();
    if (edemaGrade || edemaLoc) {
      const text = [edemaGrade, edemaLoc].filter(Boolean).join(" - ");
      ms.push({vital_type:"edema", value_text:text, recorded_at:sessionISO});
    }
    // Urine rows
    document.querySelectorAll("[data-urine]").forEach(r => {
      const t = r.querySelector(".u-time").value;
      const v = r.querySelector(".u-vol").value;
      const desc = r.querySelector(".u-desc").value.trim();
      if (!t || (v === "" && !desc)) return;
      const sessionDate = sessionISO.slice(0, 10);
      const recorded = `${sessionDate}T${t}:00`;
      ms.push({
        vital_type:"urine_output",
        value_numeric: v === "" ? null : parseFloat(v),
        value_text: desc,
        recorded_at: recorded,
      });
    });
    return ms;
  }

  let currentSessionId = null;
  let inFlight = false;
  let autoTimer = null;

  function autoIndicator(text, color) {
    const el = $("#vd-autosave");
    el.textContent = text;
    el.style.color = color || "#9ca3af";
  }

  function scheduleAutosave() {
    if (!BOOT.patient_key) return;
    if (autoTimer) clearTimeout(autoTimer);
    autoIndicator("Unsaved changes…", "#f59e0b");
    autoTimer = setTimeout(() => { submit(false, true); }, 2000);
  }

  function resetForm() {
    $("#vd-form").reset();
    document.querySelectorAll("[data-urine]").forEach(r => r.remove());
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    $("[name=session_datetime]").value = d.toISOString().slice(0, 16);
    currentSessionId = null;
    autoIndicator("");
  }

  async function submit(finish, quiet) {
    if (inFlight) return;
    inFlight = true;
    if (autoTimer) { clearTimeout(autoTimer); autoTimer = null; }
    const saveBtn = $("#vd-save");
    const finishBtn = $("#vd-finish");
    saveBtn.disabled = true;
    finishBtn.disabled = true;
    if (!quiet) msg(finish ? "Saving and creating note…" : "Saving…", "#6b7280");
    else autoIndicator("Saving…", "#6b7280");

    const sessionISO = $("[name=session_datetime]").value;
    const measurements = buildMeasurements(sessionISO);
    if (!measurements.length) {
      if (!quiet) msg("Enter at least one measurement before saving.", "#b45309");
      else autoIndicator("");
      saveBtn.disabled = false;
      finishBtn.disabled = false;
      inFlight = false;
      return;
    }

    const sessionUTC = new Date(sessionISO).toISOString();
    const measurementsUTC = measurements.map(m => {
      if (m.recorded_at && !m.recorded_at.endsWith("Z")) {
        try { m.recorded_at = new Date(m.recorded_at).toISOString(); } catch (e) {}
      }
      return m;
    });

    const body = {
      patient_key: BOOT.patient_key,
      entered_by_staff_key: BOOT.staff_key || "unknown",
      session_datetime: sessionUTC,
      session_datetime_display: sessionISO.replace("T", " "),
      measurements: measurementsUTC,
      finish: !!finish,
    };
    if (currentSessionId) body.update_session_id = currentSessionId;

    try {
      const res = await fetch(`${API_BASE}/sessions`, {
        method: "POST",
        credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (res.ok) {
        if (json.note_created) {
          msg(`Session saved (${json.measurement_count} measurements) · Vitals note created. Syncing to chart...`, "#059669");
          resetForm();
          if (json.session_id) {
            syncObservationsWithRetry(json.session_id);
          }
        } else {
          currentSessionId = json.session_id;
          const t = new Date().toLocaleTimeString([], {hour:"numeric", minute:"2-digit"});
          if (quiet) {
            autoIndicator(`Autosaved ${t}`, "#059669");
          } else {
            autoIndicator(`Saved ${t}`, "#059669");
            msg(`Saved draft (${json.measurement_count} measurements) · values preserved. Click "Finish Session" when done.`, "#059669");
          }
        }
      } else {
        const errText = "Error: " + (json.note_error || json.error || res.statusText);
        if (quiet) autoIndicator("Autosave failed", "#b91c1c");
        else msg(errText, "#b91c1c");
      }
    } catch (err) {
      if (quiet) autoIndicator("Autosave failed", "#b91c1c");
      else msg("Network error: " + err.message, "#b91c1c");
    } finally {
      saveBtn.disabled = false;
      finishBtn.disabled = false;
      inFlight = false;
    }
  }

  async function syncObservationsWithRetry(sessionId, attempt = 0) {
    const MAX = 6;  // ~20s ceiling with backoff
    if (attempt >= MAX) {
      msg("Vitals saved, but chart sync timed out. Reload to retry.", "#b45309");
      return;
    }
    const delay = Math.min(600 * Math.pow(1.7, attempt), 4000);
    await new Promise(r => setTimeout(r, delay));
    try {
      const r = await fetch(`${API_BASE}/sync_observations`, {
        method: "POST",
        credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({session_id: sessionId}),
      });
      if (r.status === 503) {
        return syncObservationsWithRetry(sessionId, attempt + 1);
      }
      const j = await r.json();
      if (r.ok && j.synced) {
        msg(`Vitals synced to chart (${j.observation_count} observations).`, "#059669");
        return;
      }
      msg(`Vitals sync failed: ${j.error || r.statusText}`, "#b91c1c");
    } catch (e) {
      return syncObservationsWithRetry(sessionId, attempt + 1);
    }
  }

  $("#vd-form").addEventListener("input", scheduleAutosave);
  $("#vd-form").addEventListener("change", scheduleAutosave);

  $("#vd-save").addEventListener("click", async () => {
    await submit(false);
    loadHistory();
  });
  $("#vd-finish").addEventListener("click", async () => {
    await submit(true);
    loadHistory();
  });
  $("#vd-clear").addEventListener("click", () => {
    resetForm();
    msg("Form cleared. Starting a new session.", "#6b7280");
  });

  // Audit table
  const VITAL_LABEL = {
    bp_systolic: "BP Systolic",
    bp_diastolic: "BP Diastolic",
    heart_rate: "Heart Rate",
    weight_current: "Weight (Current)",
    weight_dry: "Weight (Dry)",
    urine_output: "Urine Output",
    oxygen_saturation: "O2 Sat",
    respiration_rate: "Resp Rate",
    temperature: "Temperature",
    pain_score: "Pain",
    edema: "Edema",
  };
  const POS_LABEL = { laying: "Laying", sitting: "Sitting", standing: "Standing" };
  const CUFF_LABEL = {
    right_arm: "Right arm", left_arm: "Left arm",
    right_thigh: "Right thigh", left_thigh: "Left thigh",
    right_wrist: "Right wrist", left_wrist: "Left wrist",
  };
  function posAndCuffLabel(r) {
    const pos = POS_LABEL[r.position] || "";
    const cuff = CUFF_LABEL[r.cuff_location] || "";
    if (pos && cuff) return `${pos} (${cuff})`;
    if (pos) return pos;
    if (cuff) return cuff;
    return "";
  }

  function fmtDateTime(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, {
        year: "numeric", month: "short", day: "numeric",
        hour: "numeric", minute: "2-digit",
      });
    } catch (e) { return iso; }
  }
  function fmtValue(row) {
    const num = row.value_numeric;
    const txt = row.value_text;
    const unit = row.unit || "";
    const parts = [];
    if (num !== null && num !== undefined && num !== "") {
      const n = parseFloat(num);
      parts.push(Number.isFinite(n) ? (Number.isInteger(n) ? n.toString() : n.toString()) : num);
    }
    if (unit) parts.push(unit);
    let out = parts.join(" ");
    if (txt) out = out ? `${out} (${txt})` : txt;
    return out;
  }
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
      "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
    }[c]));
  }

  const charts = {};
  let lastRows = [];

  const WINDOW_LABEL = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "all": "All time",
  };

  function destroyCharts() {
    Object.values(charts).forEach(c => { try { c.destroy(); } catch (e) {} });
    Object.keys(charts).forEach(k => delete charts[k]);
  }

  const POS_COLORS = { laying: "#2563eb", sitting: "#059669", standing: "#d97706" };

  function fmtTick(ms) {
    try {
      const d = new Date(ms);
      return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    } catch (e) { return String(ms); }
  }

  function mergeOpts(overrides) {
    const base = baseTimeOptions();
    overrides = overrides || {};
    return {
      ...base,
      ...overrides,
      plugins: { ...base.plugins, ...(overrides.plugins || {}) },
      scales: { ...base.scales, ...(overrides.scales || {}) },
    };
  }

  function baseTimeOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { display: true, position: "bottom", labels: { boxWidth: 10, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: (items) => {
              if (!items.length) return "";
              const x = items[0].parsed && items[0].parsed.x !== undefined ? items[0].parsed.x : (items[0].raw && items[0].raw.x);
              return typeof x === "number" ? fmtTick(x) : "";
            },
            label: (ctx) => {
              const y = ctx.parsed && ctx.parsed.y !== undefined ? ctx.parsed.y : (ctx.raw && ctx.raw.y);
              const lbl = ctx.dataset && ctx.dataset.label ? `${ctx.dataset.label}: ` : "";
              return `${lbl}${y}`;
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          ticks: {
            maxRotation: 0,
            font: { size: 10 },
            autoSkip: true,
            maxTicksLimit: 6,
            callback: (v) => fmtTick(v),
          },
        },
        y: { beginAtZero: false, ticks: { font: { size: 10 } } },
      },
    };
  }

  function renderCharts(rows) {
    if (typeof Chart === "undefined") {
      $("#vd-charts-status").textContent = "Chart library failed to load (check network / CSP).";
      $("#vd-charts-status").style.color = "#b91c1c";
      $("#vd-charts-status").style.display = "";
      $("#vd-charts-body").style.display = "none";
      return;
    }
    destroyCharts();

    const activeRows = rows.filter(r => !r.is_deleted);
    const byType = {};
    for (const r of activeRows) {
      (byType[r.vital_type] ||= []).push(r);
    }
    const asPoints = (arr, filterPos) => {
      const f = filterPos !== undefined ? arr.filter(r => r.position === filterPos) : arr;
      return f
        .map(r => ({ x: r.recorded_at ? new Date(r.recorded_at).getTime() : NaN, y: r.value_numeric !== null ? parseFloat(r.value_numeric) : null }))
        .filter(p => p.y !== null && !Number.isNaN(p.x))
        .sort((a, b) => a.x - b.x);
    };

    // BP: 6 lines (sys+dia x 3 positions) — only drawn if data exists for that position
    const bpDatasets = [];
    for (const pos of ["laying", "sitting", "standing"]) {
      const sys = asPoints(byType.bp_systolic || [], pos);
      const dia = asPoints(byType.bp_diastolic || [], pos);
      if (sys.length) bpDatasets.push({ label: `Systolic - ${POS_LABEL[pos]}`, data: sys, borderColor: POS_COLORS[pos], backgroundColor: POS_COLORS[pos], tension: 0.2, pointRadius: 3 });
      if (dia.length) bpDatasets.push({ label: `Diastolic - ${POS_LABEL[pos]}`, data: dia, borderColor: POS_COLORS[pos], backgroundColor: POS_COLORS[pos], borderDash: [4, 4], tension: 0.2, pointRadius: 3 });
    }
    if (bpDatasets.length) {
      charts.bp = new Chart($("#vd-chart-bp").getContext("2d"), {
        type: "line",
        data: { datasets: bpDatasets },
        options: mergeOpts({ scales: { y: { beginAtZero: false, title: { display: true, text: "mmHg" } } } }),
      });
    }

    // HR — one line, colored by position (mostly unpositioned)
    const hrPoints = asPoints(byType.heart_rate || []);
    if (hrPoints.length) {
      charts.hr = new Chart($("#vd-chart-hr").getContext("2d"), {
        type: "line",
        data: { datasets: [{ label: "Heart Rate", data: hrPoints, borderColor: "#d72638", backgroundColor: "#d72638", tension: 0.2, pointRadius: 3 }] },
        options: mergeOpts({ plugins: { legend: { display: false } } }),
      });
    }

    // Weight — current + dry
    const cur = asPoints(byType.weight_current || []);
    const dry = asPoints(byType.weight_dry || []);
    if (cur.length || dry.length) {
      const ds = [];
      if (cur.length) ds.push({ label: "Current", data: cur, borderColor: "#2563eb", backgroundColor: "#2563eb", tension: 0.2, pointRadius: 3 });
      if (dry.length) ds.push({ label: "Dry", data: dry, borderColor: "#059669", backgroundColor: "#059669", borderDash: [4, 4], tension: 0.2, pointRadius: 3 });
      charts.weight = new Chart($("#vd-chart-weight").getContext("2d"), { type: "line", data: { datasets: ds }, options: mergeOpts() });
    }

    // Urine — bar chart
    const urine = asPoints(byType.urine_output || []);
    if (urine.length) {
      charts.urine = new Chart($("#vd-chart-urine").getContext("2d"), {
        type: "bar",
        data: { datasets: [{ label: "Volume (mL)", data: urine, backgroundColor: "#7c3aed", borderColor: "#7c3aed" }] },
        options: mergeOpts({
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, title: { display: true, text: "mL" } } },
        }),
      });
    }

    // Mini charts
    const mini = [
      ["o2", "oxygen_saturation", "#0ea5e9"],
      ["rr", "respiration_rate", "#16a34a"],
      ["temp", "temperature", "#dc2626"],
      ["pain", "pain_score", "#a855f7"],
    ];
    for (const [key, type, color] of mini) {
      const pts = asPoints(byType[type] || []);
      if (!pts.length) continue;
      charts[key] = new Chart($(`#vd-chart-${key}`).getContext("2d"), {
        type: "line",
        data: { datasets: [{ label: VITAL_LABEL[type], data: pts, borderColor: color, backgroundColor: color, tension: 0.2, pointRadius: 2 }] },
        options: mergeOpts({ plugins: { legend: { display: false } } }),
      });
    }
  }

  function localDatetimeValue(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
      return d.toISOString().slice(0, 16);
    } catch (e) { return ""; }
  }

  function renderRowView(r) {
    const isText = r.vital_type === "edema";
    const errored = !!r.is_deleted;
    const rowStyle = errored
      ? "border-bottom:1px solid #f3f4f6;color:#9ca3af;text-decoration:line-through;text-decoration-color:#9ca3af;background:#fafafa;"
      : "border-bottom:1px solid #f3f4f6;";
    const actionsCell = errored
      ? `<span style="color:#9ca3af;font-size:.75rem;font-style:italic;text-decoration:none;">Entered in error</span>`
      : `<button type="button" data-act="delete" style="background:transparent;border:1px solid #fecaca;padding:.2rem .55rem;border-radius:4px;font-size:.8rem;cursor:pointer;color:#b91c1c;">Mark as Entered in Error</button>`;
    return `
      <tr data-row-id="${esc(r.id)}" data-vital-type="${esc(r.vital_type)}" data-is-text="${isText ? "1" : "0"}" style="${rowStyle}">
        <td class="vd-col-dt" style="padding:.45rem .5rem;white-space:nowrap;">${esc(fmtDateTime(r.recorded_at))}</td>
        <td style="padding:.45rem .5rem;">${esc(VITAL_LABEL[r.vital_type] || r.vital_type)}</td>
        <td style="padding:.45rem .5rem;">${esc(posAndCuffLabel(r))}</td>
        <td class="vd-col-val" style="padding:.45rem .5rem;font-variant-numeric:tabular-nums;">${esc(fmtValue(r))}</td>
        <td style="padding:.45rem .5rem;">${esc(r.entered_by?.name || r.entered_by?.id || "")}</td>
        <td style="padding:.45rem .5rem;">${esc(r.provider_of_record?.name || "")}</td>
        <td style="padding:.45rem .5rem;">${r.note_id ? `<span title="${esc(r.note_id)}" style="color:#059669;text-decoration:none;">✓</span>` : ""}</td>
        <td class="vd-col-actions" style="padding:.45rem .5rem;white-space:nowrap;text-decoration:none;">${actionsCell}</td>
      </tr>`;
  }

  function enterEditMode(tr, r) {
    const isText = tr.dataset.isText === "1";
    const dtVal = localDatetimeValue(r.recorded_at);
    const valueInput = isText
      ? `<input type="text" class="vd-edit-value" value="${esc(r.value_text || "")}" style="width:100%;padding:.25rem .4rem;border:1px solid #d1d5db;border-radius:4px;" />`
      : `<input type="number" step="0.01" class="vd-edit-value" value="${r.value_numeric !== null && r.value_numeric !== undefined ? esc(r.value_numeric) : ""}" style="width:90px;padding:.25rem .4rem;border:1px solid #d1d5db;border-radius:4px;" />`;
    tr.querySelector(".vd-col-dt").innerHTML = `<input type="datetime-local" class="vd-edit-dt" value="${esc(dtVal)}" style="padding:.25rem .4rem;border:1px solid #d1d5db;border-radius:4px;font-size:.85rem;" />`;
    tr.querySelector(".vd-col-val").innerHTML = valueInput;
    tr.querySelector(".vd-col-actions").innerHTML = `
      <button type="button" data-act="save" style="background:#059669;color:#fff;border:0;padding:.25rem .65rem;border-radius:4px;font-size:.8rem;cursor:pointer;">Save</button>
      <button type="button" data-act="cancel" style="background:transparent;border:1px solid #d1d5db;padding:.25rem .65rem;border-radius:4px;font-size:.8rem;cursor:pointer;margin-left:.25rem;">Cancel</button>`;
  }

  async function saveEdit(tr, r) {
    const isText = tr.dataset.isText === "1";
    const newDt = tr.querySelector(".vd-edit-dt").value;
    const newVal = tr.querySelector(".vd-edit-value").value;
    const payload = {};
    if (newDt) {
      try { payload.recorded_at = new Date(newDt).toISOString(); } catch (e) {}
    }
    if (isText) payload.value_text = newVal;
    else payload.value_numeric = newVal === "" ? null : parseFloat(newVal);

    try {
      const res = await fetch(`${API_BASE}/measurements/${encodeURIComponent(r.id)}?patient_key=${encodeURIComponent(BOOT.patient_key)}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        msg("Edit failed: " + (j.error || res.statusText), "#b91c1c");
        return;
      }
      msg("Measurement updated.", "#059669");
      loadHistory();
    } catch (err) {
      msg("Network error: " + err.message, "#b91c1c");
    }
  }

  async function deleteRow(r) {
    if (!window.confirm(`Mark this ${VITAL_LABEL[r.vital_type] || r.vital_type} entry as entered in error? It will be removed from charts and history (the record is preserved for audit).`)) return;
    try {
      const res = await fetch(`${API_BASE}/measurements/${encodeURIComponent(r.id)}?patient_key=${encodeURIComponent(BOOT.patient_key)}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        msg("Delete failed: " + (j.error || res.statusText), "#b91c1c");
        return;
      }
      msg("Measurement deleted.", "#059669");
      loadHistory();
    } catch (err) {
      msg("Network error: " + err.message, "#b91c1c");
    }
  }

  function applyAuditFilter(rows) {
    const f = ($("#vd-filter") && $("#vd-filter").value) || "";
    if (!f) return rows;
    if (f === "bp") return rows.filter(r => r.vital_type === "bp_systolic" || r.vital_type === "bp_diastolic" || (r.vital_type === "heart_rate" && r.position));
    if (f === "heart_rate") return rows.filter(r => r.vital_type === "heart_rate" && !r.position);
    if (f === "weight") return rows.filter(r => r.vital_type === "weight_current" || r.vital_type === "weight_dry");
    return rows.filter(r => r.vital_type === f);
  }

  function renderAuditTable(rows) {
    const status = $("#vd-audit-status");
    const wrap = $("#vd-audit-wrap");
    const body = $("#vd-audit-body");
    const filtered = applyAuditFilter(rows || []);
    if (!filtered.length) {
      const hasAny = Array.isArray(rows) && rows.length > 0;
      status.textContent = hasAny
        ? "No measurements match the selected filter."
        : "No measurements in this window.";
      status.style.color = "#6b7280";
      status.style.display = "";
      wrap.style.display = "none";
      return;
    }
    body.innerHTML = filtered.map(r => renderRowView(r)).join("");
    status.style.display = "none";
    wrap.style.display = "";
  }

  async function loadHistory() {
    if (!BOOT.patient_key) return;
    const auditStatus = $("#vd-audit-status");
    const chartsStatus = $("#vd-charts-status");
    const chartsBody = $("#vd-charts-body");
    const auditWrap = $("#vd-audit-wrap");
    const win = $("#vd-window").value || "7d";

    auditStatus.textContent = "Loading…"; auditStatus.style.display = ""; auditWrap.style.display = "none";
    chartsStatus.textContent = "Loading charts…"; chartsStatus.style.display = ""; chartsBody.style.display = "none";

    try {
      const res = await fetch(`${API_BASE}/measurements?patient_key=${encodeURIComponent(BOOT.patient_key)}&since=${encodeURIComponent(win)}`, { credentials: "include" });
      const rows = await res.json();
      if (!res.ok) {
        const errText = "Error loading: " + (rows.error || res.statusText);
        auditStatus.textContent = errText; auditStatus.style.color = "#b91c1c";
        chartsStatus.textContent = errText; chartsStatus.style.color = "#b91c1c";
        return;
      }
      lastRows = Array.isArray(rows) ? rows : [];
      renderAuditTable(rows);
      if (!Array.isArray(rows) || rows.length === 0) {
        chartsStatus.textContent = "No data to chart in this window.";
        chartsStatus.style.color = "#6b7280";
      } else {
        chartsStatus.style.display = "none";
        chartsBody.style.display = "";
        renderCharts(rows);
      }
    } catch (err) {
      const errText = "Network error: " + err.message;
      auditStatus.textContent = errText; auditStatus.style.color = "#b91c1c";
      chartsStatus.textContent = errText; chartsStatus.style.color = "#b91c1c";
    }
  }

  $("#vd-window").addEventListener("change", loadHistory);
  $("#vd-filter").addEventListener("change", () => renderAuditTable(lastRows));

  $("#vd-audit-body").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const tr = btn.closest("tr[data-row-id]");
    if (!tr) return;
    const rowId = tr.dataset.rowId;
    const r = lastRows.find(x => String(x.id) === String(rowId));
    if (!r) return;
    if (btn.dataset.act === "delete") deleteRow(r);
  });

  async function carryForward() {
    if (!BOOT.patient_key) return;
    msg("Loading last session…", "#6b7280");
    try {
      const res = await fetch(`${API_BASE}/sessions/last?patient_key=${encodeURIComponent(BOOT.patient_key)}`, { credentials: "include" });
      const data = await res.json();
      if (!res.ok) {
        msg("Carry forward failed: " + (data.error || res.statusText), "#b91c1c");
        return;
      }
      if (!data.session || !data.session.measurements || !data.session.measurements.length) {
        msg("No previous finished session to carry forward.", "#b45309");
        return;
      }
      const sess = data.session;

      function setIfField(name, val) {
        const el = $(`[name=${name}]`);
        if (el && val !== null && val !== undefined && val !== "") el.value = val;
      }

      let orthoCuff = "", stdCuff = "";
      for (const m of sess.measurements) {
        const v = m.value_numeric;
        switch (m.vital_type) {
          case "bp_systolic":
            if (m.position) { setIfField(`sys_${m.position}`, v); if (m.cuff_location) orthoCuff = m.cuff_location; }
            else { setIfField("std_sys", v); if (m.cuff_location) stdCuff = m.cuff_location; }
            break;
          case "bp_diastolic":
            if (m.position) { setIfField(`dia_${m.position}`, v); if (m.cuff_location) orthoCuff = m.cuff_location; }
            else { setIfField("std_dia", v); if (m.cuff_location) stdCuff = m.cuff_location; }
            break;
          case "heart_rate":
            if (m.position) { setIfField(`hr_${m.position}`, v); if (m.cuff_location) orthoCuff = m.cuff_location; }
            else { setIfField("std_hr", v); if (m.cuff_location) stdCuff = m.cuff_location; }
            break;
          case "weight_current":
          case "weight_dry":
          case "oxygen_saturation":
          case "respiration_rate":
          case "temperature":
          case "pain_score":
            setIfField(m.vital_type, v);
            break;
          case "edema":
            if (m.value_text) {
              const parts = m.value_text.split(" - ");
              const grade = (parts[0] || "").trim();
              const loc = parts.slice(1).join(" - ").trim();
              const gradeEl = $("[name=edema_grade]");
              if (gradeEl) {
                const match = Array.from(gradeEl.options).find(o => o.value === grade || o.text === grade);
                if (match) gradeEl.value = match.value;
              }
              $("[name=edema_location]").value = loc;
            }
            break;
          // urine_output intentionally skipped - log-style, not a snapshot
        }
      }
      if (orthoCuff) setIfField("ortho_cuff", orthoCuff);
      if (stdCuff) setIfField("std_cuff", stdCuff);

      const prevLabel = sess.session_datetime ? new Date(sess.session_datetime).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
      msg(`Carried forward from previous session${prevLabel ? ` (${prevLabel})` : ""}. Review and edit any values that have changed, then Save or Finish.`, "#2563eb");
      scheduleAutosave();
    } catch (err) {
      msg("Network error: " + err.message, "#b91c1c");
    }
  }

  $("#vd-carry").addEventListener("click", carryForward);

  function csvEscape(v) {
    const s = v === null || v === undefined ? "" : String(v);
    return `"${s.replace(/"/g, '""')}"`;
  }

  function exportCSV() {
    if (!lastRows.length) {
      msg("No data in current window to export.", "#b45309");
      return;
    }
    const header = ["Date/Time","Vital","Position","Cuff Location","Value","Unit","Entered By","Provider","Entered in Error","Note Created"];
    const lines = [header.map(csvEscape).join(",")];
    for (const r of lastRows) {
      lines.push([
        fmtDateTime(r.recorded_at),
        VITAL_LABEL[r.vital_type] || r.vital_type,
        POS_LABEL[r.position] || "",
        CUFF_LABEL[r.cuff_location] || "",
        r.value_numeric !== null && r.value_numeric !== undefined ? r.value_numeric : (r.value_text || ""),
        r.unit || "",
        (r.entered_by && (r.entered_by.name || r.entered_by.id)) || "",
        (r.provider_of_record && r.provider_of_record.name) || "",
        r.is_deleted ? "Yes" : "",
        r.note_id ? "Yes" : "",
      ].map(csvEscape).join(","));
    }
    const csv = lines.join("\\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const dateStr = new Date().toISOString().slice(0, 10);
    const win = $("#vd-window").value || "7d";
    a.href = url;
    a.download = `vitals_${BOOT.patient_key || "patient"}_${win}_${dateStr}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
  }

  async function fetchReportContext() {
    try {
      const res = await fetch(`${API_BASE}/report_context?patient_key=${encodeURIComponent(BOOT.patient_key)}`, { credentials: "include" });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) { return null; }
  }

  function fmtDOB(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso + "T12:00:00");
      return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    } catch (e) { return iso; }
  }

  async function printReport() {
    if (!lastRows.length) {
      msg("No data in current window to print.", "#b45309");
      return;
    }
    const win = $("#vd-window").value || "7d";
    const windowLabel = WINDOW_LABEL[win] || win;
    const generated = new Date().toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

    msg("Preparing report…", "#6b7280");
    const ctx = await fetchReportContext();
    msg("", "");

    const chartImages = {};
    for (const [key, chart] of Object.entries(charts)) {
      try { chartImages[key] = chart.toBase64Image(); } catch (e) {}
    }

    const chartBlock = (key, title, fullWidth) => {
      if (!chartImages[key]) return "";
      return `<div class="chart ${fullWidth ? "full" : ""}"><h3>${title}</h3><img src="${chartImages[key]}" alt="${title}" /></div>`;
    };

    const patient = (ctx && ctx.patient) || {};
    const practice = (ctx && ctx.practice) || {};
    const ageSex = [
      patient.age !== null && patient.age !== undefined ? `${patient.age} y/o` : "",
      patient.sex || "",
    ].filter(Boolean).join(" ");

    const practiceHeader = `
      <div class="practice-header">
        ${practice.logo_url ? `<img class="practice-logo" src="${practice.logo_url}" alt="" />` : ""}
        <div class="practice-info">
          <div class="practice-name">${esc(practice.name || "")}</div>
          ${(practice.address_lines || []).map(l => `<div>${esc(l)}</div>`).join("")}
          ${practice.phone ? `<div>${esc(practice.phone)}</div>` : ""}
        </div>
      </div>`;

    const patientHeader = `
      <div class="patient-header">
        <div class="patient-name">${esc(patient.full_name || BOOT.patient_key || "—")}</div>
        <table class="patient-demographics">
          <tr>
            <td><strong>MRN:</strong> ${esc(patient.mrn || "")}</td>
            <td><strong>DOB:</strong> ${esc(fmtDOB(patient.birth_date))}${ageSex ? ` (${esc(ageSex)})` : ""}</td>
          </tr>
          ${(patient.phone || (patient.address_lines && patient.address_lines.length)) ? `
          <tr>
            <td>${patient.phone ? `<strong>Phone:</strong> ${esc(patient.phone)}` : ""}</td>
            <td>${(patient.address_lines || []).length ? `<strong>Address:</strong> ${(patient.address_lines || []).map(esc).join("<br>")}` : ""}</td>
          </tr>` : ""}
        </table>
      </div>`;

    const tableRows = lastRows.map(r => {
      const errStyle = r.is_deleted ? ' style="color:#9ca3af;text-decoration:line-through;"' : '';
      return `
      <tr${errStyle}>
        <td>${fmtDateTime(r.recorded_at)}</td>
        <td>${VITAL_LABEL[r.vital_type] || r.vital_type}</td>
        <td>${posAndCuffLabel(r)}</td>
        <td>${fmtValue(r)}</td>
        <td>${(r.entered_by && (r.entered_by.name || r.entered_by.id)) || ""}</td>
        <td>${(r.provider_of_record && r.provider_of_record.name) || ""}</td>
        <td>${r.note_id ? "Yes" : ""}${r.is_deleted ? " (entered in error)" : ""}</td>
      </tr>`;
    }).join("");

    const doc = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Vitals Report - ${esc(patient.full_name || "")}</title>
<style>
  @page { margin: 0.5in; }
  body { font-family: system-ui, -apple-system, sans-serif; color: #1a1a1a; margin: 0; padding: 1rem; }
  .practice-header { display: flex; align-items: center; gap: 1rem; border-bottom: 2px solid #1a1a1a; padding-bottom: .75rem; margin-bottom: 1rem; }
  .practice-logo { max-height: 60px; max-width: 180px; object-fit: contain; }
  .practice-info { flex: 1; }
  .practice-name { font-size: 14pt; font-weight: 700; margin-bottom: .15rem; }
  .practice-info div { font-size: 9.5pt; color: #333; line-height: 1.35; }
  .patient-header { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 4px; padding: .75rem 1rem; margin-bottom: 1rem; }
  .patient-name { font-size: 13pt; font-weight: 700; margin-bottom: .4rem; }
  .patient-demographics { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
  .patient-demographics td { padding: 2px 0; vertical-align: top; }
  .patient-demographics td:first-child { width: 50%; padding-right: 1rem; }
  .report-title { display: flex; align-items: baseline; justify-content: space-between; border-bottom: 1px solid #e5e7eb; padding-bottom: .35rem; margin-bottom: .75rem; }
  h1 { font-size: 15pt; margin: 0; }
  .report-meta { color: #555; font-size: 9pt; }
  h2 { font-size: 12pt; margin: 1rem 0 .5rem; }
  h3 { font-size: 10pt; margin: .5rem 0 .25rem; }
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
  .chart { page-break-inside: avoid; break-inside: avoid; }
  .chart.full { grid-column: 1 / -1; }
  .chart img { width: 100%; max-height: 2.5in; height: auto; object-fit: contain; border: 1px solid #eee; border-radius: 4px; }
  .chart.full img { max-height: 2.2in; }
  .practice-header, .patient-header { page-break-inside: avoid; break-inside: avoid; }
  h2 { page-break-after: avoid; break-after: avoid; }
  h3 { page-break-after: avoid; break-after: avoid; }
  table.history { width: 100%; border-collapse: collapse; font-size: 9pt; margin-top: .75rem; page-break-inside: auto; }
  table.history thead { display: table-header-group; }
  table.history tr { page-break-inside: avoid; }
  table.history th, table.history td { padding: 4px 6px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }
  table.history th { background: #f5f5f5; font-weight: 600; }
  .no-print { margin-bottom: 1rem; }
  @media print { .no-print { display: none; } body { padding: 0; } }
</style>
</head>
<body>
  <div class="no-print">
    <button onclick="window.print()" style="padding:.5rem 1rem;font-size:1rem;background:#2563eb;color:#fff;border:0;border-radius:6px;cursor:pointer;">Print / Save as PDF</button>
    <button onclick="window.close()" style="padding:.5rem 1rem;font-size:1rem;background:#fff;border:1px solid #d1d5db;border-radius:6px;cursor:pointer;margin-left:.5rem;">Close</button>
  </div>

  ${practiceHeader}
  ${patientHeader}

  <div class="report-title">
    <h1>Vitals Report</h1>
    <div class="report-meta">Window: ${esc(windowLabel)} · Generated ${esc(generated)}</div>
  </div>

  <h2>Trends</h2>
  <div class="charts">
    ${chartBlock("bp", "Blood Pressure", true)}
    ${chartBlock("hr", "Heart Rate (bpm)", false)}
    ${chartBlock("weight", "Weight (lbs)", false)}
    ${chartBlock("urine", "Urine Output (mL)", true)}
    ${chartBlock("o2", "O2 Saturation (%)", false)}
    ${chartBlock("rr", "Respiration Rate", false)}
    ${chartBlock("temp", "Temperature (F)", false)}
    ${chartBlock("pain", "Pain (0-10)", true)}
  </div>

  <h2>Measurement History (${lastRows.length} rows)</h2>
  <table class="history">
    <thead><tr><th>Date/Time</th><th>Vital</th><th>Position</th><th>Value</th><th>Entered By</th><th>Provider</th><th>Note</th></tr></thead>
    <tbody>${tableRows}</tbody>
  </table>
</body>
</html>`;

    const w = window.open("", "_blank");
    if (!w) {
      msg("Popup blocked — allow popups for this site to print.", "#b91c1c");
      return;
    }
    w.document.open();
    w.document.write(doc);
    w.document.close();
  }

  $("#vd-export-csv").addEventListener("click", exportCSV);
  $("#vd-print").addEventListener("click", printReport);

  async function loadDraft() {
    if (!BOOT.patient_key) return;
    try {
      const res = await fetch(`${API_BASE}/sessions/draft?patient_key=${encodeURIComponent(BOOT.patient_key)}`, { credentials: "include" });
      const data = await res.json();
      if (!res.ok || !data.draft) return;
      const draft = data.draft;
      if (!draft.measurements || draft.measurements.length === 0) return;

      currentSessionId = draft.session_id;

      let originalLabel = "";
      if (draft.session_datetime) {
        try {
          const orig = new Date(draft.session_datetime);
          originalLabel = orig.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
        } catch (e) {}
      }
      // Always reset the datetime field to NOW on restore — user can edit if needed.
      // Keeping the original session_datetime ties the restored draft to a potentially
      // stale timestamp; NOW reflects when the user is actually charting.
      const now = new Date();
      now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
      $("[name=session_datetime]").value = now.toISOString().slice(0, 16);

      function setIfField(name, val) {
        const el = $(`[name=${name}]`);
        if (el && val !== null && val !== undefined && val !== "") el.value = val;
      }

      let orthoCuff = "", stdCuff = "";
      for (const m of draft.measurements) {
        const v = m.value_numeric;
        switch (m.vital_type) {
          case "bp_systolic":
            if (m.position) { setIfField(`sys_${m.position}`, v); if (m.cuff_location) orthoCuff = m.cuff_location; }
            else { setIfField("std_sys", v); if (m.cuff_location) stdCuff = m.cuff_location; }
            break;
          case "bp_diastolic":
            if (m.position) { setIfField(`dia_${m.position}`, v); if (m.cuff_location) orthoCuff = m.cuff_location; }
            else { setIfField("std_dia", v); if (m.cuff_location) stdCuff = m.cuff_location; }
            break;
          case "heart_rate":
            if (m.position) { setIfField(`hr_${m.position}`, v); if (m.cuff_location) orthoCuff = m.cuff_location; }
            else { setIfField("std_hr", v); if (m.cuff_location) stdCuff = m.cuff_location; }
            break;
          case "weight_current":
          case "weight_dry":
          case "oxygen_saturation":
          case "respiration_rate":
          case "temperature":
          case "pain_score":
            setIfField(m.vital_type, v);
            break;
          case "edema":
            if (m.value_text) {
              const parts = m.value_text.split(" - ");
              const grade = (parts[0] || "").trim();
              const loc = parts.slice(1).join(" - ").trim();
              const gradeEl = $("[name=edema_grade]");
              if (gradeEl) {
                const match = Array.from(gradeEl.options).find(o => o.value === grade || o.text === grade);
                if (match) gradeEl.value = match.value;
              }
              $("[name=edema_location]").value = loc;
            }
            break;
          case "urine_output": {
            let t = "";
            if (m.recorded_at) {
              const d = new Date(m.recorded_at);
              t = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
            }
            addUrineRow(t);
            const rows = document.querySelectorAll("[data-urine]");
            const row = rows[rows.length - 1];
            if (row) {
              row.querySelector(".u-vol").value = v !== null && v !== undefined ? v : "";
              row.querySelector(".u-desc").value = m.value_text || "";
            }
            break;
          }
        }
      }

      if (orthoCuff) setIfField("ortho_cuff", orthoCuff);
      if (stdCuff) setIfField("std_cuff", stdCuff);

      const origBit = originalLabel ? ` (originally saved ${originalLabel})` : "";
      msg(`Draft restored (${draft.measurements.length} values)${origBit}. Timestamp reset to now — edit if needed, then Save or Finish.`, "#2563eb");
    } catch (err) {
      console.warn("Failed to load draft:", err);
    }
  }

  if (!BOOT.patient_key) {
    msg("No patient context — open this tab from a patient chart.", "#b45309");
    $("#vd-save").disabled = true;
    $("#vd-finish").disabled = true;
    $("#vd-audit-status").textContent = "No patient context.";
  } else {
    loadDraft();
    loadHistory();
  }
})();
</script>
""".replace("__BOOTSTRAP__", bootstrap_json)
    )


def _ortho_row(label: str, key: str) -> str:
    return (
        f'<tr><td style="padding:.4rem .5rem;font-weight:500;">{label}</td>'
        f'<td style="padding:.4rem .5rem;"><input type="number" name="sys_{key}" min="0" max="300" '
        f'style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;"/></td>'
        f'<td style="padding:.4rem .5rem;"><input type="number" name="dia_{key}" min="0" max="250" '
        f'style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;"/></td>'
        f'<td style="padding:.4rem .5rem;"><input type="number" name="hr_{key}" min="0" max="300" '
        f'style="width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px;"/></td></tr>'
    )
