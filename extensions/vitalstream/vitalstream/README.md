VitalStream by Caretaker Medical
===========

This plugin provides an integration for the VitalStream device by Caretaker Medical, enabling real-time vital signs monitoring within Canvas Medical.

## Features

- **One session per note**: When the staff member first clicks "Record with VitalStream" on a note, a session is created and tied to that note. Re-clicking the button (or reopening the chart pane) resumes the same session and shows the same QR code — the device stays paired and the user can close and revisit the pane at will without losing data.

- **Real-time persistence**: Each reading the device pushes is persisted to a `VitalstreamReading` custom data row as it arrives. The browser tab no longer has to stay open for data to be recorded. Reopening the pane backfills the live feed from history before subscribing to the WebSocket for new readings.

- **Single end-session-and-save button**: When the user is finished recording they click "End Session & Save Summary". The server atomically flips the session row to `closed` (further device posts are rejected from that instant), reads all persisted readings, computes a mean over a 1-minute window (±30s) around each Nth-minute mark, and writes Observations + a CustomCommand summary to the chart. Other open UIs are notified via a `session_closed` broadcast.

- **Observation Recording**: Averaged measurements are saved to the patient's chart as Observations with appropriate LOINC codes for:
  - Mean heart rate (103205-1)
  - Mean respiratory rate (103217-6)
  - Mean oxygen saturation (103209-3)
  - Blood pressure panel with mean systolic and diastolic components (96607-7)

- **Selectable summary increment**: 5, 10, 15, 20, or 30 minutes.

- **Secure Session Management**: Each VitalStream session is tied to a specific note and staff member, with QR code-based device pairing. The device authenticates by serial number; per-session authorization is enforced by the unguessable session UUID embedded in the QR code.

## Components

- **VitalstreamUILauncher**: Action button in the note header that opens the VitalStream UI in the right chart pane. It just emits a `LaunchModalEffect`; the UI handler resolves (or creates) the `VitalstreamSession` for the note when the page renders.

- **CaretakerPortalAPI**: Receives incoming vital sign data from VitalStream devices. Validates the device serial number, looks up the `VitalstreamSession` by `patid`, rejects readings if the session is closed, otherwise bulk-creates `VitalstreamReading` rows and broadcasts to active UIs.

- **VitalstreamUIAPI**: Serves the VitalStream UI at `/vitalstream-ui/notes/<note_dbid>/` (where the get-or-create on the session row happens), plus the session-scoped `/sessions/<session_id>/readings/` backfill endpoint, the Spravato `/sessions/<session_id>/save-intervals/` endpoint, and the `/sessions/<session_id>/end-session/` endpoint that closes the session and writes the summary Observations + CustomCommand.

- **LiveObservationsChannel**: WebSocket channel that streams readings and the `session_closed` event to the UI. Authorizes the connection by looking up the session row in the DB.

## Custom data

The plugin owns the `canvas__vitalstream` namespace with two models:

| Model | Purpose |
|---|---|
| `VitalstreamSession` | One row per note. Tracks `session_id`, `staff_id`, `status` (`open`/`closed`), `started_at`, `ended_at`, `summary_increment_minutes`. |
| `VitalstreamReading` | One row per individual device reading. Holds `reading_time`, `hr`, `sys`, `dia`, `resp`, `spo2`. Indexed by `(session, reading_time)`. |

## Configuration

The plugin uses the following secrets:

- `AUTHORIZED_SERIAL_NUMBERS` (required): A newline-separated list of authorized VitalStream device serial numbers. You can get the device's serial number from the "About" section of the Settings screen in the VitalStream app.

- `ENABLE_MOCK_VITALS` (optional, default disabled): When enabled, exposes a "Mock Vitals" button in the chart pane and the `/mock-vitals/` endpoint, which generate random vitals for development/testing. Mock readings are persisted to `VitalstreamReading` just like real ones, so the full end-session flow can be exercised without a device. Accepted truthy values (case-insensitive): `1`, `true`, `yes`, `on`, `enabled`. Any other value (including `false`, `0`, `disabled`, or unset) leaves the feature off. Do not enable in production.

In the VitalStream app on the tablet:

- Under "settings", go to the "Data Forwarding" menu.
  - "Enable Forwarding" should be ON
  - "Portal" should be "Caretaker Portal"
  - "Portal URL" should be `https://<subdomain>.canvasmedical.com/plugin-io/api/vitalstream`

## Usage

- In Canvas, open a note and click "Record with VitalStream".
- The right chart pane opens with a QR code.
- On the Caretaker tablet, start a session and tap the camera icon to scan the QR.
- Readings start streaming and are persisted in real time. The user can close the chart pane and return; the same QR/session is shown and the prior readings are still on the timeline.
- Choose a summary increment (5, 10, 15, 20, or 30 min).
- When finished, click "End Session & Save Summary":
  - The session is closed atomically — further device readings are rejected.
  - For each increment mark (0, N, 2N, ... minutes from session start), readings in the 1-minute window around that mark (±30 seconds) are averaged.
  - Averaged readings are saved as Observations.
  - A command is inserted into the note summarizing the measurements.

## Spravato workflow

The UI offers a Spravato "Treatment Intervals" workflow (pre-administration, 40-minute post, and pre-discharge BP intervals) in addition to the standard windowed-averaging summary. This workflow is enabled by inspecting the note's type name and title — if either contains `spravato` (case-insensitive), the Treatment Intervals panel is shown and the treatment-type dropdown defaults to Spravato.

This is intentionally name-based so customers can opt note types into the Spravato workflow without a code change. To enable it, name the note type (or set the note title) to include `spravato` — e.g. "Spravato Session", "Spravato Treatment". Note types that should _not_ surface the Spravato workflow must avoid that substring in their display name.

"Save Intervals to Chart" writes the interval Observations and `spravato:vitals_data` / `spravato:bp_pre_admin` / `spravato:bp_40min_post` / `spravato:bp_pre_completion` note metadata that the Spravato charting app and REMS extractor consume. This is independent of "End Session & Save Summary" — Spravato users typically click both.

## Testing

Run the test suite with:

```bash
uv run pytest tests/ -v
```

To run tests for a specific module:

```bash
uv run pytest tests/test_vitalstream_ui_api.py -v
uv run pytest tests/test_vitalstream_api.py -v
uv run pytest tests/test_vitalstream_ui.py -v
uv run pytest tests/test_live_observations.py -v
```
