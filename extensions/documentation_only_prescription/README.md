# documentation_only_prescription

A Canvas SDK plugin that adds a **Documentation only** opt-in field to the **Prescribe** command. The field renders as a single-option dropdown (`Yes`); leaving it unset is the implicit "No". When the user selects **Yes**, all electronic-transmission and print actions are removed from the command — both before signing (*sign and send*, *print*) and after (*send*, *print*) — so the prescription can be signed for the chart record but cannot be transmitted electronically or printed.

## Why

Clinicians sometimes need to record a prescription that already exists or was issued elsewhere (e.g., a medication a patient is bringing in from another prescriber, a sample, or a historical Rx) without electronically transmitting it. Surfacing a single explicit toggle on the Prescribe command — and gating sign / sign-and-send on it — prevents accidental transmission of documentation-only entries.

## What it does

When a clinician opens the Prescribe command, the plugin contributes one extra form field:

| Property | Value |
|---|---|
| Label | Documentation only |
| Type | Single-select dropdown |
| Options | Yes (only — blank is the implicit "No") |
| Required | No |

Behavior:

- **Documentation only = Yes** → `sign_send_action`, `send_action`, and `print_action` are filtered out of the available actions in every command state. `sign_action` is retained so the entry can still be signed into the chart, but it cannot be transmitted to a pharmacy or printed — even after it has been signed.
- **Documentation only = blank** *(implicit "No")* → all default actions remain available, including sign, sign & send, send, and print.


The selected value is persisted as command metadata under the key `documentation_only` (value `"Yes"` or `"No"`). Downstream consumers can read it via:

```python
from canvas_sdk.v1.data.command import CommandMetadata

entry = CommandMetadata.objects.filter(
    command__id=command_uuid,
    key="documentation_only",
).first()
```

## How it works

Two `BaseHandler` subclasses, both registered in `CANVAS_MANIFEST.json`:

### `DocumentationOnlyFormHandler`

Subscribes to `EventType.COMMAND__FORM__GET_ADDITIONAL_FIELDS`. When the event's `schema_key` is `prescribe`, it returns a `CommandMetadataCreateFormEffect` declaring the `Documentation only` field. The same effect fires for both chart UI (`purpose="form"`) and printout (`purpose="print"`), so the field surfaces in both contexts.

### `DocumentationOnlyActionFilter`

Subscribes to `EventType.PRESCRIBE_COMMAND__AVAILABLE_ACTIONS`. On each render of the command's action menu — both pre- and post-commit — it reads the stored `documentation_only` metadata. If the value equals `"Yes"`, it emits a `COMMAND_AVAILABLE_ACTIONS_RESULTS` effect with `sign_send_action`, `send_action`, and `print_action` removed (sign is retained). Otherwise it returns no effect, leaving default actions in place.

## Project layout

```
documentation_only_prescription/                     # repo root
├── pyproject.toml
├── README.md
├── tests/
│   ├── __init__.py
│   └── test_documentation_only_form.py
└── documentation_only_prescription/                 # plugin package
    ├── CANVAS_MANIFEST.json
    ├── __init__.py
    └── protocols/
        ├── __init__.py
        └── documentation_only_form.py
```

## Installation

```bash
uv run canvas install --host <your-instance> documentation_only_prescription
```

`<your-instance>` is the section header from your `~/.canvas/credentials.ini`.

## Configuration

None. The plugin declares no secrets, no environment variables, and no scopes — it consumes only the platform-supplied event context and writes to command metadata.

## Development

```bash
uv sync
uv run pytest --cov=documentation_only_prescription --cov-report=term-missing --cov-branch
```

## References

- [CommandMetadataCreateFormEffect](https://docs.canvasmedical.com/sdk/command-metadata-create-form-effect/)
- [Commands — updating actions](https://docs.canvasmedical.com/sdk/commands/#example)
- Reference plugin: [`alert_facility_fields`](https://github.com/canvas-medical/gtm-extensions/tree/main/alert_facility_fields)
