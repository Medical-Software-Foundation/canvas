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

The Elements modal loads from `https://esm.sh` and talks to `*.neutron.health`/
`*.photon.health`; those are declared in `url_permissions`. The SPA app's
whitelisted callback URLs in Photon must include the modal's served origin.

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

- Medication lookup: `medications(filter: { drug: { name } })` → the returned
  medication `id` is used as the prescription `treatmentId`. Matches on the
  medication name from the Canvas command (NDC/code-level lookup needs parent
  ids, so name search is used).
- `createPrescription` uses `treatmentId` and `refillsAllowed` (= Canvas
  refills). **It has no `prescriberId` argument** — the prescriber is taken from
  the authenticated identity.
- `createOrder` uses `fills: [{ prescriptionId }]` + `address` (`pharmacyId`
  optional → patient's preferred pharmacy).

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
