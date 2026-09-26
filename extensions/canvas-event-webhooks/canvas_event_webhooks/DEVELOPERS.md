# Developers guide

How this plugin is built, how to change it, and how not to get bitten by the Canvas sandbox.

User-facing docs: [README](README.md). Repo overview: [../README.md](../README.md).

---

## Mental model

Handlers are thin. Almost everything interesting lives in one dispatcher.

```
EventType fires
    → category handler (RESPONDS_TO from events_catalog)
        → WebhookDispatcherBase._dispatch()
            → build envelope
            → for each matching webhook:
                  skip if the URL is not allowed (HTTPS, public host)
                  optionally enrich names/details
                  HMAC timestamp + body
                  HttpRequestEffect (async, retries)
```

`events_catalog.py` is the source of truth for event names (string names in `_RAW_CATEGORIES`). The UI, `RESPONDS_TO`, and the README catalog should all come from it. Names that do not resolve to an int on the host `EventType` are skipped at import so older Canvas versions still load.

---

## Layout

```
canvas_event_webhooks/
├── CANVAS_MANIFEST.json    plugin metadata, handlers, secrets, custom_data
├── README.md               operators + receivers
├── DEVELOPERS.md           this file
├── events_catalog.py       verified EventType lists + labels
├── event_details.py        optional actor / patient / data enrichment
├── config_store.py         WebhookConfig, AttributeHub, URL + secret rules
├── config_page.py          CONFIG_HTML string (sandbox cannot use pathlib)
├── static/config.html      edit the UI here, then regenerate config_page.py
├── assets/icon.png
└── handlers/
    ├── base.py             payload, HMAC, HTTPS filter, dispatch
    ├── event_handlers.py   one class per catalog category
    ├── config_api.py       SimpleAPI (staff session + config-admin-staff-ids allowlist)
    └── config_app.py       global Application → config UI
tests/
├── handlers/
│   ├── test_config_api.py
│   └── test_config_app.py
├── test_canvas_event_webhooks.py
├── test_config_store.py
├── test_webhook_routing.py
├── test_patient_id.py
├── test_events_catalog.py
└── test_event_details.py
```

`WebhookDispatcherBase` is **not** in the manifest. Canvas warns about that on validate. That is expected — it is a base class, not a loaded handler.

---

## Canvas sandbox (read this first)

The plugin runs in a restricted interpreter. These will fail `canvas validate` / install:

| Banned | What to use instead |
|---|---|
| `secrets` | `uuid4().hex` (backed by `os.urandom`) |
| `pathlib` | Embed files as strings (`config_page.py`) |
| `urllib.parse.urlparse` | Manual `https://` prefix + host checks |
| `type()` | `getattr(obj, "__class__", None)` then `__name__` |
| `@dataclass` | A plain class (`WebhookConfig`) |

Allowed and already used: `uuid`, `hmac`, `hashlib`, `json`, `datetime`, `http.HTTPStatus`.

Do not log secrets or patient names.

---

## Adding an event

1. Confirm it exists:

   ```python
   from canvas_sdk.events import EventType
   EventType.Name(EventType.YOUR_EVENT)
   ```

2. Add `("YOUR_EVENT", "Human Label")` to the right category in `_RAW_CATEGORIES` in `events_catalog.py`.
3. If it is **not** about a patient, add the name to `_NON_PATIENT_EVENT_NAMES`.
4. If it needs a new category, add a handler class in `event_handlers.py` with `RESPONDS_TO = event_type_names("your_key")`, register it in `CANVAS_MANIFEST.json`, and map it in `tests/test_events_catalog.py`.
5. If details enrichment should know the model, add a `_from_*` helper in `event_details.py` and list the model under that handler’s `data_access.read`.
6. Bump `plugin_version`. Run tests + `uv run canvas validate canvas_event_webhooks`.

Never invent names like `PATIENT_DELETED` — they are not on `EventType`.

---

## Changing the config UI

Edit `static/config.html` (self-contained HTML/CSS/JS). Then embed it:

```python
from pathlib import Path

html = Path("canvas_event_webhooks/static/config.html").read_text()
Path("canvas_event_webhooks/config_page.py").write_text(
    '"""Embedded configuration UI HTML."""\n\nCONFIG_HTML = ' + repr(html) + "\n"
)
```

`config_api.py` serves `CONFIG_HTML`. Do not load the file at runtime.

