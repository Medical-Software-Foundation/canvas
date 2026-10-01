# Salesforce Reference Implementation

This folder is a deployable Salesforce CLI project showing one way to
configure a Salesforce org for the deliberate sync. It is an example, not a
managed package and not the only valid shape. Deploy it to a sandbox to see
the integration work end to end, then tailor it to the org's needs, or use
the files as the exact blueprint for manual Setup work. The plugin side of
the contract is described in the plugin README under Salesforce side setup.

## The model in one paragraph

Sync is a deliberate act, a button a rep clicks, not a side effect of saving
a record. Two Quick Actions on the Contact carry intent, Sync to Canvas
pushes the Contact to Canvas, Remove from Canvas marks the linked Canvas
patient for removal and does not touch the Salesforce Contact. Each button
runs a short screen Flow that calls one Apex emitter, and the emitter posts a
signed payload to the plugin's single webhook endpoint. Every request lands
in the Canvas admin console where a human operator resolves it. Nothing
changes in Canvas automatically, and nothing fires on a plain record save.

## What is inside

```
force-app/main/default/
├── classes/CanvasSyncEmitter.cls               The invocable the button Flows call
├── classes/CanvasSyncJob.cls                   The retrying Queueable that delivers the callout
├── classes/CanvasSyncEmitterTest.cls           End to end enqueue and deliver test
├── classes/CanvasSyncJobTest.cls               Per status retry classification test
├── flows/Canvas_Sync_To_Canvas_Action.flow-meta.xml      The screen action behind the Sync button
├── flows/Canvas_Remove_From_Canvas_Action.flow-meta.xml  The screen action behind the Remove button
├── quickActions/Contact.Canvas_Sync_To_Canvas.quickAction-meta.xml
├── quickActions/Contact.Canvas_Remove_From_Canvas.quickAction-meta.xml
├── objects/Contact/fields/Canvas_Patient_ID__c.field-meta.xml             The reverse link the plugin writes
├── objects/Contact/fields/Canvas_Status__c.field-meta.xml                 The derived at a glance badge
├── objects/Contact/fields/Canvas_Sync_Status__c.field-meta.xml            Delivered, Retrying, Failed
├── objects/Contact/fields/Canvas_Sync_Last_Error__c.field-meta.xml
├── objects/Contact/fields/Canvas_Sync_Last_Attempt__c.field-meta.xml
├── objects/Webhook_Config__mdt/                The custom metadata type, the secret, the endpoint, and the field list
├── customMetadata/Webhook_Config.Default.md-meta.xml   The seeded Default record, blank secret
├── permissionsets/Canvas_Sync_Access.permissionset-meta.xml
└── remoteSiteSettings/Canvas_Plugin_Webhook.remoteSite-meta.xml
```

## The artifacts

### The two action buttons

Two Quick Actions on Contact let a rep drive the sync by clicking, Sync to
Canvas and Remove from Canvas. Each is a Flow action that launches a small
screen Flow. The Flow receives the Contact through a `recordId` input
variable, confirms intent on a screen, and then calls the same
`CanvasSyncEmitter` invocable, passing a fixed intent, sync for one button
and delete for the other. Because the buttons reuse the emitter, the signing,
retry, and status writeback all behave exactly as the emitter defines them.

The Remove Flow guards itself. It first reads the Contact and checks
`Canvas_Patient_ID__c`, and if nothing is linked it tells the rep there is
nothing to remove rather than firing. That guard is the reason the old no
delete on create validation rule is no longer needed, the same protection now
lives in the Flow.

The emitter is fire and forget, it enqueues an async job, so the button
cannot show the final Delivered or Failed outcome on screen. It confirms the
request was queued, and the status badge reflects the real result within
seconds.

### The reverse link field

`Canvas_Patient_ID__c`, Text(64). The plugin writes the Canvas patient UUID
into it after a successful Create patient resolution, over the OAuth
connection established in the plugin admin console Settings tab. If an
inbound payload carries this field the plugin's matcher short circuits
straight to that patient. Reps see it read only through the permission set.

