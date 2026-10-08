# Application-layout module.
from __future__ import annotations

import sys

from git_wt import doctor as action


def doctor() -> None:
    """Run repository diagnostics for both standard and bare worktree layouts.

    Checks repository layout, the .bare directory, linked worktree paths,
    default remote and branch detection, and migration readiness for
    standard repositories.
    """
    sys.exit(action.run())
