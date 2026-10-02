# Canvas Theme Kit

Admin-editable CSS and design tokens for Canvas plugins, served with caching
tuned so pages never flash unstyled.

One plugin owns the stylesheet. Every other plugin links to it. An authorized
staff member edits and publishes it from the Canvas UI — no redeploy, no
version bump, no code change in the consumers.

Apache-2.0.

## What it does

- **One shared stylesheet and token set** for all your Canvas plugins.
- **A staff-gated editor** reachable from the provider menu, the app drawer, or
  directly at `/plugin-io/api/canvas_theme_kit/admin/ui`: edit CSS and design
  tokens, preview instantly, publish when ready.
- **Multiple named themes**, each independently versioned.
- **Revision history with rollback**, because one bad stylesheet affects every
  consuming page at once.
- **No flash of unstyled content**, which is most of the engineering here.

## What it does not do

- **It cannot restyle Canvas's own UI.** There is no SDK hook to inject CSS or
  JavaScript into Canvas chrome. Styling reaches only HTML that plugins render:
  `PortalWidget` content, `Application` / `LaunchModalEffect` iframes,
  `portal_menu_item` apps, and SimpleAPI-served pages.
- **It does not let admins edit JavaScript.** `core.js` ships with the plugin and
  is versioned in the repository. Admin-authored JavaScript served into patient
  portal sessions would be a stored-XSS surface by design, where one compromised
  staff account becomes script execution on every page.

## How the flash is avoided

Three layers, and each one matters:

1. **Inline critical CSS.** A consuming plugin reads the active revision's tokens
   from the shared custom-data namespace at render time and inlines a `:root`
   block into `<head>`. First paint has the right colors and spacing with **zero
   network requests**.
2. **A non-blocking stylesheet.** `core.css` is served
   `private, max-age=300, stale-while-revalidate=86400`. The browser paints from
   cache and revalidates in the background. **Nothing in that policy may forbid
   serving stale** — `no-cache`, `no-store` and `must-revalidate` each require a
   successful revalidation before reuse, which puts a round trip back in front of
   first paint while the header still looks reasonable. That is the flash.
3. **Weak ETag comparison.** Canvas's edge gzips `text/css` and, as a gzipping
   proxy must, marks the ETag weak. The browser sends back `W/"<hash>"`. A
   verbatim comparison never matches, so every revalidation returns a full body
   instead of a 304.

Points 2 and 3 are pinned by tests. Treat them as load-bearing.

An editor's own preview deliberately uses `no-store`, so they see their change
immediately. Everyone else gets it through the cached path within about five
minutes. That is the whole "instant preview, five-minute publish" design.

## Setup

### 1. Install

```bash
canvas install canvas_theme_kit --host <instance>
```

Installing initializes the `canvas_theme_kit__themes` custom-data namespace.

**Supply both namespace keys on that first install.** Canvas will generate them
otherwise, but the only supported way to read a generated key back is the Django
admin plugin page — which many operator accounts cannot reach, and without the
read key no consumer plugin can be installed at all:

```bash
canvas install canvas_theme_kit --host <instance>   --secret namespace_read_access_key=$(uuidgen)   --secret namespace_read_write_access_key=$(uuidgen)
```

Both keys must be supplied together or Canvas ignores them and generates its own.
Store them outside Canvas: uninstalling a plugin deletes its secrets while the
namespace survives, so a copy kept elsewhere is the only way to regain access.

### 2. Grant access

**Nobody is authorized until you configure this.** Both allowlists are empty by
default, which is deliberate — an unconfigured install is inert rather than open.

Access is granted by `StaffRole.internal_code`. To discover the codes on your
instance, open the app and call:

```
GET /plugin-io/api/canvas_theme_kit/admin/roles
```

Then set the variables from the Canvas plugin configuration page, or:

```bash
canvas config set canvas_theme_kit DS_EDITOR_ROLES=designer,admin
canvas config set canvas_theme_kit DS_PUBLISHER_ROLES=release-manager
```

- `DS_EDITOR_ROLES` — edit drafts and use preview.
- `DS_PUBLISHER_ROLES` — publish and roll back. Falls back to `DS_EDITOR_ROLES`
  when unset, never to something wider.

Editing and publishing are separate on purpose: a draft edit affects nobody,
while publishing changes every consuming page in the organization at once.

> **Do not gate on `CareTeamRole`.** It is a per-patient care-team assignment,
> not an authorization construct, and it is what most instance-configuration
> reports list. `StaffRole` is the right one.

### 3. Create a theme

