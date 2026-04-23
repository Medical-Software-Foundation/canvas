"""Put the plugin's parent dir on sys.path so tests can import `vitals_visualizer`.

Unlike the other companion plugins this plugin doesn't use the nested
`<name>/<name>/` layout — the inner package is directly under
`extensions/visualizations/`, so we add the grandparent of `tests/` to
`sys.path`.
"""
import os
import sys

_PARENT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
