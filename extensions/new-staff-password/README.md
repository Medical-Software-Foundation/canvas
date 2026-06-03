# new-staff-password

Automatically sends a Canvas password-reset (account-activation) email when a staff member is
**activated** - either created with `active=True` or reactivated from inactive.

## What it does

Listens for the `STAFF_ACTIVATED` event and invokes the Canvas FHIR operation
`POST /Practitioner/{id}/$send-reset-password-email` for the activated practitioner. Canvas then
emails that staff member the link to set their password and access their account. No manual step.

## Problem it solves

When a new staff member is added (or an existing one reactivated), someone normally has to remember
to trigger the password-activation email by hand. Miss it, and the staff member can't log in. This
plugin removes that manual step: the activation email goes out the moment the staff record becomes
active, every time, with no one having to remember.

## Who it's for

Practices that onboard or reactivate staff regularly and want account activation to be hands-off -
admins and operations teams responsible for staff setup.

## How it works

1. Listens for the `STAFF_ACTIVATED` event (covers new active staff and reactivations).
2. Fetches an OAuth client-credentials token from the EMR instance.
3. Calls `POST /Practitioner/{id}/$send-reset-password-email` for the matching practitioner.

The plugin emits no effects - the reset email is the side effect. Failures (missing config, token
error, non-2xx responses) are written to the plugin logs; the handler always returns no effects.
The instance host is derived at runtime from `CUSTOMER_IDENTIFIER`, so no URL is configured.

## How to install

```bash
canvas install new-staff-password --host <your-instance>
```

Then set the two configuration variables (below).

## Configuration

Set these on the plugin configuration page or via `canvas config set`. Both are declared
`sensitive` in `CANVAS_MANIFEST.json`, so their values are hidden in the Admin UI and CLI:

| Variable | Purpose |
|---|---|
| `CANVAS_FHIR_CLIENT_ID` | OAuth client id for a Confidential, client-credentials application. |
| `CANVAS_FHIR_CLIENT_SECRET` | OAuth client secret. |

The OAuth application must carry the scope `system/Practitioner.send-reset-password-email`.

## Requirements

- Canvas instance on 1.305.0+ (for the `variables` / `sensitive` manifest schema).

## Screenshots

This plugin has no UI. Its output is the standard Canvas password-activation email delivered to the
staff member - the same "Update Password / Canvas Account" email Canvas sends from the
`$send-reset-password-email` operation.

<img width="556" height="320" alt="reset-password" src="https://github.com/user-attachments/assets/eb6ee3b7-c94c-40ba-9419-ccc3af53c701" />



## Running tests

```bash
uv run pytest tests/
```
