role-based-homepage
===================

## Description

Redirects each staff member to a **role-specific default homepage** when they log in to the
Canvas provider application. It is a generic, configuration-driven generalization of the
`custom_homepage` pattern: instead of sending everyone to one fixed page, it picks a destination
based on the staff member's role.

On the `GET_HOMEPAGE_CONFIGURATION` event the plugin:

1. Resolves the acting user (`event.actor`) to a `Staff` record.
2. Looks up each of the staff member's roles by `StaffRole.internal_code` in the
   `ROLE_HOMEPAGE_MAP` secret.
3. If several roles match, the one with the **highest `domain_privilege_level`** wins
   (so a provider-nurse routes as a provider).
4. Returns a `DefaultHomepageEffect` for the matched destination.

If nothing matches and a `"*"` catch-all is configured, that default is used. Otherwise the
plugin returns no override and Canvas falls back to its normal default (`/schedule`).

## Configuration

Set the **`ROLE_HOMEPAGE_MAP`** secret to a JSON object mapping a role `internal_code` to a
destination. An optional `"*"` key is the catch-all for unmapped/custom roles.

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

Application identifier example: `panel_dashboard.applications.panel_management:PanelManagementApp`.

### Built-in role internal codes (reference)

`MD`/`DO` Physician · `NP` Nurse Practitioner · `PA` Physician Assistant · `RN` Nurse ·
`LMFT` Psychotherapist · `LCSW` Social Worker · `MA` Medical Assistant · `CC` Care Coordinator ·
`OM` Office Manager · `BL` Biller · `CL` Clerk · `EP` EPCS Administrator · `CD`/`AD` Developer.
Custom roles defined per instance have their own codes.

Keys are matched against `internal_code` case- and whitespace-insensitively.

## Installation

```bash
canvas install role-based-homepage
```

Then set the `ROLE_HOMEPAGE_MAP` secret on the plugin's configuration page
(`<emr_base_url>/admin/plugin_io/plugin/<plugin_id>/change/`).

## Notes

- This affects only the provider application homepage. A homepage redirect is not a security
  boundary — Canvas authorization still governs access to every page and application.
- The plugin reads `Staff` / `StaffRole` data only; it performs no writes and no external calls.
