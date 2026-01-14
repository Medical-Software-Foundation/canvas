VitalStream by Caretaker Medical
===========

This plugin provides an integration for the VitalStream device by Caretaker Medical, enabling real-time vital signs monitoring within Canvas Medical.

## Features

- **Real-time Vital Signs Display**: Receives continuous vital sign measurements from VitalStream devices via WebSocket, displaying them in a live feed within the patient chart.

- **User-Controlled Averaging**: When ready, the user selects the desired number of readings (1-50, default 10) and clicks "Save to Chart". The measurements are averaged into evenly-distributed time buckets across the session duration.

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

The plugin requires the following secret:

- `AUTHORIZED_SERIAL_NUMBERS`: A newline-separated list of authorized VitalStream device serial numbers. You can get the device's serial number from the "About" section of the Settings screen in the VitalStream app.

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
- When finished recording, select the desired number of readings (1-50) and click "Save to Chart"
  - The raw measurements are averaged into the selected number of time buckets
  - Averaged readings are saved as Observations
  - A command is inserted into the note summarizing the measurements

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
