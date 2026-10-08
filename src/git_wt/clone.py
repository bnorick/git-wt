# Application-layout module.
"""Clone a repository into a bare worktree layout."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from git_wt import _fsutil, _git, _worktree, console


def run(url: str, folder: str) -> None:
    # Derive target directory from URL if not specified
    if not folder:
        folder = Path(url).stem
        folder = folder.removesuffix(".git")

    target = Path(folder).resolve()

    def _step_create(write):
        target.mkdir(parents=True, exist_ok=False)

    def _step_clone(write):
        _git.run("clone", "--bare", url, str(target / ".bare"))

    def _step_configure(write):
        _configure_bare(target)

    def _step_fetch(write):
        _git.run("fetch", "--all", "--progress", dir=target)

    def _step_worktree(write):
        remote = _worktree.default_remote(target)
        branch = _worktree.default_branch(remote, target)
        wt_path = target / branch
        try:
            _git.run(
                "worktree",
                "add",
                "-B",
                branch,
                str(wt_path),
                f"{remote}/{branch}",
                dir=target,
            )
        except _git.GitError:
            _git.run("worktree", "add", branch, dir=target)
        _fsutil.relativize_worktree_gitdir(wt_path)
        write(str(wt_path))

    steps = [
        console.Step(f"Creating {console.path_style(str(target))}", run=_step_create),
        console.Step("Cloning bare repository", raw_output=True, run=_step_clone),
        console.Step("Configuring bare repository", run=_step_configure),
        console.Step("Fetching all remotes", raw_output=True, run=_step_fetch),
        console.Step("Creating default worktree", run=_step_worktree),
    ]

    try:
        console.run_steps(steps)
    except _git.GitError as exc:
        console.error(str(exc))
        sys.exit(1)
    except FileExistsError:
        console.error(f"{folder} already exists")
        sys.exit(1)

    console.success(f"\nCloned into {console.path_style(str(target))}")
    _print_hints(target)


def _configure_bare(root: Path) -> None:
    bare = root / ".bare"
    # Write .git file pointing to .bare
    (root / ".git").write_text("gitdir: ./.bare\n")
    _git.run("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*", dir=bare)
    _git.run("config", "core.logallrefupdates", "true", dir=bare)
    with contextlib.suppress(_git.GitError):
        _git.run("config", "worktree.useRelativePaths", "true", dir=bare)


def _print_hints(target: Path) -> None:
    name = target.name
    console.print()
    console.print(f"{name}/")
    console.print(f"  ├── {name}/.bare")
    console.print(f"  ├── {name}/.git   (gitdir: ./.bare)")
    console.print(f"  └── {name}/<branch>/")
    console.print()
    console.print(console.subtle("Next steps:"))
    console.print(f"  cd {name} && git wt add <branch-name> <branch-name>")
