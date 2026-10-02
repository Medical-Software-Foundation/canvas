"""Guards the model mirror against silent drift.

The SDK requires every plugin sharing custom tables to declare identical model
definitions. Nothing enforces that at install time: a field that drifts here
does not raise, it just reads the wrong shape. Given the parent plugin owns the
tables and this one only reads them, a mismatch would surface as tokens that
are quietly empty or wrong on a live page — the hardest kind of bug to trace.

So compare the two definitions structurally, and fail loudly when they diverge.
"""

import ast
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
MIRROR = HERE / "canvas_theme_kit_demo" / "models" / "__init__.py"
SOURCE = HERE.parent / "canvas-theme-kit" / "canvas_theme_kit" / "models" / "__init__.py"


def model_shape(path: Path) -> dict[str, list[str]]:
    """Map each CustomModel class to a normalized list of its field definitions.

    Compares the source text of each assignment rather than evaluating it, so a
    changed default, field type or constraint all count as drift. Docstrings and
    comments are ignored, since those are free to differ.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    shape: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, (ast.AnnAssign, ast.Assign)):
                fields.append(ast.unparse(stmt))
            elif isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                for meta_stmt in stmt.body:
                    if isinstance(meta_stmt, (ast.AnnAssign, ast.Assign)):
                        fields.append(f"Meta.{ast.unparse(meta_stmt)}")
        shape[node.name] = fields

    return shape


@pytest.mark.skipif(
    not SOURCE.exists(),
    reason="canvas-theme-kit is not checked out alongside this plugin",
)
def test_mirror_matches_the_source_of_truth() -> None:
    mirror = model_shape(MIRROR)
    source = model_shape(SOURCE)

    assert set(mirror) == set(source), (
        "Mirrored models do not cover the same classes.\n"
        f"  here:   {sorted(mirror)}\n"
        f"  parent: {sorted(source)}"
    )

    for name in sorted(source):
        assert mirror[name] == source[name], (
            f"Model {name!r} has drifted from canvas_theme_kit.\n"
            f"  here:   {mirror[name]}\n"
            f"  parent: {source[name]}\n\n"
            "Plugins sharing custom tables must declare identical models. A "
            "mismatch does not raise at install time — it silently reads the "
            "wrong shape on a live page."
        )


@pytest.mark.skipif(not SOURCE.exists(), reason="parent plugin not checked out")
def test_mirror_declares_the_fields_the_reader_depends_on() -> None:
    """The specific fields `tokens.py` queries, named so a rename fails here."""
    shape = model_shape(MIRROR)

    assert any("slug" in f for f in shape["Theme"])
    for field in ("tokens", "is_active", "revision", "theme"):
        assert any(field in f for f in shape["ThemeRevision"]), field
