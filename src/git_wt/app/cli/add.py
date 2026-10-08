# Application-layout module.
from __future__ import annotations

from typing import Annotated

import cyclopts

from git_wt import add as action
from git_wt.app.context import get_context


def add(
    worktree: Annotated[str, cyclopts.Parameter(show_default=False, help="Worktree path to create")] = "",
    commitish: Annotated[str, cyclopts.Parameter(show_default=False, help="Branch, tag, or commit to check out")] = "",
    *,
    branch: Annotated[str, cyclopts.Parameter(short_alias=True, show_default=False, help="Create a new branch")] = "",
    force_branch: Annotated[
        str, cyclopts.Parameter(name=["--force-branch", "-B"], show_default=False, help="Create or reset a branch")
    ] = "",
    detach: Annotated[
        bool, cyclopts.Parameter(name=["--detach", "-d"], show_default=False, help="Detach HEAD at the new worktree")
    ] = False,
    force: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--force", "-f"], show_default=False, help="Checkout even if branch is checked out elsewhere"
        ),
    ] = False,
    lock: Annotated[bool, cyclopts.Parameter(show_default=False, help="Lock the worktree after creation")] = False,
    reason: Annotated[str, cyclopts.Parameter(show_default=False, help="Lock reason (use with --lock)")] = "",
    no_checkout: Annotated[bool, cyclopts.Parameter(show_default=False, help="Don't populate the worktree")] = False,
    from_remote: Annotated[
        bool,
        cyclopts.Parameter(
            name="--from-remote",
            show_default=False,
            help="Fetch remotes and pick a branch; path is auto-derived from the branch name",
        ),
    ] = False,
    from_local: Annotated[
        tuple[str, ...] | None,
        cyclopts.Parameter(
            name="--from-local",
            consume_multiple=(0, 1),
            show_default=False,
            help="Create the new branch from a selected local branch, or name the source branch directly",
        ),
    ] = None,
) -> None:
    """Create a new worktree.

    With no arguments, opens an interactive picker to select from remote
    branches or create a new branch. Always fetches from the remote before
    creating the worktree. When using -b/-B, upstream tracking is set
    automatically if the branch exists on the remote.

    On success, prints the absolute worktree path to stdout. Progress,
    prompts, and hints are written to stderr.

    Run without arguments for interactive selection, or pass a path and
    commitish directly (git wt add feature origin/feature). Use -b/-B to
    create or reset a branch (git wt add -b new-feature main), or
    --detach to check out a detached HEAD. Use --from-local with a
    repo-relative worktree name to select a local starting branch, or pass
    that source branch directly after the option.
    """
    action.run(
        worktree,
        commitish,
        branch=branch,
        force_branch=force_branch,
        detach=detach,
        force=force,
        lock=lock,
        reason=reason,
        quiet=get_context().quiet,
        no_checkout=no_checkout,
        from_remote=from_remote,
        from_local=from_local,
    )
