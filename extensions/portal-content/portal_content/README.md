# Portal Content

Unified patient portal plugin that consolidates educational materials, imaging reports, lab reports, and visit notes into a single configurable plugin.

## Features

- **Educational Materials**: View educational materials shared by providers
- **Imaging Reports**: View imaging test results and reports
- **Lab Reports**: View lab test results and reports
- **Visit Notes**: View visit note summaries after provider completion

## Configuration

### Secrets

| Secret | Description | Required |
|--------|-------------|----------|
| `ENABLED_COMPONENTS` | Comma-separated list of enabled components. Valid values: `education`, `imaging`, `labs`, `visits`. If empty, all components are enabled. | No |
| `CLIENT_ID` | OAuth2 client ID for FHIR API access | Yes |
| `CLIENT_SECRET` | OAuth2 client secret for FHIR API access | Yes |
| `NOTE_TYPES` | Comma-separated list of note type codes to filter visit notes (e.g., `therapy,psych`). Only used by visits component. | No |

### Examples

**Enable all components (default):**
```
ENABLED_COMPONENTS=
```

**Enable only labs and imaging:**
```
ENABLED_COMPONENTS=labs,imaging
```

**Enable only visit notes with specific note types:**
```
ENABLED_COMPONENTS=visits
NOTE_TYPES=therapy,psych
```

## API Endpoints

| Content Type | Portal URL | Data URL | PDF URL |
|-------------|------------|----------|---------|
| Education | `/education/portal` | `/education/reports` | `/education/pdf` |
| Imaging | `/imaging/portal` | `/imaging/reports` | `/imaging/pdf` |
| Labs | `/labs/portal` | `/labs/reports` | `/labs/pdf` |
| Visits | `/visits/portal` | `/visits/notes` | `/visits/pdf` |

All endpoints are prefixed with `/plugin-io/api/portal_content/`.

## Security

- Patient-only access (staff users rejected)
- Patient-scoped OAuth tokens for FHIR API
- Document ownership verification before serving PDFs
- Finalized notes only (SGN, LKD, RLK, DSC states) for visit notes
