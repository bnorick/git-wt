# Application-layout module.
"""Show status of all worktrees."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from git_wt import _git, _worktree, console
from git_wt.app.console import TableColumn


@dataclass
class WorktreeStatus:
    entry: _worktree.Entry
    name: str = ""
    is_current: bool = False
    state: str = ""  # "clean" | "dirty" | "error"
    sync: str = ""  # "synced" | "↑N ahead" | "↓N behind" | etc.
    last_commit: str = ""
    flags: list[str] = field(default_factory=list)


def run() -> None:
    entries = _worktree.list_worktrees()
    if not entries:
        console.print(console.subtle("No worktrees found."))
        return

    try:
        root = _worktree.bare_root()
    except Exception:
        root = None

    try:
        cwd_root = _worktree.current_root()
    except Exception:
        cwd_root = None

    statuses = _fetch_all(entries, root, cwd_root)
    _display(statuses, root)


def _fetch_all(
    entries: list[_worktree.Entry],
    root,
    cwd_root,
) -> list[WorktreeStatus]:
    results: dict[str, WorktreeStatus] = {}

    with ThreadPoolExecutor() as pool:
        futures = {pool.submit(_fetch_one, e, root, cwd_root): e for e in entries}
        for fut in as_completed(futures):
            ws = fut.result()
            results[ws.entry.path] = ws

    # Sort: current first, then alpha by name
    def _key(ws: WorktreeStatus):
        return (0 if ws.is_current else 1, ws.name.lower())

    return sorted(results.values(), key=_key)


def _fetch_one(entry: _worktree.Entry, root, cwd_root) -> WorktreeStatus:
    name = _worktree.workspace_name(entry, root) if root else Path(entry.path).name
    p = Path(entry.path)
    is_current = cwd_root is not None and p.resolve() == cwd_root.resolve()

    ws = WorktreeStatus(entry=entry, name=name, is_current=is_current)

    if entry.locked:
        ws.flags.append("locked")
    if is_current:
        ws.flags.append("current")

    if not p.exists():
        ws.state = "error"
        return ws

    # git status --porcelain=v2 --branch
    try:
        status_out = _git.query("status", "--porcelain=v2", "--branch", dir=p)
        dirty = any(ln and not ln.startswith("#") for ln in status_out.splitlines())
        ws.state = "dirty" if dirty else "clean"

        # Parse branch tracking info from # branch.ab +N -N
        for ln in status_out.splitlines():
            if ln.startswith("# branch.ab "):
                parts = ln[12:].split()
                if len(parts) == 2:
                    ahead = int(parts[0].lstrip("+"))
                    behind = int(parts[1].lstrip("-"))
                    if ahead == 0 and behind == 0:
                        ws.sync = "✓ synced"
                    elif ahead > 0 and behind == 0:
                        ws.sync = f"↑{ahead} ahead"
                    elif ahead == 0 and behind > 0:
                        ws.sync = f"↓{behind} behind"
                    else:
                        ws.sync = f"↑{ahead} ↓{behind}"
            elif ln.startswith("# branch.upstream "):
                pass  # upstream exists
            elif ln == "# branch.upstream (none)":
                ws.sync = "local only"
    except _git.GitError:
        ws.state = "error"

    if not ws.sync:
        ws.sync = "local only"

    # Last commit age
    try:
        ts = _git.query("log", "-1", "--format=%ct", dir=p)
        if ts.strip().isdigit():
            age = int(time.time()) - int(ts.strip())
            ws.last_commit = _humanize_age(age)
    except _git.GitError:
        ws.last_commit = "n/a"

    return ws


def _humanize_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _display(statuses: list[WorktreeStatus], root) -> None:
    rows = []
    for ws in statuses:
        entry = ws.entry
        branch = entry.branch or (console.subtle("detached HEAD") if entry.detached else console.subtle("no branch"))

        if ws.state == "clean":
            state_str = console.green("● clean")
        elif ws.state == "dirty":
            state_str = console.yellow("● dirty")
        else:
            state_str = console.red("● error")

        if ws.sync == "✓ synced":
            sync_str = console.green(ws.sync)
        elif "ahead" in ws.sync:
            sync_str = console.accent(ws.sync)
        elif "behind" in ws.sync or "↓" in ws.sync:
            sync_str = console.yellow(ws.sync)
        else:
            sync_str = console.subtle(ws.sync)

        name_str = console.accent(ws.name) if ws.is_current else ws.name
        flags_str = " ".join(console.accent(f) if f == "current" else console.yellow(f) for f in ws.flags)
        path_str = console.subtle(_worktree.display_path(entry.path, root))

        rows.append([name_str, branch, state_str, sync_str, ws.last_commit, flags_str, path_str])

    console.print_table(
        [
            TableColumn("WORKTREE"),
            TableColumn("BRANCH"),
            TableColumn("STATE"),
            TableColumn("SYNC"),
            TableColumn("LAST COMMIT"),
            TableColumn("FLAGS"),
            TableColumn("PATH"),
        ],
        rows,
    )

    clean = sum(1 for ws in statuses if ws.state == "clean")
    dirty = sum(1 for ws in statuses if ws.state == "dirty")
    errors = sum(1 for ws in statuses if ws.state == "error")
    parts = [f"{len(statuses)} worktree(s)", f"{clean} clean", f"{dirty} dirty"]
    if errors:
        parts.append(f"{errors} error")
    console.print(console.subtle(" · ".join(parts)))
