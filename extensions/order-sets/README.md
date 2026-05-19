# Order Sets

A Canvas plugin that lets clinical staff select predefined bundles of lab, imaging, and point-of-care (POC) orders from the patient chart. Instead of adding tests one at a time, providers can apply a whole order set with a single click.

## What it does

Order Sets adds an "Order Sets" application to the patient chart's app drawer. Clicking it opens a browse view of shared (practice-wide) and personal (per-staff) order set favorites. From the browse view, a user can:

- **Quick-order** an entire set (every item is placed)
- **Preview** a set and deselect specific items before confirming
- **Manage** sets (create, edit, delete) through an admin view reached via the gear icon

Orders are placed against the patient's currently open note using the standard Canvas Lab, Imaging, and Perform commands.

## Problem it solves

Most clinics have a small number of order combinations they place repeatedly — annual physical lab panels, hypertension follow-up labs, urgent-care strep workups, pre-op imaging, etc. Without order sets, a provider has to add each test individually from inside an order command, every time. This is slow, error-prone (it's easy to forget one of the tests in a panel), and inconsistent across providers in the same practice.

Order Sets eliminates the per-encounter friction by letting clinics curate the standard panels they use, then place them with one click. It also surfaces the panel composition before ordering, so a provider can deselect tests that don't apply to a specific patient without rebuilding the whole panel.

## Who it's for

- **Providers** (MD, DO, NP, PA) who place the same combinations of labs/imaging frequently
- **Medical assistants and nurses** who place orders on behalf of a provider as part of standing orders or rooming workflows
- **Practice administrators** who want to standardize what their clinic orders for a given clinical scenario

The plugin is workflow-agnostic and works for primary care, urgent care, weight-management, behavioral health, and specialty practices that have repeatable lab/imaging panels.

## Features

- **Shared & personal sets** — Practice-wide sets editable by administrators; personal favorites editable only by the staff member who created them
- **Lab, imaging, and POC support** — Build sets for send-out labs, imaging studies, or in-office POC tests with CPT codes
- **Preview before ordering** — Review and deselect individual items before confirming
- **Quick order** — One-click ordering for trusted sets
- **Diagnosis codes** — Attach ICD-10 codes to orders automatically
- **Dynamic catalogs** — Lab tests pulled from your instance's configured `LabPartner`s; POC CPT codes from `ChargeDescriptionMaster`
- **Provider attribution** — Orders are placed under the logged-in provider's name; non-providers (MAs, nurses) must explicitly choose an ordering provider

## How to install

```
canvas install order_sets
```

After install, the **Order Sets** app appears in the patient-chart app drawer (9-box). No additional configuration is required.

## Configuration options

| Setting | Where | Notes |
|---|---|---|
| Plugin secrets | n/a | This plugin declares no secrets and requires no external credentials |
| Lab partners | Canvas instance config | Lab order sets pull tests from your instance's configured `LabPartner` records; managed in Canvas, not the plugin |
| POC catalog | Canvas instance config | POC sets search `ChargeDescriptionMaster` for CPT codes; managed in Canvas, not the plugin |
| Set visibility | Per-set, at create/edit time | "Personal Favorite" (visible only to creator) or "Shared (Practice-wide)" (visible to all staff, editable only by admins) |
| Admin permission | Canvas instance config | A staff member is treated as an admin (and can edit/delete shared sets) if they have any `StaffRole` with `domain == "ADM"` (Administrative) |

## Authorization model

- **Listing**: All authenticated staff see all shared sets. Personal sets are visible only to their creator.
- **Create**: Any authenticated staff can create personal or shared sets.
- **Update / delete**:
  - *Personal sets*: only the creator can update or delete
  - *Shared sets*: only staff with an Administrative role can update or delete
- **Ordering**: If the logged-in user is a Provider, orders are placed under their name. If the logged-in user is not a Provider (e.g., an MA), they must explicitly select an ordering provider; the order is then placed under the selected provider's name.

## Usage

**Ordering** (patient chart):

1. Open a patient chart with an open note and click the **Order Sets** icon in the app drawer
2. Browse shared sets or personal favorites; filter by type (Lab / Imaging / POC)
3. Click **Quick Order** to place all items immediately, or **Preview** to deselect items before confirming

**Managing order sets** (global, no patient chart required):

1. From the global app drawer, click the **Order Sets Admin** icon
2. Create, edit, or delete personal favorites and shared sets
3. The same admin view is also reachable from the in-chart browse view via the gear icon, as a convenience for admins who arrive via a patient chart

## Architecture

- **Patient-scoped app** (`applications/order_sets_app.py`) — `patient_specific` scope; hosts the in-chart browse / order flow
- **Global-scope admin app** (`applications/order_sets_admin_app.py`) — `global` scope; hosts the management UI for creating / editing / deleting order sets, with no patient context required
- **SimpleAPI handler** (`api/endpoints.py`) — Staff-authenticated REST endpoints for CRUD operations and order execution
- **Data model** (`models/order_set.py`) — `OrderSet(CustomModel)` Django-backed persistence (no cache, no TTL)
- **Vanilla JS frontend** (`static/js/`, `templates/`) — Interactive UI for browsing, managing, and executing order sets

## Screenshots

> Screenshots of the browse view, preview overlay, and admin form will be added to `assets/`.

## Running Tests

```
uv run pytest tests/
```

## License

MIT — see [LICENSE](LICENSE).
