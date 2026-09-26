"""Mock LLM responses for testing visit-summaries flows without API keys."""
from __future__ import annotations


def mock_previous_visit(note_context: str) -> str:
    """Return mock HTML for previous visit summary."""
    return """
<div class="summary-section">
  <h3>Chief Complaint</h3>
  <p>Follow-up visit for chronic condition management.</p>
</div>
<div class="summary-section">
  <h3>Key Diagnoses Assessed</h3>
  <ul>
    <li><strong>J06.9</strong> - Acute upper respiratory infection: Patient reports improvement.</li>
    <li><strong>R10.9</strong> - Unspecified abdominal pain: Resolved, no further workup needed.</li>
  </ul>
</div>
<div class="summary-section vitals-section">
  <h3>Vitals Snapshot</h3>
  <div class="vitals-grid">
    <div class="vital-item"><div class="vital-label">BP</div><div class="vital-value">128/82</div></div>
    <div class="vital-item"><div class="vital-label">HR</div><div class="vital-value">74</div></div>
    <div class="vital-item"><div class="vital-label">SpO2</div><div class="vital-value">98%</div></div>
    <div class="vital-item"><div class="vital-label">Temp</div><div class="vital-value">98.4 F</div></div>
    <div class="vital-item"><div class="vital-label">Weight</div><div class="vital-value">165 lbs</div></div>
    <div class="vital-item"><div class="vital-label">BMI</div><div class="vital-value">24.5</div></div>
  </div>
</div>
<p style="margin-top:16px;font-size:11px;color:#9ca3af;font-style:italic;">Mock data — set LLM_PROVIDER to a real provider for AI-generated summaries.</p>
"""


def mock_since_last_visit(interim_context: str) -> str:
    """Return mock HTML for since-last-visit summary."""
    return """
<div class="interim-header">
  <p>Interim activity since your last visit.</p>
</div>
<div class="summary-section">
  <h3>Lab Results</h3>
  <table>
    <tr><th>Test</th><th>Value</th><th>Reference</th><th>Flag</th></tr>
    <tr><td>HbA1c</td><td>6.8%</td><td>&lt; 5.7%</td><td style="color:#be123c;">[H]</td></tr>
    <tr><td>TSH</td><td>2.1 mIU/L</td><td>0.4 - 4.0</td><td></td></tr>
    <tr><td>Lipid Panel - LDL</td><td>142 mg/dL</td><td>&lt; 100</td><td style="color:#be123c;">[H]</td></tr>
  </table>
</div>
<div class="trend-alert">HbA1c trending up from 6.5% to 6.8% over last 3 months.</div>
<div class="summary-section">
  <h3>Medication Changes</h3>
  <ul>
    <li><strong>Metformin 500mg</strong> — dose increased to 1000mg BID</li>
    <li><strong>Atorvastatin 20mg</strong> — newly started</li>
  </ul>
</div>
<div class="summary-section">
  <h3>New Diagnoses</h3>
  <p class="no-data">None.</p>
</div>
<div class="summary-section">
  <h3>Completed Care Tasks</h3>
  <ul>
    <li>Annual wellness labs completed</li>
    <li>Diabetic eye exam referral sent</li>
  </ul>
</div>
<div class="summary-section">
  <h3>Other Encounters</h3>
  <ul>
    <li>Telehealth follow-up with Dr. Smith on Feb 28, 2026</li>
  </ul>
</div>
<p style="margin-top:16px;font-size:11px;color:#9ca3af;font-style:italic;">Mock data — set LLM_PROVIDER to a real provider for AI-generated summaries.</p>
"""


def mock_avs(patient_info: dict) -> str:
    """Return mock HTML for After Visit Summary."""
    first_name = patient_info.get("first_name", "Patient")
    visit_date = patient_info.get("visit_date", "today")
    return f"""
<div class="avs-greeting">
  <p>Hi {first_name},</p>
  <p>Thank you for visiting us on {visit_date}. Here is a summary of your visit.</p>
</div>
<div class="avs-section">
  <h3>What We Discussed Today</h3>
  <p>We talked about how you have been feeling and reviewed your current health. We checked your blood pressure and weight, and discussed your medications.</p>
</div>
<div class="avs-section">
  <h3>Your Medications</h3>
  <ul>
    <li><strong>Metformin 1000mg</strong>: Take one tablet twice a day with meals. <span class="med-badge increased">INCREASED</span></li>
    <li><strong>Atorvastatin 20mg</strong>: Take one tablet at bedtime. <span class="med-badge new">NEW</span></li>
    <li><strong>Lisinopril 10mg</strong>: Take one tablet every morning. No changes.</li>
  </ul>
</div>
<div class="avs-section">
  <h3>Next Steps</h3>
  <ul>
    <li>Follow-up appointment in 3 months</li>
    <li>Repeat blood work (HbA1c, lipid panel) in 3 months</li>
    <li>Referral to ophthalmology for annual diabetic eye exam</li>
  </ul>
</div>
<div class="avs-section avs-warning">
  <h3>When to Seek Care</h3>
  <p>Go to the emergency room or call 911 if you experience:</p>
  <ul>
    <li>Chest pain or trouble breathing</li>
    <li>Sudden severe headache or confusion</li>
    <li>Signs of low blood sugar: shaking, sweating, fast heartbeat, dizziness</li>
  </ul>
</div>
<div class="avs-section">
  <h3>Questions?</h3>
  <p>Please contact our office if you have any questions about your care.</p>
</div>
<p style="margin-top:16px;font-size:11px;color:#9ca3af;font-style:italic;">Mock data — set LLM_PROVIDER to a real provider for AI-generated summaries.</p>
"""
