"""Worktree lifecycle hook execution."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from git_wt import _git

HookEvent = Literal["beforeadd", "afteradd", "beforeremove", "afterremove"]


@dataclass(frozen=True)
class HookContext:
    path: Path
    branch: str
    bare_root: Path


def _debug() -> bool:
    from git_wt.app.context import get_context

    return bool(os.environ.get("DEBUG")) or get_context().dry_run


def load(event: HookEvent, dir: Path | None = None) -> list[str]:
    try:
        result = _git.query("config", "--null", "--get-all", f"wt.{event}", dir=dir)
    except _git.GitError as exc:
        if exc.returncode == 1:
            return []
        raise
    if not result:
        return []
    return result.rstrip("\x00").split("\x00")


def run(event: HookEvent, context: HookContext, commands: list[str], stderr: Callable[[str], None]) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_WT_EVENT": event,
            "GIT_WT_PATH": str(context.path),
            "GIT_WT_BRANCH": context.branch,
            "GIT_WT_BARE_ROOT": str(context.bare_root),
        }
    )
    for command in [command for command in commands if command and "\x00" not in command]:
        if _debug():
            stderr(f"[wt.{event} in {context.bare_root}] sh -c {command}\n")
            continue
        completed = subprocess.run(["sh", "-c", command], cwd=context.bare_root, env=env)
        if completed.returncode:
            raise HookError(event, command, completed.returncode)


class HookError(RuntimeError):
    def __init__(self, event: HookEvent, command: str, exit_code: int) -> None:
        super().__init__(f"wt.{event} hook {command!r} failed (exit {exit_code})")
        self.event = event
        self.command = command
        self.exit_code = exit_code


def run_to_stderr(event: HookEvent, context: HookContext, commands: list[str]) -> None:
    run(event, context, commands, lambda line: print(line, file=sys.stderr, end=""))
