role-based-homepage
===================

## What it does

When a staff member logs in to Canvas, this plugin sends them straight to the page that matters
most for their job — providers to the schedule, billers to revenue, panel managers to the patient
list, and so on. You decide which role goes where with a single piece of configuration; no code
changes are needed to adjust the routing.

## Problem it solves

Out of the box, every user lands on the same default homepage after login, so most people start
each day by clicking away to the screen they actually use. Teams that want role-appropriate
landing pages otherwise have to build and maintain a separate plugin per role or per customer.
This plugin replaces all of that with one configurable, reusable rule set.

## Who it's for

Any Canvas practice that wants different staff to start on different screens. It works for every
staff role — clinical and administrative alike:

- **Providers / clinical support** (Physician, NP, PA, Nurse, Therapist, Social Worker, Medical
  Assistant) → typically the schedule
- **Front desk / office management** (Clerk, Office Manager) → schedule
- **Panel / cohort managers** (Care Coordinator) → patient list
- **Billing & finance** (Biller) → revenue
- **Developers / integration admins** → data integration

Routing is fully configurable, so the mapping above is just a sensible starting point.

## How it works

On the `GET_HOMEPAGE_CONFIGURATION` event the plugin:

1. Resolves the acting user (`event.actor`) to a `Staff` record.
2. Looks up each of the staff member's roles by `StaffRole.internal_code` in the
   `ROLE_HOMEPAGE_MAP` secret.
3. If several roles match, the one with the **highest `domain_privilege_level`** wins
   (so a provider-nurse routes as a provider).
4. Returns a `DefaultHomepageEffect` for the matched destination.

If nothing matches and a `"*"` catch-all is configured, that default is used. Otherwise the
plugin returns no override and Canvas falls back to its normal default (`/schedule`).

## How to install

```bash
canvas install role-based-homepage
```

Then set the `ROLE_HOMEPAGE_MAP` secret on the plugin's configuration page
(`<emr_base_url>/admin/plugin_io/plugin/<plugin_id>/change/`).

## Configuration options

The plugin has a single secret, **`ROLE_HOMEPAGE_MAP`** — a JSON object mapping a role
`internal_code` to a destination. An optional `"*"` key is the catch-all for unmapped/custom
roles.

```json
{
  "MD": "SCHEDULE",
  "DO": "SCHEDULE",
  "NP": "SCHEDULE",
  "PA": "SCHEDULE",
  "RN": "SCHEDULE",
  "LMFT": "SCHEDULE",
  "LCSW": "SCHEDULE",
  "MA": "SCHEDULE",
  "CL": "SCHEDULE",
  "OM": "SCHEDULE",
  "CC": "PATIENTS",
  "BL": "REVENUE",
  "CD": "DATA_INTEGRATION",
  "AD": "DATA_INTEGRATION",
  "*": "PATIENTS"
}
```

### Destinations

A destination is **either** a built-in page name **or** a plugin application identifier
(auto-detected — application identifiers contain a `:` so they never collide with page names):

| Built-in page | Lands on |
|---|---|
| `PATIENTS` | `/patients` |
| `SCHEDULE` | `/schedule` |
| `REVENUE` | `/revenue` |
| `CAMPAIGNS` | `/campaigns` |
| `DATA_INTEGRATION` | `/data-integration` |

To route a role to a custom application instead of a built-in page, use that application's
identifier as the destination, e.g. `"MD": "my_dashboard.applications.overview:OverviewApp"`.

### Built-in role internal codes (reference)

`MD`/`DO` Physician · `NP` Nurse Practitioner · `PA` Physician Assistant · `RN` Nurse ·
`LMFT` Psychotherapist · `LCSW` Social Worker · `MA` Medical Assistant · `CC` Care Coordinator ·
`OM` Office Manager · `BL` Biller · `CL` Clerk · `EP` EPCS Administrator · `CD`/`AD` Developer.
Custom roles defined per instance have their own codes.

Keys are matched against `internal_code` case- and whitespace-insensitively.

## Screenshots

<!--
TODO before publishing: add at least one screenshot showing the plugin in action — e.g. a Biller
landing on the Revenue page (or a provider on the Schedule) immediately after login. Place image
files alongside this README and reference them here.
-->

_Screenshots coming soon._

## Notes

- This affects only the provider application homepage. A homepage redirect is not a security
  boundary — Canvas authorization still governs access to every page and application.
- The plugin reads `Staff` / `StaffRole` data only; it performs no writes and no external calls.

## License

MIT — see [LICENSE](../LICENSE).
