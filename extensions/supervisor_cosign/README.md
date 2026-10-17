# supervisor_cosign

## What it does

When a clinician's note is locked, this plugin automatically creates a co-sign task for that clinician's supervising provider and adds a "Co-sign" button to the note's header. The supervisor opens the note, picks an attestation template (or writes their own), and submits. The plugin appends the attestation to the chart as a custom command and re-signs the note in the supervisor's name, all in one click.

## Problem it solves

Many practices require a supervising physician to review and co-sign notes written by residents, NPs, PAs, or other clinicians under supervision. Without this plugin, that workflow is manual: someone tracks which notes need cosigning in a spreadsheet, the supervisor opens each note, types out the same attestation language by hand, manually unlocks/relocks the note, and updates the tracker. It is slow, easy to skip, and the attestation language drifts from note to note.

This plugin replaces all of that with native Canvas effects: tasks for tracking, a one-click button on the note header, standardized attestation templates, and an audit-friendly addendum log per note.

## Who it's for

- **Teaching practices** with residents and attending physicians under GME teaching-physician rules.
- **Group practices** with NPs, PAs, or other supervised clinicians who require oversight per state scope-of-practice rules.
- **Any specialty** that uses Canvas's native `Staff.default_supervising_provider` field to model supervisor relationships, including primary care, behavioral health, urgent care, and addiction medicine.

Primary users:
- **Supervisees** (residents, NPs, PAs): no extra workflow - the plugin runs in the background when they lock their note.
- **Supervisors** (attendings, MDs, DOs): get tasks for everything they need to co-sign and a one-click attestation flow.
- **Compliance / clinic admins**: can pull a per-supervisee co-sign rate report to monitor compliance.

## How to install

```bash
canvas install supervisor_cosign
```

Then complete the configuration steps below.

## Configuration

### Required Canvas setup

- `Staff.default_supervising_provider` must be set for each supervisee in the native Canvas staff admin. The plugin reads this directly and does not maintain its own mapping.
- **The instance setting "only the provider can sign/unlock the note" must be turned OFF.** The cosign flow works by having the supervisor unlock the supervisee's locked note, append the attestation, and re-lock/re-sign. With the "only the provider" restriction enabled, the supervisor's unlock is rejected by the effect interpreter (`UNLOCK_NOTE: This note can only be unlocked by the provider.`) and the chart write fails. The cosign record and task completion still happen in custom data, but the attestation never lands in the chart.

### Custom command schema

The plugin declares an "Attestation Review" custom command in `CANVAS_MANIFEST.json`. The schema_key `attestation_review` must be configured on the Canvas instance for the attestation to render in the note timeline.

### Secrets

Configure these via the Canvas admin (Plugins -> supervisor_cosign -> Secrets):

| Key | Required | Purpose |
|-----|----------|---------|
| `SAMPLE_PERCENTAGE` | No | Float 0-100 controlling what percentage of locked notes get a co-sign task. Defaults to `100` (every locked note). Use a lower value to phase the workflow in gradually. |

## Triggers

| Event | Handler | Behavior |
|-------|---------|----------|
| `NOTE_STATE_CHANGE_EVENT_CREATED` (LOCKED) | `NoteLockHandler` | Looks up supervisor via `default_supervising_provider`, creates a `CoSignRecord`, emits an `AddTask` for the supervisor with a 3-day due date. |
| `SHOW_NOTE_HEADER_BUTTON` | `CoSignButton` | Renders "Co-sign" or "Co-signed ✓" on notes with a `CoSignRecord`. Click opens the attestation modal. |
| `POST /plugin-io/api/supervisor_cosign/cosign/<note_id>/` | `SupervisorCoSignAPI.submit_cosign` | Records attestation, writes the `Attestation Review` custom command into the note (unlock -> originate -> lock -> sign), completes the supervisor's task. Staff-only; rejects callers who are not the assigned supervisor. |
| `GET /plugin-io/api/supervisor_cosign/report/` | `SupervisorCoSignAPI.compliance_report` | Per-supervisee summary (total / approved / pending / pct_cosigned), filterable by `start` and `end` query params. Each requester sees only their own supervisees. |

## Effects produced

- `AddTask` - creates the supervisor's co-sign task with a 3-day due date.
- `NoteEffect.unlock()` + `CustomCommand.originate(schema_key="attestation_review")` + `LOCK_NOTE` + `SIGN_NOTE` - writes the attestation as a custom command into the note, then re-locks and re-signs so the cosigner is recorded as the signer. `LOCK_NOTE` and `SIGN_NOTE` are constructed manually to bypass SDK construct-time state validation; effects only apply in order at runtime, so building them directly avoids the construct-time check.
- `AddTaskComment` + `UpdateTask(status=COMPLETED)` - closes the supervisor's task with the attestation text.
- `LaunchModalEffect` - renders the attestation modal in the note header.

## Custom data

Namespace: `supervisor__cosign` (read_write).

| Model | Purpose |
|-------|---------|
| `CoSignRecord` | One row per (note, supervisee, supervisor). Tracks status, due date, task linkage, persisted attestation text. |
| `CoSignAddendum` | One row per attestation submitted. Powers the modal's attestation log. |

## Screenshots

> Screenshots and a screen recording will be added once the plugin is deployed to a clean instance.

## Running Tests

```bash
uv sync
uv run pytest tests/
```

## License

MIT - see [LICENSE](./LICENSE).
