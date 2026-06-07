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
