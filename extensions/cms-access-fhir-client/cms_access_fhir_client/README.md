# cms-access-fhir-client

Canvas plugin that integrates with the CMS ACCESS Model FHIR APIs (IG v0.9.1).

## What it does

Care coordinators can check a patient's CMS ACCESS eligibility, enroll them in a care track (eCKM, CKM, MSK, or BH), and unalign them — all from chart action buttons. The plugin handles the async submission pattern (POST → 202 → poll Content-Location URL) and surfaces alignment status through banners, a custom chart summary section with real-time WebSocket updates, and optional profile fields.

Inbound: the plugin exposes a webhook endpoint that receives all seven CMS FHIR Subscription event types and dispatches each to a dedicated handler.

## Handlers

| Class | Type | Role |
|---|---|---|
| `EligibilityActionButton` | ActionButton | Opens eligibility check modal |
| `AlignActionButton` | ActionButton | Opens enrollment modal |
| `UnalignActionButton` | ActionButton | Opens unalignment modal |
| `AccessOperationsApi` | SimpleAPI | Internal endpoints backing the modals |
| `AccessWebhookApi` | SimpleAPI | Public CMS webhook receiver |
| `AccessChartSummaryWebSocket` | WebSocketAPI | Authenticates chart summary WS connections |
| `SubmissionStatusPoller` | CronTask | Polls outstanding submission-status URLs (exponential backoff) |
| `AccessBannerHandler` | BaseHandler | Emits banner alert (gated by `ACCESS_SHOW_BANNER`) |
| `AccessChartSummaryConfiguration` | BaseHandler | Registers chart summary layout (gated by `ACCESS_SHOW_CHART_SUMMARY`) |
| `AccessChartSummarySection` | PatientChartSummaryCustomSectionHandler | Renders alignment state in chart summary |
| `AccessRealtimeBroadcaster` | BaseHandler | Broadcasts WS invalidation on model changes |

## Plugin models

- **`ACCESSAlignment`** — one row per (patient, track) historical alignment; tracks status, care period dates, async submission state, poll backoff
- **`ACCESSWebhookEvent`** — audit log of every inbound CMS notification

## Secrets

| Secret | Purpose |
|---|---|
| `ACCESS_BASE_URL` | CMS FHIR API base URL, up to (but not including) `/access` — e.g. `https://impl-cdxapi.cmmi.cms.gov/cdx/services/fhir` |
| `ACCESS_OAUTH_CLIENT_ID` | OAuth 2.0 client_id |
| `ACCESS_OAUTH_CLIENT_SECRET` | OAuth 2.0 client_secret |
| `ACCESS_OAUTH_TOKEN_URL` | OAuth 2.0 token endpoint — e.g. `https://impl.idp.idm.cms.gov/oauth2/ausqf73jnuHioLLg3297/v1/token` |
| `ACCESS_OAUTH_SCOPE` | OAuth scopes to request (default: `cdx/*.read cdx/fhir-resource.write`; leave blank to use the default) |
| `ACCESS_PARTICIPANT_ID` | Your entity ID — format is `ACCES` (5 letters) + 5 digits, e.g. `ACCES10098` |
| `ACCESS_WEBHOOK_SECRET` | Shared secret for `X-Access-Webhook-Secret` header validation |
| `ACCESS_SHOW_BANNER` | `true` to enable banner alert in the chart |
| `ACCESS_SHOW_CHART_SUMMARY` | `true` to enable the custom chart summary section |
| `ACCESS_SHOW_PROFILE_FIELD` | `true` to enable custom patient profile fields |

All operations fail closed if a required secret is missing.

## MBI source

The plugin does **not** accept an MBI from the user. Instead, it reads the Medicare Beneficiary Identifier from the patient's active Medicare Part B Coverage record in Canvas.

**How the lookup works:**

1. The plugin calls `get_active_medicare_part_b_coverage(patient, secrets)` before invoking any CMS operation.
2. Two filter mechanisms are supported (evaluated in order):
   - **Allowlist** (`ACCESS_MEDICARE_PART_B_PAYER_IDS`): comma-separated list of Transactor UUIDs. If set, the plugin matches `coverage.issuer.id` against this list — useful for precise control when you know the exact payer IDs on your Canvas instance.
   - **Name pattern** (`ACCESS_PAYER_NAME_PATTERN`, default `Medicare Part B`): case-insensitive substring match against `coverage.issuer.name`. This is the default and requires no configuration. It matches payers like `IL Medicare Part B` or `AK Medicare Part B` while excluding Medicare Advantage payers (e.g. `ASPIRUS MEDICARE ADVANTAGE`), which do not contain the substring `Medicare Part B`.
3. Only coverages with `state=active` are considered.
4. If multiple active Part B coverages are found, the one with the lowest `coverage_rank` (primary) is used.
5. The MBI is read from `coverage.id_number`.

**Fail-closed behavior:** If no active Medicare Part B coverage is found for the patient, all three operations (eligibility, align, unalign) return HTTP 422 with the error:

```
Patient has no active Medicare Part B coverage on file — cannot perform ACCESS operation
```

The staff member must attach a Medicare Part B coverage to the patient via the Canvas insurance section before the ACCESS operations will succeed.

**How the MBI is sent to CMS:** The patient is sent as an inline FHIR `Patient` resource (not a reference), with the MBI in `identifier[system=http://hl7.org/fhir/sid/us-mbi]`. Name and date of birth are also included.

## Webhook endpoint

Point the CMS participant portal at:

```
https://<your-instance>.canvasmedical.com/plugin-io/api/cms_access_fhir_client/webhook
```

Set the `ACCESS_WEBHOOK_SECRET` secret to the shared secret you configure in the CMS portal.

## Deferred (not in MVP)

- **Monthly G-code claim cron** — generate ACCESS G-code claims via Canvas Claim SDK
- **Full `$report-data`** — currently scaffolded with a NotImplementedError; implement when IG v0.9.6+ publishes the payload spec
- **Outcome data capture** — BP device readings, PROM responses, lab data for `$report-data`

## Install steps

1. `canvas install --url https://<instance>.canvasmedical.com` from this directory
2. Navigate to the plugin configuration page and fill in all required secrets
3. Set `ACCESS_SHOW_BANNER=true` and/or `ACCESS_SHOW_CHART_SUMMARY=true` to enable display surfaces
