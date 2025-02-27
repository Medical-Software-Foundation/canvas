# LogNoteLocksAndUnlocks Handler

## Overview

The `LogNoteLocksAndUnlocks` class is an event handler that logs changes in the state of a note. It listens for `NOTE_STATE_CHANGE_EVENT_CREATED` events and logs messages when a note is locked, unlocked, or transitions to any other state.

## Requirements

This handler requires:

- `canvas_sdk`: For handling Canvas events and effects.
- `logger`: A logging module to capture state transitions.

## Event Handling

The handler is triggered by the `NOTE_STATE_CHANGE_EVENT_CREATED` event. It inspects the `state` and `note_id` from the event context and logs messages accordingly.

### Note States

The following note states are referenced in the code:

- `LKD` (Locked) - Logs when a note is locked.
- `ULK` (Unlocked) - Logs when a note is unlocked.
- Any other state - Logs a general message with the state identifier.

## Code Breakdown

1. **Class Declaration:**
   - Inherits from `BaseHandler`.
   - Specifies `RESPONDS_TO` as `NOTE_STATE_CHANGE_EVENT_CREATED`.

2. **`compute` Method:**
   - Retrieves the new state (`state`) and `note_id` from the event context.
   - Logs specific messages based on the state:
     - `"Note {note_id} was just locked!"` if the state is `LKD`.
     - `"Note {note_id} was just unlocked!"` if the state is `ULK`.
     - `"Note {note_id} just entered state {new_note_state}!"` for any other state.
   - Returns an empty list as no effects are applied.

## Usage

This handler should be integrated within a system that processes Canvas Medical SDK events. When a note state changes, the handler will log the relevant information.

## Example Log Output

```plaintext
INFO: Note 12345 was just locked!
INFO: Note 67890 was just unlocked!
INFO: Note 54321 just entered state RVT!




### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
