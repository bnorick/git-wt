# Application-layout module.
"""Remove admin records for worktrees whose directories no longer exist."""

from __future__ import annotations

from pathlib import Path

from git_wt import _fsutil, _git, _worktree, console


def run(*, dry_run: bool = False) -> None:
    entries = _worktree.list_worktrees()
    stale = [e for e in entries if not Path(e.path).exists()]

    if not stale:
        console.print(console.subtle("No stale worktree metadata found."))
        return

    try:
        bare = _worktree.bare_root() / ".bare"
    except Exception:
        console.error("Could not locate bare repository root.")
        return

    ok = err = 0
    for entry in stale:
        label = Path(entry.path).name
        if dry_run:
            console.print(f"  [dry-run] would prune {label}")
            ok += 1
            continue
        try:
            _git.run("worktree", "remove", "--force", entry.path)
            console.print(f"  pruned {label}")
            ok += 1
        except _git.GitError:
            if _fsutil.delete_worktree_admin(Path(entry.path), bare):
                console.print(f"  pruned {label}")
                ok += 1
            else:
                console.error(f"  failed to prune {label}")
                err += 1

    if err:
        console.print(f"\n{ok} pruned, {err} failed")
    else:
        console.print(f"\n{ok} pruned")
