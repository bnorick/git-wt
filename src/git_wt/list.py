# Application-layout module.
"""List worktrees with repo-relative paths and structured JSON output."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TypedDict

from git_wt import _git, _worktree


class _ListRow(TypedDict):
    path: str
    branch: str
    head: str
    detached: bool
    locked: bool
    locked_reason: str
    prunable: bool
    prunable_reason: str


def run(*extra_args: str) -> int:
    if "--json" in extra_args:
        try:
            root = _worktree.bare_root()
            prefix = str(root) + "/"
        except Exception:
            prefix = None

        entries = _worktree.list_worktrees()
        rows = [asdict(entry) for entry in entries]
        for row in rows:
            row["path"] = _clean_path(row["path"], prefix)
        sys.stdout.write(json.dumps(rows) + "\n")
        return 0

    try:
        root = _worktree.bare_root()
        prefix = str(root) + "/"
        targets = _worktree.gitdir_targets()
    except Exception:
        prefix = None
        targets = {}

    try:
        raw = _git.query("worktree", "list", *extra_args)
    except _git.GitError as e:
        return e.returncode

    if "--porcelain" in extra_args:
        separator = "\0" if "\0" in raw or "-z" in extra_args else "\n"
        sanitized = _sanitize_porcelain(raw, targets, separator)
        sys.stdout.write(sanitized)
        if sanitized and not sanitized.endswith(separator):
            sys.stdout.write(separator)
        return 0

    sanitized = _sanitize_human(raw, targets)
    sys.stdout.write(_relativize(sanitized + "\n", prefix, targets))
    return 0


def _target_exists(path: str, targets: dict[str, Path]) -> bool | None:
    target = targets.get(path)
    if target is not None:
        return target.is_file()
    candidate = Path(path)
    if candidate.is_absolute():
        return (candidate / ".git").is_file()
    return None


def _listed_path(line: str, targets: dict[str, Path]) -> str:
    """Extract a list row's path, including paths containing spaces."""
    for path in sorted(targets, key=len, reverse=True):
        if line == path or line.startswith(path + " "):
            return path
    return line.split(None, 1)[0] if line.split(None, 1) else ""


def _sanitize_human(output: str, targets: dict[str, Path]) -> str:
    """Remove false old-Git prunable annotations from human list output."""
    result: list[str] = []
    current_exists: bool | None = None
    for line in output.splitlines():
        if line[:1].isspace():
            if current_exists is True and line.lstrip().startswith("prunable:"):
                continue
            result.append(line)
            continue

        path = _listed_path(line, targets)
        current_exists = _target_exists(path, targets)
        if current_exists is True and line.endswith(" prunable"):
            line = line.removesuffix(" prunable")
        result.append(line)
    return "\n".join(result)


def _sanitize_porcelain(
    output: str,
    targets: dict[str, Path],
    separator: str,
) -> str:
    """Remove false prunable fields while preserving porcelain delimiters."""
    result: list[str] = []
    current_exists: bool | None = None
    for field in output.split(separator):
        if field.startswith("worktree "):
            current_exists = _target_exists(field[9:], targets)
        elif not field:
            current_exists = None
        elif field.startswith("prunable") and current_exists is True:
            continue
        result.append(field)
    return separator.join(result)


def _clean_path(path: str, prefix: str | None) -> str:
    if prefix and path.startswith(prefix):
        return path[len(prefix) :]
    return re.sub(r"^(\.\./)+", "", path)


def _relativize(
    output: str,
    prefix: str | None,
    targets: dict[str, Path] | None = None,
) -> str:
    lines = [ln.rstrip("\n\r") for ln in output.splitlines()]

    # Non-porcelain: git aligns columns to the longest absolute path.
    # Re-parse all lines into (path, info), shorten prefix lines, then re-align.
    rows: list[tuple[str, str] | str | None] = []
    for line in lines:
        if not line:
            rows.append(None)
            continue
        if line[:1].isspace():
            rows.append(line)
            continue
        raw_path = _listed_path(line, targets or {})
        info = line[len(raw_path) :].strip()
        rows.append((_clean_path(raw_path, prefix), info))

    max_width = max(
        (len(r[0]) for r in rows if isinstance(r, tuple)),
        default=0,
    )
    result = []
    for row in rows:
        if row is None:
            result.append("")
        elif isinstance(row, str):
            result.append(row)
        else:
            path, info = row
        result.append(f"{path:<{max_width}}  {info}" if info else path)
    return "\n".join(result) + "\n"
