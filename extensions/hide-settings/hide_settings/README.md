hide-settings
=============

## What it does

Hides the **Settings** item in the Canvas main menu (the hamburger menu at the top left) from staff
whose roles an administrator has not allowed. Administrators pick the allowed roles on a simple
**Settings Access** page. Staff holding any allowed role keep Settings. Everyone else stops seeing it
the next time they refresh.

## Problem it solves

Settings opens Canvas's administration area. Every staff member sees the link by default, so
pharmacists, nurses, front desk staff, and outside partners land in screens meant for
administrators and developers. Practices otherwise have to explain to each new hire that Settings
isn't for them, or strip permissions those staff need for their daily work. This plugin removes the
link for the roles that don't need it and leaves their other permissions untouched.

## Who it's for

- **Practice administrators and IT leads** who decide who sees Settings
- **Practices with network or partner staff** (outside pharmacists, contracted clinicians, care
  partners) who use Canvas for a narrow workflow
- **Clinical and front desk staff**, who get a shorter menu without a link they never use

## Good to know

- **It hides the menu link. It does not block the page.** Someone who types the Settings address
  into the browser can still open it, and what they see there is still governed by their Canvas
  permissions. Treat this plugin as a way to keep staff out of the wrong screens, not as a security
  control. Restrict access with Canvas permissions.
- **Nothing changes until a role is checked.** With no roles saved, everyone keeps Settings.
- **Roles, not people.** A staff member with any allowed role keeps Settings. Staff with no roles
  at all lose it once any role is allowed.
- **The role list shows roles your staff actually hold.** A role nobody holds yet won't appear
  until someone is assigned it.
- **Google Calendar menu item.** When this plugin hides Settings for someone, it also hides the
  Google Calendar menu item for that person on instances where Google Calendar is turned on, because
  the SDK's list of menu items doesn't include it yet.
- **One menu plugin at a time.** Canvas uses the menu from whichever plugin answers last, without
  combining them. Don't install this alongside another plugin that changes the main menu (for
  example, a schedule plugin that hides the native Schedule item).

## How it works

- On `GET_PROVIDER_MENU_CONFIGURATION`, the plugin reads the saved list of allowed role codes.
- If the list is empty, it returns nothing and the menu is unchanged.
- Otherwise it looks up the logged-in staff member's roles (`StaffRole.internal_code`). If none of
  them are allowed, it returns a `ProviderMenuConfiguration` with every menu item except Settings.
- The **Settings Access** app (global scope) opens a page served by a SimpleAPI route. Only staff
  listed in `ADMIN_STAFF_IDS` can open or save it. If that variable is empty, nobody can.
- The allowed list is stored in the plugin's own custom data table.

## How to install

```bash
canvas install hide_settings
```

Then:

1. Open the plugin's configuration page in Canvas (`/admin/plugin_io/plugin/`, then
   **hide_settings**) and set `ADMIN_STAFF_IDS` to the staff ids of the people who manage this
   setting, separated by commas.
2. As one of those people, open **Settings Access** from the app menu.
3. Check the roles that should keep Settings, then select **Save**.
4. Ask affected staff to refresh Canvas.

Check that no other installed plugin changes the main menu (see "One menu plugin at a time" above).

## Configuration options

| Variable | Required | Description |
| --- | --- | --- |
| `ADMIN_STAFF_IDS` | Yes | Comma-separated staff ids allowed to open **Settings Access**. Dashed or undashed ids both work. If it's empty, nobody can open the page. |
| `namespace_read_write_access_key` | Set automatically | Access key for the plugin's custom data table. Canvas generates it on first install. Keep a copy, and set it again if you reinstall the plugin. |

Which roles keep Settings is chosen on the **Settings Access** page, not in a variable.

## Screenshots

<!-- TODO before merge: add a screenshot of the Settings Access page and of the menu without Settings. -->
