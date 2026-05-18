"""
Pytest configuration for practitioner-bulk-loader tests.

Sets Django settings environment variable required by the canvas SDK.
"""
import os

import django
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "canvas_sdk.tests.settings")


def pytest_configure(config):
    """Configure Django settings for tests."""
    if not settings.configured:
        settings.configure(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            INSTALLED_APPS=[
                "django.contrib.contenttypes",
                "django.contrib.auth",
            ],
        )
