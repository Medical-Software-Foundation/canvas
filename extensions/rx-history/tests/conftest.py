import os
import sys


def pytest_configure():
    plugin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
