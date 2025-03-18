# Any Scribe AI Plugin

## Overview

The Any Scribe Extension enables organizations to streamline operational efficiency in using an AI scribe alongside Canvas. The extension interprets output created by an AI scribes into Canvas commands within a note. In the process of creating Canvas commands, the extension also parses the content of the AI scribe output into the associated commands. Commands created by the Any Scribe retain all of the same properties of user created commands. To trigger the Any Scribe Extension when installed in a Canvas instance, a user can simply paste the output into a new line in a note.

The Any Scribe Extension utilizies the `CLIPBOARD_COMMAND__POST_INSERTED_INTO_NOTE` event.

Any Scribe Extension commands:
- Assess Condition
- History of Present Illness (HPI)
- Past Medical History
- Plan
- Reason for Visit (RFV)
- Vitals

This extension can be extended to support additional commands from the Canvas SDK Commands Module

---

## Installation

   ```bash
   canvas install ai_scribe
   ```


