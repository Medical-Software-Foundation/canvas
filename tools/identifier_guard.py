#!/usr/bin/env python3
"""Stop a customer identifier from reaching a public repository.

The test suite has a guard too (``tests/test_manifest.py``), but a test only
fails when somebody runs it. This runs from git hooks, so it fails *before* the
object exists -- which is the difference that matters, because a commit cannot
be un-made by a later commit.

Three modes, one per hook:

    --staged            what is about to be committed (pre-commit)
    --message FILE      the commit message itself (commit-msg)
    --range A..B        everything a push would publish (pre-push)

The denylist is never stored in this repository. It is read from
``$CANVAS_FORBIDDEN_IDENTIFIERS``, or ``~/.canvas/forbidden-identifiers.txt``.
A missing list is a hard failure here, unlike in the test suite: on a machine
that commits to this repo the list is supposed to exist, and silently skipping
is how the original disclosure happened. Set
``CANVAS_IDENTIFIER_GUARD_OPTIONAL=1`` to downgrade that to a warning.

Nothing this script prints ever includes a matched token. It reports where the
match was, never what it was -- a hook that echoes the identifier into a
terminal, a CI log or a transcript has leaked it by a different route.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

LIST_VARIABLE = "CANVAS_FORBIDDEN_IDENTIFIERS"
DEFAULT_LIST = Path.home() / ".canvas" / "forbidden-identifiers.txt"
OPTIONAL_VARIABLE = "CANVAS_IDENTIFIER_GUARD_OPTIONAL"

BINARY_SUFFIXES = {
    ".png", ".pyc", ".gz", ".tar", ".zip", ".ico", ".woff", ".woff2",
    ".jpg", ".jpeg", ".pdf", ".whl", ".so", ".dylib",
}
SKIP_DIRS = {
    ".venv", "venv", ".git", "__pycache__", "node_modules", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".tox",
}


def git(*args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *args], capture_output=True, check=False
    )
    if result.returncode != 0 and not binary:
        return ""
    return result.stdout if binary else result.stdout.decode("utf-8", "replace")


def load_tokens() -> list[str]:
    override = os.environ.get(LIST_VARIABLE)
    path = Path(override) if override else DEFAULT_LIST
    if not path.is_file():
        message = (
            f"identifier guard: no denylist at {path}. "
            f"Set {LIST_VARIABLE} or create the file "
            f"(one lowercase token per line)."
        )
        if os.environ.get(OPTIONAL_VARIABLE) == "1":
            print(f"warning: {message}", file=sys.stderr)
            return []
        print(f"error: {message}", file=sys.stderr)
        print(
            f"       set {OPTIONAL_VARIABLE}=1 to allow committing without it.",
            file=sys.stderr,
        )
        sys.exit(2)
    tokens = []
    for line in path.read_text(errors="ignore").splitlines():
        token = line.split("#", 1)[0].strip().lower()
        if token:
            tokens.append(token)
    if not tokens:
        print(f"error: identifier guard: {path} has no tokens.", file=sys.stderr)
        sys.exit(2)
    return tokens


def scannable(name: str) -> bool:
    path = Path(name)
    if path.suffix.lower() in BINARY_SUFFIXES:
        return False
    return not SKIP_DIRS & set(path.parts)


@lru_cache(maxsize=None)
def pattern_for(tokens: tuple[str, ...]) -> re.Pattern[str]:
    """One regex for the whole denylist, each token anchored to word edges.

    Substring matching was the wrong rule. A customer whose name is also an
    ordinary word -- and several are -- made this flag any file that happened to
    use that word, and a token also matched inside longer unrelated words. The
    edges are alphanumeric-only on purpose: ``-`` and ``_`` stay *inside* a
    match, so a real reference like ``<slug>-prod`` or ``<slug>_portal`` is
    still caught.

    Longest first, so an overlapping short token cannot shadow a longer one.
    """
    ordered = sorted(tokens, key=len, reverse=True)
    body = "|".join(re.escape(token) for token in ordered)
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])")


def normalised(line: str) -> str:
    return " ".join(line.lower().split())


def line_digest(line: str) -> str:
    return hashlib.sha256(normalised(line).encode("utf-8")).hexdigest()[:16]


# Lines that match the denylist but disclose nothing: a customer name that is
# also a common clinical word, used as that word. Without these the whole-tree
# scan below fails on files that have been public on ``main`` for ages, and a
# guard that fails on every run gets bypassed with ``--no-verify``.
#
# Digests, not tokens, and of the *whole line* rather than the token: every line
# recorded here is already published verbatim in this public repository, so its
# hash adds no disclosure -- which is not true of a hashed token. Editing such a
# line changes its digest and re-flags it, so a real identifier cannot be
# smuggled in under an old exemption.
_COMPANION = (
    "extensions/provider_clinical_summary_companion"
    "/provider_clinical_summary_companion"
)

KNOWN_BENIGN_LINES: dict[str, frozenset[str]] = {
    # An icon inventory: the word names a waveform, not the customer.
    f"{_COMPANION}/README.md": frozenset({"3e947b6552404441"}),
    f"{_COMPANION}/assets/clinical-summary-icon.svg": frozenset(
        {"f5221095f00cf383"}
    ),
}


def hits(text: str, tokens: list[str], path: str | None = None) -> int:
    """Count lines carrying a denylisted token, ignoring known-benign ones."""
    if not tokens:
        return 0
    pattern = pattern_for(tuple(tokens))
    allowed = KNOWN_BENIGN_LINES.get(path or "", frozenset())
    return sum(
        1
        for line in text.splitlines()
        if pattern.search(line.lower()) and line_digest(line) not in allowed
    )


def check_staged(tokens: list[str]) -> list[str]:
    listed = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    offenders = []
    for name in str(listed).split("\0"):
        if not name or not scannable(name):
            continue
        blob = git("show", f":{name}", binary=True)
        try:
            text = bytes(blob).decode("utf-8")
        except (UnicodeDecodeError, TypeError):
            continue
        if hits(text, tokens, name):
            offenders.append(name)
    return offenders


def check_message(path: Path, tokens: list[str]) -> list[str]:
    if not path.is_file():
        return []
    # Ignore the commented scissors section git appends; it is not committed.
    body = "\n".join(
        line for line in path.read_text(errors="ignore").splitlines()
        if not line.startswith("#")
    )
    return ["<commit message>"] if hits(body, tokens) else []


def check_range(rev_range: str, tokens: list[str]) -> list[str]:
    offenders: list[str] = []
    commits = str(git("rev-list", rev_range)).split()

    for sha in commits:
        message = str(git("log", "-1", "--format=%B", sha))
        if hits(message, tokens):
            offenders.append(f"{sha[:8]} <commit message>")

    # Every version of every file the range introduces, read at the commit that
    # introduced it -- plus the whole tree at the tip.
    #
    # Reading candidates at the tip instead was a hole of exactly the kind this
    # script exists to close: a file added and then deleted before the tip no
    # longer exists there, so `show tip:name` returned nothing and the push went
    # out with the content sitting in its history. Deleting a file does not
    # unpublish it, which is the whole reason this runs before the push rather
    # than after the commit.
    seen: set[str] = set()

    def scan(rev: str, name: str, label: str) -> None:
        name = name.strip()
        if not name or not scannable(name):
            return
        # Dedupe on content, not on path: the same blob at twenty commits is one
        # scan, while two different versions of one path are two.
        blob_id = str(git("rev-parse", f"{rev}:{name}")).strip()
        if not blob_id or blob_id in seen:
            return
        seen.add(blob_id)
        try:
            text = bytes(git("show", blob_id, binary=True)).decode("utf-8")
        except (UnicodeDecodeError, TypeError):
            return
        if hits(text, tokens, name):
            offenders.append(label)

    tip = rev_range.split("..")[-1] or "HEAD"
    for name in str(git("ls-tree", "-r", "--name-only", tip)).split("\n"):
        scan(tip, name, name.strip())

    for sha in commits:
        changed = str(
            git("diff-tree", "-r", "--no-commit-id", "--name-only", sha)
        ).split("\n")
        for name in changed:
            # Named with the commit, because a path that is clean at the tip but
            # dirty in history needs a rewrite and not an edit.
            scan(sha, name, f"{sha[:8]} {name.strip()}")
    return offenders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--message", type=Path)
    group.add_argument("--range", dest="rev_range")
    args = parser.parse_args()

    tokens = load_tokens()
    if not tokens:
        return 0

    if args.staged:
        offenders, what = check_staged(tokens), "staged changes"
    elif args.message:
        offenders, what = check_message(args.message, tokens), "commit message"
    else:
        offenders, what = check_range(args.rev_range, tokens), args.rev_range

    if not offenders:
        return 0

    print(
        f"\nBLOCKED: customer identifier found in {what} "
        f"({len(offenders)} location(s)):",
        file=sys.stderr,
    )
    for offender in sorted(set(offenders)):
        print(f"  {offender}", file=sys.stderr)
    print(
        "\nThe matched tokens are deliberately not printed. Check locally against\n"
        f"your own list at {os.environ.get(LIST_VARIABLE) or DEFAULT_LIST}.\n"
        "If this is already in history, a follow-up commit will not clear it --\n"
        "the history has to be rewritten.\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
