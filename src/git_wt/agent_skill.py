# Application-layout module.
"""Install the git-wt agent skill definition."""

from __future__ import annotations

import sys
from pathlib import Path

from git_wt import console
from git_wt._skills import SKILL_MD


def run(*, force: bool, print_only: bool, dir: str) -> None:
    if print_only:
        print(SKILL_MD)
        return

    base = Path(dir).expanduser() if dir else Path.home() / ".agents" / "skills" / "git-wt"

    dest = base / "SKILL.md"

    if dest.exists() and not force:
        console.error(f"{dest} already exists — use --force to overwrite")
        sys.exit(1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(SKILL_MD)
    console.success(f"Installed skill to {dest}")
