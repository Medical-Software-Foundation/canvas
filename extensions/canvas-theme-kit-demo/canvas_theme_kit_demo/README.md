# Canvas Theme Kit Demo

Reference consumer for [`canvas_theme_kit`](../../canvas-theme-kit). It exists to
demonstrate — and prove — the one thing that is hard to get right when sharing a
stylesheet between plugins: **rendering a page whose first paint already carries
the published design tokens.**

Apache-2.0.

## What it demonstrates

A page that links a stylesheet paints twice: once with browser defaults, and
again when the stylesheet arrives. That second repaint is the flash of unstyled
content.

This plugin avoids it by reading the active theme's tokens **at render time**,
straight out of the shared custom-data namespace, and inlining them into
`<head>` before the response is sent:

```html
<style>:root{--ctk-color-accent:#0b5fff;--ctk-space-4:1rem;…}</style>
<link rel="stylesheet" href="/plugin-io/api/canvas_theme_kit/assets/default/core.css" />
```

By the time the browser has the first bytes it knows the colors, spacing and
type. **No request has to complete for the first paint to be correct.** The
linked stylesheet fills in the rules behind it, cached and never blocking.

View source on the demo page — the first `<style>` block is the proof.

## Routes

| Route | Serves | Auth |
|---|---|---|
| `GET /demo/page` | the token-styled page | any logged-in session |
| `GET /demo/tokens` | what this plugin can see through the namespace | any logged-in session |

`/demo/tokens` exists to make failure legible. A page rendering with fallback
colors could mean a missing namespace key, an unpublished theme, or genuinely
empty tokens — three different problems that look identical on screen.

## Setup

Requires `canvas_theme_kit` installed first, with a published theme.

```bash
canvas install canvas_theme_kit_demo --host <instance> \
  --secret namespace_read_access_key=<the publisher's read key>
```

The install **fails without that key** — Canvas refuses to authorize a plugin
that declares namespace access it cannot prove. Note that `canvas install` prints
`uploaded!` and exits 0 even when the server-side install then fails, so check
`canvas logs` rather than the exit code.

## How it reads the tokens

Two things make this work, and both are constraints rather than choices:

**Identical model definitions.** `models/__init__.py` is a deliberate mirror of
the publisher's. The SDK requires every plugin sharing custom tables to declare
identical models — the `read_write` plugin creates them, `read` plugins query
them. Drift does not raise; it silently reads the wrong shape, which is why
`tests/test_model_mirror.py` compares the two structurally and fails loudly.

**Namespace sharing, not HTTP.** Fetching tokens over HTTP from the publisher
would cost a plugin-runner round trip on the render path — the very thing being
avoided. It also would not work: the publisher's asset routes are session-gated,
and a server-side call from another plugin carries no user session.

`tokens.py` caches the token map for 60 seconds, so a page render costs no
database round trip, and a published change reaches server-rendered pages within
a minute. It caches the map rather than the rendered block because the page uses
both; caching only the block left every render paying for the queries anyway.

## Sandbox constraints worth copying

Both were found the hard way, and neither is caught by `canvas validate` or by
unit tests — only by running on a real instance:

- **Import names, never modules.** `from x import y` then `y()`. Canvas's
  RestrictedPython forbids attribute access on a plugin's own modules, so
  `import x` then `x.y()` raises `AttributeError` at runtime.
- **Query through the manager, not a reverse accessor.**
  `ThemeRevision.objects.filter(theme=theme, ...)`, never `theme.revisions`,
  which returns `None` for CustomModels inside the sandbox.

`tests/test_sandbox_compatibility.py` AST-scans for the first and can be copied
into any Canvas plugin.

## Development

```bash
uv run pytest --cov=canvas_theme_kit_demo --cov-report=term-missing --cov-branch
canvas validate canvas_theme_kit_demo
```

On Windows, prefix with `PYTHONIOENCODING=utf-8` — `canvas validate` prints
Unicode status marks a cp1252 console cannot encode.
