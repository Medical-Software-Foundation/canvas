# patient_sync_target

Target half of the [patient-sync](../) extension. Installs on a **lower-environment** Canvas instance (staging, UAT, training, preview). Exposes `POST /sync` to receive a patient bundle from a paired source plugin.

See [SPEC.md](../SPEC.md) for the full design.

## What's implemented

The per-entity dispatcher (`services/dispatcher.py`) handles the *currently possible* release:

- `Note` → `NoteEffect(instance_id=..., ...).create()` (verified server-side honor at `home-app/plugin_io/interpreters/notes/base.py:43,201`).
- `Command` → `<*Command>(command_uuid=..., ...).originate(commit=True)` (verified at `home-app/plugin_io/interpreters/commands/originate.py:25-32`). The full SDK schema_key → Command class map is in `dispatcher.SCHEMA_KEY_TO_COMMAND`.
- `Task` → `AddTask(id=..., ...).apply()` (verified at `home-app/plugin_io/interpreters/tasks/add_task.py:31-32`).

Every other entity type in the bundle (Patient, PatientExternalIdentifier, Appointment, Message, etc.) is counted in the response's `unsupported_entities` field. They'll move to the dispatcher as their plumbing fixes (client + server) or new-effect work lands.

## Staff / PracticeLocation fallback

`NoteEffect.create()`'s validator requires the referenced `Staff` and `PracticeLocation` to already exist on target. Staff and PracticeLocation have no create-effect in the SDK today (see SPEC.md > SDK gaps), so until the new-effect tier lands the dispatcher falls back: if source's `provider_id` / `location_id` happens to match a row already on target it's honored; otherwise the first active row of each is used. the integrating system joins on Note / Command / Patient ids — Staff and Location ids aren't part of that contract — so the mismatch is acceptable for now. The full-coverage release syncs these with preserved ids.

## Secrets

| Name                    | Purpose                                                       |
| ----------------------- | ------------------------------------------------------------- |
| `source_shared_secret`  | HMAC key for verifying signed requests from the source plugin.|

## Access gating

The Canvas plugin manifest gates access via per-handler `data_access` blocks declaring which resource types each handler can `read` and `write`. The target plugin's manifest will need to enumerate `notes`, `commands`, and `tasks` under `write` (and any further entity types as they're added).

## Replay prevention

`models/applied_sync.py` defines an `AppliedSync(sync_id unique, applied_at)` CustomModel in the plugin's `patient_sync_target` namespace. The handler short-circuits with `status=succeeded` when a duplicate `sync_id` arrives. Retention is forever (no auto-prune) per Beau's decision.
