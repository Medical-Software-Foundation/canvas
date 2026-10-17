# Security model

## Threat model

This plugin does not touch patient data. What it does is take **CSS authored by a
staff user and serve it to every page of every consuming plugin**, including
patient-facing portal pages.

So the risks worth thinking about are not data exposure. They are:

1. Who is allowed to publish.
2. What published content can do once it renders on a patient's page.
3. Availability — one bad stylesheet degrading every surface at once.

## Authorization

### Two role concepts, and picking the wrong one is the easy mistake

Canvas has two unrelated things called "roles":

- **`CareTeamRole`** — a per-patient care-team assignment ("who is on *this
  patient's* care team"). **Not an authorization construct.** This is what most
  instance-configuration reports list, which is exactly why it gets reached for.
- **`StaffRole`** — reachable as `staff.roles`, the staff member's actual role in
  the organization. This is the right one.

### Matching on `internal_code`, never `name`

```python
allowed = parse_role_codes(secrets.get("DS_EDITOR_ROLES"))
return bool(allowed & {r.internal_code for r in staff.roles.all()})
```

Display names can be renamed or localized by an organization. Matching on them
would let a rename silently grant or revoke access to every stylesheet in the
instance. Codes are short and opaque — a real instance had `AD`, `CD`, `EP`, `MD`
against names like "Administrative Developer".

`GET /admin/roles` lists them, because no instance-configuration export reliably
captures StaffRoles.

### Deny by default

Both allowlists are **empty on install**. An unconfigured plugin authorizes
nobody, including staff who hold every role in the organization.

This is deliberate and creates no bootstrap problem: the variables are set
through Canvas's plugin configuration page or `canvas config set`, both already
admin-gated and outside this plugin.

### Editing and publishing are separate

| Permission | Grants |
|---|---|
| `DS_EDITOR_ROLES` | Edit drafts, use preview, reset, load a revision into the draft |
| `DS_PUBLISHER_ROLES` | Publish, roll back |

A draft edit affects nobody. Publishing changes every consuming page in the
organization at once. When `DS_PUBLISHER_ROLES` is unset, publishing falls back
to the editor list — never to something wider, and never to "any staff member".

Verified live: a user holding `CD` with `DS_PUBLISHER_ROLES=AD` kept full edit
rights and lost publish, including a 403 from the API rather than merely a
greyed-out button.

### Per-route

| Route group | Gate |
|---|---|
| `/assets/*` | Any logged-in session (staff **or patient**) |
| `/preview/*` | `StaffSessionAuthMixin` + editor role |
| `/admin/*` mutating | `StaffSessionAuthMixin` + role + same-origin |
| `/admin/roles`, `/admin/ui` | Staff session only |

`/assets/*` uses a hand-written `authenticate()` returning any logged-in user.
The standard checklist flags that shape, and here it is correct: the published
stylesheet, token block and script are **organization design values containing no
patient data**, and patient portal pages are a primary consumer, so it cannot
narrow to staff.

`/admin/roles` is open to any staff session on purpose. Gating it on the editor
role would make an unconfigured install impossible to configure — you could not
discover the codes needed to grant yourself access. It exposes role names and
codes, which is organizational configuration, not patient data.

## Published content

### CSS is not inert

A stylesheet can make network requests. `@import` pulls in a remote stylesheet,
and a `url()` pointing off-origin issues a request the moment its rule matches —
enough to leak that a page was rendered, and with attribute selectors, something
about what was on it. From a patient-facing page that matters.

Both are rejected on save, again on publish, and again on rollback:

```python
validate_css(css)   # rejects @import; url() limited to same-origin and data:
```

The check is lexical, not a parser, and deliberately conservative — it can reject
an exotic-but-harmless stylesheet, which is the right trade for content published
to every consuming page at once. Specifically:

- Each `url(` is read to its real end, honoring quotes, rather than matched by a
  regex. A regex failed to *match* a quoted target containing `)` or the other
  quote, and a failed match meant nothing was checked. A `url()` that cannot be
  read to the end is rejected.
- `image-set()` is rejected. It takes a bare string as an image URL, so it can
  fetch without any `url()`.
- Backslash escapes are rejected. They can spell a scheme (`8ttps:`) or the
  function name (`=rl(`) in a form no lexical check recognizes.

Rollback re-validates for the same reason publish does: the validator may have
tightened since the content was saved, and replayed content is the oldest there
is. Without the check, rollback would be the way around it.

CSS comments are stripped before the rules run, so a stylesheet whose comment
explains that it avoids `@import` is not rejected for saying so. Comment bytes
still count toward the size limit, since they are stored and served.

### Tokens are constrained, not escaped

Token values are interpolated directly into a `:root` block, so a value carrying
`}` or `;` could close the rule and append arbitrary CSS. Names must match
`^[a-z0-9]+(?:-[a-z0-9]+)*$`; values reject `{`, `}`, `;`, `<`, `>` outright.
There is no legitimate token needing those characters, so rejecting beats
escaping.

Token values also go through the same fetch checks as the stylesheet. A token
reaches the page through `var()`, so a check that covered only the stylesheet
would let `url(https://…)` move into a token.

### No admin-editable JavaScript

`core.js` ships with the plugin and is versioned in the repository.

This was a deliberate scope reduction. Admin-authored JavaScript served into
patient portal sessions is a stored-XSS surface *by design*: one compromised
staff account becomes script execution on every patient page, and no amount of
review at publish time changes that. CSS and tokens only.

### Size limits

| Limit | Value |
|---|---|
| `MAX_CSS_BYTES` | 256 KB |
| `MAX_TOKENS` | 500 |
| Token name | 64 chars |
| Token value | 256 chars |

Published content is loaded into memory on every cache miss and served on every
consuming page. Without a cap, an editor could degrade the whole organization —
most plausibly by accident, since a paste gone wrong is not far-fetched. Size is
measured in **bytes**, not characters, so multibyte content cannot slip past.

## CSRF

Mutating routes authenticate on the Canvas session cookie. Whether that alone
resists CSRF depends on the instance's cookie policy, which a plugin cannot
inspect.

Django defaults to `SameSite=Lax`, which blocks cookies on cross-site POST. The
editor sends `Content-Type: application/json`, but the routes do not require it,
so it is not counted as a defense here.

Rather than depend on an unverified assumption, every mutating route rejects a
request whose `Origin` is present and not exactly the instance host. Requests
with **no** `Origin` are allowed — server-to-server callers omit it and are not
the threat.

The comparison is exact on the origin's host and port, case-insensitive. It was
once a suffix match, which accepted `https://evilacme.canvasmedical.com` for the
host `acme.canvasmedical.com`. That sibling is same-site, so `SameSite=Lax` would
not have stopped it either.

## Namespace access

The publisher holds `read_write`; consumers hold `read`, enforced by the
platform:

```
Plugin 'canvas_theme_kit_demo' has read-only access to namespace
  'canvas_theme_kit__themes' - skipping custom model table creation
```

A consumer cannot write to the shared tables even if its code tried.

Consumers hold only `namespace_read_access_key`. The read-write key belongs to
the publisher alone.

**Namespace keys are declared `sensitive: false`**, which looks wrong and is
correct: the SDK requires the value to stay readable in the admin UI, because
that is the supported way to copy it into a sibling plugin. Treat them as
deployment credentials — real, but scoped to reading one namespace, and useless
without an authenticated session to the instance.

## Audit trail

Every published revision records `published_by` and `published_at`. Rollback
republishes rather than rewrites, so the history of who published what survives
every operation. There is no code path that mutates or deletes a published
revision.

## Known limits

- **Tests mock the ORM.** No test would catch a field-name error or a query the
  sandbox rejects. See [canvas-sandbox.md](canvas-sandbox.md).
- **`/admin/roles` scans staff records** to collect distinct roles, since the SDK
  exposes no direct `StaffRole` manager. Bounded to 500, but it is a scan.
- **The CSS validator is lexical.** It is conservative by design, but it is not a
  CSS parser and does not claim to be.
- **Pre-login portal pages cannot load assets**, since the routes require a
  session. To serve them, make `ThemeAssets.authenticate` return `True`
  unconditionally — the assets carry no patient data. That is a deployment
  decision, not a default.
