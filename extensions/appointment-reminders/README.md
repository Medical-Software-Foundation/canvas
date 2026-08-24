# appointment_reminders

Appointment reminders and confirmations over SMS and email, with per-business-line branding and routing and a two-way Y/N confirm flow.

## What it does

- **Appointment notifications** — confirmation, reminder, cancellation, no-show, and telehealth-join messages via Twilio (SMS) and SendGrid (email). Per-note-type templates with `{{placeholder}}`s; multi-interval reminder cadence (default `[4320, 45]` = 3 days + 45 min).
- **Per-business-line branding + routing** — `{{business_line_attribution}}` / `{{business_line}}` placeholders; per-line **attribution** override → default fallback; per-line outbound **from-number** → global fallback. A patient's business line (`Patient.business_line`) drives which branding/number is used.
- **Two-way structured confirm** — a signature-gated Twilio inbound webhook: `Y` confirms the patient's nearest upcoming appointment, `N` opens a follow-up Task. Strict Y/N token match (no free-form), `MessageSid` replay dedup, fail-closed signature check.
- **STOP writes back to the chart** — a patient who texts a Twilio opt-out keyword has `has_consent` cleared on the number they texted from, so the opt-out survives in Canvas and not just in Twilio's block list. `START` / `UNSTOP` / `YES` restore it.
- **Admin console gated by role** — the `/admin` endpoints require a staff role listed in `ADMIN_ROLE_NAMES`. Fail-closed: unset means nobody.
- **Testing-mode gate** — a fail-closed allowlist (`TESTING_MODE`) that restricts *all* sends to specific patients **and** recipients, for safe troubleshooting on a live instance.

> **Reminder and telehealth-join are independent campaigns, so overlapping intervals double up.** Telehealth-join runs whether or not the reminder campaign is on for that visit type. Give them the same interval and a patient with a telehealth visit receives two SMS and two emails about the same appointment, seconds apart (observed in UAT with both set to 15 minutes). Configure around it: stagger the intervals, for example reminders at 45 minutes and the join nudge at 15, or switch the reminder campaign off for telehealth visit types under **Per-visit-type settings**.

## Screenshots

Campaign configuration in the provider-menu admin app. Each campaign has its own SMS and email template, channel toggles, and enable switch.

![Campaign configuration showing the Booking Acknowledgement templates](screenshots/01-admin-campaigns.png)

Per-business-line overrides set the patient-facing attribution and an outbound number for each line.

![Business Line Overrides tab](screenshots/02-business-line-overrides.png)

Every campaign can be turned off or customized per visit type.

![Visit Type Overrides tab](screenshots/03-visit-type-overrides.png)

In a patient's chart, staff can preview the rendered copy for any campaign, send it by hand, and review everything sent to that patient.

![Patient chart panel showing the send form and reminder history](screenshots/04-patient-panel.png)

## Problem it solves

Canvas ships native appointment reminders, but they are a single global setting: one cadence, one wording, no per-visit-type variation, and a confirm loop you cannot extend. Practices that run several lines of business, or that need compliance-approved wording, or that want a telehealth join link delivered separately from the reminder itself, have no way to express that natively.

This plugin replaces the native reminders with campaigns you configure per visit type and per business line, and it turns patient replies into real state: `Y` confirms the appointment on the schedule, `N` opens a follow-up Task for staff.

## Who it's for

Practices on Canvas that need more than one reminder policy. Typically that means one of:

- **Multiple business lines or payers** where each needs its own sender number and its own patient-facing name.
- **Telehealth visits** that need a join link close to the appointment, separate from the day-before reminder.
- **Compliance-approved copy** that must not be reworded by whoever sends a message by hand.
- **Two-way confirmation** where a patient's reply should update the schedule rather than land in an inbox.

If you need one reminder, at one interval, with one wording, Canvas's native setting is simpler and you should use that instead.

> ### ⚠ Read before you enable a campaign
>
> **This plugin replaces Canvas's native appointment reminders. It cannot detect them.** Native reminders are driven by the `appointmentReminders` **organization setting**, which plugins cannot read — there is no SDK model for it and no way for this plugin to warn you at runtime. If it is still set when you enable the `reminder` or `confirmation` campaign, **every patient gets two reminders**: one from Canvas, one from here.
>
> Installing is safe on its own — all five campaigns ship **disabled**, so nothing sends until you turn one on. The checklist below is what has to happen before that first switch.

