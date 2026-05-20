# Order Sets

A Canvas plugin that lets providers apply predefined bundles of lab, imaging, and point-of-care (POC) orders to a patient chart with one click — instead of adding tests one by one.

## Problem it solves

Repeatedly placing the same group of orders (e.g. a diabetes workup, a sports physical lab panel, a standard chest workup) is slow and error-prone. Providers have to remember every test, look up CPT codes, and re-enter the same diagnosis codes and comments every visit. Order Sets bundles these into reusable templates that any active provider can apply in seconds.

## Who it's for

Primary care, urgent care, and specialty clinics whose providers repeatedly order the same group of tests. Admins curate practice-wide ("shared") sets; individual providers maintain their own personal favorites.

## Features

- **Shared & personal sets** — Practice-wide order sets managed by admins, plus personal favorites for each provider
- **Lab, imaging, & POC support** — One workflow for `LabOrderCommand`, `ImagingOrderCommand`, and `PerformCommand`
- **Preview before ordering** — Review and deselect individual items before confirming
- **Quick Order** — One click places every item in the set
- **Optional diagnosis codes** — Attach ICD-10 codes that flow through to every order in the set
- **Dynamic lab tests** — Tests pulled live from the instance's configured lab partners

## How to install

```sh
canvas install order_sets
```

After install, the **Order Sets** icon appears in the 9-box app drawer on every patient chart.

## Usage

1. Open a patient chart and click the **Order Sets** icon
2. Browse shared sets or personal favorites; filter by type (Lab / Imaging / POC)
3. Click **Quick Order** to place all items immediately, or **Preview** to customize
4. Use the gear icon to open the admin view and create/edit order sets

## Configuration

### `ADMIN_STAFF_IDS` (optional plugin secret)

Comma-separated list of staff UUIDs allowed to modify or delete order sets they did not create — for example, an operations admin maintaining the practice's shared sets.

```
ADMIN_STAFF_IDS=57f3668ea9f84f3980e772ea8451af38,a1b2c3d4e5f6...
```

Authorization model:

- **Create:** any authenticated staff member can create an order set (shared or personal).
- **Read:** every authenticated staff member sees all `is_shared=true` sets plus their own personal sets.
- **Update / delete:** allowed only if the caller is the original `created_by` *or* their id appears in `ADMIN_STAFF_IDS`. Fails closed: if the secret is unset or empty, only the creator can modify a set — shared sets stay editable by their original author until an admin list is configured.

The plugin also reads lab tests from the instance's configured lab partners and CPT codes from `ChargeDescriptionMaster` (when available in the SDK version installed). No other configuration is required.

## Architecture

- **Application handler** — 9-box app drawer entry point (`patient_specific` scope)
- **SimpleAPI handler** — REST endpoints for CRUD on order sets and order execution; persists via the plugin cache
- **Vanilla JS frontend** — Interactive UI for browsing, managing, and executing order sets

Order execution requires an open note on the patient. The plugin uses the note's ordering provider when present, and falls back to an explicit provider selection from the UI.

## Screenshots

_Screenshots TBD — capture the patient-chart "Order Sets" panel and the admin view before tagging a release._

## Running tests

```sh
uv run pytest
```

Tests use `canvas[test-utils]` and mock the Canvas SDK ORM via `pytest-mock`.
