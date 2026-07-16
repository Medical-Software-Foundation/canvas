# Consent Capture

A Canvas plugin that lets clinical and front-desk staff **record a patient's
consent right from the chart** — for *any number* of consent types — and files a
documented FHIR `Consent` for each: who collected it, when, from whom, by what
method, plus a generated PDF (or, for written consents, the signed document
itself).

The plugin surfaces consents three ways in the chart:

1. A **Consents** button in the chart header — **always present** for a patient.
   It is **red** when the patient still has a **required** consent that isn't on
   file, and a neutral **gray** button once all required consents are on file.
   Inactive/deceased patients always see the gray button and never the red one.
   (The label is always "Consents".)
2. A **Consents** launcher in the chart **app drawer** — always available, so staff
   can review what's on file or record an optional consent any time.
3. A **warning banner** on the chart and profile — shown while a required consent
   is outstanding, cleared once it's on file. Can be turned off entirely with the
   `CONSENT_BANNERS_ENABLED` plugin variable.

All three open (or reflect) the same **picker**, which lists every configured
consent grouped into **Required**, **Optional**, and **On File**, and captures the
selected one via the Canvas FHIR API.

The consents themselves are the **Patient Consent Codings** configured in Canvas
admin — the plugin does not create them. What you configure at runtime, on the
**Consent Settings** page (no code, no redeploy), is the *workflow* layered onto
each coding: the verbiage to read, the questions to ask, method/who/capacity, and
whether it shows in the consent modal.

Consent Settings is its own page at
**`/plugin-io/api/consent_capture/admin/settings`** (open it while signed in to Canvas;
also reachable from the gear icon in the consent picker).

> **User & admin guides** live in **[`docs/`](../docs/)** (Markdown + printable PDFs):
> [Setup & Configuration](../docs/SETUP_GUIDE.md) for admins, and the
> [Staff Guide](../docs/RECORDING_GUIDE.md) / [Quick Start](../docs/RECORDING_QUICKSTART.md)
> for recording consents day to day.

---

## Why this plugin exists

Practices frequently capture **verbal, electronic, or written consents** (treatment,
remote patient monitoring, care programs, etc.) during a visit and need a durable
record of each. Doing this by hand is slow and error-prone, and it multiplies with
every consent type a program requires.

Consent Capture turns that into a guided flow that:

- **Scales to many consents** — the picker lists every configured consent grouped
  by Required / Optional / On File, so staff see what's outstanding at a glance.
- **Chases the required ones** — the chart-header button turns red (and the
  chart/profile banner appears) only when a *required* consent is missing, and both
  clear themselves when it's on file; the button then stays as a neutral gray
  entry point.
- **Records who did what** — the collecting staff member comes from the logged-in
  Canvas session, not from anything the browser sends.
- **Captures the details that matter** — the **method** (Verbal / Electronic /
  Written / Other), **who gave consent** (patient or a representative), per-consent
  **questions**, and a **capacity statement** — all configurable per consent.
- **Produces the right artifact** — a clean one-page PDF for verbal/electronic
  consents, or the provider-supplied **signed document** (camera-captured or
  uploaded) for written consents.
- **Files it as structured data** — a FHIR `Consent` (effective today, document
  attached) so the consent is queryable and shows in the record.
- **Is configured without code** — admins manage consents in Consent Settings.

---

## How it works (staff experience)

### Recording a consent

1. Open a patient chart. The **Consents** button in the chart header is always
   present; it turns **red** (with the warning banner) when an **active,
   non-deceased** patient has a required consent not on file, and is a neutral gray
   otherwise. The **Consents** app-drawer entry is always present.
2. Opening it shows the **picker**, grouped:
   - **Required** — required consents that are needed, or expired and due for
     **Renew**.
   - **Optional** — non-required consents that can be recorded.
   - **On File** — the patient's consent **history**: every accepted consent, shown
     **On file** (active) or **Expired**, including consents recorded outside this
     plugin or on codings it doesn't manage. Each row opens its attached document.
