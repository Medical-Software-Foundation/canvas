# Appointment Rooming Status Banner

## What it does

When an appointment is updated to **Arrived** or **Roomed**, the plugin adds a banner alert to the patient's chart timeline:

- Arrived -> "`{First name}` has arrived."
- Roomed -> "`{First name}` has been roomed."

If the appointment moves to any other status, the matching banner is removed. A nightly cron task runs at midnight (`0 0 * * *`, instance time) and clears any rooming-status banners still open, so every chart starts the next day clean.

## Problem it solves

Front-desk and clinical staff need an at-a-glance signal of where a patient is in the visit - checked in versus already in a room - without opening the schedule or messaging back and forth. This surfaces that status directly on the chart and removes it automatically, so stale banners do not pile up.

## Who it's for

In-person clinics that want a visible arrival and rooming indicator on the patient chart: front desk, medical assistants, and providers coordinating live visits.

## How to install

1. Download or clone this plugin directory.
2. From the directory that contains the plugin, install it against your instance:
   ```
   canvas install appointment_rooming_status_banner
   ```
3. Confirm it is enabled under **Settings > Plugins** in your instance.

See the [Canvas plugin documentation](https://docs.canvasmedical.com/sdk/plugins-overview/) for CLI setup and authentication.

## Configuration options

None. The plugin has no secrets or settings. The banner placement (chart timeline), banner intent (info), and the nightly cleanup schedule (`00:00`) are fixed in code.

## Screenshots or screen recordings

_Screenshots pending. The banner appears at the top of the patient chart timeline when an appointment is marked Arrived or Roomed._
