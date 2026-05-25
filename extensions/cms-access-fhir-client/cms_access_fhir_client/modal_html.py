"""HTML templates for the three ACCESS chart-button modals.

Embedded directly via LaunchModalEffect(content=...) so the modal doesn't
need to fetch a separate URL (which had auth/iframe-cookie issues).

Each template expects a single ``patient_id`` substitution via ``.format()``.
The form-submission scripts POST to /plugin-io/api/cms_access_fhir_client/<op>
with the staff session cookie (same-origin), which is gated by StaffSessionAuthMixin.
"""

ELIGIBILITY_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         padding: 24px; max-width: 480px; margin: auto; }}
  h2 {{ margin-bottom: 16px; }}
  .result {{ margin-top: 16px; padding: 12px; border-radius: 4px; }}
  .ok {{ background: #dcfce7; color: #16a34a; }}
  .err {{ background: #fee2e2; color: #dc2626; }}
  button {{ padding: 8px 16px; background: #2563eb; color: white;
            border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
  button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
</style>
</head>
<body>
  <h2>Check ACCESS Eligibility</h2>
  <p>Patient ID: <code>{patient_id}</code></p>
  <button id="btn" onclick="checkEligibility()">Check Eligibility</button>
  <div id="result"></div>
  <script>
    async function checkEligibility() {{
      const btn = document.getElementById('btn');
      const result = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Checking...';
      try {{
        const resp = await fetch('/plugin-io/api/cms_access_fhir_client/eligibility', {{
          method: 'POST',
          credentials: 'include',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{patient_id: '{patient_id}'}})
        }});
        const data = await resp.json();
        result.className = 'result ' + (resp.ok ? 'ok' : 'err');
        result.textContent = resp.ok
          ? 'Status: ' + data.status
          : 'Error: ' + (data.error || resp.status);
      }} catch (e) {{
        result.className = 'result err';
        result.textContent = 'Request failed: ' + e.message;
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Check Eligibility';
      }}
    }}
  </script>
</body></html>"""

ALIGN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         padding: 24px; max-width: 480px; margin: auto; }}
  h2 {{ margin-bottom: 16px; }}
  label {{ display: block; margin-bottom: 4px; font-weight: 500; }}
  select, textarea {{ width: 100%; margin-bottom: 12px; padding: 6px;
                      border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }}
  textarea {{ height: 80px; resize: vertical; }}
  .result {{ margin-top: 16px; padding: 12px; border-radius: 4px; }}
  .ok {{ background: #dcfce7; color: #16a34a; }}
  .err {{ background: #fee2e2; color: #dc2626; }}
  button {{ padding: 8px 16px; background: #16a34a; color: white;
            border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
  button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
</style>
</head>
<body>
  <h2>Enroll in ACCESS</h2>
  <form id="form" onsubmit="submitAlign(event)">
    <label for="track">Track</label>
    <select id="track" required>
      <option value="">Select track...</option>
      <option value="eCKM">eCKM &mdash; Enhanced Kidney Care Model</option>
      <option value="CKM">CKM &mdash; Kidney Care Model</option>
      <option value="MSK">MSK &mdash; Musculoskeletal</option>
      <option value="BH">BH &mdash; Behavioral Health</option>
    </select>
    <label for="justification">Clinical Justification</label>
    <textarea id="justification" required placeholder="Enter clinical justification..."></textarea>
    <button type="submit" id="btn">Submit Enrollment</button>
  </form>
  <div id="result"></div>
  <script>
    async function submitAlign(e) {{
      e.preventDefault();
      const btn = document.getElementById('btn');
      const result = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Submitting...';
      try {{
        const resp = await fetch('/plugin-io/api/cms_access_fhir_client/align', {{
          method: 'POST',
          credentials: 'include',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            patient_id: '{patient_id}',
            track: document.getElementById('track').value,
            clinical_justification: document.getElementById('justification').value,
          }})
        }});
        const data = await resp.json();
        result.className = 'result ' + (resp.ok ? 'ok' : 'err');
        result.textContent = resp.ok
          ? 'Enrollment submitted. Status: ' + data.status
          : 'Error: ' + (data.error || resp.status);
      }} catch (e) {{
        result.className = 'result err';
        result.textContent = 'Request failed: ' + e.message;
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Submit Enrollment';
      }}
    }}
  </script>
</body></html>"""

UNALIGN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         padding: 24px; max-width: 480px; margin: auto; }}
  h2 {{ margin-bottom: 16px; }}
  label {{ display: block; margin-bottom: 4px; font-weight: 500; }}
  select {{ width: 100%; margin-bottom: 12px; padding: 6px;
            border: 1px solid #d1d5db; border-radius: 4px; font-size: 14px; }}
  .result {{ margin-top: 16px; padding: 12px; border-radius: 4px; }}
  .ok {{ background: #dcfce7; color: #16a34a; }}
  .err {{ background: #fee2e2; color: #dc2626; }}
  button {{ padding: 8px 16px; background: #dc2626; color: white;
            border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
  button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
</style>
</head>
<body>
  <h2>Unalign from ACCESS</h2>
  <form id="form" onsubmit="submitUnalign(event)">
    <label for="reason">Reason for Unalignment</label>
    <select id="reason" required>
      <option value="">Select reason...</option>
      <option value="patient-request">Patient Request</option>
      <option value="provider-decision">Provider Decision</option>
      <option value="care-completed">Care Completed</option>
      <option value="other">Other</option>
    </select>
    <button type="submit" id="btn">Submit Unalignment</button>
  </form>
  <div id="result"></div>
  <script>
    async function submitUnalign(e) {{
      e.preventDefault();
      const btn = document.getElementById('btn');
      const result = document.getElementById('result');
      btn.disabled = true;
      btn.textContent = 'Submitting...';
      try {{
        const resp = await fetch('/plugin-io/api/cms_access_fhir_client/unalign', {{
          method: 'POST',
          credentials: 'include',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            patient_id: '{patient_id}',
            reason_code: document.getElementById('reason').value,
          }})
        }});
        const data = await resp.json();
        result.className = 'result ' + (resp.ok ? 'ok' : 'err');
        result.textContent = resp.ok
          ? 'Unalignment submitted.'
          : 'Error: ' + (data.error || resp.status);
      }} catch (e) {{
        result.className = 'result err';
        result.textContent = 'Request failed: ' + e.message;
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Submit Unalignment';
      }}
    }}
  </script>
</body></html>"""
