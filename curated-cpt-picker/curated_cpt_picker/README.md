# Curated CPT Picker

Speeds up CPT-code selection in the note footer by giving providers a curated
list of codes — not every entry in your `ChargeDescriptionMaster` — and a
polished admin app for maintaining that list.

## What it does

**For providers** — adds an **"Add CPT codes"** button to every note footer.
Clicking it opens a modal showing the curated CPT favorites that are currently
active in your CDM. Providers can check the codes they need, tweak units or
modifiers per row, hit "Add selected", and the codes appear as billing line
items on the note.

**For admins** — installs an **app drawer entry** (CPT Favorites) where
practice admins can add, edit, reorder, enable/disable, and remove favorite
codes. The CPT field is a dropdown of the currently active codes in your
ChargeDescriptionMaster — descriptions pre-fill from CDM and stay editable so
admins can supply a more provider-friendly label.

## How CDM validation works

A curated entry is considered usable when its CPT code has at least one
`ChargeDescriptionMaster` row where:

- `effective_date` is set and `<=` today
- `end_date` is null OR `>=` today

A null `effective_date` is treated as an invalid (misconfigured) CDM row.
This rule runs in two places — at admin save (rejects the entry with a 422)
and at modal open (silently filters out the entry). Codes can be added by
admins and later become invalid if their CDM record expires; the picker
handles that gracefully.

## Install

Install the plugin via the Canvas CLI from this directory's parent:

```bash
canvas install curated_cpt_picker
```

The first install creates a custom-data namespace called
`canvas_medical__curated_cpt_picker` and generates a
`namespace_read_write_access_key` secret that the plugin needs to read/write
its own `CuratedCptCode` table. Canvas sets that secret automatically.

## Configuration

| Secret | Default | Purpose |
|---|---|---|
| `namespace_read_write_access_key` | auto-generated at install | Lets the plugin access its custom-data namespace. Do not edit. |
| `ADMIN_STAFF_IDS` | empty | Optional. Comma-separated list of staff UUIDs allowed to use the admin app. |

### About `ADMIN_STAFF_IDS`

**When unset (default), any logged-in Canvas staff member can access the admin
app.** This is deliberate so the plugin works out-of-the-box without
configuration, but for production deployments you almost certainly want to
restrict it.

To restrict access, set `ADMIN_STAFF_IDS` in the plugin configuration page in
your Canvas admin UI to a comma-separated list of staff UUIDs:

```
ADMIN_STAFF_IDS=8f3a1c2b-...,d2e7f4a9-...,...
```

When the secret is set, only those staff IDs can list, create, edit, or delete
curated entries. Everyone else gets a 403.

A warning is logged on every admin request when `ADMIN_STAFF_IDS` is unset, so
you can spot unconfigured installs by tailing `canvas logs`.

## Architecture

```
curated-cpt-picker plugin
├── NOTE_FOOTER ActionButton ─────────► LaunchModalEffect ─► /picker
├── SimpleAPI /picker, /apply ────────► provider modal + AddBillingLineItem
├── Application (app drawer) ─────────► LaunchModalEffect ─► /admin
├── SimpleAPI /admin, /admin/codes ───► admin UI + CRUD with CDM validation
└── CuratedCptCode custom data model ─► persisted list of curated entries
```

## Known limitations

- **Picker lives alongside the standard footer dropdown.** Canvas does not
  expose an SDK effect to hide or replace the built-in code picker, so the
  curated picker appears as a second affordance. Future SDK work
  (`BILLING__CHARGE__POST_SEARCH_RESULTS` or similar) could close this gap.
- **One global curated list.** v1 ships a single list for the whole practice;
  per-role / per-note-type / per-provider lists are not supported.
- **No assessment linkage.** The picker only adds the CPT — it does not link
  to diagnosis codes (`assessment_ids`). Providers add diagnosis pointers in
  the standard footer UI as they do today.
- **No audit log of admin edits.** Entries have `created_at` / `updated_at`
  but no actor tracking; the standard Canvas plugin audit log captures the
  bare fact of edits.

## Development

```bash
# Install runtime + test deps
uv sync

# Run tests
uv run pytest

# Type check
uv run mypy curated_cpt_picker
```
