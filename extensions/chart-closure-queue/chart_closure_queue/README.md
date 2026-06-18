# Chart-Closure Queue

A global provider companion app that gives the logged-in clinician one compact, aged worklist of **their own open/unsigned notes** that still need to be locked — closing the documentation loop for the visit.

## What it does

When a provider opens the Chart-Closure Queue from the companion launcher, a modal lists every note that is **theirs** and is still in an open (lockable) state, ordered **oldest date-of-service first** so the most overdue work is at the top. Each row shows:

- **Patient name** — deep-links to the patient's companion chart (opens with `target="_top"` so it replaces the modal rather than nesting an iframe)
- **Note title / type**
- **Date of service**
- **Days open** — calendar days between the date of service and today, in the provider's local timezone
- **Current state** — a friendly label such as *New*, *Unlocked*, *Checked in*, *Charges pushed*, *Restored*, or *Undeleted*

Rows are color-coded by age: a left border and pill turn **amber** at the warning threshold and **red** at the overdue threshold. When the queue is empty the modal shows *"No open notes — you're all caught up."*

The app is **read-only**: it never mutates the chart. It is the documentation-loop bookend to the Pre-Visit Brief (preps the start of the visit) and the Results Follow-Up Queue (closes the diagnostic-result loop).

## How it decides what's "open"

A note appears when its current state (`CurrentNoteStateEvent.state`) is one of the lockable states — `NEW`, `PUSHED`, `CONVERTED`, `UNLOCKED`, `RESTORED`, `UNDELETED` — which mirrors the SDK's own `CurrentNoteStateEvent.editable()` definition. Locked / signed / deleted notes and the appointment-lifecycle states (scheduling, booked, cancelled, no-show, etc.) are excluded. Future-scheduled notes (date of service after today) are excluded as well.

## Problem it solves

Notes left unlocked after an encounter delay billing, break care continuity, and create compliance risk. Canvas surfaces an aggregate, cross-provider *locked-note* report (`note-production-dashboard`), but there is no personal, actionable "these are mine and still open" view in the companion surface. Chart-Closure Queue is that view: a provider opens it between visits or at the end of the day and works the list top-down.

## Who it's for

- **Any provider** who authors encounter notes and is responsible for locking them
- The list is scoped strictly to the **logged-in provider** via the non-spoofable `canvas-logged-in-user-id` session header, so a non-authoring user sees an empty list rather than anyone else's notes

## How to install

```bash
canvas install chart_closure_queue
```

After install, the app appears as **Chart-Closure Queue** in the provider companion launcher at `/companion/`.

## Configuration

Two optional secrets control the aging thresholds (both measured in *days open*):

| Secret | Default | Meaning |
|---|---|---|
| `AGING_AMBER_DAYS` | `2` | Rows at or above this many days open are highlighted **amber** |
| `AGING_RED_DAYS` | `4` | Rows at or above this many days open are highlighted **red** |

Unset, non-numeric, or negative values fall back to the defaults. Set them on the plugin configuration page (`<emr_base_url>/admin/plugin_io/plugin/<plugin_id>/change/`).

The browser computes the local-timezone end-of-today and sends it to the server, so the date-of-service cutoff and the days-open count always track the provider's local clock — no server-side timezone configuration is needed.

## Architecture

| Component | Class | Role |
|---|---|---|
| Application | `ChartClosureApp` | Opens the modal from the companion launcher |
| SimpleAPI | `ClosureAPI` | Serves the HTML shell, static assets, and JSON data |

All notes are fetched in a **single bulk query** against `CurrentNoteStateEvent`, with `select_related` across the note's patient, note-type version, and provider — a constant query count with no N+1. The query is scoped to the authenticated provider and never accepts a client-supplied provider id; if the staff header is missing the endpoint fails closed with a 400 and returns no data.

## Refreshing data

Close and reopen the modal. Each open triggers a fresh fetch against the current local day.
