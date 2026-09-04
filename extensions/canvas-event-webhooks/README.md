# Canvas Event Webhooks

Forward Canvas EHR events to your own HTTPS endpoints — Zapier, Slack, a warehouse, or an API you already run.

Up to **three** destinations. **156** real Canvas events. A staff UI so you do not have to live in the CLI.

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

Each destination picks its own events, has its own signing secret, and is POSTed independently. One failure does not block the others.

---

## Problem it solves

Canvas fires events internally, but getting them out to the rest of your stack normally means writing and hosting a plugin per integration. Teams end up with one-off webhook plugins for Slack, another for their data warehouse, another for a Zapier hook — each with its own signing and retry code, none configurable without a redeploy.

This plugin does it once: a single signed, retrying event pipeline with a staff-facing UI, so non-engineers can point Canvas at a new endpoint, pick which events it gets, and rotate its secret without touching code.

## Who it's for

- **Integration engineers** wiring Canvas into an external API, ETL job, or message queue.
- **Practice operations / RevOps staff** who need appointment, task, or billing events in Slack or Zapier and want to configure it themselves.
- **Analytics teams** streaming clinical and scheduling events into a warehouse.

No specialty assumptions — it covers patients, appointments, notes, clinical records, medications, prescriptions, labs, tasks, staff, documents, messages, care teams, billing, coverage, and consent.

---

## Start here

| If you want to… | Go here |
|---|---|
| Install it and turn it on | [Install](#install) |
| Point Canvas at your URL | [Configure](#configure) |
| Handle the JSON in your app | [Receive events](#receive-events) |
| See every event name | [Event catalog](canvas_event_webhooks/README.md#event-catalog) |
| Change the plugin itself | [Developers guide](canvas_event_webhooks/DEVELOPERS.md) |

---

## Install

```bash
uv sync
uv run pytest
uv run canvas validate canvas_event_webhooks
uv run canvas install canvas_event_webhooks --host <your-subdomain>
```

Bump `plugin_version` in `canvas_event_webhooks/CANVAS_MANIFEST.json` before you reinstall, or Canvas may keep the old package.

---

## Configure

After install, open the Canvas apps grid (the 3×3 icon in the top bar) and choose **Event Webhooks**. It is a global app, not inside a patient chart.

![Open Event Webhooks from the Canvas apps menu](canvas_event_webhooks/assets/webhook_access_location.png)

For each destination you can set:

- A name and an **`https://` URL** (HTTP is rejected)
- A generated signing secret — copy it into your receiver
- Which events to send (Select All, or pick by category)
- **Include names and details** — off by default; on, the payload includes who did it, the patient name, and major record fields

![Webhook configuration card: name, URL, secret, events, and names-and-details](canvas_event_webhooks/assets/webhook_configuration.png)

**Test Webhook** sends a signed `webhook.test` ping. Canvas delivers that asynchronously, so the page cannot show your server’s HTTP status. Check your logs or `canvas logs --host <subdomain>` and look for `[Webhooks]`.

You can save at most three webhooks. Need a fourth? That is a plugin change, not a UI setting.

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
