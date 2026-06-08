# Photon Health Prescription Integration

Routes signed prescriptions through [Photon Health](https://docs.photon.health/)
instead of (or in addition to) Canvas's native pharmacy transmission.

## Architecture

Photon only lets an **authenticated provider** write prescriptions (the backend
Machine-to-Machine token has `write:patient`/`write:order` but **never**
`write:prescription`). So the integration is split:

- **Backend (M2M token):** patient sync (and, where applicable, orders + status).
- **Frontend (Photon Elements):** a provider authenticates in the browser and
  writes the prescription with their own token.

## What it does

1. **"Send via Photon" field** on the **Prescribe**, **Refill**, and **Adjust
   Prescription** commands (single-option select). When set, the Canvas *send* /
   *sign & send* actions are removed (*sign* and *print* remain).
2. **Patient sync (backend, M2M).** On sign, and when the prescribe modal opens,
   the patient is resolved in Photon — reusing the stored Photon id, else
   creating the patient — and Photon's patient id is **persisted** on the Canvas
   patient as an external identifier (`https://photon.health/patient`).
3. **"Prescribe via Photon" app (frontend, Elements).** A patient-chart
   application opens a modal embedding Photon **Elements**
   (`photon-prescribe-workflow`). The provider authenticates via Photon SSO and
   writes the prescription / places the order with their user token.
4. **On a backend Photon failure**, a Canvas **Task** is created (assigned to the
   prescriber when a valid Staff UUID is available, else a fallback team).

## Configuration (secrets)

| Secret | Required | Description |
|---|---|---|
| `PHOTON_CLIENT_ID` | yes | M2M client id (backend patient sync) |
| `PHOTON_CLIENT_SECRET` | yes | M2M client secret (backend patient sync) |
| `PHOTON_SPA_CLIENT_ID` | yes (modal) | **Single Page Application** client id used by Photon Elements for provider SSO |
| `PHOTON_ORG_ID` | yes (modal) | Photon organization id (`org_…`) |
| `PHOTON_ENV` | no | `sandbox` (default, Neutron) or `production` |
| `PHOTON_REDIRECT_URI` | no | Override the Elements SSO redirect URI (defaults to the modal's own URL) |
| `PHOTON_FALLBACK_TEAM_ID` | no | Team id for failure Tasks when no prescriber is known |

Photon Elements is **vendored** at `static/elements_bundle.js`
(`@photonhealth/elements@0.23.4`, the jsDelivr `+esm` Rollup bundle wrapped in a
Django `{% verbatim %}` block) and served same-origin via the `/elements.js`
route, so it isn't subject to cross-origin script-src/CSP limits inside the
modal. To update it, re-fetch
`https://cdn.jsdelivr.net/npm/@photonhealth/elements@<version>/+esm`, re-wrap in
`{% verbatim %}`…`{% endverbatim %}`, and bump the version here. At runtime the
modal talks to `*.neutron.health`/`*.photon.health` (declared in
`url_permissions`); the SPA app's whitelisted callback URLs in Photon must
include the modal's served paths (`…/photon/` and `…/photon/send`).

**Provider sign-in uses a popup, not a redirect.** Photon's Auth0 connection is
Google-backed, and Google refuses to render its sign-in inside an iframe (which
the Canvas modal is) — both `loginWithRedirect` and Auth0's silent
`getTokenSilently` iframe hit a Google 403. So the modal reads only the cached
session (`getTokenSilently({ cacheMode: 'cache-only' })`) and, when there's no
token, shows a **Sign in to Photon** button that calls `loginWithPopup` (a popup
is a top-level window Google accepts); on success it reloads. For the popup's
web-message callback to be accepted, the Canvas instance origin must be listed
under **Allowed Web Origins** in the Photon SPA app (alongside the Allowed
Callback URLs). The modal never calls `logout()` — the SDK's logout is a full
redirect that can federate out to Google and strand the user on an external 403.

The API-direct send flow loads **`@photonhealth/sdk`** (provider auth only) from
`https://cdn.jsdelivr.net` — it can't be vendored as a single file because its
deps (Apollo/auth0) stay external `/npm/...` imports, and loading it same-origin
404s those. jsDelivr is allowed by Canvas's `script-src` (and listed in
`url_permissions`), so the SDK and its deps resolve against jsDelivr. The actual
prescription/order calls use the validated `createPrescription`/`createOrder`
GraphQL with the provider's user token.

Set these on the plugin's configuration page after install:
`<emr_base_url>/admin/plugin_io/plugin/<plugin_id>/change/`

## Environments

| | Auth | API (GraphQL) |
|---|---|---|
| sandbox | `https://auth.neutron.health/oauth/token` | `https://api.neutron.health/graphql` |
| production | `https://auth.photon.health/oauth/token` | `https://api.photon.health/graphql` |

## Install

```bash
canvas install photon_integration
```

## Schema notes (verified against Neutron via introspection)

The GraphQL calls in `client/photon_client.py` match the live Neutron schema:

- Medication lookup (API-direct send): **code-based, not name.** Photon's catalog
  stores RxNorm (`rxcui`) but not NDC, so the chain is Canvas NDC →
  `ontologies_http` `/fdb/ndc-to-medication/<ndc>/` → `rxnorm_rxcui` → Photon
  `medications(filter: { drug: { code: <rxcui> } })` → exact `treatmentId`
  (correct strength/form). No RxNorm match → the Rx is flagged for the provider
  to use the Elements modal rather than auto-sending a guess.
- `createPrescription` uses `treatmentId` and `refillsAllowed` (= Canvas
  refills). **It has no `prescriberId` argument** — the prescriber is taken from
  the authenticated identity.
- `createOrder` uses `fills: [{ prescriptionId }]` + `address` (`pharmacyId`
  optional → patient's preferred pharmacy).

### Prescriber attribution

Photon attributes a prescription to the **authenticated Photon user** (there is
no `prescriberId` on `createPrescription`), and the SDK caches that session in
the browser's `localStorage` — independent of the Canvas user. To prevent
sending under the wrong identity, the send modal resolves each command's
prescriber to an email (Canvas Staff) and **only sends an Rx when the signed-in
Photon provider's email matches**; otherwise it blocks that Rx and offers a
"Sign in to Photon as the prescriber" re-auth. This assumes a provider's Photon
account email equals their Canvas email. Notes with multiple prescribers require
each provider to authenticate in turn.

### ⚠️ Open question: prescription authorization

Photon documents that a Machine-to-Machine token "can complete all actions
**except write prescriptions**, as prescriptions can only be written by
authorized providers." Patient creation works with the M2M token; if
`createPrescription` returns an authorization error, the org must either permit
M2M prescription writes or the flow needs a provider **user-access token**
(e.g. via Photon Elements). This is the main item still to confirm in UAT.

## Tests

```bash
uv run pytest --cov=photon_integration
```
