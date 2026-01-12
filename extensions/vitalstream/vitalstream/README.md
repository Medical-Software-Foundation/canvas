VitalStream by Caretaker Medical
===========

This plugin provides an integration for the VitalStream device by Caretaker Medical, enabling real-time vital signs monitoring within Canvas Medical.

## Features

- **Real-time Vital Signs Display**: Receives continuous vital sign measurements from VitalStream devices via WebSocket, displaying them in a live feed within the patient chart.

- **Automatic Averaging**: Configurable time-based averaging of vital signs (30 seconds, 1 minute, or 5 minutes) to reduce noise and provide clinically meaningful readings.

- **Observation Recording**: Averaged measurements are automatically saved to the patient's chart as Observations with appropriate LOINC codes for:
  - Mean heart rate (103205-1)
  - Mean respiratory rate (103217-6)
  - Mean oxygen saturation (103209-3)
  - Blood pressure panel with mean systolic and diastolic components (96607-7)

- **Secure Session Management**: Each VitalStream session is tied to a specific note and staff member, with QR code-based device pairing.

## Components

- **VitalstreamUILauncher**: Action button in the note header that launches the VitalStream UI in the right chart pane.

- **CaretakerPortalAPI**: Receives incoming vital sign data from VitalStream devices, validates device authorization via serial number, and broadcasts measurements to active sessions.

- **VitalstreamUIAPI**: Serves the VitalStream UI and handles saving averaged measurements as Observations.

- **LiveObservationsChannel**: WebSocket channel for real-time communication between the device API and the UI.

## Configuration

The plugin requires the following secret:

- `AUTHORIZED_SERIAL_NUMBERS`: A newline-separated list of authorized VitalStream device serial numbers.

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
