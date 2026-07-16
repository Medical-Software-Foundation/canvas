// Shared helpers for the screenshot scripts.
import { mkdirSync, existsSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO = resolve(HERE, '..', '..');
export const OUT_DIR = resolve(REPO, 'docs', 'screenshots');
export const ASSET_DIR = resolve(HERE, 'assets');
export const SAMPLE_FORM = resolve(ASSET_DIR, 'sample-consent-form.png');

export function ensureDirs() {
  mkdirSync(OUT_DIR, { recursive: true });
  mkdirSync(ASSET_DIR, { recursive: true });
}

export function shotPath(name) {
  return resolve(OUT_DIR, name);
}

// A plain, faux "signed consent form" image (no PHI) for the Written/Upload path.
// Drawn once with a canvas so the Written review/crop/pages screens show a real-looking
// document rather than a camera test pattern.
export async function ensureSampleForm(page) {
  if (existsSync(SAMPLE_FORM)) return SAMPLE_FORM;
  const dataUrl = await page.evaluate(() => {
    const c = document.createElement('canvas');
    c.width = 850; c.height = 1100;
    const x = c.getContext('2d');
    x.fillStyle = '#ffffff'; x.fillRect(0, 0, c.width, c.height);
    x.strokeStyle = '#d0d0d0'; x.lineWidth = 2; x.strokeRect(40, 40, c.width - 80, c.height - 80);
    x.fillStyle = '#111827'; x.font = 'bold 34px Georgia, serif';
    x.fillText('Financial Responsibility Agreement', 70, 120);
    x.strokeStyle = '#e5e7eb'; x.beginPath(); x.moveTo(70, 140); x.lineTo(780, 140); x.stroke();
    x.fillStyle = '#374151'; x.font = '18px Georgia, serif';
    const lines = [
      'I understand that I am financially responsible for all charges',
      'whether or not they are covered by insurance. I authorize the',
      'release of any medical information necessary to process claims,',
      'and I assign benefits to the provider named above.',
      '',
      'I have read and understand this agreement, and I accept its terms.',
    ];
    let y = 200; lines.forEach((l) => { x.fillText(l, 70, y); y += 34; });
    // Signature block
    y = 900;
    x.strokeStyle = '#111827'; x.lineWidth = 1.5;
    x.beginPath(); x.moveTo(70, y); x.lineTo(430, y); x.stroke();
    x.beginPath(); x.moveTo(500, y); x.lineTo(760, y); x.stroke();
    x.fillStyle = '#6b7280'; x.font = '15px Georgia, serif';
    x.fillText('Patient signature', 70, y + 26);
    x.fillText('Date', 500, y + 26);
    // A scrawled "signature"
    x.strokeStyle = '#1d4ed8'; x.lineWidth = 2.5; x.beginPath();
    x.moveTo(90, y - 12); x.bezierCurveTo(150, y - 60, 210, y + 30, 260, y - 20);
    x.bezierCurveTo(300, y - 50, 340, y + 10, 400, y - 30); x.stroke();
    x.fillStyle = '#111827'; x.font = '18px Georgia, serif'; x.fillText('06 / 20 / 2025', 520, y - 8);
    return c.toDataURL('image/png');
  });
  const b64 = dataUrl.split(',')[1];
  writeFileSync(SAMPLE_FORM, Buffer.from(b64, 'base64'));
  return SAMPLE_FORM;
}

export function log(...a) { console.log('[shots]', ...a); }
export function ok(name) { console.log('  ✓', name); }
export function skip(name, why) { console.log('  – SKIP', name, why ? '(' + why + ')' : ''); }
