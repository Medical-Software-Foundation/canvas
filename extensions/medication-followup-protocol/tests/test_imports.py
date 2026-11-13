"""Every module the manifest names must import, or the plugin fails on the instance.

The module list is read out of CANVAS_MANIFEST.json rather than written down here. It used
to be a hardcoded copy, and on 2026-08-28 two handlers were added to the manifest while that
copy stayed as it was, so the suite ran green while the manifest named two modules that did
not exist on disk. That is exactly the failure this file exists to catch, and it would have
surfaced as a failed canvas install instead.

The modules the manifest has no reason to name are listed separately below, because a
service or a model is never declared as a component and still has to import.
"""

import importlib
import json
from pathlib import Path

import pytest

#: The project root, the directory holding the package and this tests directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _manifest_path() -> Path:
    """The one CANVAS_MANIFEST.json under the project, found rather than spelled out.

    Dot prefixed directories are skipped, both because canvas install ignores them when it
    packages and because the virtual environment underneath one carries manifests belonging
    to other plugins entirely.
    """
    found = [
        path
        for path in PROJECT_ROOT.rglob("CANVAS_MANIFEST.json")
        if not any(part.startswith(".") for part in path.relative_to(PROJECT_ROOT).parts)
    ]
    assert len(found) == 1, f"expected exactly one manifest, found {len(found)}"
    return found[0]


def _declarations() -> list[tuple[str, str]]:
    """Every module and class pair the manifest points a component at.

    A class is declared as module.path:ClassName, so the module is everything before the
    colon. Applications and handlers are the two component kinds that name a class.
    """
    manifest = json.loads(_manifest_path().read_text())
    components = manifest.get("components", {})
    pairs = []
    for kind in ("applications", "handlers"):
        for component in components.get(kind, []):
            module_name, _, class_name = component.get("class", "").partition(":")
            if module_name and class_name:
                pairs.append((module_name, class_name))
    return sorted(set(pairs))


DECLARATIONS = _declarations()

#: What the manifest names, read fresh so this cannot drift from it.
MANIFEST_MODULES = sorted({module for module, _class_name in DECLARATIONS})

#: What the manifest has no reason to name and which still has to import.
SUPPORTING_MODULES = [
    "medication_followup_protocol.models",
    "medication_followup_protocol.services.banner",
    "medication_followup_protocol.services.conditions",
    "medication_followup_protocol.services.eligibility",
    "medication_followup_protocol.services.practice_time",
    "medication_followup_protocol.services.program_pane",
    "medication_followup_protocol.services.recheck",
]


@pytest.mark.parametrize("module", MANIFEST_MODULES)
def test_every_module_the_manifest_names_imports(module: str) -> None:
    """A module the manifest points at that does not import fails the install."""
    importlib.import_module(module)


@pytest.mark.parametrize("module", SUPPORTING_MODULES)
def test_every_supporting_module_imports(module: str) -> None:
    """The models and services, which the manifest never names and every handler needs."""
    importlib.import_module(module)


def test_the_manifest_names_something() -> None:
    """A manifest declaring nothing would make the parametrised test above vacuous.

    Without this, a manifest emptied by accident leaves that check passing with no cases at
    all, which reads identically to every module importing cleanly.
    """
    assert MANIFEST_MODULES, "the manifest declares no component classes"


@pytest.mark.parametrize("module_name,class_name", DECLARATIONS)
def test_every_declared_class_exists(module_name: str, class_name: str) -> None:
    """The class half of each declaration resolves, not only the module half.

    Importing the module proves the first half only. A renamed or deleted class leaves the
    module importing cleanly and the plugin failing on the instance the moment the platform
    looks the class up.
    """
    module = importlib.import_module(module_name)

    assert hasattr(module, class_name), f"{module_name} declares no {class_name}"
