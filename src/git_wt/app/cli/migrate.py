# Application-layout module.
from __future__ import annotations

from git_wt import migrate as action
from git_wt.app.context import get_context


def migrate() -> None:
    """Migrate an existing repository to the bare worktree layout. [EXPERIMENTAL]

    Converts a standard git repository in-place: moves git data into a .bare
    directory and sets up a linked worktree for the current branch. Use the
    global --dry-run flag to preview changes without modifying anything.
    """
    action.run(dry_run=get_context().dry_run)
