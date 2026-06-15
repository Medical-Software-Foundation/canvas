import sys
from pathlib import Path

# Ensure the plugin package is importable from the repo root during tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