API routes (prefix `/config`). `authenticate()` requires a staff session. Every route except `GET /` also requires the caller's staff ID in `config-admin-staff-ids`, and denies everyone when that variable is unset. POST/PUT/DELETE return 415 unless `Content-Type` is `application/json`.

| Method | Path | Role |
|---|---|---|
| GET | `/` | HTML page (static, no data) |
| GET | `/catalog` | Event categories for the UI |
| GET/POST | `/webhooks` | List (secrets masked) / create (returns the new secret once) |
| PUT/DELETE | `/webhooks/<id>` | Update / delete |
| GET | `/webhooks/<id>/secret` | Reveal one secret (backs the **Copy** button) |
| POST | `/webhooks/<id>/regenerate` | New secret (returned once) |
| POST | `/webhooks/<id>/test` | Signed `webhook.test` |
| POST | `/webhooks/import-legacy` | Persist CLI webhook |

Every successful change, reveal, and test send goes through `_audit()`, which logs the acting staff ID, webhook ID, and destination host. Never add secrets or full URLs to that line.

Persistence: AttributeHub `type=plugin_config`, `id=canvas_event_webhooks`, attribute `webhooks`. Namespace in the manifest: `canvas__event_webhooks` `read_write`.

---

## Payloads and signing

Envelope is built in `handlers/base.py` (`_build_payload`). Details are merged per webhook in `_dispatch` so HMAC matches the body actually sent.

Signature (plugin 0.4.0+):

```
X-Canvas-Timestamp: <unix>
X-Canvas-Signature: t=<unix>,v1=<hex>
```

`sign_body(secret, body, timestamp)` HMACs `f"{timestamp}.{body}"`. `validate_webhook_url` requires HTTPS to a public host. It parses IPv4/IPv6 literals by hand because `ipaddress` is not allowed in the sandbox. It also rejects backslashes, whitespace, and host characters outside `[a-z0-9._-]`: HTTP clients end the host at a backslash, so `https://127.0.0.1\@example.com` would otherwise pass as `example.com` and connect to `127.0.0.1`. `_dispatch` runs it again, so configs saved before a rule change cannot leak.

When adding payload fields, keep them additive. Receivers already depend on `event`, `occurred_at`, `target`, `context`.

---

## Tests

Use the existing `.venv` / `uv`. Do not create a second virtualenv.

```bash
uv run pytest -q
```

Worth covering when you touch behavior:

- HMAC of the **body that was sent** (details on vs off can differ)
- `patient_id` never fabricated
- HTTP and internal-address URLs rejected and not dispatched
- Config routes deny staff missing from `config-admin-staff-ids`, and everyone when it is unset
- Secrets stay out of list responses and logs
- Catalog names all exist on `EventType`
- Details lookup failures still deliver the event

---

## Deploy

```bash
# always bump this first
# canvas_event_webhooks/CANVAS_MANIFEST.json → plugin_version

uv run canvas validate canvas_event_webhooks
uv run canvas install canvas_event_webhooks --host <subdomain>
uv run canvas logs --host <subdomain>   # lines prefixed [Webhooks]
```

Install to a host is a remote write. Confirm the subdomain (`<your-instance>`) before running it.

The validate warning about `WebhookDispatcherBase` not being in the manifest is normal.

---

## Pitfalls

- **Partial module imports in the sandbox.** Keep top-level imports to things Canvas allows. Local-import `EventType` in helpers if a cycle appears.
- **Mocks in unit tests.** `event.target.instance` on a `Mock` looks like it has every attribute. `event_details` ignores `Mock` / `MagicMock` class names on purpose. Use real simple classes in details tests.
- **Regenerate `config_page.py`.** If you forget, the deployed UI will not match `static/config.html`.
- **`data_access.read`.** If production lookups of `Patient` / `Staff` / target models start failing, declare them on the handler in the manifest.
- **Legacy CLI.** `WebhookConfigStore` falls back to `webhook-url` only when AttributeHub has never been saved. First UI save wins forever after that.
- **Hot path.** All 156 subscribed events run `_dispatch`, which loads the config (`AttributeHubBackend.load`, one indexed query) even when no webhook wants the event. Keep that load to a single query and per-event logging at `debug`. The plugin cache is database-backed at runtime, so caching the config does not save a round trip.
- **Large columns in details.** When an extractor starts using a model with big text/JSON fields, add them to `_DEFERRED_FIELDS` in `event_details.py`. `test_deferred_fields_exist_on_sdk_models` checks the names against the real models.
