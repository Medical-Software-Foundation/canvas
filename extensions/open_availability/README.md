# Open Availability

## What it does

Automatically creates a Clinic calendar and a daily recurring "Available" event for each eligible staff member as soon as they are activated in Canvas. When a staff member is deactivated, the plugin ends the recurring event so historical availability is preserved. An admin app is included for on-demand provisioning of existing staff.

## Problem it solves

Out of the box, Canvas does not give providers any open availability when they are activated. A scheduler has to manually open each provider's calendar, set business hours, and create a recurring availability block - repeated for every new hire. This plugin alllows for default open hours every day of the week which is most beneficial if your scheduling is handled outside of Canvas

## Who it's for

Practices that want providers to be schedulable the moment they are activated, with a single org-wide availability window. Most useful for:

- Outpatient clinics with consistent daily business hours
- Specialty groups onboarding new providers regularly
- Any practice that has experienced "the provider was activated but their calendar was empty" gaps

If you need per-provider availability windows or location-aware timezones, this plugin will not be a fit - it uses a single org-wide configuration.

## How to install

1. Clone or download this plugin directory
2. From the plugin directory, run:
   ```
   canvas --host=<your-canvas-host> plugin install ./open_availability
   ```
3. After install, configure the secrets in the Canvas admin UI (`Admin > Plugin I/O > Plugins > open_availability`). See Configuration options below.
4. To provision availability for staff who were already active before installation, open the **Provision Availability** app from the app drawer and click **Run Provisioning**.

## Configuration options

All configuration is via plugin secrets, set in the Canvas admin UI after install.

### AVAILABILITY_START_TIME

Start of the daily availability window. 24-hour `HH:MM` format (e.g. `08:00`, `13:00`).

**Default:** `08:00`

### AVAILABILITY_END_TIME

End of the daily availability window. 24-hour `HH:MM` format. If the end time is before the start time, the window wraps to the next day.

**Default:** `20:00`

### AVAILABILITY_TIMEZONE

IANA timezone name for interpreting start and end times. Any valid IANA timezone is accepted (e.g. `America/New_York`, `America/Chicago`, `America/Phoenix`, `Pacific/Honolulu`, `UTC`). Daylight saving time is applied based on the date the event is created. Invalid values fall back to the default and the error is logged.

**Default:** `America/New_York`

### SCHEDULABLE_ROLES

Comma-separated list of role abbreviations that should receive automatic availability calendars. Only staff whose `top_role_abbreviation` matches one of these values will be processed.

**Default:** `MD,DO,NP,PA`

**Example:** `MD,DO,NP,PA,RN`

**Important:** Any roles listed here must also be added to the organization setting `SCHEDULABLE_STAFF_ROLES` for those staff to appear on the scheduling UI. The plugin creates the calendar and event; Canvas controls visibility.

### ADMIN_USERS

Comma-separated list of staff names authorized to use the **Provision Availability** admin app. Names are matched case-insensitively against the staff member's first and last name.

**Example:** `Jane Smith, John Doe`

If empty or unset, **all users are denied access** (fail-closed).

### simpleapi-api-key

Secret key for the SimpleAPI endpoint that powers the admin app. Generate a random string and store it here. If empty, the API rejects all requests.

## Admin application: Provision Availability

The plugin includes a **Provision Availability** application accessible from the Canvas app drawer.

**Two buttons:**

- **Run Provisioning** - creates calendars and availability events for active schedulable staff who do not already have an active event. Safe to run repeatedly.
- **Force Provision** - ends existing "Available" events and creates new ones for all active schedulable staff. Use this after changing `AVAILABILITY_TIMEZONE`, `AVAILABILITY_START_TIME`, or `AVAILABILITY_END_TIME` to apply the new window to already-provisioned providers.

The status banner shows counts of created, skipped, ended (force mode), and errored staff. If any staff failed, their names are listed.

## How it works

1. **On staff activation:** Checks the staff member's role against `SCHEDULABLE_ROLES`. If eligible, creates a Clinic calendar (or reuses an existing one) and a daily recurring "Available" event for 25 years using the configured window.
2. **On staff deactivation:** Finds all active "Available" events on the plugin's calendar for that staff member and ends each one as of the deactivation timestamp. Historical availability is preserved.
3. **Manual provisioning:** Use the admin app for staff that were active before the plugin was installed, after role changes, or to apply a new availability window across the organization.

## Screenshots

<img width="2704" height="1302" alt="screenshot-primary05252026014692@2x" src="https://github.com/user-attachments/assets/2ba312bd-9a6a-47d8-be02-dcb2814283d3" />


## Edge cases

- Reactivated staff get a fresh 25-year availability window
- Deactivation with no plugin-created calendar logs a warning and exits cleanly
- Leap-year recurrence end dates (Feb 29 + 25 years) fall back to Feb 28
- Per-staff errors during force provisioning do not block the rest of the batch
