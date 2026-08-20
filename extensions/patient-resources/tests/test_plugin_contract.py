"""Static checks on the plugin as a shippable artifact.

Everything here guards a failure mode that the rest of the suite cannot see,
because pytest runs under plain CPython while the plugin runs inside
RestrictedPython with a Django DDL pipeline that emits no constraints.

``canvas validate`` covers most of that ground now -- it sandbox-loads every
declared handler and lints for ``setattr``, augmented attribute assignment,
custom-model placement and more. These tests cover the few things it does not,
and they run in CI where the CLI may not.
"""

import ast
import json
import re
import struct
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "patient_resources"
MANIFEST = json.loads((PACKAGE / "CANVAS_MANIFEST.json").read_text())

PY_FILES = sorted(PACKAGE.rglob("*.py"))
JS_FILES = sorted((PACKAGE / "static" / "js").rglob("*.js"))


def _module_source(path: Path) -> str:
    return path.read_text()


def _css_code(path: Path) -> str:
    """CSS with comments removed.

    The stylesheets document the rule they are restating, so a substring search
    over the raw text finds the prose first.
    """
    return re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.DOTALL)


def _js_code(path: Path) -> str:
    """JavaScript with comments removed.

    These files document the rules they follow ("never innerHTML"), so a plain
    substring search over the raw text matches the prose rather than the code and
    the check fails for the wrong reason. Strings are left intact, which is fine:
    none of the banned tokens appear inside a string literal here.
    """
    source = path.read_text()
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


# --- naming -----------------------------------------------------------------


def test_manifest_name_matches_the_package_directory():
    """The plugin runner derives a plugin's name from the installed folder name.

    For SimpleAPI requests it then keeps only handlers whose plugin name matches
    the name in the URL, and returns 404 when that leaves none. A mismatch here
    means every route 404s on the instance while the manifest still validates --
    the most likely cause of the order-sets plugin's unfixable 404s.
    """
    assert MANIFEST["name"] == PACKAGE.name


def test_every_declared_class_is_rooted_at_the_package():
    for group in ("protocols", "applications", "handlers"):
        for entry in MANIFEST["components"].get(group, []):
            assert entry["class"].split(".")[0] == PACKAGE.name, entry["class"]


def test_every_declared_class_resolves_to_a_file_and_a_class():
    for group in ("protocols", "applications", "handlers"):
        for entry in MANIFEST["components"].get(group, []):
            module_path, class_name = entry["class"].split(":")
            path = PACKAGE.parent / (module_path.replace(".", "/") + ".py")
            assert path.exists(), entry["class"]
            tree = ast.parse(path.read_text())
            defined = {
                node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            }
            assert class_name in defined, entry["class"]


def test_no_class_is_declared_under_two_manifest_keys():
    """Two declarations register the handler twice.

    The runner then sees more than one handler able to respond and returns HTTP
    500 for every request -- not a routing preference, an outage.
    """
    seen: list[str] = []
    for group in ("protocols", "applications", "handlers"):
        for entry in MANIFEST["components"].get(group, []):
            seen.append(entry["class"])
    assert len(seen) == len(set(seen))


# --- sandbox traps ----------------------------------------------------------


def test_no_module_mixes_future_annotations_with_a_dataclass():
    """The trap that makes a plugin pass its tests and then fail to load.

    ``from __future__ import annotations`` stringifies every annotation, and
    ``@dataclass`` resolves those strings through ``sys.modules[cls.__module__]``.
    The sandbox execs each module into a synthetic scope that is not registered
    there, so the lookup returns None and the class body raises at import time.
    """
    for path in PY_FILES:
        tree = ast.parse(_module_source(path))

        has_future_annotations = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in ast.walk(tree)
        )
        if not has_future_annotations:
            continue

        decorated = [
            decorator
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for decorator in node.decorator_list
        ]
        names = {
            decorator.id
            if isinstance(decorator, ast.Name)
            else decorator.func.id
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
            else ""
            for decorator in decorated
        }
        assert "dataclass" not in names, path


