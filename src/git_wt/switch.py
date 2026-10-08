# Application-layout module.
"""Switch to a worktree interactively."""

from __future__ import annotations

import sys

from git_wt import _picker, _worktree, console
from git_wt.preview import worktree_preview_cmd


def run() -> None:
    entries = _worktree.list_worktrees()
    if not entries:
        console.info("No worktrees available")
        sys.exit(0)

    try:
        root = _worktree.bare_root()
    except Exception:
        root = None

    items = [
        _picker.Item(
            value=e.path,
            label=_worktree.workspace_name(e, root) if root else e.path,
            desc=_worktree.workspace_name(e, root) if root else e.path,
        )
        for e in entries
    ]

    exe = sys.argv[0]
    selected = _picker.run(
        _picker.PickerConfig(
            items=items,
            multi=False,
            prompt="worktree> ",
            header="Select worktree  (Enter to switch)",
            preview_cmd=worktree_preview_cmd(exe),
        )
    )

    if not selected:
        sys.exit(1)

    # Print path to stdout for shell substitution: cd $(git wt switch)
    print(selected[0].value)
