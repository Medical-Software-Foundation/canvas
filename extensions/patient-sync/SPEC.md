# Cross-instance patient sync — design spec

**Status:** Reference design

## Motivation

Customers with an external system tightly coupled to Canvas (one that creates notes via SDK, listens to webhooks, joins on Canvas-assigned ids from prior webhook payloads, and orchestrates workflows across both systems) need a way to replicate a real, complex production patient into a lower environment (staging / UAT / training / preview) for testing. Generating those scenarios from scratch via SDK calls creates a circular problem — the scenario-generation code itself needs testing, and the resulting patient never matches production reality (patients re-patched with new diagnostics, many reschedules, layered tasks/messages/orders, etc.).

What this plugin provides: take a real, complex patient from a production Canvas instance, anonymize PHI in flight, and land them in a lower Canvas environment preserving Note / Command / Task ids end-to-end (so the integrating system's joins keep working) and minting a fresh globally-unique key on the target side for the Patient itself. Triggered on demand via two POSTs, with an optional callback when the sync completes.

### A note on "IDs"

Canvas uses two distinct primary-key shapes — the spec calls both of them "the `id`" or "the Canvas-assigned id" to avoid confusion:

- **`Patient` and `Staff`** have `id = CharField(max_length=32, default=create_key)` — a 32-character base62 "key", not a UUID. (See `canvas_sdk/v1/data/patient.py:48`, `staff.py:31`.)
- **`Note`, `Encounter`, `Command`, and every model inheriting `IdentifiableModel`** have `id = UUIDField(default=uuid.uuid4)` — actual UUIDs. (See `canvas_sdk/v1/data/base.py:345`.)

Both are surfaced as `id` in webhook payloads and SDK queries, and both are what this spec means by "preserve the id." The sync needs to handle both shapes — that's a detail of the import effect, not a design choice.

Separately, Canvas also has **`*ExternalIdentifier`** child tables (e.g. `PatientExternalIdentifier`, `AppointmentExternalIdentifier`) — these are different from the primary key. See the *ExternalIdentifier records* section below.

## Scope

### In scope

- Export a single patient, by `id` or external identifier, from a **source** Canvas instance.
- Anonymize PHI fields (name, DOB, SSN, address, phone, email, MRN) in transit. Canvas-assigned `id`s are preserved verbatim; PHI is replaced with deterministic fakes.
- Transmit to a **target** Canvas instance over authenticated HTTPS.
- Recreate the patient + every related object (encounters, notes, commands, tasks, messages, lab orders/results, documents, conditions, medications, allergies, immunizations, appointments, billing line items, consents, observations, care team memberships) using **the same `id` as on source**.
- Sync `PatientExternalIdentifier` and `AppointmentExternalIdentifier` rows alongside their parents, with the original `system`/`value`/`identifier_type` intact (those are the integrating system's own data, not Canvas PHI; anonymizing them would defeat their purpose).
- Sync referenced staff/practitioner/location records if they don't already exist on the target, preserving their `id`s too.
- Fire a configurable callback URL when the sync completes (`succeeded` | `failed` | `partial`), so the integrating system can pull matching data on their side.
- Idempotent re-sync: running the same export twice converges (does not duplicate, does not fail).

### Out of scope (for v1)

- Bulk export of many patients in one call. (v1 is one patient per request; callers can batch by calling N times.)
- Configuration sync (instance-level Constance settings, code lists, plugin config). Most customers configure these separately.
- Reverse sync (target → source). One-way only.
- Real-time streaming sync. Each call is a snapshot at request time.
- Historical audit replay (recreating the exact sequence of events that produced the patient's state). We sync the final state, not the journey.

## Architecture

Two plugins. Both live in this directory.

```
┌─────────────────────┐       authenticated HTTPS        ┌─────────────────────┐
│  source plugin      │ ───────────────────────────────▶ │  target plugin      │
│  (installed on prod │   POST  /sync                    │  (installed on      │
│   Canvas instance)  │   body: {patient_bundle}         │   staging Canvas)   │
│                     │                                  │                     │
│  exposes:           │                                  │  exposes:           │
│    POST /export     │                                  │    POST /sync       │
│    (auth: shared    │                                  │    (auth: shared    │
│     secret)         │                                  │     secret)         │
│                     │                                  │                     │
│  on POST /export:   │                                  │  on POST /sync:     │
│   1. walk patient   │                                  │   1. validate auth  │
│      graph          │                                  │   2. dispatch       │
│   2. anonymize PHI  │                                  │      ImportEntity   │
│   3. POST bundle    │                                  │      effects        │
│      to target      │                                  │      (idempotent)   │
│   4. fire callback  │                                  │   3. return status  │
│      to caller              │                                  │                     │
└─────────────────────┘                                  └─────────────────────┘
         ▲                                                          │
         │                                                          │
         │  POST /export                                             │
         │  body: {patient_id, target_url, callback_url, ...}        │
         │                                                          ▼
   caller             ◀──────  POST {callback_url}  ──────────  (sync result)
   (or Canvas UI)            body: {status, applied_counts, ...}
```

Two plugins because the auth surfaces are different (source needs auth from the integrating system; target needs auth from source) and the install scope is different (source on prod, target on staging) — keeping them separate makes the trust boundaries explicit.

### Why HTTPS (not direct DB or S3)

- **Direct DB**: customers consistently raise this; Canvas does not give customers DB write access, period. Even a one-way replication channel into staging-only would let a buggy source query corrupt staging.
- **S3 bundle**: viable but adds a third trust boundary and a credentials story (signed URLs, bucket policy). Plugin-to-plugin HTTPS is one fewer moving piece.
- **HTTPS via SDK**: source uses `HttpRequestEffect` to POST to target's `SimpleAPI` endpoint. Auth via shared secret in plugin secrets. Retries + async execution available out of the box.

For very large bundles (a real production patient may have hundreds of notes/documents), we'll stream rather than send a single huge JSON. Concretely: source POSTs a manifest first, then POSTs each entity-type batch keyed by a `sync_id`. See **Wire format** below.

## API contract

### Source plugin endpoints

**`POST /export`** (called by the integrating system or Canvas UI to kick off a sync)

```jsonc
{
  "patient_id": "abc123def456...",          // Canvas patient id, OR
  "external_identifier": "EXT-12345",        // the integrating system external ID (lookup first)
  "target_url": "https://staging-instance.canvasmedical.com/plugin-io/api/target/sync",
  "callback_url": "https://case-manager.example.com/canvas-sync/webhook",
  "include": ["all"]                        // future: subset filters
}
```

Response (immediate, 202):

```jsonc
{
  "sync_id": "01HZX7…",                     // ULID, for callback correlation
  "status": "accepted",
  "started_at": "2026-05-18T18:32:00Z"
}
```

The actual work runs async (`HttpRequestEffect.set_async(...)`). the integrating system learns about completion via the callback.

### Target plugin endpoints

**`POST /sync`** (called by source plugin only — auth: shared secret)

Request body is the bundle (see **Wire format**). Response:

```jsonc
{
  "sync_id": "01HZX7…",
  "status": "dispatched" | "rejected",      // see note on async dispatch below
  "dispatched": {                           // counts of import effects enqueued
    "Patient": 1,
    "Note": 142,
    "Command": 318,
    "Task": 27,
    "...": "..."
  },
  "errors": [                               // bundle-validation errors caught before dispatch
    {"entity": "Note", "id": "…", "reason": "…"}
  ]
}
```

**Note on async dispatch.** Effects are processed asynchronously by Canvas — when target's `/sync` returns `dispatched`, the effects are queued but not yet applied. Target listens for effect-completion signals and reports final per-entity success/failure to source, which forwards them in the callback (see below). This is gap #4 in **SDK gaps** — the platform doesn't yet have a clean "wait until this batch settles" primitive, so the current design accepts eventual consistency on the order of seconds-to-minutes per sync.

### Callback fired by source

When the sync finishes (success or otherwise), source POSTs to the integrating system's `callback_url`:

```jsonc
{
  "sync_id": "01HZX7…",
  "status": "succeeded" | "partial" | "failed",
  "patient_id_on_source": "abc123…",
  "patient_id_on_target": "abc123…",        // same id; included for explicitness
  "finished_at": "2026-05-18T18:32:42Z",
  "summary_url": "https://prod.canvasmedical.com/plugin-io/api/source/syncs/01HZX7…"
}
```

Callback body is signed: header `X-Canvas-Signature: sha256=<hmac(secret, body)>`. the integrating system verifies before trusting.

## Wire format (patient bundle)

The bundle is JSON, streamed in chunks if large. Schema:

```jsonc
{
  "schema_version": "1.0",
  "sync_id": "01HZX7…",
  "source_instance": "prod.canvasmedical.com",
  "exported_at": "2026-05-18T18:32:00Z",
  "entities": {
    "Patient":                     [ { /* one record */ } ],
    "PatientExternalIdentifier":   [ /* ... */ ],
    "Staff":                       [ /* ... */ ],
    "PracticeLocation":            [ /* ... */ ],
    "Note":                        [ /* ... */ ],
    "Command":                     [ /* ... */ ],
    "Task":                        [ /* ... */ ],
    "Message":                     [ /* ... */ ],
    "LabOrder":                    [ /* ... */ ],
    "LabReport":                   [ /* ... */ ],
    "DocumentReference":           [ /* ... */ ],
    "Condition":                   [ /* ... */ ],
    "Medication":                  [ /* ... */ ],
    "AllergyIntolerance":          [ /* ... */ ],
    "Immunization":                [ /* ... */ ],
    "Appointment":                 [ /* ... */ ],
    "AppointmentExternalIdentifier": [ /* ... */ ],
    "Claim":                       [ /* ... */ ],
    "ClaimLineItem":               [ /* ... */ ],
    "PatientConsent":              [ /* ... */ ],
    "Observation":                 [ /* ... */ ],
    "CareTeamMembership":          [ /* ... */ ]
  }
}
```

### Apply order on target

Effects are dispatched in strict dependency order, because foreign keys. Target dispatches one `ImportEntity` effect per record, in this order:

1. **Reference data first**: `PracticeLocation`, `Staff` (the `ImportEntity` upsert no-ops if already present at same id).
2. **Patient**.
3. **PatientExternalIdentifier** (FK → Patient).
4. **Note** (note `id` referenced by commands; Canvas auto-creates the `Encounter` sidecar on Note creation).
5. **Command** (references Note).
6. Everything else, in order: `Condition`, `Medication`, `AllergyIntolerance`, `Immunization`, `Observation`, `LabOrder`, `LabReport`, `DocumentReference`, `Task`, `Message`, `Appointment`, `AppointmentExternalIdentifier`, `Claim`, `ClaimLineItem`, `PatientConsent`, `CareTeamMembership`.

Effects run asynchronously and independently. If effect N fails, effects 1..N-1 have already applied; idempotency makes a retry of the whole sync safe. Per-entity outcomes are aggregated as effects settle and forwarded to source for the callback.

### Idempotency

Every entity write is `INSERT … ON CONFLICT (id) DO UPDATE SET …` semantically (in Django: `update_or_create(id=…, defaults=…)`). Re-syncing the same patient overwrites the target with the latest source state. `id`s never change, so FK references stay valid.

## Anonymization policy

Performed on source before transmit, per entity. **Always on, no opt-out** — the API takes no `anonymize` flag because there's no scenario where shipping real PHI across instances is the right call. If a future use case ever needs un-anonymized data (e.g. a same-customer prod→prod restore for incident recovery), that's a different feature with a different audit trail, not a parameter on this one.

| Field                          | Replacement strategy                                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| `first_name`, `last_name`, etc.| Deterministic fake from a per-patient seed (so re-sync gives the same fake names).   |
| `birth_date`                   | Shifted by a per-patient ±30-day deterministic offset; preserves rough age cohort.   |
| `mrn`                          | Regenerated deterministically from `(source_instance, patient_id)`.                  |
| `social_security_number`       | Cleared.                                                                             |
| Address fields                 | Replaced with a generic address keyed on patient seed (same city, fake street/zip).  |
| Phone, email                   | Replaced with `+15550100xxxx` / `patient-<short_id>@example.invalid`.                |
| Free text (`administrative_note`, `clinical_note`, command bodies, message bodies, document content) | **v1: redact entire field.** v2: pluggable PHI scrubber (we'd want a real NLP pass before letting this through). |

Fields that are **not** PHI (codes, timestamps, FK relationships, statuses) pass through unchanged. The deterministic seed is derived from `HMAC(per-instance-anonymization-key, source_patient_id)` so the same input patient always produces the same fake — necessary for idempotent re-sync and for the integrating system to be able to map a synced patient back to a real one offline if they need to.

## ID preservation strategy

**Required:** target ends up with patient + every related record at the same `id` as source. this is the hard requirement ("encounter IDs and everything related to each object in the patient's home data set"). "The `id`" here means whatever Canvas put as the primary key on that record — a 32-char base62 key for `Patient`/`Staff`, a UUID for everything else (see *A note on "IDs"* in the Motivation section).

**Constraint:** the Canvas plugin runtime does **not** permit direct ORM writes to SDK-model tables. Every write must flow through an Effect.

**Status of the constraint, as of this audit:** more permissive than first assumed. Several effects already accept a client-supplied id on create:

| Effect                          | Client-supplied id field | Source                                                                                     |
| ------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------ |
| `Note` (visit notes)            | `instance_id`            | `effects/note/note.py` + [Note Effect docs](https://docs.canvasmedical.com/sdk/effect-notes/) |
| `Appointment`, `ScheduleEvent`  | `instance_id`            | `effects/note/appointment.py` + same docs page                                              |
| `Task`                          | `id`                     | `effects/task/task.py`                                                                      |
| Every `*Command` (Diagnose, Allergy, MedicationStatement, Immunization, Vitals, LabOrder, Goal, Plan, Prescribe, etc.) | `command_uuid` (set before `.originate()`) | [Commands docs — Chaining Methods with a User-set UUID](https://docs.canvasmedical.com/sdk/commands/) |
| `CompoundMedication`            | `instance_id`            | `effects/compound_medications/compound_medication.py`                                       |

**Approach:** use the existing effects with client-supplied ids for everything they cover (which is most of the volume in a real patient's record: notes, commands, tasks, appointments). For entity types where the effect rejects client ids or where the effect doesn't exist at all, follow the SDK-gap workstream in the *SDK gaps* section.

### Why not the obvious fallbacks

1. **Source-id-to-target-id mapping table** (sync via existing create effects, which mint a fresh `id` on target, and maintain a `source_id ↔ target_id` table that the integrating system queries before joining). rejected as an alternative. Mentioned only for completeness.
2. **FHIR REST `PUT /Resource/{id}` with client-supplied IDs.** Canvas's FHIR layer assigns server-side ids on POST and PUT requires the resource to already exist — so FHIR alone doesn't preserve ids today, though Canvas could extend it to support FHIR-standard "update-as-create" semantics. See the *Minimum SDK change to unblock this work* section for that option.

## ExternalIdentifier records

`PatientExternalIdentifier` and `AppointmentExternalIdentifier` are **separate from the primary key**. They're child tables with a FK back to the parent (`related_name="external_identifiers"`), and a parent can have **many** of them — one for each external system that has its own identifier for that record:

```python
class PatientExternalIdentifier(TimestampedModel, IdentifiableModel):
    patient = models.ForeignKey("v1.Patient", related_name="external_identifiers", ...)
    use = models.CharField(...)              # e.g. "official", "secondary"
    identifier_type = models.CharField(...)  # e.g. "MR", "MB"
    system = models.CharField(...)           # which external system (URI or name)
    value = models.CharField(...)            # the external id value
    issued_date = models.DateField()
    expiration_date = models.DateField()
```
(`canvas_sdk/v1/data/patient.py:243`)

This is how the integrating system would record, on the Canvas side, "this Canvas patient corresponds to `EXT-12345` in our integrating system." These rows are the integrating system's *own data*, not Canvas PHI — so they sync verbatim, no anonymization.

**Sync behavior:**

- Each `PatientExternalIdentifier` row sets sync-wise alongside its parent `Patient`. The row's own `id` (a UUID, since it inherits `IdentifiableModel`) is preserved.
- `system`/`value`/`identifier_type`/`use` are passed through unchanged.
- `issued_date` is preserved (it's not PHI on its own).
- Same applies to `AppointmentExternalIdentifier`.

**Coverage caveat:** only `Patient` and `Appointment` have `*ExternalIdentifier` child tables in the SDK today (I checked — no other model in `canvas_sdk/v1/data/` defines one). `Note`, `Encounter`, `Command`, `Task`, etc. don't. So for entities other than Patient and Appointment, the only thing the integrating system can use to join from their integrating system is the Canvas-assigned `id` itself — which is exactly why preserving it is the hard requirement.

## Security

- **Mutual shared secret** between source and target (different secret per pair). Stored as plugin secrets on each side.
- **Signed requests:** every body POSTed between plugins includes `X-Canvas-Signature: sha256=<hmac>`. Constant-time verify.
- **Per-request `sync_id`** prevents replay against an already-applied sync (target stores applied sync_ids forever; pruning is not on the roadmap).
- **caller callback** signed with a separate caller-issued secret (so source proves itself to caller, not the same key that protects source↔target).
- **TLS everywhere.** No plaintext fallback.
- **Audit log** on both source and target: who triggered, which patient, what got applied, when, success/failure. Plain Canvas events.
- **Same-instance guard**: source refuses any `/export` whose `target_url` resolves to the source's own host. Returns 400 with a clear error.
- **Source `/export` is API-key authenticated** (the `APIKeyAuthMixin` pattern used by other Canvas SimpleAPI plugins). the integrating system controls *who* can trigger by controlling who has the key; no per-user identity needed on Canvas's side. No UI surface ships with the plugin — if the integrating system wants a button, they add one in their own plugin that POSTs to `/export`.

## Failure modes

| Failure                                              | Behavior                                                                 |
| ---------------------------------------------------- | ------------------------------------------------------------------------ |
| Target unreachable (network)                         | `HttpRequestEffect` retries (configurable). On give-up: callback `failed`. |
| Target rejects auth                                  | No retry. Immediate `failed` callback.                                   |
| Mid-bundle FK violation (a referenced staff missing) | Target returns `partial` + the missing FK. the operator investigates.         |
| Sync_id already applied                              | Target returns `succeeded` (idempotent) without re-applying.             |
| Patient missing on source                            | Source returns 404 from `/export`. No callback fired.                    |
| Callback URL unreachable                             | Retry with exponential backoff up to 1 hour, then log + give up.         |
| `target_url` resolves to source's own host           | Source returns 400 from `/export` with `same-instance refused`. No callback fired. |

## SDK gaps

These are things the current Canvas SDK doesn't support, that this plugin requires. Each one is a candidate ticket for the SDK team. Listed in order of severity for this work.

1. **Id preservation is uneven across effects.** *(Severity: partial — see breakdown.)* Findings from an audit of `canvas_sdk/effects/` and the SDK docs:

   - **No change needed:** `Note`, `Appointment`/`ScheduleEvent`, `Task`, every `*Command`, `CompoundMedication` already accept a client-supplied id on create (see the table in *ID preservation strategy* above). For these entities, id preservation works on the current SDK.
   - **Small validator change needed:** these effects reject client ids today even though there's no underlying reason they couldn't accept them:
     - `Message` — explicit reject: `"Can't set message ID when creating a message."`
     - `Observation` — explicit reject: `"Observation ID should not be set when creating a new observation."`
     - `CreatePatientExternalIdentifier` — no id field on the effect at all (server assigns).
     - `AddBillingLineItem` — same; payload has no id.
   - **New effect needed entirely:** see gap #2.

   The fix for the middle bucket is small: add an optional `id` / `*_id` field to each effect's pydantic model and remove the reject-on-create validator. Each one is a ~10-line change in canvas-plugins.
2. **Several entities have no create-effect today.** Even setting id preservation aside, an `ImportEntity` is only useful if there's *some* sanctioned way to put a record of that type into Canvas. Inventory based on the current `canvas_sdk/effects/` and `canvas_sdk/commands/` tree:

   **Has a create-path today (verified end-to-end against home-app handlers):**

   | Entity                         | Create-path                                                                          | Client-supplied id, end-to-end?           |
   | ------------------------------ | ------------------------------------------------------------------------------------ | ----------------------------------------- |
   | `Note`                         | `NoteEffect.create()`                                                                | **Yes — verified.** `home-app/plugin_io/interpreters/notes/base.py:43,201` uses `payload_data.get("instance_id", uuid4())` and passes it as `externally_exposable_id` on `Note.objects.create()`. |
   | Any `*Command` (Diagnose, Allergy, MedicationStatement, Immunization, Vitals, LabOrder, Goal, Plan, Prescribe, etc.) | `cmd.originate()` after setting `cmd.command_uuid` | **Yes — verified.** `home-app/plugin_io/interpreters/commands/originate.py:25-32` passes `uuid=self.command_uuid` to `commands.originate_command(...)`. |
   | `Task`                         | `AddTask` effect (`CREATE_TASK`)                                                     | **Yes — verified.** `home-app/plugin_io/interpreters/tasks/add_task.py:31-32`: `data["integration_payload"]["externally_exposable_id"] = task_id`. |
   | `Appointment`                  | `AppointmentEffect.create()`                                                         | **No — server ignores.** Client effect accepts `instance_id`, but `home-app/plugin_io/interpreters/notes/appointment.py:108-119` calls `Appointment.objects.create(...)` without `externally_exposable_id`. The *inner* Note keeps its id; the Appointment row gets a fresh UUID. Plumbing fix needs a home-app PR. |
   | `ScheduleEvent`                | `ScheduleEventEffect.create()`                                                       | **No — server ignores.** Same pattern, `home-app/plugin_io/interpreters/notes/schedule_event.py:17-27`. Plumbing fix needs a home-app PR. |
   | `CompoundMedication`           | `CompoundMedication.create()`                                                        | **No — server ignores.** Client effect serializes `instance_id`, but `home-app/plugin_io/interpreters/compound_medications/compound_medication.py:121-162` (the create-validator) doesn't pull it into `cleaned_data`. Plumbing fix needs a home-app PR. |
   | `Patient`                      | `Patient.create()` (`canvas_sdk/effects/patient/base.py:106`)                        | **No.** Client rejects `patient_id` on create (`canvas_sdk/effects/patient/base.py:176-183`); server also drops it (`home-app/data_integration/messages/consumers/patient.py:62-100` builds `patient_fields` without a `key`). **Two-PR plumbing fix** (client validator + server handler). |
   | `Message`                      | `Message.create()` / `Message.create_and_send()`                                     | **No.** Client rejects, server ignores. Two-PR plumbing fix. |
   | `Observation`                  | `Observation.create()`                                                               | **No.** Client rejects, server ignores. Two-PR plumbing fix. |
   | `PatientExternalIdentifier`    | `CreatePatientExternalIdentifier` effect                                             | **No.** Effect has no id field. Two-PR plumbing fix (add field + plumb through server). |
   | `BillingLineItem`              | `AddBillingLineItem` effect (`ADD_BILLING_LINE_ITEM`)                                | **No.** Effect has no id field. Two-PR plumbing fix. |
   | `QuestionnaireResponse`        | `CreateQuestionnaireResult` effect                                                   | **No.** Effect has no id field; plumbing fix if the integrating system cares about these. |

   **Methodology note:** an earlier draft listed Appointment/ScheduleEvent/CompoundMedication as "probably yes" based on the client-side effect accepting `instance_id`. Reading the home-app handlers showed those values get dropped on the server. The verified-end-to-end set is now Note + Commands + Task only.

   **No create-path today (new effect needed):**

   | Entity                            | SDK gap                                                          | FHIR coverage                                                                  | Net status                                                                                  |
   | --------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
   | `Staff`                           | Read-only via SDK.                                               | `POST /Practitioner` creates.                                                  | Reachable via FHIR (server-assigned id only).                                               |
   | `PracticeLocation`                | Read-only via SDK.                                               | FHIR read/search only.                                                         | **Genuinely uncreatable** through any sanctioned surface.                                   |
   | `Encounter` (standalone)          | No create-effect.                                                | FHIR read/search only.                                                         | **Genuinely uncreatable.** Encounters may be side effects of note/appointment creation today. |
   | `LabReport`                       | `HealthGorillaLabReportIngest` effect exists (KOALA-4854, shipped May 2026); the server-side handler accepts `external_id` for partner-dedup but doesn't read a client-supplied `externally_exposable_id`. **Same shape as the other plumbing-fix entries** — small server-side change to preserve Canvas's internal id. | `DiagnosticReport` is FHIR read/search only. | **Plumbing fix** (see plumbing-fix list).                                                  |
   | `DocumentReference`               | No create-effect.                                                | `POST /DocumentReference` creates.                                             | Reachable via FHIR (server-assigned id only).                                               |
   | `Claim`                           | Several edit effects exist; no `CREATE_CLAIM`.                   | `POST /Claim` creates.                                                         | Reachable via FHIR (server-assigned id only). Claims are typically derived from finalized notes anyway. |
   | `ClaimLineItem`                   | `UPDATE_CLAIM_LINE_ITEM` only.                                   | Line items are part of the `Claim` payload.                                    | Reachable via FHIR as a side effect of `Claim` create.                                      |
   | `PatientConsent`                  | No create-effect.                                                | `POST /Consent` creates.                                                       | Reachable via FHIR (server-assigned id only).                                               |
   | `CareTeamMembership`              | No create-effect.                                                | `CareTeam` has FHIR update, no create — but Canvas only has one CareTeam per patient. | Reachable via FHIR `PUT /CareTeam/{patient_id}`.                                            |
   | `AppointmentExternalIdentifier`   | No create-effect (only the *Patient* variant has one).           | The `identifier` array is part of the `Appointment` FHIR payload.              | Reachable via FHIR `PUT /Appointment/{id}` after create.                                    |

   **Important caveat:** every FHIR create endpoint assigns the id server-side. Canvas's FHIR docs say "On success, the new Patient's identifier is returned in the `Location` header of the response" — meaning POST does not accept client-supplied ids, and PUT requires the resource to already exist (no "update-as-create" behavior documented). So **FHIR fills the "can it be created at all?" gap, but does not solve id preservation.** That's why these entities are described as "reachable via FHIR" but still tracked as gaps until either a) SDK create-effects with client-supplied ids exist, or b) Canvas's FHIR layer supports update-as-create.

   **Net work for the new-effect tier:**
   - For the seven entities reachable via FHIR, options are: (a) add SDK create-effects that accept client-supplied ids, or (b) extend Canvas's FHIR layer to honor client-supplied ids on PUT (FHIR-standard "update-as-create"). See *Minimum SDK change to unblock this work* for the trade-off.
   - For the one entity with no write path (`PracticeLocation`), no FHIR fallback exists; the SDK has to add a create-path regardless of which option is chosen.
3. **Limited transactional multi-effect grouping.** Effects commit independently in general — except for commands, which have `BatchOriginateCommandEffect` (`canvas_sdk/effects/batch_originate.py`) that originates a batch of commands as a single effect. So the gap is real for everything *except* commands; for commands, the primitive exists today and the sync plugin can use it to atomically apply a note's worth of commands in one go. A `transaction` / `bundle` primitive that generalizes to other effects would be the broader fix.
4. **Effect dispatch is asynchronous.** When the target plugin returns from `POST /sync`, it has *enqueued* effects, not confirmed they ran. So the response can only honestly say "dispatched", not "applied", and the source-side callback has to wait for per-effect completion signals. Either (a) an SDK primitive for "wait until these effects settle" or (b) an event the plugin can subscribe to that fires when a given effect succeeds/fails.
5. **No SDK helpers for PHI anonymization.** Every plugin that touches PHI rolls its own. A `canvas_sdk.privacy` module with deterministic fakers (name, DOB shift, address, MRN, SSN) keyed on a per-plugin secret would prevent each customer from inventing this poorly. Lower severity for our work (we'll write our own), but worth flagging.
6. **No standard pattern for plugin-to-plugin auth.** Each pair invents its own shared-secret + signed-body scheme. A small `canvas_sdk.federation` module (shared-secret config + HMAC verify helper + signed-request middleware for `SimpleAPI`) would let this plugin and future cross-instance plugins skip the boilerplate.
7. **No bundle-export helper for "everything related to a patient."** Walking 20+ FK relationships from `Patient` is plugin-side work today, and easy to get wrong (drop a relation, miss a record). A `Patient.export_bundle()` SDK method (or a documented graph spec) would make this plugin a hundred lines shorter. Could ship as part of #1, since import and export both want the same graph definition.
8. **Existing originate-command effects model user intent, not state restore.** `ORIGINATE_*_COMMAND` effects represent "a user wrote this command and committed it" — they fire downstream side effects (claim generation, billing, notifications, etc.). For sync we want server-side state restore *without* downstream side effects. The new `ImportEntity` effect in gap #1 should have a `suppress_side_effects: true` option, or be a separate restore-only family. Without this, syncing a patient could spuriously fire billing claims, send messages, etc.

## Minimum SDK change to unblock this work

Audit-revised view: **a verified-end-to-end subset of this plugin can ship with zero SDK changes.** Notes, clinical commands (all command types), and tasks accept client-supplied ids end-to-end today (both the client-side SDK effect AND the server-side home-app handler honor the id). Together these cover the bulk of the volume in a real production patient — commands and notes are typically 80%+ of the record by row count.

The remaining work needed to do a *complete* sync, in two tiers:

### Plumbing fixes: two-PR changes to existing effects (canvas-plugins + home-app)

Each effect on this list needs **both** a client-side change (to accept/serialize the id) **and** a server-side change (to honor the id on `objects.create()`). Each PR is small (~10 lines), but you need both halves before id preservation works end-to-end:

- `Patient` — client: remove reject at `canvas_sdk/effects/patient/base.py:176-183`; server: include `key` from `payload_data["patient_id"]` in `home-app/data_integration/messages/consumers/patient.py:process_patient_message`.
- `Appointment` — client: already accepts `instance_id`; server: include `externally_exposable_id` in `Appointment.objects.create(...)` at `home-app/plugin_io/interpreters/notes/appointment.py:108-119`.
- `ScheduleEvent` — client: already accepts `instance_id`; server: same fix at `home-app/plugin_io/interpreters/notes/schedule_event.py:17-27`.
- `CompoundMedication` — client: already accepts `instance_id`; server: pull it into `cleaned_data` in the create-validator at `home-app/plugin_io/interpreters/compound_medications/compound_medication.py:121-162`.
- `Message` — client: remove reject at `canvas_sdk/effects/note/message.py:86-93`; server: include `externally_exposable_id` at `home-app/plugin_io/interpreters/message/message.py:112`.
- `Observation` — client: remove reject at `canvas_sdk/effects/observation/base.py:108-115`; server: include `externally_exposable_id` at `home-app/plugin_io/interpreters/observations/observation.py:204-214`.
- `CreatePatientExternalIdentifier` — client: add an `id` field; server: plumb through.
- `AddBillingLineItem` — client: add an `id` field; server: plumb through.
- `LabReport` (via `HealthGorillaLabReportIngest`, KOALA-4854 shipped May 2026) — client: add an internal-id field; server: include `externally_exposable_id` in `LabReport.objects.create(...)` at `home-app/plugin_io/interpreters/lab_orders/lab_report_ingest.py:139`.

### New effects for entities that have no create-path today

Eleven entity types still need *some* create-path. Three options for shape (smallest to largest):

### Option 0 — Extend FHIR to support update-as-create *(smallest, but partial coverage)*

Canvas's FHIR layer already supports create/read/update for ~20 of the entity types in the bundle. FHIR-standard "update-as-create" means: a `PUT /Resource/{id}` where `{id}` doesn't yet exist creates the resource at that id. Canvas's FHIR docs today imply PUT requires an existing resource (404 on missing). Extending the FHIR layer to honor client-supplied ids on PUT would:

- Let the target plugin POST entities via FHIR with preserved ids, using `HttpRequestEffect` against the local FHIR endpoint.
- Cover (per the gap table above): Patient, Practitioner (Staff), AllergyIntolerance, Appointment, Claim+ClaimLineItem, Communication (Message), Condition, Consent (PatientConsent), Coverage, DetectedIssue, DocumentReference, Group, Immunization, Media, MedicationStatement, Observation, PaymentNotice, QuestionnaireResponse, Task, CareTeamMembership (via CareTeam update).
- Leave **2 entity types still uncreatable**: `PracticeLocation`, `Encounter` — these have no FHIR create endpoint at all. Those would need new SDK effects regardless. (`Note` has a create-effect already; `LabReport` is a plumbing fix via the existing HG ingest effect.)

Cost on Canvas's side: changes to the FHIR layer (fumage) to accept client-supplied ids and create-on-missing semantics. Per-resource since each resource controller is its own module. Not a small change, but stays inside an existing system and inherits FHIR conformance/test coverage.

Foot-gun: id collisions. If the client supplies an id that already exists with different content, what wins — the upsert or a 409 conflict? FHIR-standard says PUT replaces, so the upsert. Need to be explicit about this in the resource validator and log every such overwrite.

This option doesn't cover Note/Encounter/LabReport/PracticeLocation, so it doesn't fully solve the problem alone — it would need to be paired with a smaller version of Option A/B for those four.

### Option A — Generic `UpsertModel` effect *(smallest possible change that covers everything)*

A single effect, shaped roughly like:

```python
UpsertModel(
    app_label="v1",
    model_name="Patient",
    id="abc123...",
    fields={"first_name": "...", "birth_date": "...", ...},
)
```

The plugin runner resolves `apps.get_model(app_label, model_name)` and calls `.objects.update_or_create(id=id, defaults=fields)` in home-app. **No per-entity-type code.** Django handles validation, FK constraints, type coercion.

Gating:
- Per-handler `data_access.write` declaration in the plugin manifest, naming each model the handler will upsert. This is Canvas's existing access-gating mechanism (e.g. `"write": ["patients", "notes", "commands"]` on the handler that dispatches `UpsertModel`). The plugin loader already validates these declarations against the schema in `canvas_cli/utils/validators/manifest_schema.py`.
- Server-side allowlist of writable `(app_label, model_name)` pairs — so even with a `data_access.write` declaration the effect can't reach `CanvasUser`, `Plugin`, billing-critical tables, etc.
- Audit log entry for every dispatch: requesting plugin, entity, id, diff, timestamp.

Cost on SDK side: roughly *one* new effect class, *one* dispatcher branch in the plugin-runner, *one* allowlist constant, *one* audit-log call site. Reuses the entire Django ORM for the actual write.

Foot-gun: bypasses any business-logic-only-enforced-in-Python (e.g. "you can't change a committed note without recording an amendment"). Also fires Django `post_save` signals, which means downstream side effects (billing claim generation, search index updates, audit logging, etc.) trigger spuriously on a restore. **Mitigation:** add a `suppress_signals: bool = True` flag on the effect that wraps the save in a signal-disconnect context manager. Conservative default = suppress, because for sync/restore that's what we want.

### Option B — Typed `ImportEntity` effects per entity type *(medium change)*

A family of effects (`ImportPatient`, `ImportNote`, `ImportCommand`, …), each with a typed schema. Plugin runner dispatches to a registry of per-entity appliers, each of which knows the model and the legal field set.

Cost on SDK side: ~20-40 new effect classes + appliers, each one small but each one another moving part. Type safety > Option A; a typo in a field name is caught at effect-construction, not at ORM-call time.

Foot-gun: still has the signal-side-effects problem. Solved the same way.

### Option C — `ImportPatientBundle` macro effect *(largest change, most opinionated)*

A single effect that takes the entire patient bundle and applies it server-side in the correct dependency order, atomically. Plugin authors don't worry about ordering; the platform owns the patient-graph definition.

Cost on SDK side: significant — defines and maintains the canonical patient-graph in the platform, which doesn't exist anywhere today and will need ongoing curation as new tables are added.

Foot-gun: less than A/B (centrally owned, atomic, no signal accidents because the import path is purpose-built). But the largest change to design and ship.

### Recommendation

**Ship the plugin in two waves.**

- **Currently possible (zero SDK changes, integration only):** ship the source/target plugins with support for Note, Commands (all clinical command types), and Task — the three entity types verified end-to-end. **This release cannot sync a brand-new patient end-to-end** — Patient id preservation needs a plumbing fix. The value alone is to prove the architecture works against a patient that already exists on target at the matching id (pre-provisioned manually). For Staff and PracticeLocation (which Notes reference and which have no create-effect today), the dispatcher falls back to any existing row on target rather than requiring a match; mismatched provider/location ids on the synced notes are acceptable because the integrating system joins on Note / Command / Patient ids, not Staff / Location. Useful for engineering validation; not for real the integrating system test scenarios.
- **After plumbing fixes (the first useful release):** once the eight plumbing-fix effects above land their client+server PR pairs, the sync covers an end-to-end patient creation including most of what a typical patient has. **This is the release customers start exercising real scenarios.**
- **Full coverage:** once the missing-create-effect work lands (whichever option below the SDK team chooses), the sync becomes complete.

For the new-effect tier, **Option A (generic `UpsertModel` effect) is the recommended shape**, with Option 0 (extend FHIR for update-as-create) as a credible runner-up. The arguments:

- Option 0 alone leaves PracticeLocation uncreatable (no FHIR Location create), so Option 0 can't ship the new-effect tier in one piece.
- Option A is one effect class plus a dispatcher; the FHIR-extension path touches ~20 resource controllers in fumage, each with its own validation and conformance considerations.
- Option A's reach is centrally allowlisted in one place; Option 0's reach is spread across the FHIR layer's existing per-resource auth.
- Option A subsumes future export/import/restore/clone use cases beyond this plugin; Option 0 specifically enables one FHIR-shaped workflow.

That said, **Option 0 is credible** if the SDK team has reasons to prefer extending fumage over adding a new effect class (e.g., security-review velocity, existing FHIR test infrastructure, or a planned audit-log story in fumage that's further along than in the plugin runner). If we go this route, the still-uncreatable entities (PracticeLocation, Encounter, LabReport, possibly AppointmentExternalIdentifier) become their own ticket and the sync plugin lists them in `unsupported_entities` until they land.

Either way, the plugin in this repo (`patient_sync_target/handlers/importer.py`) carries the per-entity ordering and dispatch logic; moving it server-side later (toward Option B or C) is straightforward once we've learned what's actually painful in practice.

Concretely, the SDK PR is approximately:

1. `canvas_sdk/effects/upsert_model.py` — new effect class.
2. `home-app/<wherever effects dispatch>` — handler that resolves the model, checks the allowlist, runs `update_or_create`, optionally suppresses signals, writes an audit log entry.
3. `home-app/<settings or constants>` — the allowlist constant (initial entries: every model we want this plugin to write).
4. A manifest-capability check in plugin-load that refuses to register the effect if the plugin's manifest doesn't request it.

Estimate: small. Most of the work is the allowlist content and getting agreement on the audit-log shape. Everything else is one effect class and a 30-line dispatcher.

## Out of this doc

- **Implementation details** of the bundle walker, anonymizer, applier — those are in the plugin code (`patient_sync_source/handlers/exporter.py`, `patient_sync_target/handlers/importer.py`) and are intentionally minimal in v1.
- **Operational concerns** (deployment, monitoring, alerting, runbook) — left to whoever adopts this past the reference-plugin stage.
- **A separate spec for the SDK changes** in the gaps section — those are tickets for the SDK team, not part of this plugin's deliverable.
