# Screenshot harness

Playwright scripts that generate the images embedded in the plugin guides
(`docs/`), and a Markdown→PDF renderer for those guides. This tooling is
**not** part of the shipped plugin — output PNGs land in `docs/screenshots/`.

## Setup (once)

```bash
cd tools/screenshots
npm install                 # installs playwright locally
npx playwright install chromium   # only if the browser isn't already cached
```

## Local render (deterministic, no login, no PHI)

Renders the plugin's own `templates/picker.html` with sample data and screenshots every
picker state. This is the source of the picker/flow images in the guides.

```bash
node capture_local.mjs
```

Produces: `04-hub-required`, `05-hub-onfile`, `06-review`, `07-finalize`,
`08-finalize-representative`, `09-done`, `10-written-camera`, `11-written-review`,
`12-written-crop`, `13-written-pages`, `14-viewer`.

These are faithful to the real UI (same template) but use sample data, so the guides caption
them as illustrative examples.

## Live capture (real instance)

Captures the things only the live instance shows: the in-chart entry points and the admin
pages, on the sanctioned playground test patient.

```bash
node capture_live.mjs
```

A headed Chromium window opens using a **persistent profile** in `.auth/` (gitignored), so you
log in via SSO **once** and later runs reuse the session. Log in if prompted and land on the
patient chart; the script polls (up to 4 minutes) until the chart loads, then captures:
`01-chart-full` / `01-chart-button`, `03-banner`, `04-hub-required` / `05-hub-onfile`,
`20-consent-settings`, `21-refresh-banners`.

Every shot is best-effort: a missing selector is logged and skipped rather than aborting. Some
shots depend on the patient's data (e.g. the red button only shows when a required consent is
missing) and on the live EHR's DOM, so selectors may need tuning after reviewing `01-chart-full`.

## Notes

- **Sanctioned test patient only.** The live script targets one designated playground patient.
  Its name/DOB may appear in the modal header of live shots — acceptable for that test patient
  on a non-production instance. Do not point this at real patients.
- **The live script records real consents** only if extended to do so; the current version does
  not submit — it captures entry points, the hub, and admin pages. (The guides' Finalize/Done
  images come from the local render.)
- `node_modules/` and `.auth/` are gitignored.
