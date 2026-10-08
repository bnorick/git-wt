# Application-layout module.
from __future__ import annotations

from git_wt import switch as action


def switch() -> None:
    """Interactively select a worktree and print its path.

    Opens a fuzzy picker over all linked worktrees and prints the chosen
    path to stdout. Use with cd to change directories:
      cd $(git wt switch)
    """
    action.run()
