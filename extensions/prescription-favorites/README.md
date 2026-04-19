# Prescription Favorites

Quick-access prescribing tool with a searchable catalog of favorite medications and batch prescribing.

## Problem it solves

Prescribing the same medications repeatedly is one of the most common sources of click fatigue for clinical staff. Providers treating patients on standard protocols - weight management, GI support, chronic disease maintenance - end up navigating the same medication search, filling in the same instructions, selecting the same pharmacy, dozens of times per day. This plugin eliminates that repetition by giving staff a one-click prescribing panel with pre-configured favorites and the ability to add their own.

## Who it's for

- **Providers and clinical staff** who prescribe the same medications frequently
- **Practices with standardized protocols** (e.g., GLP-1 weight management, chronic disease management)

## What it does

- Displays a searchable panel of prescription favorites inside a patient chart
- Supports both default favorites and user-created custom favorites
- Allows staff to add, edit, and delete custom favorites
- Supports batch prescribing (select multiple medications, add to note at once)
- Staff can hide/unhide default favorites per user
- Custom favorites are stored via Canvas Custom Data (CustomModel)

## Installation

```bash
canvas install prescription-favorites
```

## Configuration

The plugin uses Canvas Custom Data for storage. The `namespace_read_write_access_key` secret is auto-generated on first install - no manual configuration required.

If another plugin needs to share this namespace, retrieve the key from **Settings > Plugins > prescription_favorites > Secrets** in the Canvas admin UI.

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

## Running Tests

```bash
uv run pytest tests/
```

## License

MIT - see [LICENSE](LICENSE) for details.


![Prescription Favorites panel in a patient chart](https://images.prismic.io/canvas-website/aeRmiJ1ZCF7ETVbM_rxfav-screenshot.jpg)