3. Selecting a consent starts the capture wizard: review the verbiage with the
   patient, then confirm:
   - **How is the consent being obtained?** — Verbal, Electronic, Written, or Other
     (limited to the methods the consent is configured for).
   - **Who is giving consent?** — the patient, or a representative (name +
     relationship, e.g. "Jane Doe (Daughter)").
   - A **capacity attestation** — when the consent requires one, a statement ("The
     patient/representative has the capacity/authority for decision-making.") is shown
     as a **Yes / No** affirmation (Yes pre-selected). Yes must stay selected to record;
     No blocks it. The wording follows the patient/representative choice and never
     inserts a name.
   - Any configured **questions** (Yes/No, Acknowledge, or typed answer).
     **Written** consents skip the questions — the signed document is the record — so
     none are shown or evaluated for them.
4. On **Record Consent**, the plugin:
   1. For verbal/electronic/other: generates a documentation PDF (built without an
      external PDF library, since the sandbox has none) with the method, capacity
      statement, questions, and full verbiage. For **Written**: the provider
      captures the signed document with the device camera (crop + multi-page,
      assembled into a PDF in the browser) or uploads a PDF — no PDF is generated.
   2. Creates a FHIR **Consent** (`status = active`, the consent's coding, effective
      date = the staff member's local calendar date, the document attached as
      `sourceAttachment`, **no** `period.end` — expiration is governed by the coding
      in Canvas admin).
   3. Reflects it under **On File** immediately.

> Canvas keeps **one consent per coding** and overwrites it on re-consent, so a
> coding shows a single current record; the On File section still lists distinct
> codings and any historical/unmanaged consents on file.

### The chart / profile banner

`ConsentBanner` keeps a red **"Required consent not on file."** warning banner in
sync on the patient's **chart and profile**:

- Added when an **active, non-deceased** patient has a required consent not on file.
- Removed once all required consents are on file, or the patient becomes inactive or
  deceased.
- Recomputed on consent and patient events (`CONSENT_CREATED/UPDATED/DELETED`,
  `PATIENT_CREATED/UPDATED`).
- Suppressed entirely when the `CONSENT_BANNERS_ENABLED` variable is off — the
  handler then clears each banner as patients hit events (see below).

Because it's event-driven, existing patients pick up (or lose) the banner on their
next relevant event — or immediately via the **backfill** page below.

### Refreshing banners across patients (admin)

**`/plugin-io/api/consent_capture/admin/banners`** (admin-only, linked from Consent
Settings) reconciles the banner across **all active patients** on demand:
**Preview Changes** reports how many banners would be added/removed without changing
anything; **Apply Changes** commits it. Use it after configuring a new required
consent so existing patients get the banner without waiting for an event — or, when
`CONSENT_BANNERS_ENABLED` is off, to clear every existing banner in one pass.

---

## Configuring consents (admin experience)

Open **Consent Settings** (the URL above, or the gear icon in the consent picker; access
is limited — see below). The left list shows the consents you've configured, each with a status
badge (Required / Optional / Not shown / Not set up). A **+** opens Canvas admin to
add a new coding; a small flag icon links to the banner backfill page.

Pick a coding — the plugin only configures **pre-existing Patient Consent Codings**,
never invents one — and configure its workflow:

| Field | Purpose |
|-------|---------|
| **General** (Name / Code / Expiration) | Read-only identity from the Canvas coding. |
| **Show in the consent modal** | Whether providers can *record* it in the picker. |
| **Prompt as due now** | Marks it required, so it lists under **Required** (and drives the button/banner) until on file. |
| **Position in the modal** | Order in the picker (editable, lower first). |
| **Content (verbiage)** | The consent language the provider reads. Blank lines start new paragraphs. |
| **Questions** | Asked and recorded in order (Yes/No, Acknowledge, Text; each required and optionally "must be Yes to record"). |
| **At capture** | Which methods are offered, whether to ask who is giving consent, and a capacity statement (templates use `[Patient name]` / `[Name]`). |

A live document preview shows how the PDF will read as you edit.

> **"Show in the consent modal" gates *recording*, not display.** A consent that's
> already on file still appears under **On File** even if the modal toggle is off.
> The plugin never creates or edits codings; expiration lives on the coding.

---

## Prerequisites

1. **Patient Consent Codings** in **Admin → Settings** — these *are* the consents.
   The plugin lists them, layers workflow onto them, and checks them for status
   (and they're where expiration is set).
2. **Canvas FHIR API OAuth credentials** (client ID + secret) with permission to
   create `Consent` resources and read `Consent`/`Binary`. Stored as sensitive
   plugin variables, never in code.

---

## Configuration (plugin variables)

| Variable | Required | Sensitive | Default | Description |
|----------|----------|-----------|---------|-------------|
| `CANVAS_FHIR_CLIENT_ID` | ✅ | 🔒 | — | OAuth client ID for the Canvas FHIR API. |
| `CANVAS_FHIR_CLIENT_SECRET` | ✅ | 🔒 | — | OAuth client secret for the Canvas FHIR API. |
| `CONSENT_ADMIN_USERS` | — | — | `""` | Comma/semicolon/newline-separated Staff ids or full names allowed into Consent Settings and the banner tools. Fails closed: **empty = root / "Canvas Support" only** (all other staff denied). Add staff here to grant them access. |
| `CONSENT_BANNERS_ENABLED` | — | — | `true` | Feature flag for the "Required consent not on file." chart/profile banner. **Opt-out:** any value except an explicit off (`false`/`0`/`no`/`off`/`disabled`) keeps banners on. When off, the event handler clears each banner as patients hit events, and the banner backfill removes them all at once. Does **not** affect the chart button. |
| `CONSENT_SYSTEM` | — | — | `INTERNAL` | Legacy default coding system; identity now comes from the selected coding, so this is rarely used. |

Consent workflow (verbiage, questions, capacity, toggles) is **not** set through
variables — it lives in Consent Settings, backed by a plugin-owned
`ConsentDefinition` custom-data table keyed to each coding's system + code.

---

## Components

Declared in `CANVAS_MANIFEST.json`:

**Protocols / endpoints**

- **`consent_button:ConsentButton`** — the **Consents** chart-header button, always
  shown for a patient; red for an eligible patient with a required consent missing,
  neutral gray otherwise. After a capture, `ConsentApi.collect` emits
  `ReloadPatientActionButtonsEffect` so its color updates live (requires the manifest's
  pinned SDK `0.179.0`).
- **`consent_api:ConsentApi`** — staff-authenticated capture + document endpoints:
  `POST /consent/collect` (generates/attaches the document, creates the FHIR
  `Consent`) and `GET /consent/document` (serves a recorded consent's PDF).
- **`consent_api:ConsentAdminApi`** — staff + admin endpoints behind Consent
  Settings: `GET /admin/settings`, `GET /admin/codings`, `/admin/consents` (list /
  upsert / delete), and the banner backfill (`GET /admin/banners`, `POST
  /admin/banners/preview`, `POST /admin/banners/refresh`).
- **`consent_banner:ConsentBanner`** — event handler that adds/removes the
  chart+profile "Required consent not on file." banner.

**Applications**

- **`consent_app:ConsentApp`** — the always-available **Consents** app-drawer
  launcher (`patient_specific`); opens the picker for the charted patient.

**Consent Settings** is not a menu application — it is a standalone page served by
`consent_api:ConsentAdminApi` at `/admin/settings` (open by URL or the picker's gear icon).

The Written-consent capture flow loads client libraries from `cdn.jsdelivr.net`
(declared in `url_permissions`): **pdf-lib** (assemble pages into a PDF),
**Cropper.js** (crop), **SortableJS** (reorder pages), **heic2any** (iOS HEIC).

### Security model

- All endpoints use `StaffSessionAuthMixin` — **only logged-in staff** reach them.
  Admin endpoints additionally require `_is_admin()` (root / "Canvas Support", or a
  member of `CONSENT_ADMIN_USERS`).
- The collecting staff member's identity is read from the authenticated session,
  never from the browser.
- The capture endpoint re-loads the selected consent's verbiage/templates from the
  server by code — the browser never supplies recorded text.
- The document endpoint is **patient-scoped**: a specific record id is verified to
  belong to the requested patient before it's served.
- Fetching a consent's `sourceAttachment.url` (and minting a token for it) is
  **restricted to this Canvas instance's own host** (derived from
  `CUSTOMER_IDENTIFIER`), so a tampered Consent can't redirect the FHIR client
  credentials off-instance.
- FHIR credentials are **sensitive** plugin variables and are never logged.

---

## Data access

The plugin reads `Patient` (name, DOB, active/deceased), `PatientConsent` (on-file
status and history), `Staff` (the collector's name), `PatientConsentCoding` (to list
the instance's consents), and `BannerAlert` (to reconcile banners). It stores
workflow overlays in its own `ConsentDefinition` custom-data table, writes the
`Consent` resource through the Canvas FHIR API, and emits `AddBannerAlert` /
`RemoveBannerAlert` effects. It does not read or write anything else.

---

## Development

### Project layout

```
consent-capture/                 # container (this repo)
├── pyproject.toml               # pytest + coverage config
├── tests/                       # test suite (mirrors the source tree)
└── consent_capture/             # the plugin
    ├── CANVAS_MANIFEST.json
    ├── constants.py             # config parsing, methods, capacity + banner constants
    ├── models/                  # ConsentDefinition custom-data model
    ├── service.py               # definitions, picker/on-file status, eligibility, backfill query
    ├── picker_modal.py          # builds the shared picker LaunchModalEffect
    ├── banner.py                # shared AddBannerAlert / RemoveBannerAlert builders
    ├── fhir.py                  # FHIR Consent payload builder
    ├── pdf.py                   # dependency-free PDF generation
    ├── questions.py             # question normalization + answer evaluation
    ├── assets/consent.png       # app icon
    ├── handlers/
    │   ├── consent_button.py    # the Consents chart-header button
    │   ├── consent_app.py       # the Consents app-drawer launcher
    │   ├── consent_banner.py    # the chart/profile banner handler
    │   └── consent_api.py       # /consent/* + /admin/* endpoints (incl. the Settings page)
    └── templates/
        ├── picker.html          # the consent picker + capture flow
        ├── admin.html           # the Consent Settings admin UI
        └── banners.html         # the banner backfill page
```

### Tests

Run from the container directory:

```bash
uv run pytest                          # full suite
uv run pytest --cov=consent_capture    # with coverage
```

The suite runs at **~98% coverage** and exercises capacity rendering, seeding, the
PDF builder, the FHIR payload, question evaluation, definition/picker-status/
eligibility helpers, the backfill query, the always-shown chart button's
status colors (red when a required consent is due, neutral gray otherwise, never
red on inactive/deceased patients), banner visibility and the
`CONSENT_BANNERS_ENABLED` feature flag (including inactive/deceased gating), the
capture and document endpoints (config errors, success, FHIR errors, the
attachment host guard, the post-capture button reload, the capacity-attestation
confirmation gate, and Written consents skipping question evaluation), and the admin
CRUD + banner endpoints.