## Pre-install checklist

Work through these in order. Steps 1–3 are required before enabling any campaign; step 4 applies only if you want two-way confirmation.

1. **Check whether native reminders are on.** Look for the `appointmentReminders` organization setting. If it holds a value like `{"daysAhead": 3, "hourOfDay": 9}`, native reminders are **active**. If the setting is absent, they're off — absence is how "disabled" is represented; there is no `false` form.
2. **Clear it if present**, via Django admin or Canvas support, and coordinate the timing with enabling this plugin. Anything else means either a gap in coverage or double messages. Note that clearing it also **retires the native `Y` confirm loop**, which is gated on the same setting — this plugin rebuilds that flow, but only once step 4 is done.
3. **Set the required variables**, including `ADMIN_ROLE_NAMES` — without it nobody can open the admin app — then verify it shows Twilio and SendGrid as *Configured*. Missing credentials mean campaigns silently deliver nothing.
4. **For two-way confirm, provision a dedicated Twilio number** whose inbound webhook points at `…/plugin-io/api/appointment_reminders/twilio/inbound`, and set `twilio-inbound-webhook-url` to that exact URL. See *Integration with Canvas core* below — this has real lead time and can't be done at the last minute.

**Strongly recommended for the first run:** set `TESTING_MODE=true` plus `TESTING_MODE_PATIENTS` and `TESTING_MODE_RECIPIENTS`, enable one campaign, and confirm delivery to your own phone or inbox before opening it up. The gate is fail-closed — with `TESTING_MODE` on, a message sends only when **both** the patient and the recipient address are allowlisted. While a campaign is enabled and `TESTING_MODE` is off, the admin app shows a live-sending warning.

## Components

| Handler | Type | Role |
| --- | --- | --- |
| `AppointmentEventHandler` | events | Confirmation / cancellation / no-show on appointment events |
| `ReminderScheduler` | cron `*/5 * * * *` | Reminder + telehealth-join messages for upcoming booked appointments |
| `NotificationAPI` | SimpleAPI | Admin config (role-gated), manual sends, notification history |
| `TwilioInboundAPI` | SimpleAPI | Signature-gated inbound-SMS webhook (`POST /twilio/inbound`) — Y/N confirm/decline, STOP/START consent write-back |
| `TimelineMessageFilter` | config | Hides "Message" notes from the patient timeline |
| `NotifyAdminApp` | Application | "Appointment Reminders" — provider-menu admin: configure campaigns, view global history. Refuses staff without an `ADMIN_ROLE_NAMES` role |
| `NotifyPatientApp` | Application | "Appointment Reminders" — chart panel: this patient's reminder history |

## Key files

| File | Purpose |
| --- | --- |
| `services/config.py` | `CampaignConfig` dataclass + load/save via `CampaignConfigRecord` |
| `services/delivery.py` | Twilio SMS + SendGrid email senders; consent + testing-mode gates; delivery audit |
| `services/templates.py` | Variable extraction + `{{placeholder}}` rendering |
| `services/business_line.py` | Resolve per-line attribution + from-number from config |
| `services/twilio_inbound.py` | Signature verification, form parsing, Y/N intent + STOP/START consent classification |
| `services/consent.py` | Build the `Patient` effect that writes SMS consent back after an opt-out/opt-in |
| `services/authz.py` | `ADMIN_ROLE_NAMES` role gate for the admin endpoints |
| `services/history.py` | `NotificationDelivery` audit rows (outbound sends + inbound responses) |

Custom data lives under the `canvas__appointment_reminders` namespace: `CampaignConfigRecord` (config singleton) and `NotificationDelivery` (activity log; `campaign_type=inbound_response` rows record confirms/declines).

## Configuration options (variables)

Set these with `canvas config set appointment_reminders --host <hostname> KEY=value`. Nothing here belongs in the repo.

