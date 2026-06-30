"""Put the plugin container on sys.path so tests can import the inner package."""

import os
import sys

_CONTAINER = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _CONTAINER not in sys.path:
    sys.path.insert(0, _CONTAINER)
