# Photon Health Prescription Integration

Routes signed prescriptions through [Photon Health](https://docs.photon.health/)
instead of (or in addition to) Canvas's native pharmacy transmission.

## What it does

1. **Adds a "Send via Photon" field** to the **Prescribe**, **Refill**, and
   **Adjust Prescription** commands (single-option select; leaving it empty uses
   the normal Canvas flow).
2. **Removes the *send* and *sign & send* actions** from those commands when the
   field is set. *Sign* and *print* remain — signing is what triggers the Photon
   push, and you can still print a paper copy.
3. **On sign** (`*_COMMAND__POST_COMMIT`), for Photon-flagged commands it:
   - Resolves the patient in Photon — reuses the stored Photon id, else looks up
     by `externalId` (Canvas patient id), else creates the patient — and
     **persists Photon's patient id** back onto the Canvas patient as an external
     identifier (`https://photon.health/patient`) for future sends.
   - Looks up the medication as a Photon **treatment** (by name).
   - Resolves the **prescriber** (test override, or by external id mapping).
   - Creates the **prescription**, then an **order** so Photon routes it to a
     pharmacy (the patient's preferred pharmacy when no Photon pharmacy id is
     available).
4. **On any Photon failure**, creates a Canvas **Task** assigned to the
   prescriber (or a fallback team) describing what went wrong.

## Configuration (secrets)

| Secret | Required | Description |
|---|---|---|
| `PHOTON_CLIENT_ID` | yes | Photon OAuth client id (use the Machine-to-Machine app) |
| `PHOTON_CLIENT_SECRET` | yes | Photon OAuth client secret (Machine-to-Machine app) |
| `PHOTON_ENV` | no | `sandbox` (default, Neutron) or `production` |
| `PHOTON_TEST_PRESCRIBER_ID` | no | Force one Photon provider for all sends (testing) |
| `PHOTON_FALLBACK_TEAM_ID` | no | Team id for failure Tasks when no prescriber is known |

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

## ⚠️ Verify against your Photon sandbox during UAT

Photon's GraphQL schema varies by account/version. Confirm these before relying
on production sends (all isolated in `client/photon_client.py`):

- **`fillsAllowed` vs `refillsAllowed`** on `createPrescription` (this plugin
  sends `fillsAllowed = refills + 1`).
- **`prescriberId` on `createPrescription`** — included here; remove it if your
  account infers the prescriber from a user-access token instead.
- **`patients`/`providers` filter shape** for `externalId` lookups.
- **`treatments(filter: { term })`** medication search — NDC-based lookup is not
  yet generally available from Photon, so this matches on the medication name.
- **`AddressInput` field names** (`street1`/`street2`/`city`/`state`/`postalCode`).

## Tests

```bash
uv run pytest --cov=photon_integration
```