Each is declared in `CANVAS_MANIFEST.json` under `variables`, with a `sensitive` flag that decides whether the value can be read back. **Sensitive** values are write-only: masked in the Admin UI and reported by `canvas config list` only as `[set]` / `[not set]`. Non-sensitive values are readable, which is what you want for things you'll need to eyeball — the from-number, the webhook URL, the allowed admin roles. The **Masked** column below records which is which; `canvas config set` never changes the flag, only the manifest does.

Every credential is sensitive. So are the two testing-mode allowlists, since they hold patient identifiers and contact details rather than configuration.

Only five are needed to send anything: `twilio-account-sid`, `twilio-auth-token`, and `twilio-phone-number` for SMS, plus `sendgrid-api-key` and `sendgrid-from-email` for email. Those exact five are what the admin app checks before showing *Configured*.

| Variable | Masked | Required | Purpose | Where to get it |
| --- | --- | --- | --- | --- |
| `namespace_read_write_access_key` | Yes | Auto | Custom Data access for `CampaignConfigRecord` + `NotificationDelivery` | **Do not set.** Canvas provisions it on install. Setting it by hand breaks custom-data reads |
| `twilio-account-sid` | Yes | Yes, for SMS | Identifies the Twilio account; always used in the request URL, even when API-key auth is in play | Twilio Console home page, "Account Info". Starts `AC` |
| `twilio-auth-token` | Yes | Yes, for SMS | Two jobs: fallback outbound auth, **and** the key used to verify the `X-Twilio-Signature` on inbound replies. Inbound confirm/decline cannot work without it | Twilio Console home page, next to the account SID. Treat as a master credential |
| `twilio-api-key-sid` | Yes | No | Preferred outbound auth when paired with the secret below, because it is revocable without rotating the master token | Twilio Console → Account → API keys & tokens → Create API key. Starts `SK` |
| `twilio-api-key-secret` | Yes | No | The other half of the API key. Both must be set or the pair is ignored | Shown **once** at API-key creation. Not retrievable later; make a new key if lost |
| `twilio-phone-number` | No | Yes, for SMS | Default outbound sender. Per-business-line from-numbers in the admin app override it; this is the fallback | Twilio Console → Phone Numbers → Active numbers. E.164 form, so `+15551234567` |
| `twilio-inbound-webhook-url` | No | Only for two-way confirm | The exact URL Twilio POSTs to. The signature is computed over this string, so any mismatch fails closed and replies are rejected | You choose it: `https://<hostname>/plugin-io/api/appointment_reminders/twilio/inbound`. Paste the identical string into the number's "A message comes in" webhook in Twilio |
| `sendgrid-api-key` | Yes | Yes, for email | Authenticates the send | SendGrid → Settings → API Keys → Create. Needs Mail Send permission. Starts `SG.` |
| `sendgrid-from-email` | No | Yes, for email | The From address on every email | Any address you have verified in SendGrid → Settings → Sender Authentication. Unverified senders are rejected at send time |
| `TESTING_MODE` | No | No | `1`/`true`/`yes`/`on` restricts **all** sending to the two allowlists below. Fail-closed: with it on and the lists empty, nothing sends at all | You set it. Strongly recommended for a first run |
| `TESTING_MODE_PATIENTS` | Yes | With `TESTING_MODE` | Comma-separated patient identifiers allowed to receive. Matched against the patient's id, key, or dbid, so whichever value you copy works | Copy the patient id from the chart URL |
| `TESTING_MODE_RECIPIENTS` | Yes | With `TESTING_MODE` | Comma-separated addresses allowed to receive. Phones compared in normalized E.164, emails case-insensitively; one list may mix both | Your own mobile and inbox, e.g. `+15551234567,you@example.com` |
| `LOCK_MESSAGE_TEMPLATES` | No | No | `1`/`true`/`yes`/`on` stops **manual senders** departing from the approved copy. See below. Unset means a manual send can be reworded freely | You set it |
| `ADMIN_ROLE_NAMES` | No | Yes, to use the admin app | Comma-separated staff roles allowed to open the admin console and call its endpoints. Fail-closed: unset locks **everyone** out, including you. See *Who can open the admin app* | Your instance's role names, e.g. `Practice Manager,Administrator`. Either the display name or the internal code matches |

