# Custom Observation Management

A Canvas plugin for managing and visualizing patient observations with table and graph views.

## Video

Here is a video demonstrating this plugin in action: https://www.loom.com/share/a475c3cba69149f2b60851b6f9ec1da8 

## Features

- **REST API** for creating and querying observations with filtering, sorting, and pagination
- **Observation Visualizer** application accessible from patient charts
- **Table View** with expandable grouped observations
- **Graph View** for trending numeric observations over time
- **Add to Chart Review** functionality to create clinical notes with observation summaries

## Components

### ObservationAPI

RESTful API for observation management. Requires API key authentication.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/observation/<observation_id>` | Get a single observation by ID |
| GET | `/observations` | List observations with filters |
| GET | `/observation-filters` | Get unique names/categories for filter dropdowns |
| POST | `/observation` | Create a new observation |

**Query Parameters for GET /observations:**

| Parameter | Description |
|-----------|-------------|
| `patient_id` | Filter by patient UUID |
| `note_dbid` | Filter by note database ID |
| `note_uuid` | Filter by note UUID |
| `name` | Filter by observation name (use `\|\|` for multiple) |
| `category` | Filter by category (use `\|\|` for multiple) |
| `effective_datetime_start` | Filter by start date (ISO 8601) |
| `effective_datetime_end` | Filter by end date (ISO 8601) |
| `sort_by` | Sort column: `date`, `name`, `value`, `units`, `category` |
| `sort_order` | Sort direction: `asc`, `desc` |
| `ungrouped` | If `true`, return flat list without parent-child grouping |
| `page` | Page number (default: 1) |
| `page_size` | Items per page (default: 25, max: 100) |

### ObservationVisualizerApp

Patient-specific application that launches the observation visualizer modal from the Applications menu in a patient chart.

### ObservationVisualizerAPI

Serves the visualizer UI and proxies requests to the ObservationAPI with staff session authentication.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/visualizer` | Main HTML page |
| GET | `/visualizer/style.css` | Stylesheet |
| GET | `/visualizer/script.js` | JavaScript |
| GET | `/visualizer/observations` | Proxy to ObservationAPI |
| GET | `/visualizer/observation-filters` | Proxy to get filter options |
| POST | `/visualizer/create-chart-review` | Create Chart Review note with observation summary |

### ObservationSummary Command

Custom command schema for embedding observation summaries in notes.

**Automatic Command Creation:** When creating an observation via the API with a `note_id` or `note_uuid`, a CustomCommand is automatically added to the associated note containing an observation summary with:
- Observation name
- Value with units
- Date/Time (displayed in EST with am/pm format)
- Category (if provided)
- Components (if provided, displayed as a line-separated list)

## Configuration

### Required Secrets

- `simpleapi-api-key` - API key for authenticating requests to the ObservationAPI

## Installation

1. Deploy the plugin to your Canvas instance
2. Configure the `simpleapi-api-key` secret in plugin settings
3. The "Observation Visualizer" application will appear in patient chart Applications menus

## Usage

### Creating Observations via API

```bash
curl -X POST "https://your-instance/plugin-io/api/custom_observation_management/observation" \
  -H "Authorization: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "patient-uuid",
    "name": "Blood Pressure",
    "effective_datetime": "2024-06-15T10:30:00Z",
    "category": "vital-signs",
    "value": "120/80",
    "units": "mmHg",
    "components": [
      {
        "name": "Systolic",
        "value_quantity": "120",
        "value_quantity_unit": "mmHg"
      },
      {
        "name": "Diastolic",
        "value_quantity": "80",
        "value_quantity_unit": "mmHg"
      }
    ]
  }'
```

### Creating Observations with Note Association

When you include a `note_id` or `note_uuid`, the observation is linked to that note and a CustomCommand with the observation summary is automatically added to the note:

```bash
curl -X POST "https://your-instance/plugin-io/api/custom_observation_management/observation" \
  -H "Authorization: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "patient-uuid",
    "name": "Blood Pressure",
    "effective_datetime": "2024-06-15T10:30:00Z",
    "note_uuid": "note-uuid-here",
    "category": "vital-signs",
    "value": "120/80",
    "units": "mmHg",
    "components": [
      {
        "name": "Systolic",
        "value_quantity": "120",
        "value_quantity_unit": "mmHg"
      },
      {
        "name": "Diastolic",
        "value_quantity": "80",
        "value_quantity_unit": "mmHg"
      }
    ]
  }'
```

This will create the observation and add a summary command to the note displaying:
- Name: Blood Pressure
- Value: 120/80 mmHg
- Date/Time: 2024-06-15 06:30 AM EST
- Category: vital-signs
- Components:
  - Systolic: 120 mmHg
  - Diastolic: 80 mmHg

### Using the Visualizer

1. Open a patient chart in Canvas
2. Click the Applications menu
3. Select "Observation Visualizer"
4. Use filters to narrow down observations
5. Toggle between Table and Graph views
6. Click "Add to Chart Review" to create a clinical note with selected observations

## Development

### Running Tests

```bash
uv run pytest tests/ -v
```

### Running Tests with Coverage

```bash
uv run pytest tests/ --cov=custom_observation_management --cov-report=term-missing
```

## License

See LICENSE file for details.
