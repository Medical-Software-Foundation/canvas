// Render the plugin guides (Markdown) to PDF with Chromium.
//
//   node tools/screenshots/render_pdf.mjs
//
// Converts each guide's Markdown to styled HTML and prints it to a PDF via
// Playwright's page.pdf(). The temp HTML is written INTO docs/ so the relative
// screenshots/... image paths resolve, then removed. PDFs land next to the guides.
import { chromium } from 'playwright';
import { marked } from 'marked';
import { readFileSync, writeFileSync, rmSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
// Guides + their screenshots live in repo-root docs/. The temp render HTML is
// written there too, so relative screenshots/... paths resolve.
const DOCS = resolve(HERE, '..', '..', 'docs');

const GUIDES = [
  { md: 'SETUP_GUIDE.md', pdf: 'SETUP_GUIDE.pdf', title: 'Consent Capture — Setup & Configuration Guide' },
  { md: 'RECORDING_GUIDE.md', pdf: 'RECORDING_GUIDE.pdf', title: 'Recording Consents — Staff Guide' },
  { md: 'RECORDING_QUICKSTART.md', pdf: 'RECORDING_QUICKSTART.pdf', title: 'Consents — Quick Start' },
];

marked.setOptions({ gfm: true, breaks: false });

const CSS = `
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1f2933; line-height: 1.55; font-size: 12.5px; margin: 0; padding: 0; }
  .page { max-width: 720px; margin: 0 auto; padding: 8px 4px 24px; }
  h1 { font-size: 24px; letter-spacing: -0.02em; margin: 0 0 12px; padding-bottom: 8px; border-bottom: 2px solid #111827; }
  h2 { font-size: 18px; margin: 26px 0 8px; padding-top: 6px; border-top: 1px solid #e5e7eb; }
  h3 { font-size: 15px; margin: 18px 0 6px; }
  p { margin: 0 0 10px; }
  ul, ol { margin: 0 0 10px; padding-left: 22px; }
  li { margin: 3px 0; }
  code { background: #f3f4f6; border-radius: 4px; padding: 1px 5px; font-size: 11.5px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  pre { background: #0f172a; color: #e5e7eb; border-radius: 8px; padding: 12px 14px; overflow: auto; }
  pre code { background: transparent; color: inherit; padding: 0; }
  a { color: #1d4ed8; text-decoration: none; }
  blockquote { margin: 12px 0; padding: 10px 14px; background: #f9fafb; border-left: 4px solid #94a3b8;
    border-radius: 0 8px 8px 0; color: #374151; }
  blockquote p { margin: 0 0 6px; } blockquote p:last-child { margin: 0; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 11.5px; }
  th, td { border: 1px solid #e5e7eb; padding: 7px 10px; text-align: left; vertical-align: top; }
  th { background: #f3f4f6; }
  hr { border: 0; border-top: 1px solid #e5e7eb; margin: 22px 0; }
  img { display: block; max-width: 100%; height: auto; margin: 12px auto 16px;
    border: 1px solid #e5e7eb; border-radius: 8px; }
  /* Avoid awkward breaks */
  h1, h2, h3 { break-after: avoid; }
  img, table, pre, blockquote { break-inside: avoid; }
`;

function wrap(title, bodyHtml) {
  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>${title}</title>
    <style>${CSS}</style></head><body><div class="page">${bodyHtml}</div></body></html>`;
}

async function run() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  for (const g of GUIDES) {
    const md = readFileSync(resolve(DOCS, g.md), 'utf8');
    const html = wrap(g.title, marked.parse(md));
    const tmp = resolve(DOCS, `.__${g.md}.render.html`);
    writeFileSync(tmp, html, 'utf8');
    try {
      await page.goto('file://' + tmp, { waitUntil: 'networkidle' });
      await page.pdf({
        path: resolve(DOCS, g.pdf),
        format: 'A4',
        printBackground: true,
        margin: { top: '16mm', bottom: '16mm', left: '14mm', right: '14mm' },
      });
      console.log('  ✓', 'docs/' + g.pdf);
    } finally {
      rmSync(tmp, { force: true });
    }
  }
  await browser.close();
}

run().catch((e) => { console.error(e); process.exit(1); });
