"""PLUGIN-462: the block edit form's date chips and what saving them changes.

The two pure helpers are pulled out of admin.js and run in Node, so these
tests check the shipped code, not a copy of it. Skipped when Node is missing.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ADMIN_JS = (
    Path(__file__).parent.parent
    / "provider_availability"
    / "static"
    / "js"
    / "admin.js"
)
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _function_source(name: str) -> str:
    src = ADMIN_JS.read_text()
    match = re.search(
        r"^function " + re.escape(name) + r"\(.*?^}\n", src, re.DOTALL | re.MULTILINE
    )
    assert match, f"{name} not found in admin.js"
    return match.group(0)


def _run(name: str, *args):
    script = (
        _function_source(name)
        + f"\nprocess.stdout.write(JSON.stringify({name}(...{json.dumps(list(args))})));\n"
    )
    out = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(out.stdout)


def _block(bid, pid, date, group="g1"):
    return {
        "id": bid,
        "provider_id": pid,
        "group_id": group,
        "start": date + "T08:00:00",
    }


OVERVIEW = [
    {
        "provider_id": "A",
        "blocks": [_block("a7", "A", "2026-12-07"), _block("a9", "A", "2026-12-09")],
    },
    {
        "provider_id": "B",
        "blocks": [
            _block("b7", "B", "2026-12-07"),
            _block("b9", "B", "2026-12-09"),
            _block("b10", "B", "2026-12-10"),
            _block("bx", "B", "2026-12-11", group="other"),
        ],
    },
]


def test_chips_show_only_the_edited_providers_dates():
    assert _run("_ownGroupChipDates", OVERVIEW, "A", "g1", "2026-12-07") == [
        "2026-12-09"
    ]


def test_a_date_removed_for_one_provider_does_not_come_back_from_another():
    """The browser-test bug: after A's Dec 9 was deleted, B's Dec 9 refilled A's chips."""
    after_removal = [
        {"provider_id": "A", "blocks": [_block("a7", "A", "2026-12-07")]},
        OVERVIEW[1],
    ]
    chips = _run("_ownGroupChipDates", after_removal, "A", "g1", "2026-12-07")
    assert chips == []
    members = after_removal[0]["blocks"]
    plan = _run(
        "_planOwnGroupDateChanges", members, "a7", "2026-12-07", ["2026-12-07"] + chips
    )
    assert plan == {"toDelete": [], "toAdd": []}


def test_plan_deletes_removed_dates_and_adds_new_ones_for_this_provider_only():
    members = OVERVIEW[0]["blocks"]
    plan = _run(
        "_planOwnGroupDateChanges",
        members,
        "a7",
        "2026-12-07",
        ["2026-12-07", "2026-12-10"],
    )
    assert plan == {"toDelete": ["a9"], "toAdd": ["2026-12-10"]}


def test_plan_never_deletes_the_edited_block_when_its_date_moves():
    members = OVERVIEW[0]["blocks"]
    plan = _run(
        "_planOwnGroupDateChanges",
        members,
        "a7",
        "2026-12-08",
        ["2026-12-08", "2026-12-09"],
    )
    assert plan == {"toDelete": [], "toAdd": []}
