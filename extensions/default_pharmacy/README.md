# Default Pharmacy

## What it does

Keeps a patient's default preferred pharmacy in sync with prescribing. The plugin listens to the `Prescribe`, `Refill`, and `Adjust Prescription` commands. When one of those commands is committed, the pharmacy selected in the command is saved as the patient's default preferred pharmacy on their profile.

How it works:

1. When a patient has a [default preferred pharmacy set](https://docs.canvasmedical.com/), it pre-populates in the prescribing workflows.
2. If a provider changes the pharmacy on a `Prescribe`, `Refill`, or `Adjust Prescription` command, that new pharmacy is automatically saved as the patient's default preferred pharmacy.
3. The next time anyone prescribes for the patient, the updated pharmacy pre-populates.

## Problem it solves

Without this plugin, changing a patient's pharmacy at the point of prescribing does not update their profile, so the next prescription defaults back to the old pharmacy. Staff have to remember to edit the profile separately. This removes that extra step by capturing the change directly from the command the provider already used.

## Who it's for

Any practice that prescribes through Canvas and wants the patient's preferred pharmacy to stay current automatically, without a separate profile edit. Useful for high-volume prescribing teams where pharmacy changes are common.

## How to install

1. Download or clone this plugin directory.
2. From the directory that contains the plugin, install it against your instance:
   ```
   canvas install default_pharmacy
   ```
3. Confirm it is enabled under **Settings > Plugins** in your instance.

See the [Canvas plugin documentation](https://docs.canvasmedical.com/sdk/plugins-overview/) for CLI setup and authentication.

## Configuration options

No plugin settings. The behavior is automatic once installed.

Requirements:

- The `prescribe`, `refill`, and `adjustPrescription` command switches must be enabled on the instance for the plugin to fire.

## Screenshots or screen recordings

_Screenshots pending. The default preferred pharmacy on the patient profile updates after a Prescribe, Refill, or Adjust Prescription command is committed with a different pharmacy._
