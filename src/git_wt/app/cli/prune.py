# Application-layout module.
from __future__ import annotations

from git_wt import prune as action
from git_wt.app.context import get_context


def prune() -> None:
    """Remove metadata for worktrees whose directories no longer exist.

    Safe replacement for `git worktree prune`: only deletes admin records
    for worktrees that are truly gone from disk. Because git-wt uses relative
    paths, git incorrectly marks all worktrees as prunable — running
    `git worktree prune` directly would corrupt the repository.
    """
    action.run(dry_run=get_context().dry_run)
