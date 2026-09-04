# Canvas Event Webhooks

## What it does

Event Webhooks turns Canvas EHR events into signed JSON POSTs to HTTPS endpoints you already run — an API, Zapier, Slack, a queue, or a warehouse. After install, open **Event Webhooks** from the Canvas apps grid and add up to three destinations. Each destination picks its own events, has its own signing secret, and is delivered independently, so one failure does not block the others.

It covers 156 real Canvas events across patients, appointments, notes, clinical records, medications, prescriptions, labs, tasks, staff, documents, messages, care teams, billing, coverage, and consent. Default payloads are IDs only; names and record details are opt-in per webhook.

```
Something happens in Canvas
            │
            ▼
     Event Webhooks
            │
     ┌──────┼──────────┐
     ▼      ▼          ▼
  your API  Zapier   Slack
```

## Problem it solves

Canvas fires events internally, but getting them out to the rest of your stack normally means writing and hosting a plugin per integration. Teams end up with one-off webhook plugins for Slack, another for their data warehouse, another for a Zapier hook — each with its own signing and retry code, none configurable without a redeploy.

Without this plugin, adding or re-pointing a destination is a code change and a reinstall. This replaces that workaround with one signed, retrying pipeline and a configuration UI, so a destination change is a save in Canvas, not a deploy.

## Who it's for

| Role | Primary use |
|---|---|
| Integration engineer | Wire Canvas into an external API, ETL job, or message queue |
| Practice operations / RevOps | Send appointment, task, or billing events to Slack or Zapier without waiting on engineering |
| Analytics / data engineer | Stream clinical and scheduling events into a warehouse |

**Specialty:** not specialty-specific. Any Canvas practice that needs events outside the EHR can use it.

## How to install

1. From this plugin directory, install into a Canvas instance:
   ```bash
   canvas install canvas_event_webhooks --host <your-instance>
   ```
2. Open Canvas. In the apps grid (the 3×3 icon in the top bar), click **Event Webhooks**. It is a global app, not inside a patient chart.

Bump `plugin_version` in `canvas_event_webhooks/CANVAS_MANIFEST.json` before you reinstall, or Canvas may keep the old package.

Optional, only if you have not saved anything in the UI yet:

```bash
canvas install canvas_event_webhooks --host <your-instance> \
    --secret webhook-url=https://your-endpoint.example.com/canvas \
    --secret webhook-secret=$(openssl rand -hex 32)
```

After the first UI save, those CLI secrets are ignored for delivery.

## Configuration options

| Setting | Where | Notes |
|---|---|---|
| Destination name, HTTPS URL, enabled flag | Event Webhooks UI | HTTP URLs are rejected and never delivered |
| Signing secret | Generated on save in the UI | Copy it into your receiver. Regenerating means updating the receiver |
| Event list | Event Webhooks UI | Select All, or pick by category / event. Max 3 destinations |
| Include names and details | Per-webhook toggle, default off | Adds description, actor, patient name/MRN, and major record fields |
| `webhook-url` / `webhook-secret` | Plugin secrets (legacy CLI) | Used only until the first UI save |
| `include-context` | Plugin secret, default off | If `true`, puts the unfiltered Canvas context in `context` (may include PHI). Instance-wide, not per webhook |

Need a fourth destination? That is a plugin code change, not a UI setting.

## Screenshots

### Open Event Webhooks

![Open Event Webhooks from the Canvas apps menu](canvas_event_webhooks/assets/webhook_access_location.png)

### Webhook configuration

![Webhook configuration card: name, URL, secret, events, and names-and-details](canvas_event_webhooks/assets/webhook_configuration.png)

**Test Webhook** sends a signed `webhook.test` ping. Canvas delivers that asynchronously, so the page cannot show your server’s HTTP status. Check your logs or `canvas logs --host <your-instance>` and look for `[Webhooks]`.

---

## Receive events

Every POST is JSON. Default shape (IDs only):

```json
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "event": "APPOINTMENT_CREATED",
  "occurred_at": "2026-09-02T12:30:00.000000+00:00",
  "source": "canvas",
  "version": "1",
  "patient_id": "pt_abc123",
  "target": { "id": "a1b2c3d4-…", "type": "Appointment" },
  "context": { "patient_id": "pt_abc123" }
}
```

With **Include names and details** on, you also get `description`, `actor`, `patient` (name, MRN), and `data` (times, status, title, provider, …). Note bodies, message text, SSN, file URLs, and payment amounts stay out.

### Prove it came from Canvas

Headers:

```
X-Canvas-Timestamp: 1756830000
X-Canvas-Signature: t=1756830000,v1=<hex>
```

HMAC-SHA256 of `{timestamp}.{raw body}` using **that webhook’s** secret. Reject unsigned traffic. Reject `t` older than 5 minutes (or more than 30 seconds in the future) so a copied POST cannot be replayed later.

Python:

```python
import hashlib, hmac, time

MAX_AGE = 300

def verify(secret: str, body: bytes, header: str) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
    timestamp = int(parts["t"])
    age = time.time() - timestamp
    if age < -30 or age > MAX_AGE:
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

More receivers (Node, retries, full payloads, the 156-event list) live in the [plugin README](canvas_event_webhooks/README.md).

---

## What you get

- Patients, appointments, notes, clinical records, meds, prescriptions, labs, tasks, staff, documents, messages, care teams, billing, coverage, consent
- Per-webhook HMAC and automatic retries on 429 / 500 / 502 / 503 / 504 (max 3, async)
- Config stored in Canvas AttributeHub after you save from the UI

Old CLI secrets (`webhook-url` / `webhook-secret`) still work **until you save in the UI**. After that, the UI is the source of truth.

---

## Docs

- **[Plugin README](canvas_event_webhooks/README.md)** — payloads, signature, retries, event catalog
- **[Developers guide](canvas_event_webhooks/DEVELOPERS.md)** — architecture, sandbox rules, adding events, tests, deploy
