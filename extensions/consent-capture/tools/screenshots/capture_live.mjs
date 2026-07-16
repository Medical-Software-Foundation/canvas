// Live capture on the sanctioned playground test patient. Headed Chromium with a
// PERSISTENT profile, so you log in once (SSO) and later runs reuse the session.
//
//   node tools/screenshots/capture_live.mjs
//
// A window opens. Log in if prompted and land on the patient chart. The script polls
// until the chart URL is loaded, then captures the shots that only the live instance
// can provide (entry points + admin pages) and attempts the in-chart modal.
//
// Every shot is wrapped in try/catch: a failure logs and moves on, so one bad
// selector never aborts the run. Re-run freely — the login persists.
import { chromium } from 'playwright';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import { ensureDirs, ensureSampleForm, shotPath, SAMPLE_FORM, log, ok, skip } from './lib.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const USER_DATA = resolve(HERE, '.auth');        // persistent login profile (gitignored)
const HOST = 'https://scribeqa-playground.canvasmedical.com';
const PATIENT = '65a4fbf85aae48e2a1a1dbf8c1035264';
const CHART_URL = `${HOST}/patient/${PATIENT}`;
const SETTINGS_URL = `${HOST}/plugin-io/api/consent_capture/admin/settings`;
const BANNERS_URL = `${HOST}/plugin-io/api/consent_capture/admin/banners`;
const LOGIN_TIMEOUT_MS = 4 * 60 * 1000;

async function shot(page, name, fn) {
  try { await fn(); ok(name); }
  catch (e) { skip(name, (e && e.message ? e.message : String(e)).slice(0, 120)); }
}

// Poll until we're on the patient chart (not an auth/login redirect) and it settled.
async function waitForChart(page) {
  log('Opening the chart. LOG IN if prompted — waiting up to 4 minutes...');
  await page.goto(CHART_URL, { waitUntil: 'domcontentloaded' }).catch(() => {});
  const deadline = Date.now() + LOGIN_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const url = page.url();
    const onChart = /\/patient\//.test(url) && !/login|auth|signin|accounts\./i.test(url);
    if (onChart) {
      // Give the SPA a moment; treat "body has substantial content" as loaded.
      const ready = await page.evaluate(() => document.body && document.body.innerText.length > 200).catch(() => false);
      if (ready) { await page.waitForTimeout(2500); log('Chart detected:', url); return true; }
    }
    await page.waitForTimeout(1500);
  }
  throw new Error('timed out waiting for the chart / login');
}

// Find the plugin iframe (picker modal) by URL substring; returns a Frame or null.
function pluginFrame(page) {
  return page.frames().find((f) => /consent_capture/.test(f.url())) || null;
}
async function waitForPluginFrame(page, ms = 15000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    const f = pluginFrame(page);
    if (f) return f;
    await page.waitForTimeout(500);
  }
  return null;
}

async function run() {
  ensureDirs();
  const ctx = await chromium.launchPersistentContext(USER_DATA, {
    headless: false,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  await ensureSampleForm(page).catch(() => {});

  await waitForChart(page);

  // ---- 01 chart button + 03 banner: capture the full chart, then try to crop --
  await shot(page, '01-chart-full.png', async () => {
    await page.screenshot({ path: shotPath('01-chart-full.png') });
  });
  // Best-effort element crops (selectors may need tuning once we see the full shot).
  await shot(page, '01-chart-button.png', async () => {
    const btn = page.getByRole('button', { name: /consents/i }).first();
    await btn.waitFor({ state: 'visible', timeout: 5000 });
    await btn.screenshot({ path: shotPath('01-chart-button.png') });
  });
  await shot(page, '03-banner.png', async () => {
    const banner = page.getByText(/required consent not on file/i).first();
    await banner.waitFor({ state: 'visible', timeout: 5000 });
    await banner.screenshot({ path: shotPath('03-banner.png') });
  });

  // ---- Live modal (bonus; written to *-live-* so it never clobbers the richer
  //      local hub shots the guides use). Open via the red button or app drawer. ---
  await shot(page, '04-live-hub.png', async () => {
    await page.getByRole('button', { name: /consents/i }).first().click({ timeout: 5000 });
    const frame = await waitForPluginFrame(page, 15000);
    if (!frame) throw new Error('plugin iframe not found; frames=' + page.frames().map((f) => f.url()).join(' | '));
    await frame.locator('#hubView').waitFor({ state: 'visible', timeout: 8000 });
    await page.waitForTimeout(800);
    await frame.locator('#hubView').screenshot({ path: shotPath('04-live-hub.png') });
    await frame.evaluate(() => document.querySelectorAll('.section.collapsed').forEach((s) => s.classList.remove('collapsed')));
    await page.waitForTimeout(400);
    await frame.locator('#hubView').screenshot({ path: shotPath('05-live-hub-onfile.png') });
    ok('05-live-hub-onfile.png');
  });

  // ---- 20 Consent Settings ---------------------------------------------------
  await shot(page, '20-consent-settings.png', async () => {
    await page.goto(SETTINGS_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1200);
    await page.screenshot({ path: shotPath('20-consent-settings.png'), fullPage: false });
  });

  // ---- 21 Refresh Consent Banners --------------------------------------------
  await shot(page, '21-refresh-banners.png', async () => {
    await page.goto(BANNERS_URL, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: shotPath('21-refresh-banners.png'), fullPage: false });
  });

  log('Live pass done. Review consent_capture/screenshots/. Leaving the browser open for 20s.');
  await page.waitForTimeout(20000);
  await ctx.close();
}

run().catch((e) => { console.error(e); process.exit(1); });
