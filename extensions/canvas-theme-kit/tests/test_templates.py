"""Guards against template comments that leak onto the rendered page.

Django's `{# ... #}` comment is single-line only. Spread across lines it is
not a comment at all, and the whole thing renders as visible text. The demo
page shipped this way: its layer-by-layer explanation printed across the top of
the page on a live instance, above the content it was describing.

Nothing else catches it. The handler tests mock `render_to_string`, so no
template is ever rendered under test, and `canvas validate` does not look at
templates. Rendering each one here is the only check.

Use `{% comment %} ... {% endcomment %}` for anything longer than a line.
"""

from pathlib import Path

import pytest
from django.template import Context, Engine

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "canvas_theme_kit" / "templates"


def templates() -> list[Path]:
    return sorted(TEMPLATE_ROOT.rglob("*.html"))


def test_there_are_templates_to_check() -> None:
    # A silent empty glob would make every check below vacuously pass.
    assert templates()


@pytest.mark.parametrize("path", templates(), ids=lambda p: p.name)
def test_no_comment_text_renders(path: Path) -> None:
    rendered = Engine().from_string(path.read_text(encoding="utf-8")).render(Context())
    assert "{#" not in rendered and "#}" not in rendered, (
        f"{path.name} renders comment text; use {{% comment %}} for multi-line comments"
    )
