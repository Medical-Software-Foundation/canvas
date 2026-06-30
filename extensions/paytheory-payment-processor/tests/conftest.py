import sys
from pathlib import Path

# Add the extension directory to sys.path so that
# `paytheory_payment_processor` is importable as a package during tests.
extension_dir = Path(__file__).resolve().parent.parent
if str(extension_dir) not in sys.path:
    sys.path.insert(0, str(extension_dir))
