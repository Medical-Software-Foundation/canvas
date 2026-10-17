# Writing a consumer plugin

How to style your own Canvas plugin with published tokens.

A working example ships alongside this plugin:
[`canvas-theme-kit-demo/`](../../canvas-theme-kit-demo), a page served by its own
plugin. Copy it and change the page.

## 1. Join the namespace

In your `CANVAS_MANIFEST.json`:

```json
{
  "custom_data": {
    "namespace": "canvas_theme_kit__themes",
    "access": "read"
  },
  "variables": [
    { "name": "namespace_read_access_key", "sensitive": false }
  ]
}
```

Install with the key:

```bash
canvas install my_plugin --host <instance> \
  --secret namespace_read_access_key=<the publisher's read key>
```

Canvas refuses to load a plugin that declares namespace access it cannot prove.
Hold only the **read** key; the read-write key belongs to the publisher.

## 2. Mirror the models

Copy `canvas_theme_kit/models/__init__.py` into your plugin as
`<your_package>/models/__init__.py`, unchanged.

**The SDK requires every plugin sharing custom tables to declare identical model
definitions.** The `read_write` plugin creates them; `read` plugins query them.
Plugins cannot import each other's code, so this is a copy rather than an import.

Drift does not raise — it silently reads the wrong shape on a live page. Copy
`tests/test_model_mirror.py` too; it compares the definitions structurally
against the publisher's and fails loudly.

## 3. Read the tokens

Copy `canvas_theme_kit_demo/tokens.py`. It gives you:

```python
inline_tokens_css(slug)   # ":root{--ctk-color-accent:#0b6b78;…}"  cached 60s
active_tokens(slug)       # {"color-accent": "#0b6b78", …}
```

Two details in there are not stylistic:

```python
from canvas_theme_kit_demo.models import Theme, ThemeRevision   # names, not modules

tokens = (
    ThemeRevision.objects                       # manager, not theme.revisions
    .filter(theme=theme, is_active=True)
    .order_by("-revision")
    .values_list("tokens", flat=True)           # projected, not hydrated
    .first()
)
```

- Import **names**, never modules — the sandbox forbids attribute access on your
  own plugin's modules.
- Query through the **manager** — a reverse accessor on a CustomModel returns
  `None` in the sandbox.
- **Project** with `values_list` — a revision row carries up to 256 KB of `css`
  this path never reads, and this runs on every render that misses cache.

See [canvas-sandbox.md](canvas-sandbox.md).

## 4. Render it

```python
return [
    HTMLResponse(
        render_to_string("templates/page.html", {
            "ctk_tokens_css": inline_tokens_css("default"),
        })
    )
]
```

```html
<head>
  <!-- 1. Inline tokens: correct first paint, zero network requests -->
  <style>{{ ctk_tokens_css|safe }}</style>

  <!-- 2. Your own rules, written against the tokens -->
  <style> .btn { background: var(--ctk-color-accent, #0b5fff); } </style>

  <!-- 3. The full published stylesheet: cached, never blocking -->
  <link rel="stylesheet" href="/plugin-io/api/canvas_theme_kit/assets/default/core.css" />
</head>
```

**Order matters.** The inline block must come before the link, so the linked
stylesheet can override tokens rather than the reverse.

**Always pass a fallback** — `var(--ctk-color-accent, #0b5fff)` — so your page
still renders sensibly against a theme that omits a token, or before one is
published.

The stylesheet URL is same-origin, so you need no `url_permissions` entry. An
external host would.

## Portal widgets are different

Widgets render into the portal page itself, not an iframe, so they cannot rely on
a `<link>` resolving. Everything travels inline with the markup:

```python
content=render_to_string("templates/widget.html", {
    "ctk_tokens_css": inline_tokens_css("default"),
})
```

```html
<style>{{ ctk_tokens_css|safe }}</style>
<style>
  .my-widget { background: var(--ctk-color-bg, #fff); … }
</style>
<div class="my-widget">…</div>
```

Read the token block **once per event** and pass it to every widget. It is
cached, but two cache reads per portal load is still one more than needed.

Prefix your widget classes. Widgets share a DOM with the portal and every other
plugin's widgets.

## Available tokens

Whatever the theme publishes — the set is not fixed. The shipped starter set and
the bundled `harbor` theme both define:

```
color-bg  color-surface  color-fg  color-fg-muted  color-border  color-border-strong
color-accent  color-accent-strong  color-accent-subtle  color-accent-contrast
color-success  color-warning  color-danger  (+ -subtle variants)

font-family  font-family-mono
font-size-xs … font-size-2xl
font-weight-regular  font-weight-medium  font-weight-bold
line-height-tight  line-height-base  letter-spacing-wide

space-1 … space-12
radius-sm  radius-md  radius-lg  radius-pill
shadow-sm  shadow-md
control-height  measure
```

Every one becomes `--ctk-<name>`.

## Checklist

- [ ] Namespace declared `read`, key supplied at install
- [ ] Models mirrored verbatim, mirror test copied
- [ ] `tests/test_sandbox_compatibility.py` copied
- [ ] Names imported, not modules
- [ ] Queries through the manager, projected with `values_list`/`values`
- [ ] Inline token block before the stylesheet link
- [ ] Every `var()` has a fallback
- [ ] Verified in the log: `Successfully loaded plugin … (N/N handlers loaded)`
