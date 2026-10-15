"""Static files are served through render_to_string, so template syntax in them would be rewritten.

admin.js, settings.js, admin.css and theme.css must come out of the template
engine exactly as written. A "{{" or "{%" in one of them would be swallowed
or raise, and the page would load a broken script or stylesheet.
"""

from pathlib import Path

import pytest
from django.template.engine import Engine

STATIC = Path(__file__).parent.parent / "provider_availability" / "static"
SERVED = ["js/admin.js", "js/settings.js", "css/admin.css", "css/theme.css"]


@pytest.mark.parametrize("rel", SERVED)
def test_served_file_survives_the_template_engine(rel):
    source = (STATIC / rel).read_text()
    rendered = Engine(dirs=[str(STATIC)]).from_string(source).render(__import__("django.template", fromlist=["Context"]).Context({}))
    assert rendered == source, f"{rel} contains template syntax"


def test_page_loads_the_theme_and_settings_script():
    page = (STATIC.parent / "templates" / "admin_page.html").read_text()
    assert "/theme.css?v={{ cache_bust }}" in page
    assert "/settings.js?v={{ cache_bust }}" in page
