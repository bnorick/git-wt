# Application-layout module.
from __future__ import annotations

from typing import Annotated

import cyclopts

from git_wt import clone as action


def clone(
    url: Annotated[str, cyclopts.Parameter(show_default=False, help="Repository URL to clone")],
    folder: Annotated[
        str, cyclopts.Parameter(show_default=False, help="Local folder name (defaults to repo name)")
    ] = "",
) -> None:
    """Clone a repository and set up the bare worktree structure.

    Creates a .bare directory for git data and an initial worktree for
    the default branch. Pass an optional folder name to override the
    default (derived from the repo name in the URL).
    """
    action.run(url, folder)
