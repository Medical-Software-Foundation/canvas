"""AST scan that blocks setattr and direct attribute writes on CustomModel locals.

Canvas plugins run under RestrictedPython. CustomModel instances do not carry
the `__guarded_setattr__` helper, so `setattr(obj, name, value)` and
`obj.field = value` raise AttributeError at runtime. Use
`MyModel.objects.filter(...).update(**fields)` instead, then re fetch.

This test walks every Python file under services/ and protocols/ and fails
if it finds either pattern against a local name that matches a known model
hint. Extend BLOCKED_MODEL_HINTS when a new idiomatic local name appears.
"""

import ast
import pathlib

import pytest


BLOCKED_MODEL_HINTS = {
    "ClinicalFavorite",
    "HiddenDefault",
    "CustomStaff",
    "favorite",
    "row",
    "hidden",
}
PLUGIN_ROOT = pathlib.Path(__file__).parent.parent / "clinical_favorites"
SCANNED_DIRS = ["services", "protocols"]


def _iter_source_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for subdir in SCANNED_DIRS:
        files.extend(sorted((PLUGIN_ROOT / subdir).rglob("*.py")))
    return files


@pytest.mark.parametrize("path", _iter_source_files(), ids=lambda p: p.name)
def test_no_setattr_on_model_instances(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text())
    offenders: list[str] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in BLOCKED_MODEL_HINTS
        ):
            offenders.append(
                f"setattr({node.args[0].id}, ...) at line {node.lineno}"
            )

        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in BLOCKED_MODEL_HINTS
                ):
                    offenders.append(
                        f"{target.value.id}.{target.attr} = ... at line {target.lineno}"
                    )

    assert not offenders, (
        f"{path.name} mutates CustomModel attributes directly, sandbox will reject. "
        f"Use MyModel.objects.filter(...).update(**fields) then re fetch. "
        f"Offenders, {offenders}"
    )
