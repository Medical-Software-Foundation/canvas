# patient_sync_source

Source half of the [patient-sync](../) extension. Installs on the **production** Canvas instance. Exposes `POST /export` (API-key authenticated) to kick off a sync of a single patient to a target Canvas instance.

See [SPEC.md](../SPEC.md) for the full design.

## What's implemented

The bundle walker (`services/bundle_walker.py`) and deterministic PHI anonymizer (`services/anonymizer.py`) are wired up. For the *currently possible* release the bundle includes:

- `Patient` (one row, anonymized).
- `PatientExternalIdentifier` (verbatim — the integrating system's own data, not Canvas PHI).
- `Note` (one row per Note on the patient; `body` is cleared per the integrating system's confirmed direction).
- `Command` (one row per committed, not-entered-in-error command across the patient's notes, with free-text fields cleared).
- `Task` (one row per Task on the patient; `title` cleared).

The target plugin will only attempt to write Note / Command / Task (the three entity types verified end-to-end for id preservation); Patient and PatientExternalIdentifier are reported in the response's `unsupported_entities` until their plumbing fixes land.

## Secrets

| Name                       | Purpose                                                                  |
| -------------------------- | ------------------------------------------------------------------------ |
| `simpleapi-api-key`        | API key callers present to authenticate against `POST /export`.          |
| `target_shared_secret`     | HMAC key for signing requests to the target plugin.                      |
| `callback_shared_secret`   | HMAC key for signing the completion callback to caller.                      |
| `anonymization_key`        | Seed for deterministic PHI replacement (same key → same fake).           |
| `source_host`              | The host this plugin is installed on. Used for the same-instance guard.  |

## Request shape

```jsonc
POST /plugin-io/api/patient_sync_source/export
Authorization: Api-Key <simpleapi-api-key>
{
  "patient_id": "abc123def456...",          // OR
  "external_identifier": {"system": "...", "value": "..."},
  "target_url": "https://staging.canvasmedical.com/plugin-io/api/patient_sync_target/sync",
  "callback_url": "https://case-manager.example.com/canvas-sync/webhook"
}
```

Response is 202 with `{"sync_id": "01HZX7…", "status": "accepted", "patient_id": "…"}`. The bundle dispatch and callback fire asynchronously via `HttpRequestEffect`.
