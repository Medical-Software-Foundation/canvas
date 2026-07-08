# Metadata Banner

**Surface the patient context your team cares about — right at the top of every chart, with zero clicks.**

Canvas stores all kinds of useful, program-specific information as [Patient Metadata](https://docs.canvasmedical.com/sdk/data-patient/#patientmetadata): a care-management diagnosis, an enrollment status, a risk tier, an assigned care manager, a payer program. It's there, but it's tucked away — a clinician has to know it exists and go looking for it.

This plugin brings it to the surface. You write one template, and every patient who has the right metadata gets a clean, informational banner at the top of their chart:

> **Care Program: CCM — Risk: High — Care Manager: Jane Smith**

No custom development, no per-patient work. Define the template once as a plugin secret and the banner appears everywhere the data exists, stays in sync as metadata changes, and disappears when it no longer applies.

## Why you'd use it

- **Make the invisible visible.** Metadata that normally lives in an API or admin screen becomes glanceable clinical context at the point of care.
- **Configure, don't code.** The banner is driven entirely by a text template you control from plugin settings. Change what it says without redeploying.
- **Always accurate.** Banners update the moment a patient's metadata changes, and clear automatically when the data goes away — so what's on the chart is never stale.
- **Safe at scale.** Works the same whether you have 50 patients or 50,000 (see [How it works](#how-it-works)).

## How the template works

The banner text comes from a single secret, `BANNER_TEMPLATE`. Write whatever you want, and use `{metadata_key}` wherever you want a patient's metadata value dropped in.

| `BANNER_TEMPLATE` | A patient with… | Banner shown |
|---|---|---|
| `Care Program: {ccm_diagnosis}` | `ccm_diagnosis = "Diabetes, Type 2"` | `Care Program: Diabetes, Type 2` |
| `{program_name} \| Status: {enrollment_status}` | `program_name = "CCM"`, `enrollment_status = "Active"` | `CCM \| Status: Active` |
| `Risk: {risk_score} — CM: {assigned_cm}` | `risk_score = "High"`, `assigned_cm = "Jane Smith"` | `Risk: High — CM: Jane Smith` |

The rule is all-or-nothing per template: a banner appears only when the patient has a **non-blank value for every `{key}`** in the template. This prevents half-filled banners like `Risk: High — CM:` — if any referenced value is missing, no banner is shown at all.

## Setup

**1. Install the plugin**

```bash
canvas install meta_data_banner --host <your-instance>
```

**2. Make sure your patients have metadata**

Patient Metadata is a key–value store on each patient. Populate it however you already do — via the [FHIR API](https://docs.canvasmedical.com/api/), a data sync, or the Canvas admin. For example:

| Key | Value |
|-----|-------|
| `ccm_diagnosis` | `Diabetes, Type 2` |
| `enrollment_status` | `Active` |

**3. Set the `BANNER_TEMPLATE` secret**

In the Canvas admin, open the settings for **meta_data_banner** and set `BANNER_TEMPLATE` to your desired text (e.g. `Care Program: {ccm_diagnosis}`).

**4. Open a patient chart**

Any patient with a `ccm_diagnosis` value now shows a blue informational banner beneath their name.

## How it works

The plugin keeps banners correct through two complementary mechanisms:

1. **Real-time, per patient.** When a patient's metadata is created or updated, the plugin immediately re-evaluates just that patient and adds, updates, or removes their banner. This is the primary path and handles ongoing changes automatically.

2. **Backfill, for everyone else.** A scheduled task covers the two things the real-time path can't: getting banners onto **existing** patients right after you install the plugin, and **re-rendering everyone** when you change `BANNER_TEMPLATE` later (editing a secret doesn't emit a plugin-update event, so a scheduled task is the only reliable trigger).

   Crucially, the backfill never scans the whole patient panel at once. It walks the active patients in **bounded pages** (500 at a time, every 5 minutes) using a cursor, then goes **dormant** — once the panel is fully reconciled, each subsequent run is a single cache check that returns instantly without touching the database. It only wakes back up when the template changes. As a rough guide, a 30,000-patient panel is fully backfilled in about 5 hours of unattended background work, with no impact on installs or day-to-day use. Both the cadence and page size are configurable at the top of `protocols/meta_data_banner_backfill.py` (`SCHEDULE`, `PAGE_SIZE`).

## Configuration reference

| Secret | Required | Description |
|--------|----------|-------------|
| `BANNER_TEMPLATE` | Yes | The banner text. Use `{metadata_key}` placeholders to insert Patient Metadata values. If unset, no banners are created. |

## Good to know

- **One banner per patient.** This plugin manages a single banner keyed `patient-metadata`; it won't collide with banners from other plugins.
- **90-character cap.** Banner text longer than 90 characters is truncated with `…`, matching the chart banner limit.
- **Informational styling.** Banners render in the neutral blue "info" style and are not clickable links.
