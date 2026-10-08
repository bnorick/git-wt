# Application-layout module.
from __future__ import annotations

from typing import Annotated

import cyclopts

from git_wt import update as action


def update(
    branch: Annotated[str, cyclopts.Parameter(show_default=False, help="Additional branch worktree to pull")] = "",
    *,
    force: Annotated[
        bool,
        cyclopts.Parameter(
            help="Discard uncommitted tracked-file changes and hard-reset to upstream (use with caution)"
        ),
    ] = False,
) -> None:
    """Fetch all remotes (with prune) and pull branch worktrees.

    Always pulls the repository's default branch. Pass a branch name
    (positional or via --branch) to also pull that worktree.
    """
    action.run(branch=branch, force=force)
