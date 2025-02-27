# Log Note Locks And Unlocks Handler

## Overview

The `LogNoteLocksAndUnlocks` class is an event handler that logs changes in the state of a note. It listens for `NOTE_STATE_CHANGE_EVENT_CREATED` events and logs messages when a note is locked, unlocked, or transitions to any other state.

## Event Handling

The handler is triggered by the `NOTE_STATE_CHANGE_EVENT_CREATED` event. It inspects the `state` and `note_id` from the event context and logs messages accordingly.


## Example Log Output

```plaintext
INFO: Note 3b25b581-a35b-4e96-bf20-2019b721c1bb was just locked!
INFO: Note 8d77dbec-c7f2-4376-8dbe-e1699f1d7c90 was just unlocked!
INFO: Note d9b787da-9386-49fc-8004-91ff707ba6d7 just entered state RVT!
INFO: Note e175e4bc-7c88-4594-aa6e-0b49a7e95f4c just entered state SCH!
```

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
