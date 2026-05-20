# Mock LKCareEvolve server

Local stdlib HTTP server that impersonates the LKCareEvolve (ELLKAY) ingestion
endpoint so you can see exactly what `vanta-lab-orders` is POSTing. Zero
dependencies.

## Run

```bash
uv run python dev/mock_lkcareevolve/server.py
```

Optional flags:

- `--port 8765` (default)
- `--host 0.0.0.0` (default — lets a tunnel reach it)
- `--api-key my-key` (default: random `mock-...` token printed on startup)

On startup it prints the URL and bearer token to drop into plugin secrets.

## Endpoints

- `POST /orders` — accepts the ELLKAY Orders JSON v2.2 payload. Validates
  `Authorization: Bearer <key>`, pretty-prints the body, returns
  `200 {"Status": "Accepted", "FillerOrderNumber": "MOCK-<uuid>"}`.
- `GET /health` — sanity check.

## Exposing to a cloud Canvas instance

Canvas runs in the cloud, so localhost isn't reachable. Open a tunnel:

```bash
# ngrok
ngrok http 8765

# cloudflared
cloudflared tunnel --url http://localhost:8765
```

Use the tunnel's HTTPS URL as `LKCAREEVOLVE_BASE_URL`. The plugin
enforces `https://` on this secret, so the tunnel URL is required for
end-to-end testing through a deployed plugin.

## Setting plugin secrets

Either via the Canvas admin UI on your instance, or by creating
`~/.canvas/plugin-secrets/<your-instance>.json`:

```json
{
  "vanta_lab_orders": {
    "LKCAREEVOLVE_BASE_URL": "https://<tunnel-host>",
    "LKCAREEVOLVE_API_KEY": "<key from server startup>",
    "VANTA_LAB_PARTNER_NAME": "Vanta Diagnostics",
    "LOCATION_TO_ACCOUNT_MAP_JSON": "{\"<practice_location_uuid>\": \"ACCT-001\"}",
    "SENDING_FACILITY_NAME": "<your facility name>"
  }
}
```

Then deploy: `uv run canvas install --host <your-instance> vanta_lab_orders`.
