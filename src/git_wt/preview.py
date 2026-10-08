# Application-layout module.
"""Hidden _preview subcommand — renders picker preview pane content."""

from __future__ import annotations

import sys
from contextlib import suppress
from pathlib import Path

from rich.console import Console
from rich.text import Text

from git_wt import _git, _worktree, console

_out = Console(highlight=False, force_terminal=True)


def run(type_: str, value: str, mode: str = "") -> None:
    if type_ == "worktree":
        _preview_worktree(value, mode)
    elif type_ == "branch":
        _preview_branch(value)
    else:
        _out.print(f"unknown preview type: {type_}")
        sys.exit(1)


def _preview_worktree(path: str, mode: str) -> None:
    p = Path(path)

    # Path and branch header
    entries = _worktree.list_worktrees()
    entry = next((e for e in entries if e.path == path), None)

    _out.print(console.bold("Worktree"))
    _out.print(f"  {console.path_style(path)}")
    if entry:
        if entry.branch:
            _out.print(f"  branch: {console.accent(entry.branch)}")
        elif entry.detached:
            _out.print(f"  {console.subtle('detached HEAD')}")

    # Actions section (for remove preview)
    if mode in ("remove", "remove-remote"):
        _out.print()
        _out.print(console.bold("Actions"))
        if entry and entry.branch:
            _out.print(f"  remove worktree {console.path_style(path)}")
            _out.print(f"  delete branch {console.accent(entry.branch)}")
            if mode == "remove-remote":
                with suppress(Exception):
                    remote = _worktree.default_remote()
                    _out.print(f"  delete remote branch {console.accent(remote + '/' + entry.branch)}")

    # Git status
    _out.print()
    _out.print(console.bold("Status"))
    try:
        status = _git.query("status", "--short", dir=p)
        if status:
            for line in status.splitlines()[:15]:
                _out.print(f"  {line}")
        else:
            _out.print(f"  {console.green('clean')}")
    except _git.GitError:
        _out.print(f"  {console.subtle('(unavailable)')}")

    # Recent commits
    _out.print()
    _out.print(console.bold("Recent Commits"))
    try:
        log = _git.query(
            "log",
            "--oneline",
            "--color=always",
            "-10",
            dir=p,
        )
        if log:
            for line in log.splitlines():
                _out.print(Text("  ") + Text.from_ansi(line))
        else:
            _out.print(f"  {console.subtle('(no commits)')}")
    except _git.GitError:
        _out.print(f"  {console.subtle('(unavailable)')}")


def _preview_branch(ref: str) -> None:
    # ref is like "origin/feature-branch"
    parts = ref.split("/", 1)
    remote = parts[0] if len(parts) == 2 else ""
    branch = parts[1] if len(parts) == 2 else ref

    _out.print(console.bold("Branch"))
    if remote:
        _out.print(f"  {console.accent(branch)} {console.subtle(f'[{remote}]')}")
    else:
        _out.print(f"  {console.accent(branch)}")

    _out.print()
    _out.print(console.bold("Recent Commits"))
    try:
        log = _git.query(
            "log",
            "--oneline",
            "--color=always",
            "-10",
            ref,
        )
        if log:
            for line in log.splitlines():
                _out.print(Text("  ") + Text.from_ansi(line))
        else:
            _out.print(f"  {console.subtle('(no commits)')}")
    except _git.GitError:
        _out.print(f"  {console.subtle('(unavailable)')}")


def worktree_preview_cmd(exe: str, mode: str = "") -> str:
    """Build the preview command string for the worktree picker."""
    mode_arg = f" {mode}" if mode else ""
    return f"{exe} _preview worktree {{value}}{mode_arg}"


def branch_preview_cmd(exe: str) -> str:
    """Build the preview command string for the branch picker."""
    return f"{exe} _preview branch {{value}}"
