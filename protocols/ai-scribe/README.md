# AI Scribe Plugin

## Overview

The AI Scribe Transcript Parser Plugin is designed to interpret the output of AI medical scribes. 
It processes "originate clipboard command" events and parses their content into  commands within a note.

---

## Installation

Follow these steps to install the plugin:

1. Install the package:
   ```bash
   pip install .
   ```

2. Register the plugin with your Canvas instance:
   ```bash
   canvas install ai_scribe
   ```

---

## Running Tests

Ensure the plugin functions as expected by running the test suite:

```bash
pytest .
```
