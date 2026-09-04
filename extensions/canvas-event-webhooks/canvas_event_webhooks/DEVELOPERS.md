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
                  skip if not https
                  optionally enrich names/details
                  HMAC timestamp + body
                  HttpRequestEffect (async, retries)
```

`events_catalog.py` is the source of truth for event names. The UI, `RESPONDS_TO`, and the README catalog should all come from it. Do not add a string that cannot resolve on `canvas_sdk.events.EventType`.

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
    ├── config_api.py       SimpleAPI (staff session)
    └── config_app.py       global Application → config UI
tests/
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

2. Add `(EventType.YOUR_EVENT, "Human Label")` to the right category in `events_catalog.py`.
3. If it is **not** about a patient, add the name to `_NON_PATIENT_EVENTS`.
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

API routes (staff session, prefix `/config`):

| Method | Path | Role |
|---|---|---|
| GET | `/` | HTML page |
| GET | `/catalog` | Event categories for the UI |
| GET/POST | `/webhooks` | List / create |
| PUT/DELETE | `/webhooks/<id>` | Update / delete |
| POST | `/webhooks/<id>/regenerate` | New secret |
| POST | `/webhooks/<id>/test` | Signed `webhook.test` |
| POST | `/webhooks/import-legacy` | Persist CLI webhook |

Persistence: AttributeHub `type=plugin_config`, `id=canvas_event_webhooks`, attribute `webhooks`. Namespace in the manifest: `canvas__event_webhooks` `read_write`.

---

## Payloads and signing

Envelope is built in `handlers/base.py` (`_build_payload`). Details are merged per webhook in `_dispatch` so HMAC matches the body actually sent.

Signature (plugin 0.4.0+):

```
X-Canvas-Timestamp: <unix>
X-Canvas-Signature: t=<unix>,v1=<hex>
```

`sign_body(secret, body, timestamp)` HMACs `f"{timestamp}.{body}"`. HTTPS is required in `validate_webhook_url` and skipped again at dispatch (`is_https_url`) so old HTTP configs cannot leak.

When adding payload fields, keep them additive. Receivers already depend on `event`, `occurred_at`, `target`, `context`.

---

## Tests

Use the existing `.venv` / `uv`. Do not create a second virtualenv.

```bash
uv run pytest tests/test_canvas_event_webhooks.py \
    tests/test_config_store.py \
    tests/test_webhook_routing.py \
    tests/test_patient_id.py \
    tests/test_events_catalog.py \
    tests/test_event_details.py -q
```

Worth covering when you touch behavior:

- HMAC of the **body that was sent** (details on vs off can differ)
- `patient_id` never fabricated
- HTTP URLs rejected and not dispatched
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
