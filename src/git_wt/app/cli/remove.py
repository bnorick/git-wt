# Application-layout module.
from __future__ import annotations

from typing import Annotated

import cyclopts

from git_wt import remove as action
from git_wt.app.context import get_context


def remove(
    *worktrees: Annotated[str, cyclopts.Parameter(show_default=False, help="Worktree names or paths to remove")],
    merged: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Select worktrees fully merged into the default branch")
    ] = False,
    gone: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Select worktrees whose upstream is gone")
    ] = False,
    stale: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Select stale or prunable worktree metadata")
    ] = False,
    sweep: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Shorthand for --merged --gone --stale")
    ] = False,
    delete_remote: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Also delete matching remote branches when possible")
    ] = False,
) -> None:
    """Remove worktrees directly or by safe cleanup filters.

    By default, also deletes the worktree's local branch. Use
    --delete-remote to also delete the remote branch when possible.

    Cleanup filters select safe bulk candidates: --merged selects branches
    fully merged into the default branch, --gone selects branches whose
    upstream is gone, --stale selects missing or prunable worktree metadata,
    and --sweep is shorthand for all three.

    With no arguments and no filters, an interactive picker is shown. Use
    the global --dry-run flag to preview what would be removed.
    """
    action.run(
        list(worktrees),
        merged=merged,
        gone=gone,
        stale=stale,
        sweep=sweep,
        delete_remote=delete_remote,
        dry_run=get_context().dry_run,
    )


def destroy(
    *worktrees: Annotated[str, cyclopts.Parameter(show_default=False, help="Worktree names or paths to remove")],
    merged: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Select worktrees fully merged into the default branch")
    ] = False,
    gone: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Select worktrees whose upstream is gone")
    ] = False,
    stale: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Select stale or prunable worktree metadata")
    ] = False,
    sweep: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Shorthand for --merged --gone --stale")
    ] = False,
    delete_remote: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Also delete matching remote branches when possible")
    ] = False,
) -> None:
    """Alias for: remove [\\<worktree>...]

    Remove worktrees and delete their local branches.
    Requires branch-name confirmation for safety.
    Supports --delete-remote to also delete remote branches.
    """
    action.run(
        list(worktrees),
        merged=merged,
        gone=gone,
        stale=stale,
        sweep=sweep,
        delete_remote=delete_remote,
        dry_run=get_context().dry_run,
        confirm_dangerous=True,
    )
