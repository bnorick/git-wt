# Application-layout module.
from __future__ import annotations

import sys
from typing import Annotated

import cyclopts

from git_wt import list as action


def list_(
    *extra_args: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
) -> None:
    """List worktrees with paths relative to the repo root.

    Wraps `git worktree list` and rewrites absolute paths to be relative
    to the bare repo root. Accepts the same flags as `git worktree list`
    (e.g. --porcelain, -v).
    """
    sys.exit(action.run(*extra_args))
