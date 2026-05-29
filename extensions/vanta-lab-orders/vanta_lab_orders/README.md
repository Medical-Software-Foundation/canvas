# vanta-lab-orders

Send signed Vanta Diagnostics lab orders from Canvas to LKCareEvolve
(ELLKAY) using the **ELLKAY Orders & Results JSON v2.2** contract.

The plugin is the Canvas-side outbound half of a Vanta Diagnostics
integration. When a provider signs a Vanta lab order, it builds the
ELLKAY Orders JSON payload directly from the Canvas SDK data module
and POSTs it to LKCareEvolve. Result write-back is owned by ELLKAY,
which posts FHIR `DiagnosticReport` resources to Canvas's prebuilt
endpoint — this plugin does **not** expose an inbound endpoint.

## Trigger

| Event | Behavior |
|---|---|
| `LAB_ORDER_COMMAND__POST_COMMIT` | If the order's lab partner equals `VANTA_LAB_PARTNER_NAME`, build the ELLKAY Orders JSON v2.2 payload and POST it to `{LKCAREEVOLVE_BASE_URL}/orders` with a bearer token. Non-VANTA partners are a silent no-op. |

Cancel and entered-in-error events (`LAB_ORDER_COMMAND__POST_DELETE`,
`LAB_ORDER_COMMAND__POST_ENTER_IN_ERROR`) are **not** handled in v1
— see the open-items list in the spec for the deferred follow-up.

## Effects

The plugin emits no Canvas `Effect`s — its side-effect is the outbound
HTTPS POST. Non-2xx responses propagate to the Canvas plugin runner
logs (no swallowing, no retry queue).

## Configuration (secrets)

All five secrets must be set on the target Canvas instance before the
plugin will function. Missing or empty values cause the handler to fail
loud (`ValueError`).

| Secret | Purpose |
|---|---|
| `LKCAREEVOLVE_BASE_URL` | Full LKCareEvolve ingestion URL (posted to as-is). Must use `https://` — http URLs are rejected to prevent the auth credential from leaking in cleartext. |
| `LKCAREEVOLVE_API_KEY` | Base64-encoded Basic auth credential issued by ELLKAY for this account. |
| `VANTA_LAB_PARTNER_NAME` | Exact `LabPartner.name` string the plugin filters on. Orders whose `lab_partner.text` doesn't match are skipped. |
| `LOCATION_TO_ACCOUNT_MAP_JSON` | JSON object mapping `PracticeLocation.id` (UUID) to LKCareEvolve account number string. Example: `{"<practice_location_uuid>": "ACCT-001"}`. A signed order whose location isn't in this map raises `KeyError`. |
| `SENDING_FACILITY_NAME` | Friendly facility name embedded in `MessageHeader.SendingFacilityName`. |

## Components

```
vanta_lab_orders/
├── CANVAS_MANIFEST.json
├── README.md                       (this file)
├── settings.py                     secret accessors + account-number lookup
├── payload.py                      pure ELLKAY Orders v2.2 builder
├── lkcareevolve_client.py          httpx-free wrapper around canvas_sdk.utils.Http
└── protocols/
    └── send_order.py               SendVantaOrder(BaseHandler)
```

The payload builder (`payload.py`) is pure: no I/O, no secret reads
inside helpers. All HTTP work is in `lkcareevolve_client.post_order`.

## Logging

Three operational log lines per signed order, all PHI-safe (UUIDs and
counts only — no patient names, DOB, addresses, SSN, or payload body):

- `error` — no signed LabOrder found for `note_uuid` / `patient_id`.
- `info` — sending order: `order_id`, `patient_id`, `location_id`, `test_count`.
- `info` — LKCareEvolve accepted: `order_id`, `http_status`.

## Local development

A zero-dependency mock LKCareEvolve server lives under `dev/mock_lkcareevolve/`
in the repo (not packaged into the plugin tarball). See its README for
the localhost + tunnel workflow used during UAT against a Canvas
sandbox instance.

### Secrets for local dev

Passing five `--secret` flags on every `canvas install` gets old fast.
Instead:

1. Copy [secrets_local.example.py](secrets_local.example.py) to `secrets_local.py`.
2. Fill in real dev values.
3. Run `canvas install vanta_lab_orders` with no `--secret` flags.

`secrets_local.py` is gitignored. [settings.py](settings.py) checks
`self.secrets` first and only falls back to `secrets_local.py` when a
value isn't supplied by Canvas, so production behavior is unchanged.
