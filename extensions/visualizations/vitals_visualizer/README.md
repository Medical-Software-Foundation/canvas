# vitals_visualizer

A patient-vitals trend visualizer. Opens a modal with time-series line charts of the values collected in the Vital Signs command. Accessible from two surfaces: an action button in the chart summary, and a patient-scope companion launcher.

## What providers see

### Open Visualizer (action button)

The **Open Visualizer** button appears in the chart summary's vitals section for any patient whose chart has at least one active `Vital Signs Panel` observation. Tapping it opens the modal with the patient's vitals trends.

### Vitals (patient companion)

On a patient's companion page, a **Vitals** launcher opens the same modal. No action-button click required; it's available wherever the patient page surfaces the companion app.

### Inside the modal

- A slim header row with a **Metric #1** selector and a **Compare Metrics** button.
- A single time-series line chart below, rendered with Chart.js, showing the selected metric across every vitals-panel observation on file.
- Hover over a data point to see the exact value and date.

Metrics exposed (with units):

| Field | Label |
|---|---|
| `weight` | Weight (lbs) — auto-converted from ounces |
| `body_temperature` | Body Temp (°F) |
| `blood_pressure` (systolic/diastolic split) | Systolic BP (mmHg) / Diastolic BP (mmHg) |
| `oxygen_saturation` | Oxygen Sat (%) |
| `height` | Height (inches) |
| `waist_circumference` | Waist Circ (cm) |
| `pulse` | Pulse (bpm) |
| `respiration_rate` | Respiration Rate (bpm) |

Narrative observations like `note` and non-numeric fields like `pulse_rhythm` are excluded.

## How to use it

### Comparing metrics

Tap **Compare Metrics** to add a second chart. The second selector lists every metric except the one already picked for the first chart; switching the first metric reconstructs the second selector so they can't duplicate. Tap the × to remove the second chart.

### Responsive layout

- On wide viewports (≥720px) the two charts display side-by-side.
- On narrow/modal viewports (<720px) the layout stacks: Metric #1 selector and Metric #2 selector each take their own row, and the two charts stack vertically. The modal body scrolls when both charts are visible.

## Installation

No environment variables or secrets are required.

```sh
canvas install --host <host> \
    ~/src/plugin-development/msf-canvas/extensions/visualizations/vitals_visualizer
```

The action button appears immediately in the chart summary vitals section for patients with at least one Vital Signs panel; the patient companion launcher appears on every patient's companion page on next load.

---

## For developers

### Scopes and surfaces

The plugin registers three components in its manifest:

- `VitalsVisualizerButton` (`ActionButton`, chart-summary vitals section). Visible when the patient has any non-errored `Vital Signs Panel` observation. `handle()` emits `LaunchModalEffect(url=f"/plugin-io/api/vitals_visualizer/?patient={self.target}")`.
- `VitalsVisualizerCompanionApp` (`Application`, scope `provider_companion_patient_specific`). Reads `patient.id` from the event context and emits the same `LaunchModalEffect` URL.
- `VisualApp` (`SimpleAPI` with `StaffSessionAuthMixin`). Serves the HTML at `GET /` and the CSS at `GET /style.css`.

Both launchers converge on the same URL / handler, so the UI is identical regardless of where it was opened from.

### Architecture

```
vitals_visualizer/
├── CANVAS_MANIFEST.json               # 1 Application + 2 protocols (action button, SimpleAPI)
├── README.md                          # this file
├── LICENSE                            # MIT
├── applications/
│   └── companion_app.py               # VitalsVisualizerCompanionApp
├── protocols/
│   └── visualizer.py                  # VitalsVisualizerButton + VisualApp
├── templates/
│   ├── index.html                     # Chart.js UI, controls, two canvases
│   └── style.css                      # responsive layout with @media break at 720px
└── assets/
    ├── icon.png                       # 256×256 companion launcher icon
    └── vitals-pulse-icon.svg          # source SVG for the icon
```

### Request flow