### The status badge

`Canvas_Status__c` is a read only formula that renders one at a glance value
from the reverse link and the last delivery outcome, a green Synced when a
Canvas patient is linked, Sent awaiting Canvas when the last request reached
Canvas and is waiting on an operator, a yellow Retrying, a red Error, or Not
synced when nothing has been pushed. It writes nothing, it only reads fields
the emitter and the plugin already maintain. Add it and the two actions to
the rep page layout, the same way the raw status fields are added.

### The Apex, an invocable and a retrying job

`CanvasSyncEmitter` exposes an `@InvocableMethod` the button Flows call. It
stays thin, it enqueues one `CanvasSyncJob` per request so the Flows never
change when the delivery mechanism does.

`CanvasSyncJob` is a `Queueable` that implements `Database.AllowsCallouts`
and does the work, reads the config record, builds the field list and
queries the Contact, builds the nested `{intent, record}` body, signs the
exact bytes it sends with HMAC SHA256 against the shared secret, and POSTs
to the configured endpoint with the signature in `X-Signature` as
`sha256=<hex>`. A sync carries the mapped demographic fields, a delete
carries only the `Id`. The keys in the record map use the Salesforce field
API names the plugin's field mapping expects, see Field mapping in the
plugin README.

The job reads the response and decides what to do. A 202 is delivered. A
400 or 401 is permanent, a bad body or a bad secret never succeeds on retry,
so it does not re enqueue. A 5xx, a timeout, or a thrown `CalloutException`
is transient and re enqueues with a growing delay up to a cap. A `Finalizer`
records a Failed status even when an unhandled limit exception escapes the
try blocks.

`CanvasSyncEmitterTest` drives the enqueue path end to end and asserts the
delivered status and the payload, `CanvasSyncJobTest` asserts the retry
decision per status code through the written status. Both inject the config
through a test seam since custom metadata cannot be inserted by DML.

### The sync status fields

The job writes three Contact fields so a rep sees a delivery failure on the
record they are already looking at. `Canvas_Sync_Status__c` reads Delivered,
Retrying, or Failed. `Canvas_Sync_Last_Error__c` holds the HTTP status and
the response body or the exception message on a failure. `Canvas_Sync_Last_Attempt__c`
holds the time of the last attempt. The permission set grants reps read on
all three, and the status badge above folds them into one value. Add them to
the rep page layout.

### Shared plumbing

| Artifact                                   | Purpose                                                                   |
| ------------------------------------------ | ------------------------------------------------------------------------- |
| Custom Metadata Type `Webhook_Config__mdt` | One `Default` record holding `Secret__c`, `Endpoint__c`, and `Fields__c`. The secret equals the plugin `SF_WEBHOOK_SECRET` |
| Remote Site Setting `Canvas_Plugin_Webhook` | Allow lists the Canvas host so the Apex callout is permitted              |
| Permission Set `Canvas_Sync_Access`        | Grants reps run access to the emitter and read on the reverse link, the three sync status fields, and the Canvas Status badge |

Endpoint and field list are config, not code. The endpoint URL and the
Salesforce field list both live on the Default record, so an admin tailors
them in Setup without editing Apex. The Remote Site Setting still has to
allow list the same host, that is org security policy Salesforce enforces on
every callout. A Named Credential would unify the endpoint and the remote
site into one artifact and is the natural production upgrade.

## Deploy with the CLI

```bash
sf org login web --alias my-org
sf project deploy start --source-dir force-app --target-org my-org
sf apex run test --class-names CanvasSyncEmitterTest CanvasSyncJobTest --target-org my-org --result-format human
```

## What to tailor before deploying

1. The endpoint. The seeded `Default` record ships with the placeholder
   `https://your-canvas.canvasmedical.com`. Set `Endpoint__c` to the real
   Canvas webhook URL and set the Remote Site Setting to the same host.
