"""Pytest config: ensure `import appointment_reminders.X` resolves regardless
of where pytest is invoked from.

Layout:
    container/                       <- this is parents[1]; goes on sys.path
        pyproject.toml
        tests/conftest.py            <- this file
        appointment_reminders/      <- inner package, importable as `appointment_reminders`
            __init__.py
            handlers/, services/, ...
"""

from __future__ import annotations

import pathlib
import sys

_PLUGIN_PARENT = pathlib.Path(__file__).resolve().parents[1]
if str(_PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_PARENT))
