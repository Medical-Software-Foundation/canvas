# Clinical Pathways

A Canvas plugin for building structured, branching clinical questionnaires ("pathways") and running them against a patient during a note encounter.

## What it does

- **Pathway Builder** — A page application reachable from the provider menu where any authenticated staff user can author pathways: segments, questions (yes/no, multiple choice, free text, numeric), branching rules between segments, and a free-text recommendation shown at completion.
- **Pathway Runner** — A note tab application that lets a provider search pathways by title, step through segments with the engine evaluating branch rules from each segment's responses, and on completion originate two custom commands into the open note: the full Q&A trail and the pathway recommendation.

## Surfaces

| Surface | Scope | Entry |
|---|---|---|
| Pathway Builder | `provider_menu_item` | Provider menu → "Pathway Builder" |
| Pathway Runner | `note_application` | Open note → "Clinical Pathways" tab |

## Data

Pathway definitions are stored as plugin-owned [CustomModels](https://docs.canvasmedical.com/sdk/custom-data-custom-models/) in the namespace `canvas__clinical_pathways`. Completed runs are persisted only as note `CustomCommand` blocks — no separate run-history table.

## Limitations (v0.1.0)

- No pathway versioning; edits are live in-place.
- Search matches pathway title only.
- Recommendation is a single free-text block (no structured fields, no ICD/order linkage).
- Any authenticated staff user can edit any pathway (no role restrictions).
- No patient-facing surfaces.