Open **Theme Kit** from the provider menu (or go straight to
`/plugin-io/api/canvas_theme_kit/admin/ui`). Click **+ New** — the theme seeds
from a brand-neutral starter token set. Edit, preview, publish.

## Consuming from another plugin

Declare read access to the shared namespace in the consumer's manifest:

```json
"custom_data": {
    "namespace": "canvas_theme_kit__themes",
    "access": "read"
},
"variables": [
    { "name": "namespace_read_access_key", "sensitive": false }
]
```

Hold only the **read** key in a consumer. The read-write key belongs to
`canvas_theme_kit` alone.

Then copy `templates/base.html` from this plugin into the consumer as its own
`templates/base.html`. Canvas resolves templates against a hard plugin-directory
boundary (`Engine(dirs=[plugin_dir])`, which raises `PermissionError` on any
path that escapes it), so a consumer cannot extend a template across the
boundary. What crosses is the CSS and the shared data, not the template.

That file documents the render-time token read, including the short-lived cache
that keeps a page render off the database.

## Routes

| Route | Serves | Auth |
|---|---|---|
| `GET /assets/<slug>/core.css` | published stylesheet | any logged-in session |
| `GET /assets/<slug>/tokens.css` | `:root` token block only | any logged-in session |
| `GET /assets/core.js` | shared script | any logged-in session |
| `GET /preview/<slug>/preview.css` | current draft, uncached | staff + editor role |
| `GET /admin/ui` | the editor page | staff session |
| `GET /admin/roles` | StaffRoles and your permissions | staff session |
| `GET /admin/themes` | theme list | editor |
| `GET /admin/themes/<slug>` | theme, draft and history | editor |
| `POST /admin/themes` | create a theme | editor |
| `POST /admin/themes/<slug>/draft` | save a draft | editor |
| `POST /admin/themes/<slug>/publish` | publish the draft | publisher |
| `POST /admin/themes/<slug>/reset-draft` | restore the starter tokens | editor |
| `POST /admin/themes/<slug>/load-draft` | copy a revision into the draft | editor |
| `POST /admin/themes/<slug>/rollback` | republish an old revision | publisher |

Published assets are session-gated, so pre-login surfaces (portal login,
registration, password reset) cannot load them. To serve those, make
`ThemeAssets.authenticate` return `True` unconditionally — the assets carry no
patient data. That is a deployment decision, not a default.

## Security notes

- **CSS is not inert.** Published CSS is validated on save, publish and
  rollback: `@import`, `image-set()` and backslash escapes are rejected, and
  `url()` is restricted to same-origin paths and `data:` URIs. Otherwise a
  stylesheet could beacon to a third party from every patient-facing page it
  renders on.
- **Token values are constrained, not escaped.** They are interpolated into a
  `:root` block, so `{`, `}`, `;`, `<` and `>` are rejected outright. They pass
  the same `url()` checks as the stylesheet, since `var()` carries them into it.
- **Publishing is audited.** Every revision records who published it and when.
  Rollback republishes rather than rewrites, so the history stays complete.
- **Published content is size-capped** at 256 KB of CSS and 500 tokens. It is
  loaded into memory on every cache miss and served on every consuming page, so
  an oversized stylesheet degrades the whole organization at once.
- **Mutating routes are same-origin only**, compared exactly on host and port. They authenticate on the session
  cookie, and whether that alone resists CSRF depends on the instance's cookie
  policy, which a plugin cannot inspect. Requests carrying a foreign `Origin`
  are rejected; requests with no `Origin` are allowed, since server-to-server
  callers omit it and are not the threat.

## Draft versus published

Worth understanding before using the editor, because the two are deliberately
separate and it is the one thing that confuses people:

- The **preview pane renders your draft.** Saving a draft changes nothing anyone
  else sees.
- **Publish** snapshots the draft as a new revision and is what changes
  `core.css`.
- **Roll back** republishes an older revision. It changes what is live and
  deliberately leaves your draft alone — so the preview does not change, which
  looks like nothing happened. Use **Load** to pull a revision back into the
  draft.
- **Reset draft** restores the shipped starter tokens. Rollback cannot do this:
  it only replays published revisions, so a draft mangled before the first
  publish would otherwise be unrecoverable.

The editor states which revision is live beneath the preview.

## Development

```bash
uv run pytest --cov=canvas_theme_kit --cov-report=term-missing --cov-branch
canvas validate canvas_theme_kit
```

On Windows, prefix with `PYTHONIOENCODING=utf-8` — `canvas validate` prints
Unicode status marks that a cp1252 console cannot encode.
