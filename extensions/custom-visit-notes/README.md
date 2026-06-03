# Custom Visit Notes

A configurable free-text notes tab on encounter notes, backed by Custom Data.

## How is this different from Private Notes and Sticky Notes?

Canvas has three built-in ways to capture unstructured text. They serve different purposes:

| | **Private Notes** | **Sticky Notes** | **Custom Visit Notes** |
|---|---|---|---|
| **Lives on** | The note (encounter) | The patient chart | The note (encounter) |
| **Persists in** | The note body | Custom Data (patient-scoped) | Custom Data (note-scoped) |
| **Visible to** | Only the author | Shared + personal per staff | All staff with chart access |
| **Best for** | Personal reminders while charting | Cross-visit context ("prefers morning appts", "allergic to latex gloves") | Visit-specific documentation that doesn't belong in the clinical note |

**Private Notes** are part of the note itself — they live inside the encounter and are tied to the note lifecycle. They're personal to the author and aren't visible to other providers.

**Sticky Notes** are attached to the *patient*, not a specific visit. They persist across encounters and are great for operational context that follows the patient everywhere. They use Custom Data with a patient FK.

**Custom Visit Notes** fills the gap between the two: documentation tied to a *specific visit* that is persistent, visible to the care team, and lives outside the clinical note structure. Think therapy session notes, counseling observations, social work assessments, or any free-text documentation that should be associated with one encounter but doesn't fit into standard note commands. It uses Custom Data with a note FK, so the content survives note edits, page refreshes, and deploys.

## Configuration

Set the `tab_name` secret to customize the tab label for your use case:

| Use case | `tab_name` value |
|----------|-----------------|
| Behavioral health | `Therapy Notes` |
| Care coordination | `Care Notes` |
| Social work | `Session Notes` |
| General | `Visit Notes` |

## Installation

```
canvas install custom_visit_notes --host <your-instance>
```

Then set the `tab_name` secret in **Settings > Plugins > Custom Visit Notes > Secrets**.

## Storage

Uses Custom Data (`custom_visit_notes__data` namespace) with a `VisitNote` model:

| Field | Type | Purpose |
|-------|------|---------|
| `note` | OneToOneField (Note) | Which encounter note (primary key) |
| `content` | TextField | Free-text note content |
| `updated_at` | DateTimeField | Auto-updated on each save |

## API Endpoints

- `GET /notes/app?note_id=<uuid>` — renders the notes UI with current content
- `GET /notes/load?note_id=<uuid>` — returns note content as JSON
- `POST /notes/save?note_id=<uuid>` — saves or updates note content

## Secrets

- `tab_name` — display name for the notes tab (default: "Visit Notes")
