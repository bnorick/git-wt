# Application-layout module.
"""Add a new worktree."""

from __future__ import annotations

import contextlib
import sys
import time
from collections.abc import Callable
from pathlib import Path

from git_wt import _fsutil, _git, _hooks, _picker, _worktree, console
from git_wt.preview import branch_preview_cmd


def _validate_worktree_name(path: str | Path) -> None:
    """Reject spaces in the new worktree's final path component."""
    name = Path(path).name
    if " " in name:
        console.error(f"Worktree names cannot contain spaces: {name!r}")
        sys.exit(1)


def _hook_context(worktree: Path, branch: str = "") -> _hooks.HookContext:
    """Build hook execution context for an adding worktree."""
    try:
        bare_root = _worktree.bare_root()
    except _git.GitError:
        bare_root = Path.cwd()
    return _hooks.HookContext(path=worktree, branch=branch, bare_root=bare_root)


def _run_add_hooks(worktree: Path, branch: str, create: Callable[[], object]) -> None:
    """Run configured worktree add lifecycle hooks around creation."""
    context = _hook_context(worktree, branch)
    try:
        _hooks.run_to_stderr("beforeadd", context, _hooks.load("beforeadd", dir=context.bare_root))
    except _hooks.HookError as exc:
        console.error(str(exc))
        sys.exit(exc.exit_code)
    try:
        create()
    except _git.GitError as exc:
        if not _hooks.load("beforeadd", dir=context.bare_root):
            raise
        console.error(str(exc))
        sys.exit(exc.returncode)
    after_context = _hooks.HookContext(path=worktree, branch=branch, bare_root=context.bare_root)
    try:
        _hooks.run_to_stderr("afteradd", after_context, _hooks.load("afteradd", dir=after_context.bare_root))
    except _hooks.HookError as exc:
        console.error(f"Worktree was created at {worktree}, but wt.afteradd failed")
        console.error(str(exc))
        sys.exit(exc.exit_code)


def run(
    worktree: str,
    commitish: str,
    *,
    branch: str,
    force_branch: str,
    detach: bool,
    force: bool,
    lock: bool,
    reason: str,
    quiet: bool,
    no_checkout: bool = False,
    from_remote: bool = False,
    from_local: tuple[str, ...] | None = None,
) -> None:
    if from_remote and from_local is not None:
        console.error("--from-remote and --from-local cannot be used together")
        sys.exit(1)
    if from_remote:
        _run_from_remote()
        return
    if from_local is not None:
        source_branch = from_local[0] if from_local else ""
        _run_from_local(worktree, source_branch)
        return
    if not worktree:
        _run_interactive()
    else:
        _run_direct(
            worktree,
            commitish,
            branch=branch,
            force_branch=force_branch,
            detach=detach,
            force=force,
            lock=lock,
            reason=reason,
            quiet=quiet,
            no_checkout=no_checkout,
        )