2. The shared secret. The seeded `Default` record ships with a blank secret,
   the value is deliberately not in source. In Setup open the `Default`
   record and paste the plugin secret `SF_WEBHOOK_SECRET` into `Secret__c`.
3. Page layouts and the action bar. Layouts are org specific so none ship
   here. Add the Sync to Canvas and Remove from Canvas actions to the Contact
   record page action bar, and add the Canvas Status badge and the three
   Canvas Sync status fields to the layouts the reps use.
4. The demographic fields. The seeded `Default` record carries the field
   list in `Fields__c`, the fifteen the default plugin mapping expects.
   Adjust it in step with the plugin's `SF_FIELD_MAPPING_JSON`, no Apex edit.
5. The source sObject. Everything here targets Contact. For Lead or a custom
   sObject, rename the field references, the two Flows, the two actions, and
   the emitter references and set the plugin secret `SF_SOURCE_SOBJECT` to
   match.

After deploying, assign the `Canvas_Sync_Access` permission set to the reps
who drive the sync.

## Manual Setup equivalents

Every file here maps to a Setup screen, so an org that prefers clicking can
rebuild the example by hand.

1. Object Manager, Contact, Fields and Relationships. Create the
   `Canvas_Patient_ID__c` text field exactly as the field file specifies,
   create the three sync status fields, `Canvas_Sync_Status__c` as a
   restricted picklist with Delivered, Retrying, and Failed,
   `Canvas_Sync_Last_Error__c` as a long text area, and
   `Canvas_Sync_Last_Attempt__c` as a datetime, create the `Canvas_Status__c`
   formula from its file, and add all of them to the page layouts.
2. Custom Metadata Types. Create `Webhook_Config__mdt` with a `Secret__c`
   text field, an `Endpoint__c` URL field, and a `Fields__c` long text area,
   add a `Default` record, paste the plugin's `SF_WEBHOOK_SECRET` into the
   secret, set the endpoint to the Canvas webhook URL, and set the field list
   to the Salesforce field API names that mirror the plugin mapping.
3. Remote Site Settings. Add the Canvas host so the callout is allowed.
4. Apex Classes. Add `CanvasSyncEmitter`, `CanvasSyncJob`, and their two test
   classes from their files. In a production org Apex cannot be created
   through Setup, deploy it from a sandbox or use the CLI path above.
5. Flow Builder. Create the two screen Flows exactly as their files specify,
   each with a `recordId` text input variable, and activate them.
6. Quick Actions. On Contact create two actions of type Flow, one pointing at
   each screen Flow, label them Sync to Canvas and Remove from Canvas, and add
   them to the record page action bar.
7. Permission Sets. Create `Canvas_Sync_Access` granting run access to the
   emitter and read on the reverse link, the three status fields, and the
   Canvas Status badge, and assign it to the reps.

## How Contacts flow after setup

A rep opens a Contact and clicks Sync to Canvas. The screen Flow confirms,
the emitter posts the signed payload, and within seconds the Contact appears
in the Canvas admin console as a pending row, Create if no Canvas patient is
linked yet, Modify if one is. A Canvas operator reviews the row and applies
or skips it, nothing is written to the chart until then. On a successful
Create the plugin writes the new patient's id back into Canvas Patient ID on
the Contact, closing the loop, and the Canvas Status badge flips to Synced.

To push later edits, the rep clicks Sync to Canvas again. Each click sends
the current demographics, and the plugin dedupes a click that changes nothing
by comparing content hashes, so a stray click is harmless. When the person
should no longer exist in Canvas, the rep clicks Remove from Canvas, which the
Flow allows only when a Canvas patient is linked, and a removal request lands
in the console for the operator to resolve.

Verify the wiring after deploy by clicking Sync to Canvas on a test Contact,
the row should land in the plugin admin console within seconds.
