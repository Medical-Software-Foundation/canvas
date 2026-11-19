"""Check the pairing editor's JavaScript: it parses, renders safely, and caps rules.

Run from the repository root:

    uv run python scripts/check_admin_page.py

The editor page (``api/admin_page.py``) is a Python string served by SimpleAPI, so the
test suite only ever sees it as text. This extracts its ``<script>`` and runs it in Node
against a stubbed DOM:

1. ``node --check`` - the script parses.
2. ``render_check.js`` - the rule list renders with balanced markup, inline SVG icons,
   and rule and questionnaire names HTML-escaped.
3. ``cap_check.js`` - "add pairing" stops at ``MAX_RULES`` with the right message.

Exits 0 if everything passes, 1 on failure, and 2 if Node is missing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questionnaire_followup.api.admin_page import build_admin_html  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent


def extract_script(html: str) -> str:
    """Return the page's single inline <script> body."""
    scripts: list[str] = re.findall(r"<script>(.*?)</script>", html, re.S)
    if len(scripts) != 1:
        raise SystemExit(f"expected exactly one <script> in the page, found {len(scripts)}")
    return scripts[0]


def run(node: str, args: list[str], label: str) -> bool:
    """Run one Node check, echo its output, and report whether it passed."""
    done = subprocess.run([node, *args], capture_output=True, text=True)
    output = (done.stdout + done.stderr).strip()
    print(f"--- {label}: {'OK' if done.returncode == 0 else 'FAILED'}")
    if output:
        print(output)
    return done.returncode == 0


def main() -> int:
    """Extract the page's script and run every Node check against it."""
    node = shutil.which("node")
    if node is None:
        print("node not found; skipping the admin page checks")
        return 2

    script = extract_script(build_admin_html())
    with tempfile.TemporaryDirectory() as tmp:
        js = Path(tmp) / "admin_page.js"
        js.write_text(script)
        results = [
            run(node, ["--check", str(js)], "node --check"),
            run(node, [str(SCRIPTS / "render_check.js"), str(js)], "render + escaping"),
            run(node, [str(SCRIPTS / "cap_check.js"), str(js)], "rule cap"),
        ]

    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
