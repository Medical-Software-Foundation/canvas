# Caching, and the flash of unstyled content

**Read this before changing a cache header.** The current policy looks
over-permissive and is not. Two of its properties are load-bearing, both are
pinned by tests, and the failure mode is a visible defect on every patient-facing
page rather than an error anyone gets paged about.

## The problem

A page that links a stylesheet paints twice: once with browser defaults, once
when the CSS arrives. On a phone over a slow connection the gap is long enough to
read. It looks broken, and on a patient portal it undermines trust in everything
else on the screen.

The instinct is to tighten cache headers so the browser always has the newest
CSS. That instinct makes it worse.

## Why the obvious headers are wrong

```
Cache-Control: no-cache          ← requires successful revalidation before reuse
Cache-Control: no-store          ← requires a full fetch every time
Cache-Control: must-revalidate   ← same, once stale
```

Every one of these puts a network round trip **in front of first paint**. The
header looks responsible. The page flashes on every single view.

This is not hypothetical. The plugin this design came from shipped
`no-cache, private` for three releases, and every portal page waited on a `304`
for the stylesheet, the script and each font before it could paint.

## What is used instead

```
Cache-Control: private, max-age=300, stale-while-revalidate=86400
ETag: "<32 hex chars of sha256(body)>"
```

- **Within 5 minutes:** no request at all.
- **After 5 minutes:** the browser paints from the stale copy *immediately* and
  revalidates in the background. Nothing blocks.
- **Bounded staleness:** at most a day, typically one page view.
- **`private`:** the routes are session-gated, so shared caches must not store
  them.

### Rule 1 — nothing may forbid serving stale

`no-cache`, `no-store` and `must-revalidate` are all banned from the published
policy. Each requires a successful validation before reuse, which reintroduces
the blocking round trip.

Pinned by `TestCachePolicy::test_published_policy_never_forbids_serving_stale`.

### Rule 2 — ETags must be compared weakly

Canvas's edge gzips `text/css` and, as a gzipping proxy must, marks the ETag weak
on the way out. The browser sends back `W/"<hash>"`.

```python
candidates = {v.strip().removeprefix("W/") for v in headers.get_list("If-None-Match")}
```

A verbatim comparison never matches, so every revalidation returns a full body
instead of a 304. Silent, and costly at scale.

Two details in that one line:

- `get_list`, not `get`. The SDK treats `If-None-Match` as list-valued; `get()`
  returns only the first tag and misses a match further down.
- `removeprefix("W/")` implements RFC 7232 §3.2 weak comparison.

Pinned by `TestConditionalGet::test_304_on_matching_weak_etag`.

### Rule 3 — ETags come from content, not version numbers

```python
etag = f'"{sha256(body).hexdigest()[:32]}"'
```

Derived from the response bytes, so it stays correct when someone publishes
without bumping anything — which is the normal case here, since publishing is a
runtime action.

## Why not `?v=` cache busting

A deploy-time token is wrong on both axes:

- **It changes when nothing changed.** Content changes on *publish*, not on
  redeploy. A redeploy-keyed token forces every user to re-fetch an identical
  file.
- **It does not change when something did.** Publishing does not redeploy the
  plugin.

And each change costs one cold, render-blocking fetch per user — the exact flash
this exists to remove.

**The exception: HTML pages.** The editor at `/admin/ui` sends
`private, no-cache`, because a stale editor after a redeploy makes a shipped fix
look like it did not ship. The correct fix for a document is to revalidate it,
not to fingerprint its URL. The editor is staff-only and off every patient-facing
path, so the revalidation costs nothing worth saving.

## The three layers

| Layer | Where | TTL | Invalidated by |
|---|---|---|---|
| Plugin cache | Canvas, server-side | 60s | Explicitly, on publish/rollback |
| Browser cache | Client | 300s + 24h stale | ETag revalidation |
| Consumer token cache | Canvas, server-side | 60s | TTL only |

The consumer cache is not invalidated on publish, because a consumer cannot
observe another plugin's writes. That is why a published change takes up to a
minute to reach a server-rendered page — an acceptable trade for never touching
the database during a render.

Every cache read and write is wrapped in try/except. A cache failure must degrade
to a slow page, never a broken one.

## Preview is the deliberate exception

```
GET /preview/<slug>/preview.css     Cache-Control: private, no-store
```

The editing admin must see their own change immediately. The route is staff-only
and low traffic, correctness beats latency, and it touches nothing on the
published path. This is what makes "instant preview, five-minute publish" work
without compromising the fast path.

## Inline critical CSS

Caching alone cannot fix the *first* visit — there is nothing in the cache yet.
That is what the inline token block solves:

```html
<style>:root{--ctk-color-accent:#0b6b78;…}</style>   ← rendered server-side
<link rel="stylesheet" href="…/core.css" />          ← cached, non-blocking
```

The token block is read from the shared namespace while the page renders, so the
first paint has correct colors and spacing with **zero network requests**.

Order matters: the inline block must come **before** the link, so the linked
stylesheet can override tokens rather than the reverse.

## Why round trips cost more here than on a static host

Each request to a SimpleAPI route is two plugin-runner dispatches
(`SIMPLE_API_AUTHENTICATE`, `SIMPLE_API_REQUEST`), each doing session auth plus a
render and a hash, on a runner shared with every other plugin on the instance.

Under `max-age=0`, a page touching the stylesheet, the script and three fonts
costs ten dispatches per view to return empty `304`s. Under the current policy a
navigation within five minutes costs none.

## If you are tempted to change this

1. Read this document.
2. Run the tests in `tests/handlers/test_assets.py` — the assertions state their
   reasoning inline.
3. Verify on a real instance with DevTools open. Watch for `200 (from disk
   cache)` within the TTL and `304 Not Modified` after it. A `200` with a real
   body on every reload means the ETag comparison is broken.
