# Portal Disable Cancel Appointments

## What it does

Hides the **Cancel** option on appointment cards in the patient portal. The plugin responds to the portal's "can this appointment be canceled?" check and always answers no, so patients cannot cancel their own appointments from the portal.

## Problem it solves

By default the patient portal lets patients cancel upcoming appointments themselves. Some practices need cancellations to go through staff instead - to manage cancellation policies, late-cancel fees, rescheduling, or schedule density. This removes the self-service cancel path without disabling the rest of the portal.

## Who it's for

Practices that want appointment cancellations handled by staff rather than self-served by patients, while keeping the patient portal otherwise fully available.

## How to install

1. Download or clone this plugin directory.
2. From the directory that contains the plugin, install it against your instance:
   ```
   canvas install portal_disable_cancel_appts
   ```
3. Confirm it is enabled under **Settings > Plugins** in your instance.

See the [Canvas plugin documentation](https://docs.canvasmedical.com/sdk/plugins-overview/) for CLI setup and authentication.

## Configuration options

None. The plugin disables patient-initiated cancellation for all portal appointments once installed. There are no secrets or settings.

## Screenshots or screen recordings

_Screenshots pending. With the plugin installed, the Cancel action no longer appears on appointment cards in the patient portal._