ALLOWED_URLLIB_PARSE_NAMES = {"quote", "unquote", "urlencode"}


def test_urllib_parse_imports_stay_inside_the_sandbox_allowlist():
    """``urlparse`` is not importable in the sandbox, only quote/unquote/urlencode.

    This is not hypothetical: the first version of services/validation.py used
    ``urlparse``, passed all 250 tests, and failed to load three of eight
    handlers under ``canvas validate``.
    """
    for path in PY_FILES:
        tree = ast.parse(_module_source(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "urllib.parse":
                names = {alias.name for alias in node.names}
                assert names <= ALLOWED_URLLIB_PARSE_NAMES, f"{path}: {names}"


def test_no_setattr_or_delattr_in_the_plugin():
    """RestrictedPython blocks both on any ordinary object.

    ``setattr(order_set, field, value)`` inside a PUT handler is what broke every
    order-set edit on the instance while its whole suite passed.
    """
    for path in PY_FILES:
        tree = ast.parse(_module_source(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"setattr", "delattr"}, f"{path}:{node.lineno}"


def test_no_augmented_assignment_to_an_attribute_or_subscript():
    """A RestrictedPython *compile-time* error, so the whole module fails to load."""
    for path in PY_FILES:
        tree = ast.parse(_module_source(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AugAssign):
                assert not isinstance(
                    node.target, (ast.Attribute, ast.Subscript)
                ), f"{path}:{node.lineno}"


def test_no_field_declares_unique_true():
    """The metaclass raises: the DDL cannot retroactively add UNIQUE to a column.

    Uniqueness belongs in ``Meta.constraints`` as a ``UniqueConstraint``.
    """
    for path in sorted((PACKAGE / "models").glob("*.py")):
        assert "unique=True" not in _module_source(path), path


def test_models_live_in_the_models_package():
    """The DDL discovery step only globs ``<plugin>/models/*.py``.

    A CustomModel anywhere else gets no table, silently.
    """
    for path in PY_FILES:
        if path.parent.name == "models":
            continue
        assert "CustomModel" not in _module_source(path), path


# --- front end --------------------------------------------------------------


def test_no_javascript_uses_innerhtml():
    """Titles and labels are staff-entered text rendered to patients."""
    for path in JS_FILES:
        assert "innerHTML" not in _js_code(path), path


def test_no_javascript_uses_a_native_confirm_or_alert():
    """These pages sit inside a host modal, where a native dialog is unreliable."""
    for path in JS_FILES:
        source = _js_code(path)
        for banned in ("window.confirm", "window.alert", "confirm(", "alert("):
            assert banned not in source, f"{path}: {banned}"


def test_every_outbound_link_is_opened_safely():
    """noopener stops tabnabbing; noreferrer withholds the portal URL."""
    for path in JS_FILES:
        source = _js_code(path)
        if '"target"' not in source:
            continue
        assert "noopener noreferrer" in source, path


def test_every_fetch_sends_the_session_cookie():
    for path in JS_FILES:
        source = _js_code(path)
        assert source.count(".fetch(") == source.count('credentials: "same-origin"'), path


# --- assets -----------------------------------------------------------------


def test_declared_icons_exist_and_are_48_square():
    """The review gate requires a 48x48 icon per declared Application."""
    for entry in MANIFEST["components"]["applications"]:
        path = PACKAGE / entry["icon"]
        assert path.exists(), path
        header = path.read_bytes()[16:24]
        assert struct.unpack(">II", header) == (48, 48), path


def test_every_served_asset_exists_on_disk():
    """render_to_string resolves against the plugin directory at request time."""
    referenced = set()
    for path in sorted((PACKAGE / "routes").glob("*.py")):
        referenced.update(re.findall(r'render_to_string\(\s*"([^"]+)"', path.read_text()))
    assert referenced
    for name in referenced:
        assert (PACKAGE / name).exists(), name


@pytest.mark.parametrize("name", ["library", "picker", "portal"])
def test_each_page_carries_a_cache_bust_token_on_its_assets(name):
    """Bumping CACHE_BUST is how a changed asset reaches a browser."""
    source = (PACKAGE / "templates" / f"{name}.html").read_text()
    for match in re.findall(r'(?:href|src)="\{\{ asset_base \}\}[^"]*"', source):
        assert "v={{ cache_bust }}" in match, match


def test_cache_bust_matches_the_manifest_plugin_version():
    from patient_resources import CACHE_BUST

    assert CACHE_BUST == MANIFEST["plugin_version"]


# --- hygiene ----------------------------------------------------------------


def test_no_debug_leftovers():
    for path in PY_FILES:
        source = _module_source(path)
        for banned in ("print(", "# TODO", "[DEBUG]"):
            assert banned not in source, f"{path}: {banned}"
    for path in JS_FILES:
        source = _js_code(path)
        for banned in ("console.log", "debugger", "TODO"):
            assert banned not in source, f"{path}: {banned}"


def test_no_raw_http_client_is_imported():
    """This plugin makes no outbound calls; links are opened by the browser."""
    for path in PY_FILES:
        source = _module_source(path)
        for banned in ("import requests", "import httpx"):
            assert banned not in source, path


def test_every_declared_variable_is_read_somewhere():
    """A declared-but-unread variable is configuration that silently does nothing."""
    sources = "\n".join(_module_source(path) for path in PY_FILES)
    for variable in MANIFEST["variables"]:
        name = variable["name"]
        if name == "namespace_read_write_access_key":
            # Supplied to the platform, not read by plugin code.
            continue
        assert name in sources, name


# --- the hidden attribute ---------------------------------------------------

CSS_FILES = sorted((PACKAGE / "static" / "css").rglob("*.css"))
TEMPLATES = sorted((PACKAGE / "templates").rglob("*.html"))


def test_every_stylesheet_guards_the_hidden_attribute():
    """An author `display` rule beats the browser's own `[hidden]` rule.

    The templates hide the Add button, the read-only notice and the archived
    toggle with the `hidden` attribute, then reveal them from JavaScript. But
    `.pr-toggle { display: flex }` is an author declaration and `[hidden] {
    display: none }` comes from the user-agent stylesheet, so the author rule
    wins and the element is visible no matter what the attribute says.

    That is not hypothetical: it shipped, and the archived-resources toggle
    appeared for a user who had not been granted curation rights.
    """
    for path in CSS_FILES:
        source = _css_code(path)
        assert "[hidden]" in source, path
        guard = source[source.index("[hidden]") :]
        guard = guard[: guard.index("}") + 1]
        assert "display" in guard and "none" in guard, path
        # Needed because the conflicting rules are both author-level, so
        # specificity alone does not settle it.
        assert "!important" in guard, path


def test_elements_hidden_in_a_template_are_covered_by_that_guard():
    """Any element the templates hide has to be in a page that loads the guard."""
    for path in TEMPLATES:
        source = path.read_text()
        if " hidden>" not in source and " hidden " not in source:
            continue
        stylesheets = re.findall(r'href="\{\{ asset_base \}\}/([^"?]+)', source)
        assert stylesheets, path
        for name in stylesheets:
            matches = [css for css in CSS_FILES if css.name == name]
            assert matches, f"{path} references {name}, which is not on disk"
            assert "[hidden]" in _css_code(matches[0]), matches[0]


def test_staff_pages_report_the_http_status_on_failure():
    """A failure the reader can act on, rather than a bare "that did not work".

    The first version said only that, which made a plugin-runner restart
    indistinguishable from a permissions problem: the page showed one red line
    and no clue whether to retry, ask for access, or report a bug.
    """
    for name in ("library.js", "picker.js"):
        source = _js_code(PACKAGE / "static" / "js" / name)
        assert "describeFailure" in source, name
        assert "response.status" in source, name
        assert "HTTP " in source, name


def test_the_patient_page_does_not_show_http_statuses():
    """Patients get a plain sentence; a status code is noise to them."""
    source = _js_code(PACKAGE / "static" / "js" / "portal.js")
    assert "HTTP " not in source
    assert "response.status" not in source
