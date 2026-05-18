VitalStream by Caretaker Medical
===========

This plugin provides an integration for the VitalStream device by Caretaker Medical, enabling real-time vital signs monitoring within Canvas Medical.

## Features

- **Real-time Vital Signs Display**: Receives continuous vital sign measurements from VitalStream devices via WebSocket, displaying them in a live feed within the patient chart.

- **Windowed Averaging at Increments**: When the user clicks "Save Summary to Chart", the plugin computes averages in a 1-minute window (30 seconds before and after) around each increment mark. The user chooses a 5 or 10 minute increment for the summary regardless of treatment type.

- **Observation Recording**: Averaged measurements are saved to the patient's chart as Observations with appropriate LOINC codes for:
  - Mean heart rate (103205-1)
  - Mean respiratory rate (103217-6)
  - Mean oxygen saturation (103209-3)
  - Blood pressure panel with mean systolic and diastolic components (96607-7)

- **Command Summary**: When saving to chart, a command is automatically inserted into the note with a summary of all recorded vital sign measurements.

- **Secure Session Management**: Each VitalStream session is tied to a specific note and staff member, with QR code-based device pairing.

## Components

- **VitalstreamUILauncher**: Action button in the note header that launches the VitalStream UI in the right chart pane.

- **CaretakerPortalAPI**: Receives incoming vital sign data from VitalStream devices, validates device authorization via serial number, and broadcasts measurements to active sessions.

- **VitalstreamUIAPI**: Serves the VitalStream UI and handles saving averaged measurements as Observations.

- **LiveObservationsChannel**: WebSocket channel for real-time communication between the device API and the UI.

## Configuration

The plugin uses the following secrets:

- `AUTHORIZED_SERIAL_NUMBERS` (required): A newline-separated list of authorized VitalStream device serial numbers. You can get the device's serial number from the "About" section of the Settings screen in the VitalStream app.

- `ENABLE_MOCK_VITALS` (optional, default disabled): When enabled, exposes a "Mock Vitals" button in the chart pane and the `/mock-vitals/` endpoint, which generate random vitals for development/testing. Accepted truthy values (case-insensitive): `1`, `true`, `yes`, `on`, `enabled`. Any other value (including `false`, `0`, `disabled`, or unset) leaves the feature off. Do not enable in production.

In the VitalStream app on the tablet:

- Under "settings", go to the "Data Forwarding" menu.
  - "Enable Forwarding" should be ON
  - "Portal" should be "Caretaker Portal"
  - "Portal URL" should be `https://<subdomain>.canvasmedical.com/plugin-io/api/vitalstream`

## Usage

- In Canvas, create a note
- Click the "Record with VitalStream" button
- Right pane opens, revealing QR code used to pair the device
- Start a session on the caretaker tablet, click the camera icon to scan the code
  - Data starts flowing in and is displayed in real-time
  - Data is not persisted until the user clicks "Save to Chart"
- Choose a summary increment (5 or 10 minutes)
- When finished recording, click "Save Summary to Chart"
  - For each increment mark (0, N, 2N, ... minutes from session start), readings in the 1-minute window around that mark (±30 seconds) are averaged
  - Averaged readings are saved as Observations
  - A command is inserted into the note summarizing the measurements

## Spravato workflow

The UI offers a Spravato "Treatment Intervals" workflow (pre-administration, 40-minute post, and pre-discharge BP intervals) in addition to the standard windowed-averaging summary. This workflow is enabled by inspecting the note's type name and title — if either contains `spravato` (case-insensitive), the Treatment Intervals panel is shown and the treatment-type dropdown defaults to Spravato.

This is intentionally name-based so customers can opt note types into the Spravato workflow without a code change. To enable it, name the note type (or set the note title) to include `spravato` — e.g. "Spravato Session", "Spravato Treatment". Note types that should _not_ surface the Spravato workflow must avoid that substring in their display name.

When intervals are assigned and saved via "Save Intervals to Chart", the plugin writes `spravato:vitals_data` and `spravato:bp_pre_admin` / `spravato:bp_40min_post` / `spravato:bp_pre_completion` metadata on the note, which the Spravato charting app and REMS extractor consume.

## Opportunities for enhancement

The UI implements optimistic creation of the averaged Observations. An
enhancement to this would be to perform a lookup of the newly created
observations to confirm persistence.

## Testing

Run the test suite with:

```bash
uv run pytest tests/ -v
```

To run tests for a specific module:

```bash
uv run pytest tests/test_vitalstream_ui_api.py -v
uv run pytest tests/test_caretaker_portal_api.py -v
uv run pytest tests/test_vitalstream_ui_launcher.py -v
uv run pytest tests/test_live_observations.py -v
uv run pytest tests/test_util.py -v
```
