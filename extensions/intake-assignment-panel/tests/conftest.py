"""Shared fixtures and import-path setup for intake_assignment_panel tests."""

import sys
from pathlib import Path

parent_dir = Path(__file__).parent.parent
inner_pkg_dir = parent_dir / "intake_assignment_panel"
sys.path.insert(0, str(parent_dir))
sys.path.insert(0, str(inner_pkg_dir))
