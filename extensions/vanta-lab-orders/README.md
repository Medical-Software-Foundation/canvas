# vanta-lab-orders

A [Canvas Medical](https://www.canvasmedical.com/) plugin that forwards
signed Vanta Diagnostics lab orders to **LKCareEvolve** (ELLKAY) using
the **ELLKAY Orders & Results JSON v2.2** contract.

When a provider signs a Vanta lab order in Canvas, the plugin builds
the ELLKAY Orders JSON payload from the Canvas SDK data module and
POSTs it to the LKCareEvolve ingestion endpoint with a bearer token.
Result write-back is owned by ELLKAY (which posts FHIR
`DiagnosticReport` resources to Canvas's prebuilt endpoint) — this
plugin only handles the outbound half.

The plugin is reusable as a reference implementation for any
**ELLKAY-fronted lab integration**. Swap the lab partner name and
account-number map and it'll work for a different lab.

## Status

| | |
|---|---|
| Plugin version | `0.0.19` |
| Canvas SDK version | `0.1.4` |
| License | MIT |
| Tests | 76 passing • 94% coverage |
| Type checking | mypy clean |

## How it works

```
                ┌─────────────────────────────────────┐
                │  Provider signs a VANTA lab order   │
                │  (LAB_ORDER_COMMAND__POST_COMMIT)   │
                └──────────────────┬──────────────────┘
                                   │
                                   ▼
                     ┌──────────────────────────┐
                     │  SendVantaOrder handler  │
                     │  (vanta_lab_orders)      │
                     └────────────┬─────────────┘
                                  │ ELLKAY Orders JSON v2.2
                                  ▼
                       ┌────────────────────┐
                       │   LKCareEvolve     │  ← bearer token
                       │     (ELLKAY)       │
                       └─────────┬──────────┘
                                 │
                                 ▼
                       ┌────────────────────┐
                       │ Vanta Diagnostics  │
                       └────────────────────┘
```

Per signed VANTA order, the plugin issues two Canvas SDK queries:
one root `LabOrder` lookup with `select_related` / `prefetch_related`,
and one filtered query for active `Coverage` rows. It emits no Canvas
`Effect`s — its side-effect is the single outbound HTTPS POST.

Cancel and entered-in-error events are not handled in v1.

## Installation

```bash
# 1. Configure the five required secrets on your Canvas instance (see
#    "Configuration" below) via the admin UI or a secrets file at
#    ~/.canvas/plugin-secrets/<your-instance>.json
#
# 2. Install the plugin
uv run canvas install --host <your-instance> vanta_lab_orders
```

Plugin folder structure follows the Canvas convention: a kebab-case
container directory (`vanta-lab-orders/`) holds a snake-case inner
package (`vanta_lab_orders/`) which is what Canvas packages and
deploys.

## Configuration

All five secrets must be set before the plugin will function. Missing
or empty values raise `ValueError` and the handler fails loud.

| Secret | Required | Purpose |
|---|---|---|
| `LKCAREEVOLVE_BASE_URL` | ✓ | Full LKCareEvolve ingestion URL (posted to as-is). Must use `https://` — `http://` is rejected to prevent the auth credential from traversing the network in cleartext. |
| `LKCAREEVOLVE_API_KEY` | ✓ | Base64-encoded Basic auth credential issued by ELLKAY for your account. |
| `VANTA_LAB_PARTNER_NAME` | ✓ | Exact `LabPartner.name` string the plugin filters on. Orders whose `lab_partner.text` doesn't equal this are skipped silently. |
| `LOCATION_TO_ACCOUNT_MAP_JSON` | ✓ | JSON object mapping `PracticeLocation.id` (UUID) → LKCareEvolve account number string. Example: `{"<practice_location_uuid>": "ACCT-001"}`. A signed order whose location isn't in the map raises `KeyError`. |
| `SENDING_FACILITY_NAME` | ✓ | Friendly facility name embedded in `MessageHeader.SendingFacilityName`. |

## Development

```bash
# Clone and bootstrap the dev environment (uv installs everything)
git clone <repo-url>
cd vanta-lab-orders
uv sync

# Run the test suite (uses canvas[test-utils] fixtures — no real Canvas instance required)
uv run pytest

# Type check
uv run mypy vanta_lab_orders

# Coverage report
uv run pytest --cov=vanta_lab_orders --cov-report=term-missing
```

### Local mock LKCareEvolve

`dev/mock_lkcareevolve/server.py` is a zero-dependency stdlib HTTP
server that impersonates the LKCareEvolve ingestion endpoint so you
can verify exactly what the plugin is POSTing without involving the
real third-party service. See `dev/mock_lkcareevolve/README.md` for
the local + tunnel workflow.

The mock isn't packaged into the Canvas plugin tarball (only the
`vanta_lab_orders/` inner directory ships).

## Design

For the protocol-level design — payload shape, code-system mappings
(CDC ethnicity → ELLKAY H/N/U, X12 relationship → ELLKAY three-letter,
etc.), spec-conformance notes, and open items pending ELLKAY
confirmation — see [docs/DESIGN.md](docs/DESIGN.md).

## License

[MIT](LICENSE).
