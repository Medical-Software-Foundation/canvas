# Delete Staged Commands Button

## What it does

Adds a **Delete All Staged Commands** button to the note header. One click removes every staged (uncommitted) command in the current note. Committed commands are never touched. The button supports 38+ command types - diagnoses, prescriptions, orders, assessments, history, vitals, and more.

## Problem it solves

Clearing a note of staged commands one at a time is tedious, especially when a clinician wants to start fresh or has left several drafts behind. This removes them all at once, while leaving anything already committed safely in place.

## Who it's for

Clinicians and documentation staff who build notes with staged commands and want a fast way to discard the uncommitted ones without deleting them individually.

## How to install

1. Download or clone this plugin directory.
2. From the directory that contains the plugin, install it against your instance:
   ```
   canvas install delete_staged_commands_button
   ```
3. Confirm it is enabled under **Settings > Plugins** in your instance.

See the [Canvas plugin documentation](https://docs.canvasmedical.com/sdk/plugins-overview/) for CLI setup and authentication.

## Configuration options

None. The button is always visible in the note header once installed and acts only on commands in the `staged` state for the current note. There are no secrets or settings.

## Screenshots or screen recordings

_Screenshots pending. The "Delete All Staged Commands" button appears in the note header; clicking it removes all staged commands from the open note._

---

For full technical detail (supported command types, architecture, tests, and how to extend the plugin), see the [package README](./delete_staged_commands_button/README.md).
