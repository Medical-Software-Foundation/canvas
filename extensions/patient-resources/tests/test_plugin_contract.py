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


def test_content_type_is_only_sent_with_a_body():
    """A bodyless GET must not advertise a JSON body it does not have.

    The header describes a payload; sending it on a GET invites whatever parses
    request bodies in front of the plugin to read an empty string as JSON. The
    browser-issued asset requests carry no Content-Type and work, which is what
    made this visible.
    """
    for name in ("library.js", "picker.js"):
        source = _js_code(PACKAGE / "static" / "js" / name)
        assert 'headers = { Accept: "application/json" }' in source, name
        assert "if (body !== undefined)" in source, name
        # Never unconditionally in the fetch options.
        assert 'headers: { "Content-Type"' not in source, name


def test_the_patient_page_sends_no_content_type():
    source = _js_code(PACKAGE / "static" / "js" / "portal.js")
    assert "Content-Type" not in source


def test_no_module_reaches_a_function_through_an_imported_submodule():
    """Import the symbol, never the module it lives in.

    `from patient_resources.services import catalog` then `catalog.list_resources()`
    imports cleanly, passes `canvas validate`, and then fails at request time in
    the sandbox: reaching a function as an attribute of a plugin submodule does
    not survive. It cost an afternoon. The two route classes that did this
    returned HTTP 500 on every call while the three that imported symbols
    directly worked, which is what finally isolated it.

    """
    package_submodules = {
        path.stem
        for path in PACKAGE.rglob("*.py")
        if path.stem not in {"__init__", "constants"}
    }

    offenders: list[str] = []
    for path in PY_FILES:
        tree = ast.parse(_module_source(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("patient_resources"):
                continue
            for alias in node.names:
                if alias.name in package_submodules:
                    offenders.append(f"{path.name}: from {node.module} import {alias.name}")
    assert not offenders, offenders


def test_modal_pages_offer_a_way_to_close_themselves():
    """The host modal for this target draws no chrome, so the page must.

    Without this the picker and library open and cannot be dismissed.
    """
    for name in ("library.html", "picker.html"):
        source = (PACKAGE / "templates" / name).read_text()
        assert 'id="pr-close"' in source, name
        assert 'aria-label="Close"' in source, name

    for name in ("library.js", "picker.js"):
        source = _js_code(PACKAGE / "static" / "js" / name)
        # The platform's contract: it hands over a MessagePort on INIT_CHANNEL
        # and listens for CLOSE_MODAL on that port.
        assert "INIT_CHANNEL" in source, name
        assert "CLOSE_MODAL" in source, name
        assert "event.origin !== window.location.origin" in source, name


def test_the_patient_page_has_no_modal_plumbing():
    """It opens as a full page, so a close control would be wrong there."""
    source = _js_code(PACKAGE / "static" / "js" / "portal.js")
    assert "CLOSE_MODAL" not in source
    assert "INIT_CHANNEL" not in source


def test_modal_pages_ask_the_host_for_a_size_that_fits():
    """The host opens the iframe at its own default, which dwarfs a short list.

    RESIZE goes over the same port as CLOSE_MODAL, and the height is measured
    from the rendered content and clamped, so a long library scrolls inside the
    modal instead of asking for a window taller than the screen.
    """
    for name in ("library.js", "picker.js"):
        source = _js_code(PACKAGE / "static" / "js" / name)
        assert "RESIZE" in source, name
        assert "requestResize" in source, name
        assert "scrollHeight" in source, name
        # Clamped in both directions.
        assert "MODAL_MIN_HEIGHT" in source and "MODAL_MAX_HEIGHT" in source, name
        assert "Math.max" in source and "Math.min" in source, name


def test_the_patient_page_does_not_resize_anything():
    source = _js_code(PACKAGE / "static" / "js" / "portal.js")
    assert "RESIZE" not in source


def test_resize_accounts_for_an_open_dialog():
    """A <dialog> is an overlay, so it adds nothing to the page's flow height.

    Measuring only #pr-app left the window sized to the list behind the form,
    which meant scrolling to reach the Save button.
    """
    for name in ("library.js", "picker.js"):
        source = _js_code(PACKAGE / "static" / "js" / name)
        assert 'querySelector("dialog[open]")' in source, name
        assert "offsetHeight" in source, name
        # And it must shrink back afterwards.
        assert 'addEventListener("close", requestResize)' in source, name


# --- the approved designs ---------------------------------------------------


def test_the_library_is_a_table_with_the_designed_columns():
    source = (PACKAGE / "templates" / "library.html").read_text()
    assert "<table" in source
    assert 'id="pr-rows"' in source
    for heading in ("Title", "Type", "Label"):
        assert f">{heading}</th>" in source, heading
    # The actions column is unlabelled in the design but still needs a name for
    # anyone not reading it visually.
    assert "Actions</span>" in source


def test_the_library_uses_the_designed_labels():
    source = (PACKAGE / "templates" / "library.html").read_text()
    assert "Resource library" in source
    assert "+ Add resource" in source
    assert "Search resources" in source


def test_the_picker_shows_a_patient_card_and_the_designed_button():
    source = (PACKAGE / "templates" / "picker.html").read_text()
    assert 'id="pr-patient-name"' in source
    assert 'id="pr-patient-meta"' in source
    assert "Choose resources (searchable)" in source
    assert "Send to patient portal" in source


def test_the_selection_count_is_still_announced():
    """The design drops the visible counter; screen readers keep it."""
    source = (PACKAGE / "templates" / "picker.html").read_text()
    assert 'id="pr-selection"' in source
    assert 'aria-live="polite"' in source
    selection_line = next(
        line for line in source.splitlines() if 'id="pr-selection"' in line
    )
    assert "pr-visually-hidden" in selection_line


def test_table_cells_are_built_without_markup_injection():
    """The new cells are still assembled node by node, never from a string."""
    source = _js_code(PACKAGE / "static" / "js" / "library.js")
    assert "renderRow" in source
    assert "createElement" in source
    assert "innerHTML" not in source
    # The title cell is an anchor, so it must carry the same link hardening as
    # everywhere else.
    assert "noopener noreferrer" in source


def test_the_type_badge_is_a_constant_until_pdfs_land():
    """Every resource is a link today, so the badge is a placeholder.

    Asserted so that a future PDF field replaces it deliberately rather than
    someone reading the constant as a bug and inventing logic for it.
    """
    for name in ("library.js", "picker.js"):
        source = _js_code(PACKAGE / "static" / "js" / name)
        assert 'pr-type-pill", "Link"' in source, name


def test_the_indigo_accent_from_the_design_is_the_only_accent():
    """The palette lives in :root so a rebrand is one block, not a sweep."""
    source = _css_code(PACKAGE / "static" / "css" / "library.css")
    assert "--pr-accent: #2f55d4" in source
    assert "--pr-pill-bg" in source and "--pr-pill-ink" in source
    # The old teal must not survive anywhere in the staff stylesheet.
    assert "#0b7285" not in source


def test_dialog_actions_stay_visible_when_the_form_is_tall():
    """Save and Cancel must never sit below the fold.

    Only the dialog body scrolls; the actions row is pinned. `min-height: 0` is
    what lets the flex child shrink below its content and actually scroll.
    """
    source = _css_code(PACKAGE / "static" / "css" / "library.css")
    assert "dialog[open]" in source
    body = source[source.index(".pr-dialog-body {") :]
    body = body[: body.index("}")]
    assert "overflow-y: auto" in body
    assert "min-height: 0" in body


def test_the_open_dialog_rule_is_scoped_to_the_open_state():
    """A bare `dialog { display: flex }` beats the UA's own hiding rule.

    That would leave every closed dialog rendered on the page -- the same trap as
    styling `display` over the `[hidden]` attribute, which already shipped once.
    """
    source = _css_code(PACKAGE / "static" / "css" / "library.css")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("dialog") and stripped.endswith("{"):
            selector = stripped[:-1].strip()
            if "display" in source.split(stripped, 1)[1].split("}", 1)[0]:
                assert "[open]" in selector, selector


def test_dialog_height_is_measured_from_content_not_the_clamped_box():
    """offsetHeight of a clamped dialog is the clamp, so it can never escape it."""
    for name in ("library.js", "picker.js"):
        source = _js_code(PACKAGE / "static" / "js" / name)
        assert "wantedDialogHeight" in source, name
        assert "scrollHeight" in source, name


def test_text_controls_are_styled_by_element_not_by_container():
    """A control outside `.pr-controls` must not fall back to browser styling.

    The header search lives in the header rather than the filter row, and a
    container-scoped rule left it visibly thinner than everything beside it.
    """
    source = _css_code(PACKAGE / "static" / "css" / "library.css")
    assert 'input[type="search"],' in source
    assert ".pr-controls input[type=\"search\"] {\n  font: inherit" not in source
    # Every text control the templates use has to be covered by that rule.
    block = source[source.index('input[type="search"],') :]
    block = block[: block.index("{")]
    for control in ('input[type="text"]', 'input[type="url"]', "select"):
        assert control in block, control


def test_the_picker_offers_search_only():
    """No label filter in the chart picker.

    A provider looking at one patient's chart wants to find a resource by name,
    not to browse categories -- and the design shows a single full-width search.
    The library keeps its filter, where curating a growing list needs it.
    """
    picker = (PACKAGE / "templates" / "picker.html").read_text()
    assert "pr-label-filter" not in picker
    assert "All labels" not in picker
    assert 'id="pr-search"' in picker

    library = (PACKAGE / "templates" / "library.html").read_text()
    assert "pr-label-filter" in library

    # And the picker must not still be fetching a vocabulary it cannot show.
    source = _js_code(PACKAGE / "static" / "js" / "picker.js")
    assert "labelFilter" not in source
    assert "/library/labels" not in source


def test_the_destructive_control_follows_what_is_actually_possible():
    """Three states, and the row must not offer an action the server refuses.

    Withdraw needs a patient currently holding it. Delete needs no share to have
    ever existed. A resource whose every share was already withdrawn is neither,
    and must get no control at all -- offering Withdraw there revoked nothing and
    re-archived an archived row.
    """
    source = _js_code(PACKAGE / "static" / "js" / "library.js")
    assert "confirmDelete" in source
    assert '"DELETE"' in source

    branch = source[source.index("if (resource.has_live_shares)") :]
    branch = branch[: branch.index("td.appendChild(group)")]
    # Withdraw first, then Delete guarded by there being no withdrawn shares
    # either. The all-withdrawn case falls through both.
    assert branch.index("Withdraw") < branch.index("has_withdrawn_shares")
    assert branch.index("has_withdrawn_shares") < branch.index("Delete")
    assert "else if (!resource.has_withdrawn_shares)" in branch


def test_deleting_is_confirmed_but_not_typed():
    """Withdraw demands a typed word because it changes what patients hold.

    Delete reaches no patient, so the same ceremony would be theatre -- but it is
    still irreversible, so it is still confirmed.
    """
    source = _js_code(PACKAGE / "static" / "js" / "library.js")
    block = source[source.index("function confirmDelete") :]
    block = block[: block.index("function submitConfirm")]
    assert "openConfirm" in block
    assert "requireTyped: false" in block


def test_row_actions_share_a_minimum_width():
    """So the three controls line up as columns down the table.

    The group is right-aligned, so a shorter label on one row -- Delete where
    another has Withdraw -- otherwise narrows the group and shifts that row's
    buttons out of line with the rows above.
    """
    source = _css_code(PACKAGE / "static" / "css" / "library.css")
    block = source[source.index(".pr-row-actions button") :]
    block = block[: block.index("}")]
    assert "min-width" in block


def test_an_inactive_row_says_why_it_is_inactive():
    """Withdraw archives the resource, so "Archived" alone hides the difference
    between a row that was retired and one taken back off patients.
    """
    source = _js_code(PACKAGE / "static" / "js" / "library.js")
    assert '"Withdrawn"' in source
    assert '"Archived"' in source
    assert "resource.has_withdrawn_shares" in source
