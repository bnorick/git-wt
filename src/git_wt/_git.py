"""Git command execution layer with DEBUG dry-run support."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Never

import duct


class GitError(Exception):
    def __init__(self, args: tuple, returncode: int) -> None:
        self.git_args = args
        self.returncode = returncode
        cmd_str = "git " + " ".join(str(a) for a in args)
        super().__init__(f"`{cmd_str}` failed (exit {returncode})")


def _debug() -> bool:
    from git_wt.app.context import get_context

    return bool(os.environ.get("DEBUG")) or get_context().dry_run


def _build(
    args: tuple,
    dir: Path | None,
    env: dict[str, str],
    stdin_data: bytes | None,
) -> duct.Expression:
    c = duct.cmd("git", *args)
    if dir is not None:
        c = c.dir(str(dir))
    for k, v in env.items():
        c = c.env(k, v)
    if stdin_data is not None:
        c = c.stdin_bytes(stdin_data)
    return c


def _raise(args: tuple, e: duct.StatusError) -> Never:
    raise GitError(args, e.output.status)


def run(*args: str, dir: Path | None = None, env: dict[str, str] | None = None) -> None:
    """Mutating command — inherits stdio, respects DEBUG."""
    if _debug():
        print(f"[DEBUG] git {' '.join(args)}", file=sys.stderr)
        return
    try:
        _build(args, dir, env or {}, None).run()
    except duct.StatusError as e:
        _raise(args, e)


def run_in(*args: str, dir: Path, env: dict[str, str] | None = None) -> None:
    run(*args, dir=dir, env=env)


def query(*args: str, dir: Path | None = None, env: dict[str, str] | None = None) -> str:
    """Read-only command — captures stdout, strips trailing newline."""
    try:
        return _build(args, dir, env or {}, None).read() or ""
    except duct.StatusError as e:
        _raise(args, e)


def query_silent(*args: str, dir: Path | None = None, env: dict[str, str] | None = None) -> str:
    """Read-only command — captures stdout, suppresses stderr (for expected-to-fail probes)."""
    try:
        return _build(args, dir, env or {}, None).stderr_null().read() or ""
    except duct.StatusError as e:
        _raise(args, e)


def query_in(*args: str, dir: Path, env: dict[str, str] | None = None) -> str:
    return query(*args, dir=dir, env=env)


def query_lines(*args: str, dir: Path | None = None) -> list[str]:
    """Read-only command — returns non-empty lines."""
    return [ln for ln in query(*args, dir=dir).splitlines() if ln.strip()]


def query_combined(*args: str, dir: Path | None = None) -> str:
    """Read-only command — captures stdout+stderr merged."""
    try:
        return _build(args, dir, {}, None).stderr_to_stdout().read() or ""
    except duct.StatusError as e:
        _raise(args, e)


def query_ok(*args: str, dir: Path | None = None) -> bool:
    """Returns True if exit code is 0."""
    result = _build(args, dir, {}, None).stderr_null().unchecked().run()
    return result.status == 0


def run_to_stderr(*args: str, dir: Path | None = None, env: dict[str, str] | None = None) -> None:
    """Mutating command — captures stdout+stderr and writes both to stderr."""
    if _debug():
        print(f"[DEBUG] git {' '.join(args)}", file=sys.stderr)
        return
    try:
        out = _build(args, dir, env or {}, None).stderr_to_stdout().read()
        if out:
            print(out, file=sys.stderr)
    except duct.StatusError as e:
        _raise(args, e)


def run_with_stdin(*args: str, stdin_data: bytes, dir: Path | None = None) -> None:
    """Mutating command with stdin bytes."""
    if _debug():
        print(f"[DEBUG] git {' '.join(args)}", file=sys.stderr)
        return
    try:
        _build(args, dir, {}, stdin_data).run()
    except duct.StatusError as e:
        _raise(args, e)
