# Architecture

How the publisher and its consumers fit together, what the data looks like, and
what happens on each request.

## Components

### `canvas_theme_kit` — the publisher

The only plugin with write access to the namespace. Five handlers:

| Class | Surface | Auth |
|---|---|---|
| `ThemeEditorApp` | App drawer (`global` scope) | staff session |
| `ThemeEditorMenuItem` | Provider menu (`provider_menu_item`) | staff session |
| `ThemeAssets` | `/assets/*` — published CSS, tokens, script | any logged-in session |
| `ThemePreview` | `/preview/*` — the unpublished draft | staff + editor role |
| `ThemeAdminAPI` | `/admin/*` — read and mutate themes | staff + role allowlist |

Two application classes exist because **scope is set per manifest entry, not in
code**. `ThemeEditorMenuItem` subclasses `ThemeEditorApp` and adds nothing; it
exists purely to occupy a second scope.

Supporting modules, none of them handlers:

- `models/` — the two CustomModels. Canvas only applies migrations for models
  under `<plugin>/models/`.
- `store.py` — persistence, publishing, rollback, and the cached read path.
- `theming.py` — token rendering, CSS validation, content hashing. Pure
  functions, no I/O, which is why it carries the densest test coverage.
- `authorization.py` — `StaffRole` allowlist checks.

### `canvas_theme_kit_demo` — reference consumer (page)

A standalone page at `/demo/page` that reads tokens and inlines them. Start here
when writing a consumer: it is the smallest complete example.

`/demo/tokens` reports what it can actually see. That exists because a page
rendering with fallback colors has three very different possible causes — a
missing namespace key, an unpublished theme, or genuinely empty tokens — and they
look identical on screen.

## Data model

Two CustomModels in the `canvas_theme_kit__themes` namespace.

```
Theme                          ThemeRevision
──────────────────────         ─────────────────────────────
slug          (unique)   ┌───< theme          (FK, CASCADE)
title                    │     revision       (int, unique per theme)
is_default               │     css
draft_css        ────────┘     tokens         (JSON)
draft_tokens (JSON)            content_hash
updated_at                     is_active
updated_by                     published_at
                               published_by
                               note
```

**The draft lives on `Theme` and is mutable. Published content lives on
`ThemeRevision` and never changes.** Publishing snapshots the draft into a new
revision. Rollback creates *another* new revision holding an old one's content —
history is append-only, so "who published what, when" survives every operation.

`is_active` marks the revision currently served. Exactly one per theme should
carry it, enforced in `_append_revision()` rather than by a database constraint,
because the SDK's supported constraint set has no conditional unique index. The
deactivate happens *before* the insert deliberately: a crash between the two
leaves zero active revisions (the asset route 404s, which is visible) rather than
two (a coin flip over which stylesheet the organization gets).

### Constraints that shape this schema

- **CustomModels key on `dbid`, not `id`.** `filter(id=…)` raises `FieldError`.
- **Tables and columns cannot be dropped once created**, which is why the schema
  is deliberately small.
- **`not null` and `max_length` are not enforced at the database level.** Every
  field carries a `default`, and validation lives in `theming.py`.
- **Models must live under `<plugin>/models/`** or no migration runs.

## Request flows

### Publishing

```
editor ──POST /admin/themes/<slug>/publish
          │
          ├─ StaffSessionAuthMixin      → reject non-staff
          ├─ Origin check               → reject cross-origin
          ├─ can_publish()              → reject non-publishers
          ├─ validate_css + tokens      → last gate before patient-facing pages
          ├─ deactivate current active revision
          ├─ insert new revision (content_hash from the bytes)
          └─ invalidate the plugin cache for this slug
```

Re-validating at publish rather than trusting the saved draft is deliberate: the
validator may have tightened since the draft was written, and this is the last
point before the content reaches a patient.

### Serving `core.css`

```
browser ──GET /assets/<slug>/core.css
           │
           ├─ session check
           ├─ store.published_css(slug)
           │    ├─ plugin cache hit?  → return (no DB)
           │    └─ miss → active revision → render → cache 60s
           ├─ ETag = sha256(bytes)[:32]
           ├─ If-None-Match matches (weak compare)? → 304
           └─ 200 + Cache-Control: private, max-age=300, stale-while-revalidate=86400
```

Read [caching.md](caching.md) before touching any of that. The header is
load-bearing and the failure mode is subtle.

### Consuming (the inline path)

```
consumer page render
   ├─ inline_tokens_css(slug)
   │     ├─ plugin cache hit? → return
   │     └─ miss → Theme by slug → active ThemeRevision → values_list("tokens")
   ├─ render <style>:root{…}</style> into <head>
   └─ <link> core.css after it
```

Token projection matters: a revision row can carry 256 KB of `css` that this path
never reads, and this runs on every render that misses cache.

## Cross-plugin data sharing

Consumers declare the same namespace with `read` access:

```json
"custom_data": { "namespace": "canvas_theme_kit__themes", "access": "read" },
"variables": [ { "name": "namespace_read_access_key", "sensitive": false } ]
```

and supply the key at install. Canvas refuses to load a plugin that declares
namespace access it cannot prove.

**Every plugin sharing the tables must declare identical model definitions.** The
`read_write` plugin creates them; `read` plugins query them. This is why
`models/__init__.py` is duplicated across the consumers rather than imported —
plugins cannot import each other's code.

Drift does not raise. It silently reads the wrong shape. Both consumers carry
`tests/test_model_mirror.py`, which compares the definitions structurally against
the publisher's and fails loudly.

`sensitive: false` on the key is intentional and comes from the SDK guidance: the
value has to stay readable in the admin UI, because that is how it gets copied
into a sibling plugin.

## Why namespace sharing instead of HTTP

The SDK offers both. HTTP would be looser coupling and avoid the duplicated
models. It does not work here:

1. **Cost.** Every SimpleAPI request is two plugin-runner dispatches on a runner
   shared with every other plugin on the instance. Putting that on a page render
   is the round trip the whole design exists to avoid.
2. **It would not authenticate.** The asset routes are session-gated, and a
   server-side call from another plugin carries no user session. It would 401.

## Caching layers

Three, doing different jobs. Confusing them is the easiest way to break this:

| Layer | Where | TTL | Invalidated by |
|---|---|---|---|
| Plugin cache | Canvas, server-side | 60s | Explicitly, on publish/rollback |
| Browser cache | Client | 300s + 24h stale | ETag revalidation |
| Consumer token cache | Canvas, server-side | 60s | TTL only |

The consumer token cache is **not** invalidated on publish — a consumer cannot
observe another plugin's writes. That is the real reason a published change takes
up to a minute to reach a server-rendered page, and it is an acceptable trade for
never touching the database on a render.

Every cache read and write is wrapped in try/except. A cache failure must degrade
to a slow page, never a broken one.

## Deliberate non-goals

- **No admin-editable JavaScript.** Stored XSS by design; see
  [security-model.md](security-model.md).
- **No restyling of Canvas chrome.** No SDK hook exists.
- **No dynamic theme resolution** (picking a theme per patient or location at
  render time). Multiple named themes exist; choosing between them at runtime
  needs a rule engine and nothing requires it yet.
- **No webfonts.** The default token set uses a system stack. Self-hosting fonts
  means base64-encoding them into the package, since the sandbox blocks
  filesystem reads, and `font-display: optional` only pays off once they are
  cached. Worth doing for a brand that needs it; not worth it by default.
