# patient-sync

Two paired Canvas plugins that together replicate a single patient (plus everything related to them) from one Canvas instance to another, preserving Note / Command / Task ids end-to-end. Patient keys themselves are globally unique by Canvas convention, so a fresh key is minted on the target side and surfaced back to the caller via a two-call protocol.

Originally built for customers with externally-coupled workflows to unblock testing of complex patient scenarios in lower environments, and generalizable to any customer with a tightly-coupled external system or to Canvas's own training / preview environments.

Tracked in KOALA-5652.

## What's in this directory

- **[SPEC.md](./SPEC.md)** — the design. Read this first.
- **[patient_sync_source/](./patient_sync_source/)** — the plugin that installs on a **production** Canvas instance. Walks the patient graph, anonymizes PHI, POSTs the bundle to the target.
- **[patient_sync_target/](./patient_sync_target/)** — the plugin that installs on a **lower-environment** Canvas instance (staging, UAT, training, preview). Receives the bundle and dispatches import effects to recreate the patient with preserved Note / Command / Task ids.

```
source plugin (prod)  ──── authenticated HTTPS ────▶  target plugin (staging)
                                                      │
                                                      ▼
                                  patient (new key) + Notes/Commands/Tasks
                                  (source ids preserved, anonymized PHI)
```

## Two-call protocol

Globally-unique patient keys mean the target patient must be minted before any Note/Command/Task can be dispatched (their `patient_id` FK has to point at the new key, not the source key).

1. **`POST /export/provision-patient`** on source → walks just the Patient, attaches a `provision_token` marker, dispatches `Patient.create()` on target. Returns `{provision_token, target_provisioned_url}`.
2. Caller polls **`GET /provisioned/<provision_token>`** on target → returns `{target_patient_id}` once the async `Patient.create()` settles.
3. **`POST /export`** on source with `{patient_id, target_url, target_patient_id}` → walks Notes/Commands/Tasks, rewrites every `patient_id` FK to `target_patient_id`, dispatches.

See SPEC.md > *Two-call protocol* for full request/response shapes.

## Status

End-to-end-verified for the entity types where id preservation works on the current SDK: **`Note`** (all clinical Commands), **`Task`**, and (with a new key per global-uniqueness) **`Patient`**. Other entity types are reported in the target's `unsupported_entities` response field until the plumbing-fix and new-effect tiers land on canvas-plugins (see SPEC.md > SDK gaps).

## Install

Each plugin installs on its own instance.

```
canvas install patient_sync_source/       # on the production-style instance
canvas install patient_sync_target/       # on the lower-environment instance
```

Variables — coordinated between the pair, set via the Canvas console at install time:

| Plugin                  | Variable                | Notes                                                                   |
| ----------------------- | ----------------------- | ----------------------------------------------------------------------- |
| `patient_sync_source`   | `simpleapi-api-key`     | API key the caller (integrating system, etc.) presents on `POST /export*`.    |
| `patient_sync_source`   | `target_api_key`        | API key source presents to target. **Must equal** target's `simpleapi-api-key`. |
| `patient_sync_source`   | `callback_shared_secret`| HMAC key for signing the optional caller callback.                          |
| `patient_sync_source`   | `anonymization_key`     | Seed for deterministic PHI replacement (same key → same fake).          |
| `patient_sync_source`   | `source_host`           | Hostname of this source instance. Used for the same-instance guard.     |
| `patient_sync_target`   | `simpleapi-api-key`     | API key target expects on `POST /sync` from source. **Same value as source's `target_api_key`.** |
