# Staff Directory

A Canvas plugin that stores and displays detailed professional information for every staff member in your organization: education history, clinical training, NUCC-coded specialties, and board certifications with expiration tracking.

## Installation

```bash
canvas install staff_directory
```

## What it does

- **Staff Directory** app in the main Canvas app menu.
- Two-pane layout: staff list on the left, detailed profile on the right.
- Four profile sections per staff member:
  - Education (medical school, degrees, graduation year)
  - Clinical training (residencies, fellowships, internships)
  - Specialties (from the NUCC Healthcare Provider Taxonomy)
  - Board certifications (with issue/expiration dates and expiration alerts)
- Live search across names, roles, and specialties.
- "Expiring certifications only" filter for quick oversight.
- Admins can add/edit/remove entries; non-admins can view only.

## Who can edit

By default, only users with the `ADMIN` or `OWNER` role code can edit profiles.
Configure which role codes count as "admin" with the `ADMIN_ROLE_CODES` secret
(comma-separated list). For example: `ADMIN,OWNER,MD,DO,NP,PA`.

## Configuration

- **Secret `ADMIN_ROLE_CODES`** (optional): comma-separated staff role codes allowed to edit. Defaults to `ADMIN,OWNER`. Case-insensitive.

## How staff members are linked

This plugin extends Canvas's built-in `Staff` records. No staff data is duplicated - the profile entries all point at existing staff via a proxy model. Deleting or deactivating a staff record in Canvas leaves the profile entries in place (they're not auto-cascaded) to preserve audit history.

## NUCC taxonomy

The plugin ships with a curated snapshot of the NUCC (National Uniform Claim Committee) Healthcare Provider Taxonomy codes. This is what powers the specialty dropdown. The snapshot is loaded once at install and does not auto-refresh.

## Running tests

```bash
uv run pytest tests/
```

The test suite stubs Canvas SDK and Django so it runs without a live Canvas environment.

## Project layout

```
staff_directory/
├── CANVAS_MANIFEST.json
├── applications/            # Staff Directory app handler
├── assets/icon.png          # App menu icon
├── data/
│   ├── nucc_taxonomy.py     # Bundled NUCC snapshot (as a module)
│   └── nucc_seeder.py       # Idempotent seed loader
├── models/                  # Custom data models
├── routes/                  # SimpleAPI handlers
├── services/                # Business logic (testable)
├── static/                  # Directory CSS + JS
└── templates/directory.html # Directory HTML shell
tests/                       # Unit tests
pyproject.toml
```
