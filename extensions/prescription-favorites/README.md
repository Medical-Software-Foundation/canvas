# prescription-favorites

Quick-access prescribing tool with a searchable catalog of favorite medications and batch prescribing.

## What it does

- Displays a searchable panel of prescription favorites inside a patient chart
- Supports both hardcoded default favorites and user-created custom favorites
- Allows staff to add, edit, and delete custom favorites
- Supports batch prescribing (select multiple medications, add to note at once)
- Staff can hide/unhide default favorites per user
- Custom favorites are stored via Canvas Custom Data (CustomModel)

## Triggers

- **Application**: `patient_specific` scope - renders when viewing a patient chart

## API Endpoints

All endpoints require staff session authentication (`StaffSessionAuthMixin`).

| Endpoint | Description |
|----------|-------------|
| `FavoritesAPI` | CRUD for prescription favorites |
| `HideDefaultAPI` | Hide/unhide default favorites per staff |
| `MedicationSearchAPI` | Search FDB medication database |
| `PharmacySearchAPI` | Search pharmacies |
| `PharmacyLookupAPI` | Look up pharmacy by NCPDP ID |
| `MedicationLookupAPI` | Look up medication clinical quantities |
| `PrescribeFavoritesAPI` | Add selected medications to most recent open note |

## Custom Data Models

- **CustomFavorite** - User-created favorites with medication details, labels, and sharing
- **HiddenDefault** - Tracks which default favorites a staff member has hidden
- **CustomStaff** - Proxy model for ForeignKey references to Canvas Staff

## Installation

```bash
canvas install prescription-favorites
```

## Configuration

Requires the `namespace_read_write_access_key` secret for custom data access. This key is auto-generated on first install.

## Running Tests

```bash
uv run pytest tests/
```
