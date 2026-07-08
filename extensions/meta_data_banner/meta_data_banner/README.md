# Meta Data Banner

Display an informational banner at the top of a patient's chart that shows values pulled from their [Patient Metadata](https://docs.canvasmedical.com/sdk/data-patient/#patientmetadata). The banner text is fully customizable through a template you define in the plugin settings.

## Quick Start

### Step 1: Install the plugin

Deploy the plugin to your Canvas instance using the Canvas CLI:

```bash
canvas install meta_data_banner --host <your-instance>
```

### Step 2: Set up Patient Metadata

Make sure the patients you want to display banners for have metadata entries. Patient Metadata is a key-value store on each patient record. You can manage it through the Canvas admin or via the FHIR API.

For example, a patient might have:

| Key | Value |
|-----|-------|
| `ccm_diagnosis` | `Diabetes, Type 2` |
| `enrollment_status` | `Active` |

### Step 3: Configure the banner template

In the Canvas admin, navigate to the plugin settings for **meta_data_banner** and set the `BANNER_TEMPLATE` secret.

Write your banner text and use `{metadata_key}` wherever you want a patient's metadata value to appear:

```
Care Program: {ccm_diagnosis}
```

### Step 4: Verify

Open a patient chart. If the patient has a `ccm_diagnosis` metadata value, you will see a blue info banner at the top of their chart:

> Care Program: Diabetes, Type 2

## Template Examples

**Single value:**

```
Care Program: {ccm_diagnosis}
```

**Multiple values separated by a pipe:**

```
{program_name} | Status: {enrollment_status}
```
> CCM | Status: Active

**Descriptive label with a value:**

```
Risk Level: {risk_score} - Care Manager: {assigned_cm}
```
> Risk Level: High - Care Manager: Jane Smith

## How It Works

The plugin checks each patient's metadata against the `{variables}` in your template. Here is what determines whether a banner appears:

- **Banner shows** when the patient has a metadata entry for every `{variable}` in the template, and none of those values are blank.
- **Banner does not show** when any referenced metadata key is missing or has an empty value.
- **Banner is removed** automatically if a patient previously qualified but no longer does (e.g., a metadata value was cleared).

The banner updates in two ways:

1. **When patient metadata changes** — whenever a patient's metadata is created or updated, the plugin re-evaluates that patient's banner immediately. This is the primary mechanism: as metadata is written, banners stay current on their own.
2. **Backfill (cron task)** — a scheduled task covers the two cases the event path can't: seeding banners for existing patients right after install, and re-rendering everyone if `BANNER_TEMPLATE` ever changes (a bare secret edit does not fire a plugin-update event, so a cron is the only reliable trigger). It sweeps the active-patient panel once in bounded pages (500 patients every 5 minutes; e.g. a ~30k-patient panel is fully reconciled in roughly 5 hours), then goes **dormant** — subsequent runs are a single cache check that returns immediately without scanning patients. It only wakes again if the template changes. This avoids both an all-patient scan on plugin lifecycle events and round-the-clock background churn. Schedule and page size are configurable in `meta_data_banner_backfill.py` (`SCHEDULE`, `PAGE_SIZE`).

## Notes

- The banner text is capped at 90 characters. Longer text is truncated with `...`.
- Only one banner per patient is created by this plugin (keyed as `patient-metadata`).
- The banner appears on the patient chart with an informational (blue) style.
