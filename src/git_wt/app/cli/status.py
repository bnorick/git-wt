# Application-layout module.
from __future__ import annotations

from git_wt import status as action


def status() -> None:
    """Show a repository-wide dashboard for all linked worktrees.

    Displays branch name, clean/dirty state, upstream sync status, last
    commit age, and a repo-relative path for each worktree.
    """
    action.run()