1. Provider taps the action button on a chart OR the Vitals launcher on a patient companion page.
2. `VitalsVisualizerButton.handle()` / `VitalsVisualizerCompanionApp.on_open()` emit `LaunchModalEffect(url="/plugin-io/api/vitals_visualizer/?patient=<uuid>")`.
3. `VisualApp.index()` serves `templates/index.html` with three pre-rendered JSON blobs injected into the template:
   - `data` — an object keyed by metric label, valued by an array of numbers (or `null` where the metric wasn't recorded for a given panel; or the original string for non-numeric values like `"Regular"`).
   - `dates` — a chronologically-sorted array of `M/D/YYYY` strings matching the `data` arrays' indices.
   - `graph_ranges` — recommended min/max per metric (currently unused by the Chart.js options but present for future y-axis clamping).
4. The browser loads Chart.js from `https://cdn.jsdelivr.net/npm/chart.js` and renders one line chart from the selected metric.

### Data access

All reads; no writes.

- `Observation.objects.for_patient(<uuid>).filter(category="vital-signs", name="Vital Signs Panel").exclude(entered_in_error__isnull=False)` → panels (the grouping rows).
- `Observation.objects.for_patient(<uuid>).filter(category="vital-signs", effective_datetime__isnull=False).exclude(name="Vital Signs Panel").exclude(entered_in_error__isnull=False).select_related("is_member_of")` → the individual vital observations that belong to one of those panels.

Post-query transforms performed in `VisualApp.index`:

- `weight` is divided by 16 (observations are recorded in ounces; the UI shows pounds).
- `blood_pressure` values of the form `"<systolic>/<diastolic>"` are split into two series.
- `note` and `pulse_rhythm` observations are skipped.
- Observations with a falsy `value` are skipped.
- Remaining values are passed through `try_parse`: numeric-ish strings become `float`, non-numeric strings are preserved as-is (so a pulse_rhythm like `"Regular"` would round-trip unchanged — it isn't emitted in practice because of the skip rule above).

### Auth

- `VisualApp` inherits `StaffSessionAuthMixin`. Non-staff sessions are rejected with `InvalidCredentialsError` at the auth layer. (Prior to this hardening the handler had a no-op `authenticate` that returned `True` unconditionally; don't reintroduce that.)
- The patient UUID is read from the `?patient=<uuid>` query parameter rather than a platform header, because the same URL is hit from the action button (which knows the patient from chart context) and the companion Application (which hardcodes it into the launch URL).

### Endpoints

All under `/plugin-io/api/vitals_visualizer/`.

| Method & path | Purpose |
|---|---|
| `GET /?patient=<uuid>` | HTML shell with rendered Chart.js page. |
| `GET /style.css` | served CSS. |

### Responsive CSS

The modal body uses a `@media (max-width: 720px)` breakpoint:

- **≥720px**: `.chart-container` uses `position: absolute; top: 48px` with `flex-direction: row` (charts side-by-side) and a fixed 48px header.
- **<720px**: body becomes a flex column, header grows to auto height with `flex-wrap: wrap` on `.controls` (so Metric #1 and Metric #2 selectors each take their own row), and `.chart-container` switches to `flex-direction: column` with vertical scrolling.

### Known considerations

- **External CDN for Chart.js**: `templates/index.html` loads Chart.js from `https://cdn.jsdelivr.net/npm/chart.js`. Pin to an explicit version + SRI hash if that matters in your threat model.
- **Patient UUID in query string, not path**: unusual for our other plugins (which use path params). Here it matches the action button's existing URL convention.
- **No pagination**: the index endpoint serializes every panel for the patient. For long histories that could balloon the payload; a future revision could window by date range.

## Testing

```sh
cd ~/src/canvas-plugins && uv run pytest \
    ~/src/plugin-development/msf-canvas/extensions/visualizations/vitals_visualizer/tests \
    --cov=vitals_visualizer --cov-branch --cov-report=term-missing
```

Target: 100% statement + branch coverage on the Python code.

## License

MIT. See [LICENSE](./LICENSE).
