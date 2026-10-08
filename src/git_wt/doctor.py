# Application-layout module.
"""Repository health checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from git_wt import _git, _worktree, console
from git_wt.app.console import TableColumn

Level = Literal["ok", "warn", "error"]


@dataclass
class Check:
    name: str
    status: Level = "ok"
    detail: str = ""


def run() -> int:
    """Run all checks and return exit code (0=ok, 1=errors)."""
    checks = _run_checks()
    _display(checks)

    errors = sum(1 for c in checks if c.status == "error")
    warnings = sum(1 for c in checks if c.status == "warn")
    ok = sum(1 for c in checks if c.status == "ok")
    total = len(checks)

    parts = [f"{total} check(s)", f"{ok} ok"]
    if warnings:
        parts.append(f"{warnings} warning(s)")
    if errors:
        parts.append(f"{errors} error(s)")
    console.print(console.subtle(" · ".join(parts)))

    return 1 if errors else 0


def _run_checks() -> list[Check]:
    checks: list[Check] = []

    # ── Repo root (--show-toplevel fails at bare root; fall back to --git-common-dir)
    try:
        repo_root = _git.query("rev-parse", "--show-toplevel")
    except _git.GitError:
        try:
            common_dir = _git.query("rev-parse", "--git-common-dir")
            common_path = Path(common_dir).resolve()
            if common_path.name == ".bare":
                repo_root = str(common_path.parent)
            else:
                checks.append(Check("Repository", "error", "not inside a git repository"))
                return checks
        except _git.GitError:
            checks.append(Check("Repository", "error", "not inside a git repository"))
            return checks

    checks.append(Check("Repository", "ok", repo_root))
    root = Path(repo_root)

    # ── Layout detection via git-common-dir
    git_path = root / ".git"
    try:
        common_dir = _git.query("rev-parse", "--git-common-dir")
        common_path = Path(common_dir).resolve()
        is_bare_layout = common_path.name == ".bare"
        is_standard = git_path.is_dir()
    except _git.GitError:
        is_bare_layout = False
        is_standard = git_path.is_dir()

    if is_bare_layout:
        checks.append(Check("repository layout", "ok", "bare worktree layout (.git → .bare)"))
    elif is_standard:
        checks.append(Check("repository layout", "warn", "standard git layout — run 'git wt migrate' to convert"))
        _check_migration_ready(root, checks)
        return checks
    else:
        checks.append(Check("repository layout", "error", ".git is neither a file nor a directory"))
        return checks

    # ── .bare directory
    bare_path = common_path if is_bare_layout else root / ".bare"
    if bare_path.is_dir():
        checks.append(Check(".bare directory", "ok", str(bare_path)))
    else:
        checks.append(Check(".bare directory", "error", f"{bare_path} not found"))

    # ── Worktree list
    try:
        entries = _worktree.list_worktrees()
        checks.append(Check("worktree list", "ok", f"{len(entries)} worktree(s)"))
    except _git.GitError as exc:
        checks.append(Check("worktree list", "error", str(exc)))
        entries = []

    # ── Worktree paths (parallel)
    if entries:
        path_checks: list[Check] = []
        with ThreadPoolExecutor() as pool:
            futures = {pool.submit(_check_wt_path, e): e for e in entries}
            for fut in as_completed(futures):
                path_checks.append(fut.result())
        # Sort by check name for deterministic output
        path_checks.sort(key=lambda c: c.name)
        checks.extend(path_checks)

    # ── Default remote
    try:
        remote = _worktree.default_remote()
        checks.append(Check("Default remote", "ok", remote))
    except Exception as exc:
        checks.append(Check("Default remote", "warn", str(exc)))
        remote = None

    # ── Default branch
    if remote:
        try:
            branch = _worktree.default_branch(remote)
            checks.append(Check("default branch", "ok", branch))
        except Exception as exc:
            checks.append(Check("default branch", "warn", str(exc)))

    return checks


def _check_wt_path(entry: _worktree.Entry) -> Check:
    p = Path(entry.path)
    name = p.name
    if p.exists():
        return Check(f"worktree {name!r}", "ok", str(p))
    return Check(f"worktree {name!r}", "error", f"path not found: {p}")


def _check_migration_ready(root: Path, checks: list[Check]) -> None:
    # No submodules
    if (root / ".gitmodules").exists():
        checks.append(Check("Migration readiness", "warn", "has submodules — migration not supported"))
        return

    # Single worktree only
    try:
        out = _git.query("worktree", "list", "--porcelain")
        wt_count = sum(1 for ln in out.splitlines() if ln.startswith("worktree "))
        if wt_count > 1:
            checks.append(Check("Migration readiness", "error", "has linked worktrees — remove before migrating"))
            return
    except _git.GitError:
        pass

    checks.append(Check("Migration readiness", "ok", "ready to migrate"))


def _display(checks: list[Check]) -> None:
    STATUS_ICON = {
        "ok": console.green("✓ ok   "),
        "warn": console.yellow("! warn "),
        "error": console.red("✗ error"),
    }

    rows = [[STATUS_ICON[c.status], c.name, c.detail] for c in checks]

    console.print_table(
        [
            TableColumn("STATUS", min_width=8),
            TableColumn("CHECK"),
            TableColumn("DETAIL"),
        ],
        rows,
    )
