import sys
from pathlib import Path

# Make the plugin package importable when pytest runs from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
