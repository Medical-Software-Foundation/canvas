# Design decisions

Why things are the way they are. Read the relevant entry before changing
something here — most of these look arbitrary until you know what they cost.

---

### Admins edit CSS and tokens, not JavaScript

The original scope was CSS *and* JS. It was cut.

Admin-authored JavaScript served into patient portal sessions is a stored-XSS
surface by design: one compromised staff account becomes script execution on
every patient page, and no amount of review at publish time changes that.

`core.js` ships with the plugin and is versioned here. If a consumer needs
behavior, it ships behavior through code review.

**Revisit if:** there is a strong case *and* a sandboxing story. "Admins are
trusted" is not one — the threat is a compromised account, not a malicious
colleague.

---

### Namespace sharing, not HTTP, for cross-plugin reads

The SDK offers both. HTTP would mean looser coupling and no duplicated models.

It does not work here:

1. Every SimpleAPI request is two plugin-runner dispatches on a runner shared
   with every other plugin. On a page render that is the round trip the entire
   design exists to avoid.
2. It would not authenticate: the asset routes are session-gated, and a
   server-side call from another plugin carries no user session. 401.

The cost is real — every consumer duplicates `models/__init__.py` and must keep
it identical. That is why both consumers carry `test_model_mirror.py`.

---

### ETag + `stale-while-revalidate`, not `?v=` cache busting

A deploy-time token changes when nothing changed (redeploys) and does not change
when something did (publishes), and each change costs a cold render-blocking
fetch per user.

Full reasoning in [caching.md](caching.md). Do not "fix" the cache headers
without reading it.

---

### Editing and publishing are separate permissions

A draft edit affects nobody. Publishing changes every consuming page in the
organization at once. Splitting them costs almost nothing up front and means
retrofitting never requires re-auditing every route.

When `DS_PUBLISHER_ROLES` is unset it falls back to the editor list — never
wider, never "any staff member".

---

### Deny by default, with `/admin/roles` open to any staff session

Both allowlists are empty on install, so an unconfigured plugin authorizes
nobody.

That would be unusable if role discovery were also gated — you could not find the
codes needed to grant yourself access. So `/admin/roles` requires only a staff
session. It exposes role names and codes: organizational configuration, not
patient data.

The bootstrap otherwise has no answer. The keys live in a Django admin page many
operator accounts cannot reach.

---

### Roles match on `internal_code`, never display name

Display names get renamed and localized. Matching on them means a rename
silently grants or revokes access to every stylesheet in the instance.

Real instance codes were `AD`, `CD`, `EP`, `MD` against names like
"Administrative Developer" — so the mistake is easy to make and the symptom is
delayed.

---

### Rollback republishes; it does not restore the draft

Rolling back to revision 3 produces revision 7 with revision 3's content. History
is append-only, so the record of who published what survives everything.

It deliberately leaves the draft alone. That surprised people during testing —
the preview shows the draft, so rollback "looked like it did nothing." The fix
was making the UI state which revision is live, and adding **Load** to pull a
revision into the draft, rather than changing rollback's semantics.

---

### "Reset draft" exists because rollback cannot cover it

Rollback only replays *published* revisions. A draft mangled before the first
publish had no way back short of retyping every token. Reset restores the shipped
starter set. Draft-only, editor permission, nothing published changes.

---

### Content-derived ETags, not version numbers

```python
etag = f'"{sha256(body).hexdigest()[:32]}"'
```

Publishing is a runtime action, so a version-derived ETag would be stale in the
normal case. Deriving from the bytes stays correct when someone publishes without
bumping anything.

---

### Deactivate before insert when publishing

A crash between the two writes leaves zero active revisions — the asset route
404s, which is visible and debuggable — rather than two, which is a coin flip
over which stylesheet the organization gets.

"Exactly one active revision" is enforced in code rather than by a constraint
because the SDK's supported constraint set has no conditional unique index.

---

### Size limits on published content

256 KB of CSS, 500 tokens. Published content is loaded into memory on every cache
miss and served on every consuming page, so an oversized stylesheet degrades the
whole organization at once — most plausibly by accident.

Measured in bytes, not characters, so multibyte content cannot slip past.

---

### The CSS validator strips comments before checking

Found by writing the first real theme for this plugin: the validator rejected it
because the file's opening comment *explained* that it avoids `@import`.

CSS comments are inert, so they are stripped before the rule checks. Their bytes
still count toward the size limit, since they are stored and served. A real
`@import` after a comment is still rejected.

---

### The CSS validator scans `url()` rather than matching it

A security review found that the original `url()` regex could be bypassed. A
quoted target containing `)` or the other quote failed to match, and a failed
match meant nothing was checked. `image-set()` and backslash escapes fetched
without the regex ever seeing a `url()`.

`url()` is now read to its real end, and anything that cannot be read to the
end is rejected. `image-set()` and backslash escapes are rejected outright. The
shipped themes use neither, and a design system has no need for them that
`url()` and plain characters do not cover. Token values get the same checks,
because they reach the page through `var()`.

---

### Origin check rather than trusting `SameSite`

Mutating routes authenticate on the session cookie. Whether that resists CSRF
depends on the instance's cookie policy, which a plugin cannot inspect.

Requests with a foreign `Origin` are rejected. Requests with **no** `Origin` are
allowed — server-to-server callers omit it and are not the threat.

The match is exact on host and port. A suffix match accepted any host ending
with the instance's name, which is same-site and so not covered by `SameSite`.

---

### The editor is reachable at a plain URL

`global` scope applications are only visible *outside* a patient chart, which is
easy to miss entirely — during development the app could not be found at all.
`/admin/ui` always works for a logged-in staff member.

It is also registered at `provider_menu_item` scope, which is far more
discoverable than the app drawer. Scope is per manifest entry, not per class,
which is why there are two application classes.

---

### Neutral defaults, `--ctk-` prefix

The plugin ships brand-neutral starter tokens and a neutral prefix rather than
inheriting any one organization's design system, because it is meant to be
installed by others. `harbor` is a real theme built on it, not a default.

---

### No dynamic theme resolution

Multiple named themes exist and are independently versioned. Choosing between
them per patient or per location at render time needs a rule engine and nothing
requires it yet. Routes are already slug-scoped, so adding it later does not
break the URL shape.

---

### No webfonts by default

Self-hosting a font means base64-encoding it into the package, because the
sandbox blocks filesystem reads. And `font-display: optional` — the only value
that guarantees a single paint — only pays off once the font is cached, so the
first visit renders in the fallback stack regardless.

A system stack has nothing to fetch and nothing to wait for. Worth revisiting for
a brand that requires a specific typeface; not worth it by default.
