#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Repository hygiene checks, as in the browser's tools/lint.py.

- Every source file carries the MPL-2.0 notice (Exhibit A).
- Text files use LF line endings.
- Relative links in Markdown point at files that exist.

Only files tracked by git are checked. Usage: python tools/lint.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
MPL_NOTICE = ("This Source Code Form is subject to the terms of the Mozilla Public License, "
              "v. 2.0. If a copy of the MPL was not distributed with this file, You can obtain "
              "one at https://mozilla.org/MPL/2.0/.")
HEADER_EXTENSIONS = {".py", ".sh", ".service", ".conf"}
HEADER_FILES = {"Caddyfile", "ghost-update-admin", "sudoers", "20auto-upgrades"}
HEADER_SEARCH_LINES = 15
_COMMENT_MARKERS = re.compile(r"^\s*(#!.*|#|//)")
_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                         check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def has_mpl_notice(text: str) -> bool:
    head = text.splitlines()[:HEADER_SEARCH_LINES]
    stripped = " ".join(_COMMENT_MARKERS.sub("", line).strip() for line in head)
    return MPL_NOTICE in " ".join(stripped.split())


def broken_links(md_path: Path, text: str) -> list[str]:
    broken = []
    for target in _MD_LINK.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            continue
        path_part = unquote(target.partition("#")[0])
        if path_part and not (md_path.parent / path_part).exists():
            broken.append(target)
    return broken


def lint(root: Path) -> list[str]:
    problems = []
    for rel in tracked_files(root):
        path = root / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        if b"\r\n" in data:
            problems.append(f"{rel}: CRLF line endings")
        text = data.decode("utf-8", "replace")
        name = Path(rel).name
        needs_notice = (Path(rel).suffix in HEADER_EXTENSIONS or name in HEADER_FILES)
        if needs_notice and not rel.startswith("tests/fixtures/") and not has_mpl_notice(text):
            problems.append(f"{rel}: missing the MPL-2.0 notice in the first "
                            f"{HEADER_SEARCH_LINES} lines")
        if rel.endswith(".md"):
            problems += [f"{rel}: broken relative link {t}" for t in broken_links(path, text)]
    return problems


def main() -> int:
    problems = lint(REPO_ROOT)
    for problem in problems:
        print(problem)
    print(f"lint: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