def _run_from_local(worktree: str, source_branch: str) -> None:
    if not worktree:
        console.error("A worktree name is required with --from-local")
        sys.exit(1)

    destination = Path(worktree)
    if destination.is_absolute():
        console.error("--from-local requires a repo-relative worktree name so it can also name the new branch")
        sys.exit(1)

    new_branch = str(destination)
    _validate_worktree_name(destination)

    if not source_branch:
        try:
            raw = _git.query(
                "for-each-ref",
                "--sort=-committerdate",
                "--format=%(refname:short)%09%(committerdate:unix)%09%(authorname)%09%(contents:subject)",
                "refs/heads",
            )
        except _git.GitError:
            raw = ""

        items: list[_picker.Item] = []
        now = int(time.time())
        for line in raw.splitlines():
            parts = line.split("\t", 3)
            branch_name = parts[0].strip() if parts else ""
            if not branch_name:
                continue
            age = _humanize_age(now - int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else ""
            author = parts[2].strip() if len(parts) > 2 else ""
            subject = parts[3].strip() if len(parts) > 3 else ""
            desc = " · ".join(part for part in (age, author, subject) if part)
            items.append(_picker.Item(value=branch_name, label=branch_name, desc=desc))

        if not items:
            console.warn("No local branches found.")
            sys.exit(0)

        selected = _picker.run(
            _picker.PickerConfig(
                items=items,
                multi=False,
                prompt="branch> ",
                header=f"Select local branch to base {new_branch} on",
                preview_cmd=branch_preview_cmd(sys.argv[0]),
            )
        )
        if not selected:
            sys.exit(0)
        source_branch = selected[0].value

    if not _git.query_ok("show-ref", "--verify", "--quiet", f"refs/heads/{source_branch}"):
        console.error(f"Local branch not found: {source_branch}")
        sys.exit(1)

    try:
        bare_root = _worktree.bare_root()
    except _git.GitError:
        bare_root = Path.cwd()
    wt_abs = bare_root / destination
    if wt_abs.exists():
        console.error(f"Path already exists: {wt_abs}")
        sys.exit(1)

    console.info(
        f"Creating worktree {console.accent(repr(worktree))} from local branch {console.accent(repr(source_branch))}..."
    )

    def _create() -> None:
        _git.run_to_stderr("worktree", "add", "-b", new_branch, str(wt_abs), source_branch)
        _fsutil.relativize_worktree_gitdir(wt_abs)

    _run_add_hooks(wt_abs, new_branch, _create)
    print(str(wt_abs))


def _run_from_remote() -> None:
    try:
        remote = _worktree.default_remote()
    except _git.GitError:
        remote = "origin"

    console.info("Fetching from all remotes...")
    with contextlib.suppress(_git.GitError):
        _git.run("fetch", "--all", "--quiet")

    entries = _worktree.list_worktrees()
    checked_out = {e.branch for e in entries if e.branch}

    try:
        raw = _git.query(
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)%09%(committerdate:unix)%09%(authorname)%09%(contents:subject)",
            "refs/remotes",
        )
    except _git.GitError:
        raw = ""

    items: list[_picker.Item] = []
    total_remote_branches = 0
    now = int(time.time())
    for line in raw.splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 1:
            continue
        ref = parts[0].strip()
        age_str = _humanize_age(now - int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else ""
        author = parts[2].strip() if len(parts) > 2 else ""
        subject = parts[3].strip() if len(parts) > 3 else ""

        slash = ref.find("/")
        if slash < 0:
            continue
        ref_remote = ref[:slash]
        branch = ref[slash + 1 :]

        if branch == "HEAD":
            continue

        total_remote_branches += 1

        if branch in checked_out:
            continue

        label = branch
        if ref_remote != remote:
            label += f" [{ref_remote}]"

        desc_parts = [p for p in [age_str, author, subject] if p]
        desc = " · ".join(desc_parts[:2])

        items.append(_picker.Item(value=ref, label=label, desc=desc))

    if not items:
        if total_remote_branches == 0:
            console.warn("No remote branches found.")
        else:
            console.warn("All remote branches already have a worktree.")
        sys.exit(0)

    exe = sys.argv[0]
    selected = _picker.run(
        _picker.PickerConfig(
            items=items,
            multi=False,
            prompt="branch> ",
            header="Select branch  (Enter to add worktree, path derived from branch name)",
            preview_cmd=branch_preview_cmd(exe),
        )
    )

    if not selected:
        sys.exit(0)

    choice = selected[0]
    ref = choice.value
    slash = ref.find("/")
    ref_remote = ref[:slash]
    branch = ref[slash + 1 :]

    try:
        bare_root = _worktree.bare_root()
    except _git.GitError:
        bare_root = Path.cwd()

    wt_abs = bare_root / branch
    _validate_worktree_name(wt_abs)

    if wt_abs.exists():
        console.error(f"Path already exists: {wt_abs}")
        sys.exit(1)

    branch_exists = _git.query_ok("rev-parse", "--verify", f"refs/heads/{branch}")

    def _create() -> None:
        if branch_exists:
            _git.run_to_stderr("worktree", "add", str(wt_abs), branch)
        else:
            _git.run_to_stderr("worktree", "add", "-b", branch, str(wt_abs), ref)
        _fsutil.relativize_worktree_gitdir(wt_abs)
        with contextlib.suppress(_git.GitError):
            _git.run_to_stderr("branch", f"--set-upstream-to={ref_remote}/{branch}", branch)

    _run_add_hooks(wt_abs, branch, _create)
    print(str(wt_abs))


def _run_interactive() -> None:
    try:
        remote = _worktree.default_remote()
    except _git.GitError:
        remote = "origin"

    # Fetch all remotes
    console.info("Fetching from all remotes...")
    with contextlib.suppress(_git.GitError):
        _git.run("fetch", "--all", "--quiet")

    # Get checked-out branches to exclude from picker
    entries = _worktree.list_worktrees()
    checked_out = {e.branch for e in entries if e.branch}

    # Query remote branches sorted by most recent commit
    try:
        raw = _git.query(
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)%09%(committerdate:unix)%09%(authorname)%09%(contents:subject)",
            "refs/remotes",
        )
    except _git.GitError:
        raw = ""

    items: list[_picker.Item] = [
        _picker.Item(value="__create_new__", label="➕ Create new branch", desc=""),
    ]

    now = int(time.time())
    for line in raw.splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 1:
            continue
        ref = parts[0].strip()  # e.g. origin/feature
        age_str = _humanize_age(now - int(parts[1])) if len(parts) > 1 and parts[1].isdigit() else ""
        author = parts[2].strip() if len(parts) > 2 else ""
        subject = parts[3].strip() if len(parts) > 3 else ""

        # Extract remote and branch name
        slash = ref.find("/")
        if slash < 0:
            continue
        ref_remote = ref[:slash]
        branch = ref[slash + 1 :]

        # Skip HEAD and already checked-out branches
        if branch == "HEAD" or branch in checked_out:
            continue

        label = branch
        if ref_remote != remote:
            label += f" [{ref_remote}]"

        desc_parts = [p for p in [age_str, author, subject] if p]
        desc = " · ".join(desc_parts[:2])  # keep concise

        items.append(_picker.Item(value=ref, label=label, desc=desc))

    exe = sys.argv[0]
    selected = _picker.run(
        _picker.PickerConfig(
            items=items,
            multi=False,
            prompt="branch> ",
            header="Select branch  (Enter to add worktree)",
            preview_cmd=branch_preview_cmd(exe),
        )
    )

    if not selected:
        sys.exit(0)

    choice = selected[0]

    try:
        bare_root = _worktree.bare_root()
    except _git.GitError:
        bare_root = Path.cwd()

    def _resolve_wt_path(raw: str) -> Path:
        p = Path(raw)
        return (bare_root / p) if not p.is_absolute() else p

    create_new = choice.value == "__create_new__"
    branch_name = console.prompt_input("Branch name") if create_new else ""
    if create_new and not branch_name:
        console.error("branch name required")
        sys.exit(1)
    worktree_path = console.prompt_input(
        "Enter worktree path", default=branch_name if create_new else choice.value[choice.value.find("/") + 1 :]
    )
    wt_abs = _resolve_wt_path(worktree_path)
    _validate_worktree_name(wt_abs)

    if create_new:
        branch = branch_name

        def _create() -> None:
            _git.run_to_stderr("worktree", "add", "-b", branch, str(wt_abs))
            _fsutil.relativize_worktree_gitdir(wt_abs)

    else:
        ref = choice.value
        ref_remote = ref[: ref.find("/")]
        branch = ref[ref.find("/") + 1 :]
        branch_exists = _git.query_ok("rev-parse", "--verify", f"refs/heads/{branch}")

        def _create() -> None:
            if branch_exists:
                _git.run_to_stderr("worktree", "add", str(wt_abs), branch)
            else:
                _git.run_to_stderr("worktree", "add", "-b", branch, str(wt_abs), ref)
            _fsutil.relativize_worktree_gitdir(wt_abs)
            with contextlib.suppress(_git.GitError):
                _git.run_to_stderr("branch", f"--set-upstream-to={ref_remote}/{branch}", branch)

    _run_add_hooks(wt_abs, branch, _create)
    print(str(wt_abs))


