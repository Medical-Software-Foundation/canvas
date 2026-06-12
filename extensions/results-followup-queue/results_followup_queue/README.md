Results Follow-Up Queue
=======================

## Description

A global **provider companion app** that lists the lab and imaging results
awaiting the logged-in provider's review — so diagnostics don't slip through the
cracks. It's the bookend to the **Pre-Visit Brief** app: that one preps the start
of the visit, this one closes the loop afterward.

For the **ordering provider**, the queue shows every lab or imaging result that:

- has **no review record yet** (`review` is unset),
- is not junked / deleted / entered-in-error, and
- is not marked "review not required" (`review_mode != "RN"`).

Each row shows:

- **Patient name** — links to the patient chart (`/companion/patient/<key>`).
- **Type badge** — `Lab` or `Imaging`.
- **Result name** — the lab test name(s) or imaging study name.
- **Result values** — for labs, the discrete result values (name, value, units,
  reference range) are listed inline, with abnormal values highlighted in red.
  (Imaging has no discrete values, so none are shown.)
- **Result date** and **days pending**, with an aging highlight
  (≥ 7 days amber, ≥ 14 days red).
- **Abnormal badge** — for labs, when any lab value carries an abnormal flag.
  (Imaging has no structured abnormal flag, so it never shows the badge.)
- **Signature badge** — when the result requires a signature.

**Sort order:** abnormal results first, then oldest-pending first.

## How it works

- **Application** (`ResultsQueueApp`, scope `provider_companion_global`) adds the
  app to the companion drawer. Opening it launches a modal pointing at the
  plugin's API.
- **SimpleAPI** (`QueueAPI`, prefix `/app`) serves the HTML/JS/CSS shell and a
  `GET /data` endpoint that returns the JSON list of results for the logged-in
  provider (identified via the `canvas-logged-in-user-id` session header).
- Two bulk queries (one labs, one imaging) — no per-result queries, no N+1.
- No write actions: the app links the provider to the chart to perform the
  review natively.

## Installation

```bash
canvas install results-followup-queue
```

After installing, the **Results Follow-Up Queue** app appears in the provider
companion drawer. No secrets or configuration are required.

## Development

```bash
uv sync
uv run pytest        # run tests
uv run ruff check .  # lint
uv run mypy .        # type-check
```
