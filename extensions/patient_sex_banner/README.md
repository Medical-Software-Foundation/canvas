# Patient Sex Banner

## What it does

Adds a banner alert to a patient's chart whenever their **sex at birth** is recorded as something other than **Female** or **Male** (for example *Other*, *Unknown*, or unset). The banner reads:

> WARNING: Patient sex is `{value}`. EPCS Rx requires a sex of F or M for successful transmission.

It appears in three places — the chart **timeline**, the **chart**, and the patient **profile**. As soon as the patient's sex at birth is corrected to Female or Male, the banner is removed automatically.

The protocol runs whenever a patient is **created** or **updated**. On plugin **install or update** it also sweeps every existing patient, so charts are back-filled in one pass.

## Problem it solves

Electronic Prescribing of Controlled Substances (EPCS) requires the patient's sex to transmit as **F** or **M**. When a chart carries any other value, the controlled-substance prescription fails at transmission — often discovered only at the pharmacy. This surfaces the mismatch directly on the chart so staff can correct the record *before* prescribing, instead of chasing a failed transmission afterward.

## Who it's for

Practices that electronically prescribe controlled substances and may register patients whose sex at birth is recorded as something other than Male or Female.

## How to install

1. Download or clone this plugin directory.
2. From the directory that contains the plugin, install it against your instance:
   ```
   canvas install patient_sex_banner
   ```
3. Confirm it is enabled under **Settings > Plugins** in your instance.

See the [Canvas plugin documentation](https://docs.canvasmedical.com/sdk/plugins-overview/) for CLI setup and authentication.

## Configuration options

None. The plugin has no secrets or settings. The banner text, its placements (timeline, chart, profile), and the alert intent are fixed in code.

## Screenshots or screen recordings

_Screenshot pending. The banner appears on the patient chart when the patient's sex at birth is not Female or Male._