def _run_direct(
    worktree: str,
    commitish: str,
    *,
    branch: str,
    force_branch: str,
    detach: bool,
    force: bool,
    lock: bool,
    reason: str,
    quiet: bool,
    no_checkout: bool = False,
) -> None:
    _validate_worktree_name(worktree)

    try:
        remote = _worktree.default_remote()
    except _git.GitError:
        remote = "origin"

    # Resolve worktree path relative to bare root (not cwd)
    if Path(worktree).is_absolute():
        wt_path = worktree
    else:
        try:
            wt_path = str(_worktree.bare_root() / worktree)
        except _git.GitError:
            wt_path = str(Path(worktree).resolve())

    # Fetch before adding
    with contextlib.suppress(_git.GitError):
        _git.run("fetch", remote, "--quiet")

    if not quiet:
        console.info(f"Creating worktree {console.accent(repr(worktree))}...")

    # When the worktree path has multiple components (e.g. bnorick/test123) and no
    # explicit branch/commitish was given, git would infer the branch name from
    # basename(path) — yielding "test123" instead of "bnorick/test123". Auto-derive
    # the branch from the full relative path to preserve the namespace.
    if not branch and not force_branch and not detach and not commitish:
        p = Path(worktree)
        if not p.is_absolute() and len(p.parts) > 1:
            branch = str(p)

    git_args = ["worktree", "add"]
    if branch:
        git_args += ["-b", branch]
    if force_branch:
        git_args += ["-B", force_branch]
    if detach:
        git_args.append("--detach")
    if force:
        git_args.append("--force")
    if lock:
        git_args.append("--lock")
    if reason:
        git_args += ["--reason", reason]
    if quiet:
        git_args.append("--quiet")
    if no_checkout:
        git_args.append("--no-checkout")

    git_args.append(wt_path)
    if commitish:
        git_args.append(commitish)

    def _create() -> None:
        _git.run_to_stderr(*git_args)
        _fsutil.relativize_worktree_gitdir(Path(wt_path))

        track_branch = branch or force_branch
        if track_branch:
            try:
                _git.query("ls-remote", "--exit-code", remote, track_branch)
                _git.run_to_stderr("branch", f"--set-upstream-to={remote}/{track_branch}", track_branch)
            except _git.GitError:
                console.print(f"\n  {console.subtle('hint:')} git push -u {remote} {track_branch}")

    _run_add_hooks(Path(wt_path), branch or force_branch, _create)
    print(wt_path)


def _humanize_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
