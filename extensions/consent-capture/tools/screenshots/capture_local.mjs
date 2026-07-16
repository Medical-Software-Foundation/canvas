// Local-render capture: screenshot every picker state from the plugin's own
// templates/picker.html with mock data. Deterministic, no login, no PHI.
//
//   node tools/screenshots/capture_local.mjs
//
// Output PNGs -> consent_capture/screenshots/. These are faithful to the real UI
// (same template) but use sample data, so guide captions mark them as examples.
import { chromium } from 'playwright';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { renderPickerHtml } from './render_picker.mjs';
import { ensureDirs, ensureSampleForm, shotPath, SAMPLE_FORM, log, ok } from './lib.mjs';

const TMP_HTML = resolve(tmpdir(), 'consent_picker_preview.html');

// Screenshot the currently-active .view as a clean, modal-like image.
async function shotActiveView(page, name) {
  const view = page.locator('.view.active').first();
  await view.screenshot({ path: shotPath(name) });
  ok(name);
}

async function run() {
  ensureDirs();
  renderPickerHtml(TMP_HTML);
  log('rendered picker ->', TMP_HTML);

  const browser = await chromium.launch({
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
  });
  const page = await browser.newPage({ viewport: { width: 760, height: 940 }, deviceScaleFactor: 2 });
  page.on('console', (m) => { if (m.type() === 'error') log('page error:', m.text()); });

  await ensureSampleForm(page);
  await page.goto('file://' + TMP_HTML, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => typeof window.renderHub === 'function');
  await page.waitForTimeout(300);

  // ---- Hub: Required (Needed + Renew) --------------------------------------
  await page.evaluate(() => { window.show('hub'); window.renderHub(); });
  await page.waitForTimeout(150);
  await shotActiveView(page, '04-hub-required.png');

  // ---- Hub: everything expanded (Optional + On File on file/Expired) --------
  await page.evaluate(() => {
    document.querySelectorAll('.section.collapsed').forEach((s) => s.classList.remove('collapsed'));
  });
  await page.waitForTimeout(150);
  await shotActiveView(page, '05-hub-onfile.png');

  // ---- Wizard: Review (Treatment Consent, index 0) --------------------------
  await page.evaluate(() => window.startWizard(0));
  await page.waitForTimeout(200);
  await shotActiveView(page, '06-review.png');

  // ---- Wizard: Finalize (method + who + questions + date) -------------------
  await page.evaluate(() => document.getElementById('nextBtn').click());
  await page.waitForTimeout(200);
  await shotActiveView(page, '07-finalize.png');

  // ---- Wizard: Finalize with Representative selected ------------------------
  await page.evaluate(() => {
    const r = document.querySelector('input[name="who"][value="representative"]');
    if (r) { r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); }
    const rep = document.querySelector('.rep');
    if (rep) {
      const [name, rel] = rep.querySelectorAll('input');
      if (name) { name.value = 'Jamie Rivera'; name.dispatchEvent(new Event('input', { bubbles: true })); }
      if (rel) { rel.value = 'Spouse (healthcare proxy)'; rel.dispatchEvent(new Event('input', { bubbles: true })); }
    }
  });
  await page.waitForTimeout(150);
  await shotActiveView(page, '08-finalize-representative.png');

  // ---- Done screen ----------------------------------------------------------
  await page.evaluate(() => {
    document.getElementById('doneSub').textContent = 'Treatment Consent was added to Jordan Rivera’s profile.';
    window.show('done');
  });
  await page.waitForTimeout(150);
  await shotActiveView(page, '09-done.png');

  // ---- Written capture: Camera tab -----------------------------------------
  await page.evaluate(() => window.startWizard(3));            // Written-only consent
  await page.waitForTimeout(150);
  await page.evaluate(() => document.getElementById('nextBtn').click());  // review -> confirm
  await page.waitForTimeout(150);
  await page.evaluate(() => document.getElementById('nextBtn').click());  // confirm -> openCapture()
  await page.waitForTimeout(600);
  // Chromium's fake camera renders a green test pattern; swap it for the sample
  // document so the viewfinder looks like a real page being framed.
  const sampleDataUrl = 'data:image/png;base64,' + readFileSync(SAMPLE_FORM).toString('base64');
  await page.evaluate((src) => {
    const vf = document.querySelector('#panCamera .vf');
    const v = document.getElementById('camVideo');
    if (v) v.style.display = 'none';
    if (vf) {
      const img = document.createElement('img');
      img.src = src;
      img.style.cssText = 'width:100%;height:100%;object-fit:cover;object-position:top center;';
      vf.insertBefore(img, vf.firstChild);
    }
  }, sampleDataUrl);
  await page.waitForTimeout(250);
  await shotActiveView(page, '10-written-camera.png');

  // ---- Written capture: Upload the sample form -> Review --------------------
  await page.evaluate(() => document.getElementById('tabUpload').click());
  await page.waitForTimeout(150);
  await page.setInputFiles('#fileInput', SAMPLE_FORM);
  await page.waitForTimeout(500);
  await shotActiveView(page, '11-written-review.png');

  // ---- Written capture: Crop -----------------------------------------------
  await page.evaluate(() => document.getElementById('cropBtn').click());
  await page.waitForTimeout(700);
  await shotActiveView(page, '12-written-crop.png');

  // ---- Written capture: Pages list -----------------------------------------
  await page.evaluate(() => document.getElementById('capRight').click());   // Apply -> review
  await page.waitForTimeout(400);
  await page.evaluate(() => document.getElementById('capRight').click());   // Add Page -> pages
  await page.waitForTimeout(400);
  await shotActiveView(page, '13-written-pages.png');

  // ---- Viewer: a completed consent's document ------------------------------
  // Headless Chromium won't render a PDF inside the iframe, so we load an HTML
  // page that mirrors the generated consent PDF (pdf.py) — same look, renders reliably.
  await page.evaluate(() => {
    const docHtml = `<!DOCTYPE html><html><head><meta charset='utf-8'><style>
      body{margin:0;background:#fff;color:#1f2933;font-family:Georgia,'Times New Roman',serif;padding:48px 56px;line-height:1.5;}
      h1{font-size:22px;margin:0 0 4px;} .meta{color:#6b7280;font-size:13px;margin:0 0 22px;font-family:-apple-system,Arial,sans-serif;}
      hr{border:0;border-top:1px solid #e5e7eb;margin:18px 0;}
      .lab{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6b7280;font-family:-apple-system,Arial,sans-serif;margin:0 0 6px;}
      p{font-size:14px;margin:0 0 12px;} .row{display:flex;gap:40px;margin-bottom:16px;}
      .foot{position:fixed;bottom:22px;left:56px;right:56px;color:#9aa4b2;font-size:11px;font-family:-apple-system,Arial,sans-serif;border-top:1px solid #eee;padding-top:8px;display:flex;justify-content:space-between;}
    </style></head><body>
      <h1>Treatment Consent</h1>
      <p class='meta'>Patient Consent Record</p>
      <div class='row'>
        <div><div class='lab'>Patient</div>Jordan Rivera</div>
        <div><div class='lab'>Date of birth</div>1984-02-19</div>
        <div><div class='lab'>Recorded</div>2025-03-12</div>
      </div>
      <hr>
      <div class='lab'>Consent statement</div>
      <p>I authorize my care team to provide the treatment, services, and procedures they determine to be reasonable and necessary for my care.</p>
      <p>I understand that no guarantee has been made about the results of any treatment, and that I may withdraw this consent at any time.</p>
      <div class='lab'>How consent was obtained</div><p>Verbal · Consent given by Patient</p>
      <div class='lab'>Questions &amp; responses</div>
      <p>Do you consent to treatment as described above? — <strong>Yes</strong><br>Have your questions been answered to your satisfaction? — <strong>Yes</strong></p>
      <div class='foot'><span>Collected by Dr. Alex Morgan</span><span>Confidential · Patient Health Information</span></div>
    </body></html>`;
    document.getElementById('viewerTitle').textContent = 'Treatment Consent';
    document.getElementById('viewerSub').textContent = 'Recorded document · Mar 12, 2025';
    document.getElementById('viewerMsg').textContent = '';
    document.getElementById('pdfFrame').src = 'data:text/html;charset=utf-8,' + encodeURIComponent(docHtml);
    window.show('viewer');
  });
  await page.waitForTimeout(600);
  await shotActiveView(page, '14-viewer.png');

  await browser.close();
  log('local capture complete ->', shotPath(''));
}

run().catch((e) => { console.error(e); process.exit(1); });
