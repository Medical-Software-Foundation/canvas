"""
Application handler for the Practitioner Bulk Loader.

Launched from the Canvas app drawer. Renders a full-page, three-state UI:
  State 1 - Upload: drag-and-drop CSV file zone + Download Template button
  State 2 - Preview: validation errors OR preview table with per-row actions
  State 3 - Results: success/error summary with Copy/Download buttons
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# The HTML/CSS/JS for the application is generated inline so the plugin is
# self-contained in a single delivery unit — no separate static file routes needed.
# Cache busting is not needed: LaunchModalEffect(content=...) ships the HTML
# inline per request rather than serving it from a cacheable plugin asset URL.
_APP_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Staff Loader</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet"/>
<style>
  :root{
    --ink:#0B1117;
    --ink-2:#1e293b;
    --muted:#64748b;
    --muted-2:#94a3b8;
    --line:#e2e8f0;
    --line-soft:#f1f5f9;
    --surface:#fff;
    --surface-2:#fafaf7;
    --bg:#f6f3ee;
    --brand:#1678C2;
    --brand-2:#1266A8;
    --accent:#EE8A39;
    --danger:#DC2626;
    --danger-bg:#fef2f2;
    --danger-line:#fecaca;
    --danger-ink:#991b1b;
    --success:#16A34A;
    --success-bg:#f0fdf4;
    --success-line:#bbf7d0;
    --success-ink:#166534;
    --warning:#D97706;
    --warning-bg:#fffbeb;
    --warning-line:#fde68a;
    --warning-ink:#92400e;
    --info-bg:#eff6ff;
    --info-line:#dbeafe;
    --info-ink:#1e40af;
    --shadow:0 1px 2px rgba(11,17,23,0.04),0 1px 4px rgba(11,17,23,0.04);
    --shadow-2:0 4px 12px rgba(11,17,23,0.06),0 1px 2px rgba(11,17,23,0.04);
    --serif:'Lato',Georgia,serif;
    --sans:'Lato',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:var(--sans);background:var(--bg);color:var(--ink-2);font-size:14px;-webkit-font-smoothing:antialiased}
  body::before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(1200px 600px at 20% -10%,rgba(22,120,194,0.06),transparent 60%),radial-gradient(800px 400px at 100% 10%,rgba(238,138,57,0.04),transparent 60%);z-index:0}
  .app{max-width:1240px;margin:0 auto;padding:32px 24px;position:relative;z-index:1}
  .header{margin-bottom:24px;display:flex;justify-content:space-between;align-items:flex-end;gap:24px;padding-bottom:20px;border-bottom:1px solid var(--line)}
  .header-text h1{font-family:var(--sans);font-weight:900;font-size:28px;color:var(--ink);letter-spacing:-0.01em;line-height:1.1;margin-bottom:6px}
  .header-text p{color:#64748b;font-size:13px}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:4px;border:none;cursor:pointer;font-size:13px;font-weight:500;transition:opacity 0.15s}
  .btn:disabled{opacity:0.5;cursor:not-allowed}
  .btn-primary{background:#1678C2;color:#fff}
  .btn-primary:hover:not(:disabled){background:#1266A8}
  .btn-secondary{background:#fff;color:#1e293b;border:1px solid #cbd5e1}
  .btn-secondary:hover:not(:disabled){background:#f1f5f9}
  .btn-success{background:#1678C2;color:#fff}
  .btn-success:hover:not(:disabled){background:#1266A8}
  .btn-danger{background:#DC2626;color:#fff}
  .btn-danger:hover:not(:disabled){background:#b91c1c}
  .card{background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.07);padding:24px;margin-bottom:16px}
  .drop-zone{border:2px dashed #cbd5e1;border-radius:8px;padding:48px;text-align:center;background:#f8fafc;cursor:pointer;transition:all 0.2s}
  .drop-zone.dragover{border-color:var(--brand);background:#f1f5f9}
  .drop-zone.uploaded{border-style:solid;border-color:var(--success);background:var(--success-bg);padding:28px}
  .drop-zone svg{margin-bottom:12px;color:#94a3b8}
  .drop-zone.uploaded svg{color:var(--success);margin-bottom:8px}
  .drop-zone p{color:#64748b;margin-bottom:8px}
  .drop-zone .hint{font-size:12px;color:#94a3b8}
  .drop-zone .file-name{font-family:var(--mono);font-size:14px;font-weight:600;color:var(--success-ink);margin-bottom:4px;word-break:break-all}
  .drop-zone .file-meta{font-size:12px;color:var(--muted)}
  .banner{padding:10px 14px;border-radius:4px;margin-bottom:8px;font-size:13px;font-weight:500;border-left:3px solid;line-height:1.5}
  .banner code{font-family:var(--mono);background:rgba(0,0,0,0.05);padding:1px 4px;border-radius:3px;font-size:12px}
  .info-glyph{display:inline-block;color:var(--brand);font-size:15px;line-height:1;vertical-align:-1px;margin-right:4px;font-weight:400}
  .hint-line{display:flex;align-items:flex-start;gap:8px;color:var(--muted);font-size:12px;margin-bottom:14px;line-height:1.5}
  .hint-line .info-icon{width:14px;height:14px;flex-shrink:0;color:var(--muted-2);margin-top:2px}
  .hint-line a{color:var(--brand);text-decoration:underline}
  .hint-line a:hover{color:var(--brand-2)}
  .banner-error{background:#fef2f2;color:#991b1b;border-left-color:#DC2626;border-top:1px solid #fee2e2;border-right:1px solid #fee2e2;border-bottom:1px solid #fee2e2}
  .banner-success{background:#f0fdf4;color:#166534;border-left-color:#16A34A;border-top:1px solid #dcfce7;border-right:1px solid #dcfce7;border-bottom:1px solid #dcfce7}
  .banner-warning{background:#fffbeb;color:#92400e;border-left-color:#D97706;border-top:1px solid #fef3c7;border-right:1px solid #fef3c7;border-bottom:1px solid #fef3c7}
  .banner-info{background:#eff6ff;color:#1e40af;border-left-color:#1678C2;border-top:1px solid #dbeafe;border-right:1px solid #dbeafe;border-bottom:1px solid #dbeafe}
  .banner a{color:inherit;text-decoration:underline;font-weight:600}
  .ack-row{display:flex;align-items:center;gap:8px;padding:10px 12px;margin-bottom:8px;border:1px solid #fecaca;background:#fef2f2;border-radius:4px;color:#991b1b;font-size:13px;cursor:pointer;transition:background 0.15s,color 0.15s,border-color 0.15s}
  .ack-row.checked{background:#eff6ff;border-color:#bfdbfe;color:#1e40af}
  .ack-row input[type=checkbox]{width:16px;height:16px;cursor:pointer;accent-color:#1678C2}
  .table-wrap{overflow-x:auto}
  table.preview-table{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}
  table.preview-table th{background:#f8fafc;text-align:left;padding:8px 10px;font-weight:600;color:#475569;border-bottom:2px solid #e2e8f0;font-size:11px;text-transform:uppercase;letter-spacing:0.04em}
  table.preview-table td{padding:8px 10px;border-bottom:1px solid #f1f5f9;vertical-align:top;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  table.preview-table td.wrap{white-space:normal;word-break:break-word}
  table.preview-table tr.data-row{cursor:pointer}
  table.preview-table tr.data-row:hover td{background:#f8fafc}
  table.preview-table > tbody > tr.expand-row > td{padding:0;background:#fafafa;border-bottom:1px solid #f1f5f9}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{background:#f1f5f9;text-align:left;padding:8px 12px;font-weight:600;color:#475569;border-bottom:2px solid #e2e8f0}
  td{padding:8px 12px;border-bottom:1px solid #f1f5f9;vertical-align:middle}
  tr:hover td{background:#f8fafc}
  .badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600}
  .badge-new{background:#f1f5f9;color:#020B14}
  .badge-existing{background:#fffbeb;color:#D97706}
  .badge-created{background:#f0fdf4;color:#16A34A}
  .badge-merged{background:#eff6ff;color:#2563eb}
  .badge-skipped{background:#f1f5f9;color:#475569}
  .badge-license-new{background:#FEF0E0;color:#EE8A39}
  .badge-license-neutral{background:#f1f5f9;color:#475569}
  .badge-error{background:#fef2f2;color:#DC2626}
  .badge-warn{background:#fffbeb;color:#D97706}
  table.preview-table > tbody > tr.match-warning-row > td{padding:0 12px 8px;background:transparent;border-bottom:1px solid #f1f5f9;overflow:visible;text-overflow:clip;white-space:normal}
  .match-warning{padding:10px 14px;background:var(--danger-bg);color:var(--danger-ink);border:1px solid var(--danger-line);border-radius:6px;font-size:12px;line-height:1.5;white-space:normal}
  .match-warning strong{font-weight:700}
  .conflict-pill{display:inline-flex;align-items:center;gap:4px;margin-top:4px;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;background:#fef2f2;color:#DC2626;border:1px solid #fecaca;cursor:pointer;user-select:none}
  .conflict-pill:hover{background:#fee2e2}
  .conflict-pill .chevron{display:inline-block;transition:transform 0.2s;font-size:10px}
  .conflict-pill.open .chevron{transform:rotate(180deg)}
  .diff-panel{margin:12px 16px;border:1px solid var(--danger-line);border-radius:6px;overflow:hidden;background:#fff;transition:border-color 0.15s}
  .diff-panel:has(.diff-ack-row.checked){border-color:var(--info-line)}
  .diff-panel-header{background:var(--danger-bg);color:var(--danger-ink);font-size:12px;font-weight:600;padding:10px 14px;border-bottom:1px solid var(--danger-line);line-height:1.5;transition:background 0.15s,color 0.15s,border-bottom-color 0.15s}
  .diff-panel:has(.diff-ack-row.checked) .diff-panel-header{background:var(--info-bg);color:var(--info-ink);border-bottom-color:var(--info-line)}
  .diff-ack-row{margin:0;border:none;border-top:1px solid var(--danger-line);border-radius:0;padding:12px 14px;background:var(--danger-bg);color:var(--danger-ink);font-size:13px;font-weight:500}
  .diff-ack-row.checked{background:#eff6ff;color:#1e40af;border-top-color:#bfdbfe}
  table.diff-table{width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed}
  table.diff-table colgroup col.col-field{width:22%}
  table.diff-table colgroup col.col-csv{width:39%}
  table.diff-table colgroup col.col-existing{width:39%}
  table.diff-table th{background:transparent;text-transform:uppercase;font-size:10px;letter-spacing:0.06em;font-weight:600;color:var(--muted);padding:10px 16px 8px;text-align:left;border-bottom:1px solid var(--line-soft)}
  table.diff-table td{padding:10px 16px;border-bottom:1px solid var(--line-soft);vertical-align:middle;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  table.diff-table tr:last-child td{border-bottom:none}
  .diff-field{font-weight:600;color:var(--ink-2)}
  .diff-csv{font-family:var(--mono);font-size:12px}
  .diff-existing{font-family:var(--mono);font-size:12px}
  .diff-csv .diff-value, .diff-existing .diff-value{color:var(--ink-2)}
  .diff-tag{display:inline-block;margin-left:8px;vertical-align:middle;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em;font-family:var(--sans)}
  .diff-csv .diff-value, .diff-existing .diff-value{display:inline-block;vertical-align:middle}
  .tag-applied-csv{background:var(--success-bg);color:var(--success-ink)}
  .tag-applied-canvas{background:var(--danger-bg);color:var(--danger-ink)}
  .tag-additional-csv{background:var(--info-bg);color:var(--info-ink)}
  .tag-additional-canvas{background:var(--success-bg);color:var(--success-ink)}
  .tag-ignored-csv{background:var(--danger-bg);color:var(--danger-ink)}
  .tag-ignored-canvas{background:var(--info-bg);color:var(--info-ink)}
  .diff-arrow{display:inline-block;color:var(--muted-2);margin-right:8px;font-family:var(--sans)}
  .npi-conflict-cell{color:#DC2626;font-family:monospace;font-size:12px}
  .npi-conflict-existing{color:#94a3b8;font-size:11px;margin-top:2px}
  .action-select{padding:4px 24px 4px 8px;border:1px solid #cbd5e1;border-radius:4px;font-size:12px;background:#fff;width:100%;text-overflow:ellipsis;appearance:auto}
  .progress-bar-wrap{height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;margin-top:8px}
  .progress-bar{height:100%;background:#020B14;transition:width 0.3s;border-radius:4px}
  .stats-row{display:flex;gap:24px;margin-bottom:16px}
  .stat-card{flex:1;padding:16px;border-radius:8px;text-align:center}
  .stat-card.success{background:#f0fdf4;border:1px solid #bbf7d0}
  .stat-card.error{background:#fef2f2;border:1px solid #fecaca}
  .stat-card .number{font-size:32px;font-weight:700}
  .stat-card.success .number{color:#16A34A}
  .stat-card.error .number{color:#DC2626}
  .stat-card .label{font-size:12px;color:#64748b;margin-top:4px}
  .spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin 0.8s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .btn-row{display:flex;gap:8px;margin-top:16px;flex-wrap:wrap}
  .error-table td:first-child{color:#DC2626;font-weight:600}
  .hidden{display:none}
  .staff-key-cell{font-family:monospace;font-size:12px;color:#475569}
  .action-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  input[type=file]{display:none}
</style>
</head>
<body>
<div class="app">
  <div class="header">
    <div class="header-text">
      <h1>Staff Loader</h1>
      <p>Upload a CSV file to onboard multiple users in one action.</p>
    </div>
    <button class="btn btn-secondary" id="btn-download-tpl" onclick="downloadTemplate()">
      Download Template
    </button>
  </div>

  <!-- STATE 1: Upload -->
  <div id="state-upload">
    <div class="card">
      <div class="drop-zone" id="drop-zone" onclick="document.getElementById('file-input').click()"
           ondragover="onDragOver(event)" ondragleave="onDragLeave(event)" ondrop="onDrop(event)">
        <div id="drop-zone-default">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
          </svg>
          <p>Drag & drop a CSV file here, or <strong>click to browse</strong></p>
          <p class="hint">Accepts .csv files only</p>
        </div>
        <div id="drop-zone-uploaded" class="hidden">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M5 13l4 4L19 7"/>
          </svg>
          <p class="file-name" id="file-name-display">&nbsp;</p>
          <p class="file-meta">Click to choose a different file</p>
        </div>
      </div>
      <input type="file" id="file-input" accept=".csv,text/csv,application/vnd.ms-excel,application/csv,text/comma-separated-values,text/plain"/>
    </div>
    <div id="upload-error" class="hidden banner banner-error"></div>
    <div class="btn-row">
      <button class="btn btn-primary" id="btn-parse" onclick="parseAndValidate()" disabled>
        Validate & Preview
      </button>
    </div>
  </div>

  <!-- STATE 2: Preview -->
  <div id="state-preview" class="hidden">
    <div id="preview-banners"></div>

    <!-- Error table (shown when there are validation errors) -->
    <div id="error-section" class="hidden card">
      <h3 style="margin-bottom:12px;color:#DC2626">Validation Errors</h3>
      <div class="table-wrap">
        <table class="error-table">
          <thead><tr><th>Row</th><th>Field</th><th>Value</th><th>Error</th></tr></thead>
          <tbody id="error-tbody"></tbody>
        </table>
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="goToUpload()">Re-upload</button>
      </div>
    </div>

    <!-- Preview table (shown when validation passes) -->
    <div id="preview-section" class="hidden card">
      <h3 style="margin-bottom:12px">Preview</h3>
      <div class="banner banner-info" style="margin-bottom:12px">
        <span class="info-glyph" aria-hidden="true">&#9432;</span> Role codes are checked during import. Any unrecognized role will fail validation. Ensure <a href="https://canvas-medical.help.usepylon.com/articles/6649603926-staff-roles" target="_blank" rel="noopener">staff roles</a> are added before importing.
      </div>
      <div class="table-wrap">
        <table class="preview-table">
          <colgroup>
            <col style="width:96px"/>
            <col style="width:124px"/>
            <col style="width:50px"/>
            <col style="width:170px"/>
            <col style="width:96px"/>
            <col style="width:114px"/>
            <col style="width:114px"/>
            <col style="width:72px"/>
            <col style="width:222px"/>
          </colgroup>
          <thead>
            <tr>
              <th>Status</th><th>Name</th><th>Role</th><th>Email</th>
              <th>Phone</th><th>NPI</th><th>Location</th><th>Licenses</th><th>Action</th>
            </tr>
          </thead>
          <tbody id="preview-tbody"></tbody>
        </table>
      </div>
      <div class="btn-row" style="margin-top:16px">
        <button class="btn btn-secondary" onclick="goToUpload()">Back</button>
        <button class="btn btn-primary" id="btn-import" onclick="importPractitioners()">
          Import Staff
        </button>
      </div>
      <div id="progress-section" class="hidden" style="margin-top:12px">
        <p id="progress-label" style="font-size:13px;color:#475569">Processing…</p>
        <div class="progress-bar-wrap"><div class="progress-bar" id="progress-bar" style="width:0%"></div></div>
      </div>
    </div>
  </div>

  <!-- STATE 3: Results -->
  <div id="state-results" class="hidden">
    <div class="stats-row">
      <div class="stat-card success"><div class="number" id="res-success">0</div><div class="label">Succeeded</div></div>
      <div class="stat-card error"><div class="number" id="res-error">0</div><div class="label">Errors</div></div>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>Name</th><th>Email</th><th>Status</th><th>Staff Key</th><th>Notes</th></tr>
          </thead>
          <tbody id="results-tbody"></tbody>
        </table>
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="copyStaffKeys()">Copy Staff Keys</button>
        <button class="btn btn-secondary" onclick="downloadResultsCsv()">Download Results CSV</button>
        <button class="btn btn-secondary" onclick="goToUpload()">Import Another File</button>
        <button class="btn btn-primary" onclick="finishAndGoToSchedule()">Done</button>
      </div>
    </div>
  </div>
</div>

<script>
// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const API_BASE = '/plugin-io/api/practitioner_bulk_loader/bulk-upload';

// Attach the file-input change handler programmatically. Canvas's plugin
// iframe strips inline onchange= attributes on <input> elements (but
// allows inline onclick= on <div>), which silently breaks file upload
// when only inline handlers are used.
(function() {
  function wire() {
    const fi = document.getElementById('file-input');
    if (fi) fi.addEventListener('change', onFileSelected);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();

let csvText = '';
let practitionersData = [];  // from parse-and-validate
let resultsData = [];         // from create-practitioners
let conflictRowIds = [];     // indices of rows with field_conflicts (need review)
let expandedConflictRowIds = new Set();  // conflict-row indices already expanded once
let ackedConflictRowIds = new Set();     // conflict-row indices whose in-panel ack has been checked

// ---------------------------------------------------------------------------
// State transitions
// ---------------------------------------------------------------------------
function showState(name) {
  ['state-upload','state-preview','state-results'].forEach(id => {
    document.getElementById(id).classList.toggle('hidden', id !== name);
  });
}

function goToUpload() {
  csvText = '';
  practitionersData = [];
  document.getElementById('file-input').value = '';
  document.getElementById('drop-zone').classList.remove('uploaded');
  document.getElementById('drop-zone-default').classList.remove('hidden');
  document.getElementById('drop-zone-uploaded').classList.add('hidden');
  document.getElementById('upload-error').classList.add('hidden');
  document.getElementById('btn-parse').disabled = true;
  document.getElementById('preview-banners').innerHTML = '';
  document.getElementById('error-tbody').innerHTML = '';
  document.getElementById('preview-tbody').innerHTML = '';
  showState('state-upload');
}

// ---------------------------------------------------------------------------
// Upload / file handling
// ---------------------------------------------------------------------------
function onDragOver(e) { e.preventDefault(); document.getElementById('drop-zone').classList.add('dragover'); }
function onDragLeave(e) { document.getElementById('drop-zone').classList.remove('dragover'); }
function onDrop(e) {
  e.preventDefault();
  document.getElementById('drop-zone').classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  if (file) loadFile(file);
}
function onFileSelected(e) {
  const file = e.target.files[0];
  if (file) loadFile(file);
}

function loadFile(file) {
  if (!file.name.toLowerCase().endsWith('.csv')) {
    showUploadError('Only .csv files are accepted.');
    return;
  }
  const reader = new FileReader();
  reader.onload = function(e) {
    csvText = e.target.result;
    document.getElementById('drop-zone').classList.add('uploaded');
    document.getElementById('drop-zone-default').classList.add('hidden');
    document.getElementById('drop-zone-uploaded').classList.remove('hidden');
    document.getElementById('file-name-display').textContent = file.name;
    document.getElementById('upload-error').classList.add('hidden');
    document.getElementById('btn-parse').disabled = false;
  };
  reader.readAsText(file);
}

function showUploadError(msg) {
  const el = document.getElementById('upload-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Template download
// ---------------------------------------------------------------------------
function downloadTemplate() {
  const a = document.createElement('a');
  a.href = API_BASE + '/template.csv';
  a.download = 'staff-template.csv';
  a.click();
}

// ---------------------------------------------------------------------------
// Parse and validate
// ---------------------------------------------------------------------------
async function parseAndValidate() {
  const btn = document.getElementById('btn-parse');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Validating…';

  try {
    const resp = await fetch(API_BASE + '/parse-and-validate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({csv_text: csvText}),
    });
    if (!resp.ok) {
      // Backend reached but returned an error status (5xx Canvas blip,
      // 4xx malformed body, etc.). Try to extract a useful message from
      // a JSON body; fall back to status text.
      let detail = resp.statusText || ('HTTP ' + resp.status);
      try {
        const errBody = await resp.json();
        if (errBody && errBody.error) detail = errBody.error;
      } catch (_) { /* body wasn't JSON */ }
      throw new Error(detail);
    }
    const data = await resp.json();
    renderPreview(data);
  } catch (err) {
    // Surface failures (network, 5xx, malformed response) instead of
    // letting the promise reject silently. Without this the spinner
    // clears and the button re-enables but the admin sees nothing,
    // stuck on the Upload screen with no indication of what happened.
    // Mirrors the catch in importPractitioners.
    showUploadError('Validation failed: ' + (err.message || String(err)));
  } finally {
    btn.disabled = false;
    btn.textContent = 'Validate & Preview';
  }
}

function renderPreview(data) {
  const { errors = [], warnings = [], practitioners = [] } = data;

  // Build banners
  const bannersEl = document.getElementById('preview-banners');
  bannersEl.innerHTML = '';

  showState('state-preview');

  if (errors.length > 0) {
    bannersEl.innerHTML = `<div class="banner banner-error">${errors.length} row(s) have errors. Please fix and re-upload.</div>`;
    document.getElementById('error-section').classList.remove('hidden');
    document.getElementById('preview-section').classList.add('hidden');

    const tbody = document.getElementById('error-tbody');
    tbody.innerHTML = '';
    errors.forEach(e => {
      const valueCell = (e.value === '' || e.value === null || e.value === undefined)
        ? '<span style="color:#94a3b8;font-style:italic">—</span>'
        : esc(e.value);
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${e.row}</td><td>${esc(e.field)}</td><td>${valueCell}</td><td>${esc(e.message)}</td>`;
      tbody.appendChild(tr);
    });
    return;
  }

  // Validation passed
  document.getElementById('error-section').classList.add('hidden');
  document.getElementById('preview-section').classList.remove('hidden');

  // Reset UI elements that importPractitioners() mutates so a second
  // upload after a successful first import doesn't show a stale
  // hidden Import button and a "Done — N processed." progress bar.
  const btnImport = document.getElementById('btn-import');
  btnImport.classList.remove('hidden');
  document.getElementById('progress-section').classList.add('hidden');
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-label').textContent = 'Processing…';

  const newCount = practitioners.filter(p => p.status === 'new').length;
  const existingCount = practitioners.filter(p => p.status === 'existing').length;
  let bannerHtml = `<div class="banner banner-success"><strong>${practitioners.length}</strong>&nbsp;staff ready · ${newCount} new · ${existingCount} existing</div>`;

  const defaultedNpiCount = practitioners.filter(p => p.npi === '1111155556').length;
  if (defaultedNpiCount > 0) {
    bannerHtml += `<div class="banner banner-info"><strong>${defaultedNpiCount}</strong>&nbsp;row(s) had a blank NPI — defaulted to <code style="font-family:var(--mono)">1111155556</code>. Canvas requires an NPI on every user. You can edit the staff profile after import if a valid NPI exists for the user.</div>`;
  }

  const conflictRows = practitioners.filter(p => (p.field_conflicts || []).length > 0);
  if (conflictRows.length > 0) {
    const totalConflicts = conflictRows.reduce((n, p) => n + p.field_conflicts.length, 0);
    bannerHtml += `<div id="field-conflicts-banner" class="banner banner-error"><div><strong>${totalConflicts}</strong> field conflict${totalConflicts === 1 ? '' : 's'} across <strong>${conflictRows.length}</strong> row${conflictRows.length === 1 ? '' : 's'}. Click any row to view a field-by-field diff. <em>Merge to existing record</em> ignores CSV values; <em>Replace record</em> overwrites them.</div></div>`;
  }

  if (warnings.length > 0) {
    // Build a row-number → practitioner-name lookup so warnings can name
    // the affected user, not just the row number.
    const rowToName = {};
    practitioners.forEach(p => {
      if (p.source_row_number) {
        const name = ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
        if (name) rowToName[p.source_row_number] = name;
      }
    });
    warnings.forEach(w => {
      // row=0 marks an upload-wide warning (no specific row) — surface it
      // without a "Row N" prefix so it reads as a banner statement rather
      // than a row-level annotation.
      if (!w.row) {
        bannerHtml += `<div class="banner banner-warning">${escWithHelpLink(w.message)}</div>`;
        return;
      }
      const name = rowToName[w.row];
      const rowLabel = name ? `Row ${w.row} (${esc(name)})` : `Row ${w.row}`;
      bannerHtml += `<div class="banner banner-warning">${rowLabel}: ${escWithHelpLink(w.message)}</div>`;
    });
  }

  bannersEl.innerHTML = bannerHtml;

  // Reset expanded-conflict-row tracking. The acknowledgment row only
  // appears once the user has expanded EVERY conflict row at least once
  // — the forcing function that "review" actually happened.
  expandedConflictRowIds = new Set();
  ackedConflictRowIds = new Set();
  conflictRowIds = conflictRows.map(p => practitioners.indexOf(p));

  // Update import button label + initial disabled state based on whether ack is needed.
  const btn = document.getElementById('btn-import');
  btn.textContent = `Import ${practitioners.length} Staff`;
  refreshImportButtonState();

  // Build preview table
  practitionersData = practitioners;
  const tbody = document.getElementById('preview-tbody');
  tbody.innerHTML = '';

  practitioners.forEach((p, idx) => {
    const isExisting = p.status === 'existing';
    // Distinguish how the duplicate was detected: email match (default) vs.
    // NPI fallback (caught a same-person-new-email case). The badge and a
    // tooltip help the admin decide Skip vs. Merge for NPI-only matches.
    let statusBadge;
    if (!isExisting) {
      // Name-only match (no email/NPI/DOB hit) is too weak to auto-flag as
      // Existing — surface as "Possible Duplicate" so the admin verifies
      // before clicking Import.
      const dupCount = p.possible_duplicate_count || 0;
      if (dupCount > 0) {
        const noun = dupCount === 1 ? 'user' : 'users';
        statusBadge = `<span class="badge badge-warn" title="${dupCount} existing ${noun} on Canvas with the same name but a different DOB / NPI / email. Verify before creating.">Possible Duplicate</span>`;
      } else {
        statusBadge = '<span class="badge badge-new">New</span>';
      }
    } else if (p.match_reason === 'npi') {
      statusBadge = '<span class="badge badge-error">Existing (by NPI)</span>';
    } else if (p.match_reason === 'name_dob') {
      statusBadge = '<span class="badge badge-error">Existing (by name + DOB)</span>';
    } else {
      statusBadge = '<span class="badge badge-existing">Existing</span>';
    }

    // Build the optional match-warning content for npi / name_dob matches.
    // Rendered as its own full-width row below the data row so it has room
    // to wrap without being clipped by the narrow Status column.
    let matchWarningHtml = '';
    if (p.match_reason === 'npi' || p.match_reason === 'name_dob') {
      const who = (esc(p.existing_first_name || '') + ' ' + esc(p.existing_last_name || '')).trim() || 'a different identity';
      const emailFragment = p.existing_email ? ' (' + esc(p.existing_email) + ')' : '';
      if (p.match_reason === 'npi') {
        // NPI-tier matches commonly fire for "same person, changed email"
        // — that's the case the tier exists for. Distinguish three sub-
        // cases by comparing names and DOB to avoid the self-contradictory
        // "different person" wording when they're actually the same record.
        const namesMatch = (
          (p.first_name || '').trim().toLowerCase() === (p.existing_first_name || '').trim().toLowerCase()
          && (p.last_name || '').trim().toLowerCase() === (p.existing_last_name || '').trim().toLowerCase()
        );
        // Both p.dob and p.existing_dob are sent in ISO YYYY-MM-DD form
        // by the backend (see the ``to_fhir_date`` call in
        // parse-and-validate), so a direct string compare is correct.
        const dobsMatch = (p.dob || '').trim() === (p.existing_dob || '').trim();
        if (namesMatch && dobsMatch) {
          matchWarningHtml = '<div class="match-warning">'
            + '<strong>&#9432; Matched by NPI.</strong> '
            + 'Names and DOB match Canvas record <strong>' + who + '</strong>' + emailFragment + '. '
            + 'Email cannot be updated via CSV import &mdash; '
            + 'to change the email, update it directly in Canvas Staff admin.'
            + '</div>';
        } else if (namesMatch && !dobsMatch) {
          matchWarningHtml = '<div class="match-warning">'
            + '<strong>&#9888; Same name and NPI, different DOB.</strong> '
            + 'Canvas record <strong>' + who + '</strong>' + emailFragment + ' has DOB ' + esc(p.existing_dob || 'unknown') + '; '
            + 'CSV says ' + esc(p.dob || 'unknown') + '. Verify which is correct before merging.'
            + '</div>';
        } else {
          matchWarningHtml = '<div class="match-warning">'
            + '<strong>&#9888; Different person, same NPI.</strong> '
            + 'CSV says ' + esc(p.first_name) + ' ' + esc(p.last_name) + '. '
            + 'Canvas record under this NPI is <strong>' + who + '</strong>' + emailFragment + '. '
            + 'NPIs should be unique per provider &mdash; verify with Canvas Staff admin before merging.'
            + '</div>';
        }
      } else {
        matchWarningHtml = '<div class="match-warning">'
          + '<strong>&#9888; Name+DOB match, different email and NPI.</strong> '
          + 'Canvas record is <strong>' + who + '</strong>' + emailFragment + '. '
          + 'Names can collide &mdash; verify this is the same provider before merging.'
          + '</div>';
      }
    }

    const hasConflicts = (p.field_conflicts || []).length > 0;
    let actionCell;
    if (isExisting) {
      const defaultAction = hasConflicts ? 'skip' : 'merge';
      p._action = p._action || defaultAction;
      const opt = (val, label) =>
        `<option value="${val}" ${p._action === val ? 'selected' : ''}>${label}</option>`;
      // Always show all four merge options. Address-specific actions
      // are still useful even when no address conflict is detected
      // (admin may want to push a CSV address into a record that has
      // none, or replace an existing one that matches.)
      const options =
        opt('skip', 'Skip') +
        opt('merge', 'Merge to existing record') +
        opt('merge_apply', 'Replace record') +
        opt('merge_replace_address', 'Replace address only') +
        opt('merge_apply_additional', 'Add address as additional');
      actionCell = `<select class="action-select" data-idx="${idx}" onchange="updateAction(${idx}, this.value)">${options}</select>`;
    } else {
      actionCell = `<select class="action-select" data-idx="${idx}" onchange="updateAction(${idx}, this.value)">
           <option value="create">Create</option>
           <option value="skip">Skip</option>
         </select>`;
    }

    const licCount = (p.licenses || []).length;
    let licBadge;
    if (licCount === 0) {
      licBadge = '<span style="color:var(--muted-2)">—</span>';
    } else if (isExisting && p.existing_read_failed) {
      // Distinguish a genuine "no merge data to show" from a fetch failure.
      // The total count is still trustworthy (it's the CSV) but the
      // new/renewal split is unknown because Canvas wouldn't return the
      // existing resource. Tooltip explains so the admin can decide
      // whether to proceed or retry the row later.
      const title = `${licCount} in CSV. Couldn't preview merge details — Canvas returned an error reading the existing record.`;
      licBadge = `<span class="badge badge-license-neutral" title="${title}">${licCount} · merge preview unavailable</span>`;
    } else if (isExisting && (p.new_license_count !== null && p.new_license_count !== undefined)) {
      const newCount = p.new_license_count;
      const renewalCount = p.renewal_count || 0;
      const totalActionable = newCount + renewalCount;
      if (renewalCount > 0) {
        const parts = [];
        if (newCount > 0) parts.push(`${newCount} new`);
        parts.push(`${renewalCount} renewal${renewalCount !== 1 ? 's' : ''}`);
        const title = `${licCount} in CSV — ${renewalCount} match an existing license with different dates`;
        licBadge = `<span class="badge badge-license-new" title="${title}">${licCount} · ${parts.join(', ')}</span>`;
      } else if (newCount > 0) {
        const title = `${licCount} in CSV — ${newCount} not yet on the Canvas record`;
        licBadge = `<span class="badge badge-license-neutral" title="${title}">${licCount} · ${newCount} new</span>`;
      } else {
        licBadge = `<span class="badge badge-license-neutral" title="All ${licCount} CSV licenses already on the Canvas record">${licCount} on file</span>`;
      }
    } else {
      licBadge = `<span class="badge badge-license-neutral">${licCount}</span>`;
    }

    // Inline red NPI cell + "existing: X" only fires for real-vs-real
    // mismatches — i.e. the admin typed a real NPI in the CSV that
    // differs from Canvas's value. The asymmetric case (CSV blank or
    // placeholder vs Canvas-has-real-NPI) is surfaced via the conflict
    // badge under the row + the diff panel, so the inline cell stays
    // plain and consistent with other blank-NPI rows where the
    // existing Canvas record also stores the placeholder. Rendering it
    // here in red would imply the admin is asking to overwrite with it,
    // which the backend's write-path guard prevents anyway.
    const csvNpiRaw = (p.npi || '').trim();
    const csvHasRealNpi = csvNpiRaw && csvNpiRaw !== '1111155556';
    const showInlineNpiWarning = p.npi_conflict && p.existing_npi && csvHasRealNpi;
    const npiCell = showInlineNpiWarning
      ? `<div class="npi-conflict-cell">${esc(p.npi)} ⚠</div><div class="npi-conflict-existing">existing: ${esc(p.existing_npi)}</div>`
      : `<span style="font-family:var(--mono);font-size:12px">${esc(p.npi || '—')}</span>`;

    const conflicts = p.field_conflicts || [];
    let conflictPill = '';
    if (conflicts.length > 0) {
      conflictPill = `<span class="conflict-pill" id="pill-${idx}" onclick="event.stopPropagation();toggleExpand(${idx})">⚠ ${conflicts.length} conflict${conflicts.length === 1 ? '' : 's'}<span class="chevron">▼</span></span>`;
    }

    const tr = document.createElement('tr');
    tr.className = 'data-row';
    tr.id = `row-${idx}`;
    if (conflicts.length > 0) {
      tr.onclick = function() { toggleExpand(idx); };
    }
    tr.innerHTML = `
      <td><div style="display:flex;flex-direction:column;gap:4px;align-items:flex-start">${statusBadge}${conflictPill}</div></td>
      <td>${esc(p.first_name)} ${esc(p.last_name)}</td>
      <td>${esc(p.role)}</td>
      <td style="font-size:12px;color:var(--muted)">${esc(p.email)}</td>
      <td style="font-family:var(--mono);font-size:12px">${esc(p.phone)}</td>
      <td>${npiCell}</td>
      <td>${esc(p.primary_practice_location || '—')}</td>
      <td>${licBadge}</td>
      <td onclick="event.stopPropagation()">${actionCell}</td>
    `;
    tbody.appendChild(tr);
    if (matchWarningHtml) {
      const warningTr = document.createElement('tr');
      warningTr.className = 'match-warning-row';
      warningTr.innerHTML = '<td colspan="9">' + matchWarningHtml + '</td>';
      tbody.appendChild(warningTr);
    }
  });
}

function toggleExpand(idx) {
  const dataRow = document.getElementById(`row-${idx}`);
  const pill = document.getElementById(`pill-${idx}`);
  const existing = document.getElementById(`exp-${idx}`);
  if (existing) {
    existing.remove();
    if (pill) pill.classList.remove('open');
    return;
  }
  if (!expandedConflictRowIds.has(idx)) {
    expandedConflictRowIds.add(idx);
  }
  const p = practitionersData[idx];
  const conflicts = p.field_conflicts || [];
  if (conflicts.length === 0) return;
  const expandTr = document.createElement('tr');
  expandTr.className = 'expand-row';
  expandTr.id = `exp-${idx}`;
  expandTr.innerHTML = '<td colspan="9">' + renderDiffPanelInner(idx) + '</td>';
  dataRow.after(expandTr);
  if (pill) pill.classList.add('open');
}

const ADDRESS_FIELDS = ['Address Line 1', 'Address Line 2', 'City', 'State', 'Zip'];

function fieldOutcome(action, field, conflict) {
  // Returns 'applied' | 'ignored' | 'additional' describing what happens
  // to this CSV field value when the row's action runs against Canvas.
  // Email is always 'ignored' — Canvas's FHIR PUT validator rejects email
  // changes, so the backend deliberately never writes email regardless of
  // action. Showing 'applied' here would mislead admins into thinking
  // their CSV email will overwrite the Canvas value.
  if (field === 'Email') return 'ignored';
  // NPI with a blank CSV side is also a no-op: csv_parser substitutes the
  // placeholder for blank cells, and the write path now guards against
  // clobbering the existing real NPI with the placeholder. The diff entry
  // still surfaces so admins see what Canvas has; this just keeps the
  // label honest.
  if (field === 'NPI' && conflict && !conflict.csv) return 'ignored';
  const isAddr = ADDRESS_FIELDS.indexOf(field) >= 0;
  switch (action) {
    case 'merge_apply': return 'applied';
    case 'merge_replace_address': return isAddr ? 'applied' : 'ignored';
    case 'merge_apply_additional': return isAddr ? 'additional' : 'ignored';
    case 'skip':
    case 'merge':
    default: return 'ignored';
  }
}

function outcomeLabel(outcome, side) {
  // side = 'csv' or 'canvas'
  if (outcome === 'applied') return side === 'csv' ? 'updates' : 'overwritten';
  if (outcome === 'additional') return side === 'csv' ? 'added' : 'primary kept';
  return side === 'csv' ? 'ignored' : 'kept';
}

function renderDiffPanelInner(idx) {
  const p = practitionersData[idx];
  const conflicts = p.field_conflicts || [];
  const action = p._action;
  const rows = conflicts.map(function(c) {
    const outcome = fieldOutcome(action, c.field, c);
    const csvLabel = outcomeLabel(outcome, 'csv');
    const canvasLabel = outcomeLabel(outcome, 'canvas');
    return '<tr class="diff-row diff-' + outcome + '">'
      + '<td class="diff-field">' + esc(c.field) + '</td>'
      + '<td class="diff-csv"><span class="diff-value">' + esc(c.csv) + '</span><span class="diff-tag tag-' + outcome + '-csv">' + csvLabel + '</span></td>'
      + '<td class="diff-existing"><span class="diff-value"><span class="diff-arrow">&rarr;</span>' + esc(c.existing) + '</span><span class="diff-tag tag-' + outcome + '-canvas">' + canvasLabel + '</span></td>'
      + '</tr>';
  }).join('');
  const isAcked = ackedConflictRowIds.has(idx);
  return '<div class="diff-panel">'
    + '<div class="diff-panel-header">' + diffHeaderText(action) + '</div>'
    + '<table class="diff-table">'
    +   '<colgroup>'
    +     '<col class="col-field"/>'
    +     '<col class="col-csv"/>'
    +     '<col class="col-existing"/>'
    +   '</colgroup>'
    +   '<thead><tr><th>Field</th><th>CSV</th><th>Canvas</th></tr></thead>'
    +   '<tbody>' + rows + '</tbody>'
    + '</table>'
    + '<label class="ack-row diff-ack-row ' + (isAcked ? 'checked' : '') + '" id="ack-row-' + idx + '">'
    +   '<input type="checkbox" id="ack-' + idx + '" ' + (isAcked ? 'checked' : '') + ' onchange="toggleRowAck(' + idx + ')"/>'
    +   '<span>I have reviewed this conflict and want to proceed.</span>'
    + '</label>'
    + '</div>';
}

function refreshDiffPanelIfOpen(idx) {
  const expandTr = document.getElementById('exp-' + idx);
  if (!expandTr) return;
  const td = expandTr.querySelector('td');
  if (td) td.innerHTML = renderDiffPanelInner(idx);
}

function toggleRowAck(idx) {
  const ack = document.getElementById(`ack-${idx}`);
  const row = document.getElementById(`ack-row-${idx}`);
  if (!ack) return;
  if (ack.checked) {
    ackedConflictRowIds.add(idx);
  } else {
    ackedConflictRowIds.delete(idx);
  }
  if (row) row.classList.toggle('checked', ack.checked);
  refreshImportButtonState();
}

function refreshImportButtonState() {
  const btn = document.getElementById('btn-import');
  if (!btn) return;
  const allAcked = conflictRowIds.every(id => ackedConflictRowIds.has(id));
  btn.disabled = conflictRowIds.length > 0 && !allAcked;
  // Sync the headline conflicts banner colour with the ack state — once
  // every conflict has been reviewed and acked, switch from danger to
  // info styling so the page no longer looks alarming.
  const banner = document.getElementById('field-conflicts-banner');
  if (banner) {
    if (conflictRowIds.length > 0 && allAcked) {
      banner.classList.remove('banner-error');
      banner.classList.add('banner-info');
    } else {
      banner.classList.remove('banner-info');
      banner.classList.add('banner-error');
    }
  }
}

function diffHeaderText(action) {
  switch (action) {
    case 'skip':
      return 'Skip: Row will be left alone. CSV values shown below will have no effect on Canvas.';
    case 'merge_apply':
      return 'Replace record: CSV values shown below will OVERWRITE the existing Canvas values (email cannot change).';
    case 'merge_replace_address':
      return 'Replace address only: Address values shown below will OVERWRITE Canvas. Name, DOB, phone, fax, NPI are kept as-is.';
    case 'merge_apply_additional':
      return 'Add address as additional: CSV address will be added as a second entry; existing primary address and all other fields are kept as-is.';
    case 'merge':
    default:
      return 'Merge to existing record: CSV values shown below will be IGNORED. Switch to <strong>Replace record</strong> in the action column to overwrite Canvas.';
  }
}

function updateAction(idx, value) {
  if (practitionersData[idx]) {
    practitionersData[idx]._action = value;
  }
  // Refresh the diff panel header text and per-row outcome tags if the
  // panel for this row is currently open.
  refreshDiffPanelIfOpen(idx);
}

// ---------------------------------------------------------------------------
// Import
// ---------------------------------------------------------------------------
async function importPractitioners() {
  // Gate: every conflict row must (a) have been expanded at least once
  // (verifying the user saw the diff) and (b) have its in-panel ack
  // checkbox checked.
  if (conflictRowIds.length > 0) {
    const allReviewed = conflictRowIds.every(id => expandedConflictRowIds.has(id));
    if (!allReviewed) {
      alert('Please open each conflicts panel before importing.');
      return;
    }
    const allAcked = conflictRowIds.every(id => ackedConflictRowIds.has(id));
    if (!allAcked) {
      alert('Please check the acknowledgment in every open conflict panel before importing.');
      return;
    }
  }

  // Extra confirmation when Replace record will overwrite an existing NPI.
  // Single-line message (no newlines) to avoid any HTML sanitizer that may
  // have been triggered by multi-line strings in earlier attempts.
  //
  // Skip rows whose CSV NPI is blank or the substituted placeholder — the
  // backend write-path guard preserves the existing NPI in those cases,
  // so warning "X will be overwritten with 1111155556" would lie about
  // what's actually going to happen. The diff panel already discloses
  // that Canvas has an NPI the CSV doesn't.
  var npiNames = [];
  for (var i = 0; i < practitionersData.length; i++) {
    var p = practitionersData[i];
    var csvNpi = (p.npi || '').trim();
    var csvWritesRealNpi = csvNpi && csvNpi !== '1111155556';
    if (p._action === 'merge_apply' && p.npi_conflict && p.existing_npi && csvWritesRealNpi) {
      npiNames.push(p.first_name + ' ' + p.last_name + ' (' + p.existing_npi + ' to ' + p.npi + ')');
    }
  }
  if (npiNames.length > 0) {
    var msg = 'You are about to overwrite the NPI for: ' + npiNames.join('; ') + '. Continue?';
    if (!confirm(msg)) return;
  }

  const btn = document.getElementById('btn-import');
  btn.classList.add('hidden');
  const progressSection = document.getElementById('progress-section');
  progressSection.classList.remove('hidden');

  // Resolve each row's action. Both dropdowns are now actionable, so
  // ``_action`` (set by updateAction when the user picks a value) wins
  // when present. The fallback default matches the option shown first
  // in the dropdown: 'create' for new rows, 'skip' for existing rows.
  const payload = practitionersData.map(p => ({
    ...p,
    action: p._action || (p.status === 'new' ? 'create' : 'skip'),
  }));

  const total = payload.length;
  let done = 0;

  function updateProgress(msg) {
    document.getElementById('progress-label').textContent = msg;
    document.getElementById('progress-bar').style.width = ((done / total) * 100) + '%';
  }

  updateProgress(`Processing 0 of ${total}…`);

  try {
    const resp = await fetch(API_BASE + '/create-practitioners', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({practitioners: payload}),
    });
    const data = await resp.json();

    done = total;
    updateProgress(`Done — ${total} processed.`);

    setTimeout(() => renderResults(data.results || [], payload), 400);
  } catch (err) {
    document.getElementById('progress-label').textContent = 'Error: ' + err.message;
    btn.classList.remove('hidden');
  }
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------
function renderResults(results, originalPayload) {
  resultsData = results;

  const successCount = results.filter(r => ['created','merged','skipped'].includes(r.status)).length;
  const errorCount = results.filter(r => r.status === 'error').length;

  document.getElementById('res-success').textContent = successCount;
  document.getElementById('res-error').textContent = errorCount;

  const tbody = document.getElementById('results-tbody');
  tbody.innerHTML = '';

  results.forEach((r, idx) => {
    const prac = originalPayload[idx] || {};
    const statusClass = {
      created: 'badge-created', merged: 'badge-merged',
      skipped: 'badge-skipped', error: 'badge-error',
    }[r.status] || 'badge-skipped';

    // Prefer the name the server echoes back (present on both success and error rows).
    // Fall back to the original payload so old server versions still render.
    const firstName = r.first_name || prac.first_name || '';
    const lastName = r.last_name || prac.last_name || '';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${r.row || idx + 1}</td>
      <td>${esc((firstName + ' ' + lastName).trim())}</td>
      <td>${esc(r.email)}</td>
      <td><span class="badge ${statusClass}">${r.status}</span></td>
      <td class="staff-key-cell">${esc(r.staff_key || '—')}</td>
      <td style="color:#64748b">${escWithHelpLink(r.message || '')}</td>
    `;
    tbody.appendChild(tr);
  });

  showState('state-results');
}

// ---------------------------------------------------------------------------
// Clipboard / Download
// ---------------------------------------------------------------------------
function csvField(value) {
  // RFC 4180 escape — quote when the value contains comma, quote, or newline.
  const s = String(value == null ? '' : value);
  if (s.includes(',') || s.includes('"') || s.includes('\\n') || s.includes('\\r')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function finishAndGoToSchedule() {
  // Done means "leave the loader" — navigate to the Canvas Schedule view.
  // Use a relative path so we stay on the customer's instance origin.
  // Try window.top first in case the modal is rendered inside an iframe;
  // fall back to window if cross-origin policy blocks the top access.
  try {
    window.top.location.href = '/schedule/';
  } catch (e) {
    window.location.href = '/schedule/';
  }
}

function copyStaffKeys() {
  const lines = ['name,email,staff_key'];
  resultsData.forEach(r => {
    if (!r.staff_key) return;
    const name = ((r.first_name || '') + ' ' + (r.last_name || '')).trim();
    lines.push([csvField(name), csvField(r.email), csvField(r.staff_key)].join(','));
  });
  navigator.clipboard.writeText(lines.join('\\n')).then(() => {
    alert('Staff keys copied to clipboard.');
  });
}

function downloadResultsCsv() {
  const lines = ['row,name,email,status,staff_key,notes'];
  resultsData.forEach(r => {
    const name = ((r.first_name || '') + ' ' + (r.last_name || '')).trim();
    lines.push([
      csvField(r.row),
      csvField(name),
      csvField(r.email),
      csvField(r.status),
      csvField(r.staff_key || ''),
      csvField(r.message || ''),
    ].join(','));
  });
  const blob = new Blob([lines.join('\\n')], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bulk-upload-results.csv';
  a.click();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// Escape a string and then swap our known help URLs for <a> tags.
// Only our own canvas-medical help URLs are linkified — arbitrary URLs in
// Canvas error text are left as plain text.
const STAFF_ROLES_HELP_URL = 'https://canvas-medical.help.usepylon.com/articles/6649603926-staff-roles';
function escWithHelpLink(str) {
  const escaped = esc(str);
  // The URL contains no HTML-special chars so esc() leaves it intact.
  return escaped.split(STAFF_ROLES_HELP_URL).join(
    `<a href="${STAFF_ROLES_HELP_URL}" target="_blank" rel="noopener">Staff Roles help</a>`
  );
}
</script>
</body>
</html>
"""


class PractitionerBulkLoaderApp(Application):
    """
    Application handler for the Practitioner Bulk Loader.

    Opens a full-page modal (LaunchModalEffect.TargetType.PAGE) so staff
    admins have a clear, uncluttered workspace for bulk data entry.
    No patient context is required — this is a global utility.
    """

    def on_open(self) -> Effect:
        """Render the bulk loader UI inline in a PAGE modal."""
        return LaunchModalEffect(
            content=_APP_HTML,
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
