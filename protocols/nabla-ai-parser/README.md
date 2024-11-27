# Nabla Transcript Parser Plugin

## Overview

The Nabla Transcript Parser Plugin is designed to interpret the output of Nabla transcripts. 
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
   canvas install nabla_ai_parser
   ```

---

## Running Tests

Ensure the plugin functions as expected by running the test suite:

```bash
pytest .
```
