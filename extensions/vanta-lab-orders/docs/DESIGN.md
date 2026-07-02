# Design: `vanta-lab-orders`

A Canvas plugin that forwards signed Vanta Diagnostics lab orders to
LKCareEvolve (ELLKAY) using the **ELLKAY Orders & Results JSON v2.2**
contract.

The plugin is reusable as a reference implementation for any
ELLKAY-fronted lab integration — the lab partner name and per-location
account-number mapping are configuration, not code.

---

## 1. Problem & outcome

The Canvas-side outbound half of a Vanta Diagnostics integration: when
a provider signs a Vanta lab order, the plugin builds the ELLKAY Orders
JSON v2.2 payload directly from the Canvas SDK data module and POSTs
it to LKCareEvolve. Result write-back is owned by ELLKAY (which posts
FHIR `DiagnosticReport` resources to Canvas's prebuilt endpoint) — no
inbound plugin endpoint is required.

---

## 2. Scope

### In scope (v1)

- Outbound only: on `LAB_ORDER_COMMAND__POST_COMMIT`, build & POST the
  ELLKAY Orders JSON payload for the configured Vanta lab partner.
  Other partners are a silent no-op.
- **AOE (Ask-on-Order-Entry)**: AOE answers captured on the lab order
  command are read from `Command.data` (keys
  `aoes|{test_ontology_code}|{question_code}`) and emitted in the
  `ObservationRequest.AOE[]` array of the matching test. Pass-through only:
  `Description` is left blank, answers are emitted verbatim, and missing
  required AOEs are not validated or blocked (ELLKAY/Vanta enforce
  downstream).
- Plugin secrets: LKCareEvolve URL + auth key, Vanta lab-partner name,
  location-to-account-number JSON map, sending facility name.
- Structured logging (no PHI) on every send: Canvas order id, patient
  id, location id, test count, LKCareEvolve HTTP status.

### Out of scope (v1)

- **Cancel / entered-in-error handler** — deferred until ELLKAY
  confirms the cancel envelope contract for LKCareEvolve. Will add a
  `CancelVantaOrder(BaseHandler)` listening on
  `LAB_ORDER_COMMAND__POST_DELETE` +
  `LAB_ORDER_COMMAND__POST_ENTER_IN_ERROR` in a follow-up.
- Inbound `SimpleAPI` for results (ELLKAY posts straight to Canvas
  FHIR `DiagnosticReport`).
- Order requisition / specimen-label printing (Canvas APIs not ready).
- ABN workflow.
- LOINC coding / reference ranges.
- Retry queue. Non-2xx propagates to Canvas logs (no swallow).
  Operational stability first.

---

## 3. Event → effect mapping

| Trigger | Canvas event | Plugin output |
|---|---|---|
| Provider signs Vanta lab order | `LAB_ORDER_COMMAND__POST_COMMIT` | HTTPS POST to LKCareEvolve with full Orders JSON (`OrderControl="NW"`) |

Cancel / entered-in-error deferred (see scope notes above).

The plugin emits no Canvas `Effect`s — its side-effect is the
outbound HTTP call.

---

## 4. Payload contract

The plugin emits **ELLKAY Orders & Results JSON v2.2** (PascalCase).
LKCareEvolve translates this internally to whatever shape Vanta /
Ovation expects downstream — that translation is ELLKAY's concern, not
this plugin's.

### Top-level envelope

```json
{
  "MessageHeader": {
    "SendingApplication": "Canvas Medical",
    "SendingFacilityName": "<sending facility name>",
    "ReceivingApplication": "LKCareEvolve",
    "ReceivingFacility": "Vanta Diagnostics",
    "MessageDateTime": "<yyyyMMddHHmmss>",
    "MessageId": "<uuid4>",
    "AccountNumber": "<account_number from secret map for note.location>",
    "OrderDateTime": "<yyyyMMddHHmmss>",
    "ResultDateTime": "",
    "PlacerOrderNumber": "<str(lab_order.id)>",
    "FillerOrderNumber": "",
    "LocationCode": "<note.location.id>",
    "LocationName": "<note.location.full_name>",

    "OrderingProvider": {
      "NPI": "<provider.npi_number>",
      "Code": "<provider.npi_number>", "CodeType": "NPI",
      "LastName": "...", "FirstName": "...",
      "MiddleName": "", "Suffix": "", "Prefix": ""
    },
    "ReferringProvider": { /* 8-key empty Provider object when unused */ }
  },

  "Patient": {
    /* full ELLKAY Patient block — see source */
  },

  "Guarantor": { /* full Guarantor block; for self-pay, mirrors patient */ },

  "Insurances": [
    /* one Insurance entry per active Coverage row, with full PolicyHolder address */
  ],

  "ObservationRequest": [
    {
      /* one entry per LabTest on the order */
      "SequenceNumber": "1",
      "PlacerOrderNumber": "<str(lab_order.id)>",
      "OrderControl": "NW",
      "OrderStatus": "SC",
      "TestCodeId": "<lab_test.ontology_test_code>",
      "TestCodeType": "L",
      "TestCodeDescription": "<lab_test.ontology_test_name>",
      "Priority": "R",
      "RequestedDateTime": "<yyyyMMddHHmmss>",
      "ObservationDateTime": "<yyyyMMddHHmmss>",
      "Diagnoses": [ { "Code": "<dotted ICD-10>", "CodingMethod": "ICD10", ... } ],
      "Notes": [{"SequenceNumber": "1", "Note": "<lab_order.comment>"}],
      "Custom": [
        {"Name": "CanvasPatientId", "Value": "<patient.id>"},
        {"Name": "CanvasOrderId",   "Value": "<lab_order.id>"},
        {"Name": "CanvasNoteId",    "Value": "<note.id>"}
      ],
      "AOE": [
        {"SequenceNumber": "1", "Code": "<question_code>", "Description": "", "Answer": "<answer>"}
      ]
    }
  ]
}
```

> **Envelope note:** `Patient`, `Guarantor`, `Insurances`, and
> `ObservationRequest` sit at the **top level** of the payload (siblings of
> `MessageHeader`), as accepted by the live LKCareEvolve SendRawMessage
> endpoint. This differs from the nesting shown in the ELLKAY spec PDF
> (everything under `MessageHeader`); the top-level shape reflects what the
> endpoint actually expects.

### Key rules

- **One `ObservationRequest` entry per test** on the lab order. All
  tests share the `PlacerOrderNumber` (the Canvas `LabOrder.id`).
- **Cross-system identity** is carried in two places for safety:
  1. `MessageHeader.PlacerOrderNumber` and each
     `ObservationRequest.PlacerOrderNumber` = `str(lab_order.id)`
  2. `ObservationRequest.Custom[]` carries `CanvasPatientId`,
     `CanvasOrderId`, `CanvasNoteId` so ELLKAY can echo them back on
     result write-back and unsolicited results match cleanly.
- **AOE answers** — sourced from the lab order `Command.data` JSONField, where
  Canvas stores them under `aoes|{test_ontology_code}|{question_code}` keys.
  Parsed by `vanta_lab_orders/aoe.py` and attached per test by matching the
  test ontology code to `TestCodeId`. ELLKAY AOE object: `SequenceNumber` (R),
  `Code` (question code), `Description` (left blank), `Answer` (verbatim).
- **Account number** comes from a JSON secret mapping `note.location.id`
  → LKCareEvolve account number string. Missing mapping → raise (fail
  loud per Canvas standards).
- **Date / DateTime formats** — per the ELLKAY appendix:
  `Date = yyyyMMdd`, `DateTime = yyyyMMddHHmmss` (no separators).
- **Code system mappings** — translated at emit time:
  - **Ethnicity**: CDC OMB codes (`2186-5`, `2135-2`) → ELLKAY
    appendix `H` / `N` / `U`.
  - **Relationship**: X12 0344 numeric codes (e.g. `"18"`) → ELLKAY
    3-letter codes (`SEL`, `SPO`, `CHD`, etc.).
  - **Gender**: Canvas `SexAtBirth` enum (word- or letter-form) →
    ELLKAY single-letter (`F`, `M`, `O`, `N`, `U`, `A`).
  - **Diagnosis CodingMethod**: emitted as `"ICD10"` (no dash).
- **ICD-10 codes** — normalized to dotted form (`Z1159` → `Z11.59`)
  at emit time; codes already carrying a dot pass through.
- **Phone / SSN format** — non-digit characters stripped at every emit
  site (per ELLKAY appendix `9999999999` / `999999999`).
- **`LKCAREEVOLVE_BASE_URL`** — the full LKCareEvolve ingestion URL (e.g. the
  ELLKAY SendRawMessage endpoint); the payload is POSTed to it as-is (no path
  appended). Required to start with `https://`; `http://` is rejected at
  settings-read time so the Basic-auth credential cannot leak in cleartext.
- **Auth** — `Authorization: Basic <LKCAREEVOLVE_API_KEY>` (ELLKAY issues the
  API key as a base64-encoded Basic credential, not a bearer token).
- **Local-dev secrets** — `settings.py` reads each secret from the
  Canvas-supplied `secrets` dict first, then falls back to a gitignored
  `secrets_local.py` (copy from `secrets_local.example.py`). Production is
  unchanged; the fallback only fills values Canvas didn't supply.
- **Cancel envelope** (delete / entered-in-error, deferred to v2):
  same envelope shape, but `OrderControl = "CA"` and `Custom` entries
  are sufficient to identify the original order. Demographics block
  should not be re-sent; payload trimmed to `MessageHeader` minus
  `Insurances` plus an `ObservationRequest[]` with only
  `PlacerOrderNumber`, `OrderControl=CA`, `OrderControlCodeReason`.

---

## 5. Plugin structure

```
vanta-lab-orders/
├── pyproject.toml
├── mypy.ini
├── LICENSE
├── README.md
├── docs/
│   └── DESIGN.md                (this file)
├── dev/
│   └── mock_lkcareevolve/       local stdlib mock LKCareEvolve server
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_lkcareevolve_client.py
│   ├── test_payload_builder.py
│   ├── test_send_order_protocol.py
│   └── test_settings.py
└── vanta_lab_orders/
    ├── CANVAS_MANIFEST.json
    ├── README.md
    ├── __init__.py
    ├── settings.py              secret accessors + LabPartner lookup helper
    ├── payload.py               pure ELLKAY Orders v2.2 builder
    ├── aoe.py                   pure parser: Command.data AOE keys → per-test answers
    ├── lkcareevolve_client.py   thin wrapper around canvas_sdk.utils.Http
    └── protocols/
        ├── __init__.py
        └── send_order.py        SendVantaOrder(BaseHandler)
```

### Component responsibilities

- **`payload.py`** — pure, no I/O, no secret reads. Takes a
  fully-loaded `LabOrder` plus the secrets dict, returns a dict ready
  to JSON-serialize. 100% unit-testable.
- **`lkcareevolve_client.py`** —
  `post_order(payload, base_url, api_key) -> Response`. Uses the
  Canvas SDK's allowed `Http` wrapper (`canvas_sdk.utils.Http`), sets
  Basic auth, calls `raise_for_status()`. No retry, no swallowing.
- **`protocols/send_order.py`** — `SendVantaOrder(BaseHandler)`.
  `RESPONDS_TO = LAB_ORDER_COMMAND__POST_COMMIT`. Filters by lab
  partner, resolves the just-committed `LabOrder` from the event,
  builds the payload, posts it, logs. Returns `[]`.
- **`settings.py`** — secret accessors and the location → account
  number lookup helper. All accessors fail loud on missing or
  malformed values.

---

## 6. Secrets

| Secret | Purpose |
|---|---|
| `LKCAREEVOLVE_BASE_URL` | Full LKCareEvolve ingestion URL (e.g. SendRawMessage endpoint). Posted to as-is. Must start with `https://`. |
| `LKCAREEVOLVE_API_KEY` | Base64-encoded Basic auth credential issued by ELLKAY. |
| `VANTA_LAB_PARTNER_NAME` | Exact `LabPartner.name` for the Vanta Diagnostics entry in this Canvas instance. |
| `LOCATION_TO_ACCOUNT_MAP_JSON` | JSON object: `{ "<practice_location_uuid>": "<lkcareevolve_account_number>" }` |
| `SENDING_FACILITY_NAME` | Friendly facility name embedded in `MessageHeader.SendingFacilityName`. |

---

## 7. Test plan

Unit tests own coverage; integration testing happens against a Canvas
sandbox instance.

- **`test_payload_builder.py`** — payload composition, code-system
  mappings, date formats, dotted ICD-10 normalization, Patient /
  Guarantor / Insurance shapes and field order.
- **`test_send_order_protocol.py`** — partner filter, LabOrder
  resolution, no-signed-order fallback, error propagation.
- **`test_lkcareevolve_client.py`** — URL used as-is, Basic auth,
  `raise_for_status` invocation, error propagation.
- **`test_settings.py`** — secret accessors, missing/empty validation,
  HTTPS-only guard on the base URL.

`pytest-mock` is used for the HTTP layer; the SDK data module is
never mocked — `canvas[test-utils]` fixtures back real DB rows.

---

## 8. Open items (pending ELLKAY confirmation)

These do not block the plugin loading or POSTing a payload; they are
payload-shape clarifications best confirmed during production
onboarding with ELLKAY.

1. ~~**Auth scheme**~~ — resolved: `Authorization: Basic <api_key>` against the
   SendRawMessage endpoint (confirmed during UAT).
2. **`BillType` code** — confirm acceptable values from the ELLKAY
   appendix (currently `T` when insurance is present, `P` otherwise).
3. **Gender / Race / Ethnicity normalization** — confirm the code-set
   translation rules built into this plugin are what ELLKAY expects
   on the inbound side.
4. **Cancel envelope minimum payload** — required to scope the
   deferred v2 cancel handler.
5. **`LabPartner` row** — create the Vanta Diagnostics partner row in
   the target Canvas instance before first end-to-end test.
6. **`OrderStatus` value for new outbound orders** — currently
   defaulted to `"SC"` (Scheduled). Confirm this is the value
   ELLKAY expects; alternatives are `"IP"` or blank.
7. **`ObservationDateTime` semantics** — currently mirrors
   `RequestedDateTime` (the order-signed timestamp). Confirm whether
   this should reflect the expected sample collection time instead.