**Outbound Twilio auth** picks the API key when `twilio-api-key-sid` and `twilio-api-key-secret` are both set, and otherwise falls back to `twilio-account-sid` + `twilio-auth-token` (`services/delivery.py:_twilio_auth`). The request URL is built from the account SID either way, which is why that secret is required even under API-key auth.

A send needs **both** allowlists to match when `TESTING_MODE` is on: the patient *and* the destination address. One without the other sends nothing, which is deliberate.

### Who can open the admin app

`ADMIN_ROLE_NAMES` lists the staff roles allowed to configure campaigns, matched case-insensitively against each role's display name *and* its internal code, so either form works. Set it before you go looking for the app — unset denies everyone, by design, since an admin console that opens itself when misconfigured is the worse failure.

The real gate is `NotificationAPI.authenticate`, which refuses every `/admin*` request from a staff member without a listed role. The per-patient chart panel is untouched and stays available to any logged-in staff member.

**The menu item itself stays visible to everyone.** Canvas has no per-user visibility hook for a `provider_menu_item` application: `visible()` is defined only on embedded (note and scheduling) applications, and the `ProviderMenuConfiguration` effect [explicitly does not apply](https://docs.canvasmedical.com/sdk/layout-effect/#provider-menu-configuration) to plugin-provided menu items. A non-admin who clicks **Appointment Reminders** gets a short "you don't have access" page instead of the console. Since the URL is reachable without the menu at all, the server-side check is what protects the configuration; the refusal page is only courtesy.

### Locking message copy

Set `LOCK_MESSAGE_TEMPLATES` to `1` / `true` / `yes` / `on` where wording is compliance-approved and must not drift on its way to a patient.

**It constrains the manual sender, not the admin.** Admins keep editing the approved copy in the admin app exactly as before. What the lock stops is the person sending a one-off message from the bell in a patient's chart from rewording that copy on the way out.

Concretely, with the lock on:

- In the patient panel the previewed SMS and email bodies become read-only.
- `POST /patient/<id>/send` re-renders the message from the stored template and **discards whatever body the client posted**, so the approved copy is what is delivered.
- A campaign with no stored template behind it is refused with **403** rather than delivered as an empty message. (The free-text **Custom** option was removed from the product entirely, so every send is template-backed regardless of the lock.)

The server-side behavior is the actual boundary; the read-only textareas are a convenience on top of it, since anything holding a staff session could POST to the endpoint directly. Unset the variable to lift the lock. It deliberately can't be lifted from inside the app, so the people who control the wording are the ones with plugin-config access.

**Independent of the lock**, a manual send is refused with **422** when the rendered body still contains a `{{placeholder}}` the renderer could not fill, so template syntax never reaches a patient verbatim. Only the channels actually selected are checked, so a typo in an unused template can't block a send.

## Consent (TCPA / opt-out)

Enforced at send time in `services/delivery.py:_get_patient_contacts`:

- **SMS** requires `has_consent=True` **and** `opted_out=False` on the phone contact point.
- **Email** requires only `opted_out=False` (implicit consent).
- A patient with neither is silently skipped, logged `skipped:no_phone_on_file`.

### STOP / START write-back

Twilio maintains its own block list. When a patient texts a standard opt-out keyword — `STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT`, `REVOKE`, `OPTOUT` — Twilio blocks the number, auto-replies, and then [forwards the message to the webhook](https://help.twilio.com/articles/223134027). Nothing in that flow reaches Canvas. `services/consent.py` closes the gap by clearing `has_consent` on the contact point the message came from, so the chart agrees with Twilio and later sends are skipped before they can fail with error 21610. `START` / `UNSTOP` / `YES` restore it, matching Twilio's opt-in keywords.

This matters specifically *because* two-way confirm repoints the number's inbound webhook at this plugin. Canvas's native incoming-SMS handler used to record the opt-out; once the webhook moves, it no longer sees the message.

Two consequences worth knowing:

- **`has_consent`, not `opted_out`.** The `Patient` effect's contact-point payload has no `opted_out` field, so no plugin can set it. That turns out to be the better field anyway: `has_consent` gates SMS alone, while `opted_out` would also suppress email, and STOP is an SMS carrier keyword. A patient who opts out of texts keeps getting email reminders.
- **Twilio's keyword sets overlap this plugin's.** `CANCEL` is both an opt-out keyword and a decline token, so it clears consent *and* opens the follow-up Task. `YES` is both an opt-in keyword and a confirm token, so it restores consent *and* confirms the appointment. Both halves are actioned; `services/twilio_inbound.py` classifies the two axes separately for exactly this reason.

The plugin never opts a patient in on its own — only in response to the patient's own opt-in keyword. Staff can still change consent by hand in the chart.

## Integration with Canvas core — read before enabling

The plugin **replaces** Canvas's native appointment-reminder + confirm flow (it can't read `OrganizationSetting`s, so it does not coordinate with them). The *Pre-install checklist* above is the short version; this section is the detail behind it.

1. **Disable native reminders.** Clear the `appointmentReminders` `OrganizationSetting` before enabling this plugin's `reminder`/`confirmation` campaigns — otherwise patients get **two** reminders (one from home-app, one from `ReminderScheduler`). The native inbound `Y` loop is gated on the same setting (plus `incomingSmsAuth`), so clearing it also retires native confirmation — which is why this plugin implements its own.
2. **Two-way confirm needs a dedicated number.** Inbound SMS routing is a Twilio concern: on a typical instance every number sits in a Canvas **Messaging Service** whose inbound webhook points at Canvas's native messaging. For the plugin's `Y`/`N` flow to receive replies, the confirmation number's inbound webhook must point at `…/plugin-io/api/appointment_reminders/twilio/inbound` (POST). Use a **dedicated number in its own Messaging Service** — sharing the general patient-messaging number would route normal replies to this plugin (which only understands Y/N and drops the rest). `twilio-inbound-webhook-url` must exactly equal that URL (the signature is validated against it).
3. **Match credentials.** Use the same Twilio from-number/creds the org already uses, or messages come from a different sender.

Campaigns ship **disabled** (opt-in). Enable per campaign in the admin app.

## Known gaps

- **No runtime detection of native reminders.** `appointmentReminders` is an `OrganizationSetting` with no `canvas_sdk` model and no replica table, and native sends are logged to `api_appointmentreminder` without writing `Message`/`MessageTransmission` rows. The plugin therefore has no signal — direct or indirect — that native reminders are still active. Avoiding double sends is a deployment-checklist step, not something the code can enforce.
- **The admin menu item cannot be hidden per role**, only made inert — see *Who can open the admin app*. Hiding it would need a Canvas platform change.
- **Contact-point update semantics are undocumented.** Canvas documents `addresses` updates as replace-based and says nothing about `contact_points`, and the payload carries no row ids. `services/consent.py` therefore resends every live contact point on each consent write, which is correct under either reading but should be confirmed against a real chart during UAT: send a STOP from a patient who has an email and a second phone on file, then check both survived.
- **Inbound patient lookup is a sequential scan.** Resolving a reply's sender matches the last 10 digits as a suffix (`telecom__value__endswith`), which compiles to `LIKE '%…'` and so cannot use a standard B-tree index. That is fine for a webhook firing a few times a minute, and cheaper than the 4-digit substring scan plus 50-row hydration it replaced. Making it fast would need a normalized or reversed-string expression index on the column — a platform change, not a plugin one.
- **No send retry queue.** Twilio/SendGrid failures are logged to `NotificationDelivery` + an `AppointmentsMetadata` effect, but not retried.
- **Email uses implicit consent** (opt-out only, no per-email opt-in) and has no built-in unsubscribe (would require SendGrid Subscription Tracking / ASM).
- **No consolidated confirmation-status view** yet — confirms surface as appointment status on the schedule, declines as Tasks, and all replies as `inbound_response` audit rows, but there's no single "needs outreach" roll-up.

## Running tests

```bash
uv run pytest tests/
```

## Deploy

```bash
canvas install appointment_reminders --host <hostname>   # add --disable to install without enabling
canvas config set appointment_reminders --host <hostname> KEY=value
canvas logs --host <hostname>
canvas list --host <hostname>
```
