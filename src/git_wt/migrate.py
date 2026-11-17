# Application-layout module.
"""Convert a regular git repository to the bare worktree layout."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import sys
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

import duct

from git_wt import _fsutil, _git, _worktree, console
from git_wt.app.console import TableColumn

_PRESERVED_PREFIXES = (
    "alias.",
    "branch.",
    "diff.",
    "merge.",
    "pull.",
    "rebase.",
    "rerere.",
    "submodule.",
    "wt.",
)
_PRESERVED_KEYS = {"core.hookspath", "user.email", "user.name"}


@dataclass
class _Remote:
    name: str
    url: str
    fetch_specs: list[str] = field(default_factory=list)


@dataclass
class _ConfigEntry:
    key: str
    values: list[str] = field(default_factory=list)


@dataclass
class _Plan:
    repo_root: Path
    repo_name: str
    parent_dir: Path
    current_branch: str
    default_branch: str
    default_remote: str
    has_changes: bool
    untracked: list[str] = field(default_factory=list)
    stash_count: int = 0
    remotes: list[_Remote] = field(default_factory=list)
    configs: list[_ConfigEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    nested_repos: list[tuple[Path, Path]] = field(default_factory=list)
    git_markers: list[Path] = field(default_factory=list)


def run(*, dry_run: bool, fast: bool = False) -> None:
    plan = _build_plan()
    if fast:
        plan.warnings.append("FAST MODE: moves original files; no rollback on failure or interruption")
    _show_plan(plan)

    if dry_run:
        console.print(console.subtle("[DRY RUN] No changes made."))
        return

    if not console.confirm("Proceed with migration?"):
        console.info("Aborted.")
        return

    pid = os.getpid()
    new_structure = plan.parent_dir / f"{plan.repo_name}-new-{pid}"
    temp_backup = plan.parent_dir / f"{plan.repo_name}-backup-{pid}"

    with _cleanup_guard(new_structure, temp_backup, preserve_on_error=fast):
        _build_migrated(plan, new_structure, fast=fast)
        if fast:
            with console.temporary_notice(_fast_recovery_notice(plan, new_structure, temp_backup)):
                _finalize_fast(plan, new_structure, temp_backup)
        else:
            _finalize(plan, new_structure, temp_backup)

    _show_result(plan)


# ---------------------------------------------------------------------------
# Pre-flight + plan building
# ---------------------------------------------------------------------------


def _build_plan() -> _Plan:
    try:
        repo_root = Path(_git.query("rev-parse", "--show-toplevel")).resolve()
    except _git.GitError:
        console.error("Not in a git repository")
        sys.exit(1)

    git_path = repo_root / ".git"

    # .git must be a directory (not already migrated)
    if not git_path.is_dir():
        console.error(".git is not a directory — repository may already be in bare layout")
        sys.exit(1)

    nested_repos, git_markers = _collect_nested_repos(repo_root)

    # Only one worktree
    try:
        out = _git.query("worktree", "list", "--porcelain")
        wt_count = sum(1 for ln in out.splitlines() if ln.startswith("worktree "))
        if wt_count > 1:
            console.error("repository has linked worktrees — remove them before migrating")
            sys.exit(1)
    except _git.GitError:
        pass

    # No sparse checkout
    try:
        sparse = _git.query("config", "core.sparseCheckout")
        if sparse.strip().lower() == "true":
            console.error("sparse checkout is not supported")
            sys.exit(1)
    except _git.GitError:
        pass

    # Current branch
    try:
        current_branch = _git.query("rev-parse", "--abbrev-ref", "HEAD")
    except _git.GitError:
        console.error("could not determine current branch")
        sys.exit(1)

    if current_branch == "HEAD":
        console.error("detached HEAD — please checkout a branch before migrating")
        sys.exit(1)

    # Remotes
    remotes = _collect_remotes()

    warnings: list[str] = []
    if len(remotes) > 1:
        warnings.append(f"multiple remotes ({len(remotes)}) — all will be preserved")

    # Default remote + branch
    try:
        default_remote = _worktree.default_remote()
    except Exception:
        default_remote = "origin"

    try:
        default_branch = _worktree.default_branch(default_remote)
    except Exception:
        default_branch = current_branch

    # Config entries to preserve
    configs = _collect_configs()

    # Working tree state
    has_changes = not _git.query_ok("diff-index", "--quiet", "HEAD", "--")
    try:
        untracked = _git.query_lines("ls-files", "--others", "--exclude-standard")
    except _git.GitError:
        untracked = []

    try:
        stash_count = len(_git.query_lines("stash", "list"))
    except _git.GitError:
        stash_count = 0

    return _Plan(
        repo_root=repo_root,
        repo_name=repo_root.name,
        parent_dir=repo_root.parent,
        current_branch=current_branch,
        default_branch=default_branch,
        default_remote=default_remote,
        has_changes=has_changes,
        untracked=untracked,
        stash_count=stash_count,
        remotes=remotes,
        configs=configs,
        warnings=warnings,
        nested_repos=nested_repos,
        git_markers=git_markers,
    )


def _collect_nested_repos(root: Path) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Find nested repositories and empty .git markers without traversing Git metadata."""
    repos: list[tuple[Path, Path]] = []
    markers: list[Path] = []
    for directory, dirs, _files in os.walk(root):
        dirs[:] = [name for name in dirs if name != ".git"]
        path = Path(directory)
        dot_git = path / ".git"
        if path == root or not dot_git.exists():
            continue
        git_dir = dot_git
        if dot_git.is_file():
            # uv uses empty .git files to keep Git from discovering a parent
            # repository inside its source cache. These are not gitdir pointers.
            if dot_git.stat().st_size == 0:
                markers.append(dot_git.relative_to(root))
                continue
            content = dot_git.read_text().strip()
            if not content.startswith("gitdir:"):
                console.error(f"invalid nested repository pointer: {dot_git}")
                sys.exit(1)
            git_dir = (path / content[len("gitdir:") :].strip()).resolve()
        if not git_dir.is_relative_to(root) or not git_dir.is_dir() or (git_dir / "commondir").exists():
            console.error(f"nested repository {path} has external or linked Git metadata — migration not supported")
            sys.exit(1)
        repos.append((path.relative_to(root), git_dir.relative_to(root)))
    return repos, markers


def _collect_remotes() -> list[_Remote]:
    remotes: list[_Remote] = []
    try:
        remote_names = _git.query_lines("remote")
    except _git.GitError:
        return remotes

    for name in remote_names:
        try:
            url = _git.query("remote", "get-url", name)
        except _git.GitError:
            url = ""
        try:
            specs = _git.query_lines("config", "--get-all", f"remote.{name}.fetch")
        except _git.GitError:
            specs = [f"+refs/heads/*:refs/remotes/{name}/*"]
        remotes.append(_Remote(name=name, url=url, fetch_specs=specs))

    return remotes


def _collect_configs() -> list[_ConfigEntry]:
    configs: list[_ConfigEntry] = []
    try:
        raw = _git.query("config", "--local", "--list")
    except _git.GitError:
        return configs

    seen: dict[str, _ConfigEntry] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not _should_preserve_config(key):
            continue
        if key not in seen:
            seen[key] = _ConfigEntry(key=key)
            configs.append(seen[key])
        seen[key].values.append(val)

    return configs


def _should_preserve_config(key: str) -> bool:
    if key in _PRESERVED_KEYS:
        return True
    return any(key.startswith(p) for p in _PRESERVED_PREFIXES)


# ---------------------------------------------------------------------------
# Display plan
# ---------------------------------------------------------------------------


def _show_plan(plan: _Plan) -> None:
    notes: list[str] = []
    if plan.warnings:
        notes.extend(plan.warnings)
    if plan.has_changes:
        notes.append("uncommitted changes will be preserved")
    if plan.untracked:
        notes.append(f"{len(plan.untracked)} untracked file(s) will be preserved")
    if plan.stash_count:
        notes.append(f"{plan.stash_count} stash(es) will be migrated")

    rows = [
        ["Repo", str(plan.repo_root)],
        ["Default remote", plan.default_remote],
        ["Default branch", plan.default_branch],
        ["Current branch", plan.current_branch],
        ["Remotes", str(len(plan.remotes))],
        ["Configs preserved", str(len(plan.configs))],
    ]
    if notes:
        rows.append(["Notes", "\n".join(f"• {n}" for n in notes)])

    console.print_table(
        [TableColumn("ITEM"), TableColumn("VALUE")],
        rows,
        summary="Migration plan",
    )


# ---------------------------------------------------------------------------
# Working tree sync
# ---------------------------------------------------------------------------


def _sync_working_tree(src: Path, dst: Path) -> None:
    """Copy src working tree into dst, skipping .git.

    Uses --checksum comparison because git worktree add writes files with
    current-time mtimes, so mtime-based diffing would copy every file regardless.

    Strategy is auto-detected (rsync → rclone → python) but can be forced via
    GIT_WT_MIGRATE_STRATEGY=rsync|rclone|python. rclone parallelism can be
    tuned with GIT_WT_MIGRATE_RCLONE_TRANSFERS=N (default: rclone's own default
    of 4).

    TODO: consider a git/plan-aware approach that reads plan.untracked and
    `git diff --name-only HEAD` to copy only the files that actually changed,
    which would be faster for the common case of few uncommitted changes. Must
    be .gitignore blind (so files git would usually ignore are also copied).
    """
    src_str = str(src).rstrip("/") + "/"
    dst_str = str(dst)
    strategy = os.environ.get("GIT_WT_MIGRATE_STRATEGY", "").lower()

    def _rsync() -> bool:
        if not shutil.which("rsync"):
            return False
        duct.cmd("rsync", "-a", "--checksum", "--exclude=.git", src_str, dst_str).run()
        return True

    def _rclone() -> bool:
        if not shutil.which("mise"):
            return False
        cmd = ["mise", "exec", "rclone", "--", "rclone", "copy", "--checksum", "--links", "--filter", "- .git/"]
        transfers = os.environ.get("GIT_WT_MIGRATE_RCLONE_TRANSFERS", "")
        if transfers:
            cmd += ["--transfers", transfers]
        cmd += [src_str, dst_str]
        try:
            duct.cmd(cmd[0], *cmd[1:]).run()
            return True
        except duct.StatusError:
            return False

    def _python() -> bool:
        console.warn("rsync and rclone not found — falling back to slow Python copy")
        _fsutil.copy_dir(src, dst, excludes=(".git",))
        return True

    if strategy == "rsync":
        _rsync()
    elif strategy == "rclone":
        _rclone()
    elif strategy == "python":
        _python()
    else:
        _rsync() or _rclone() or _python()


# ---------------------------------------------------------------------------
# Build migrated structure
# ---------------------------------------------------------------------------


def _build_migrated(plan: _Plan, new_dir: Path, *, fast: bool = False) -> None:
    bare = new_dir / ".bare"

    def _step_clone(write):
        _git.run("clone", "--bare", str(plan.repo_root), str(bare))

    def _step_configure(write):
        # Write .git pointer
        (new_dir / ".git").write_text("gitdir: ./.bare\n")
        _configure_bare(bare)
        _apply_remotes(bare, plan.remotes)
        _apply_configs(bare, plan.configs)

    def _step_fetch(write):
        with suppress(_git.GitError):
            _git.run("fetch", "--all", "--progress", dir=bare)
        _cleanup_local_branch_refs(bare)

    def _step_stashes(write):
        if plan.stash_count == 0:
            return
        old_git = plan.repo_root / ".git"
        for src_name, dst_name in [
            ("refs/stash", "refs/stash"),
            ("logs/refs/stash", "logs/refs/stash"),
        ]:
            src = old_git / src_name
            dst = bare / dst_name
            if src.exists():
                _fsutil.copy_file(src, dst)

    def _step_worktrees(write):
        _create_migration_worktrees(plan, new_dir, fast=fast)

    def _step_restore(write):
        if fast:
            return
        # Find the current branch worktree path
        wt_path = new_dir / plan.current_branch
        if not wt_path.exists():
            return
        _sync_working_tree(plan.repo_root, wt_path)
        _restore_nested_repos(plan, wt_path)
        # Sync excludes .git entries; restore cache markers as ordinary files.
        for marker in plan.git_markers:
            _fsutil.copy_file(plan.repo_root / marker, wt_path / marker)
        # Copy index to preserve staged changes
        old_index = plan.repo_root / ".git" / "index"
        if old_index.exists():
            # Find the worktree index in the new bare
            new_index = Path(_git.query("rev-parse", "--absolute-git-dir", dir=wt_path)) / "index"
            if new_index.parent.exists():
                _fsutil.copy_file(old_index, new_index)

    steps = [
        console.Step("Cloning bare repository", raw_output=True, run=_step_clone),
        console.Step("Configuring bare repository", run=_step_configure),
        console.Step("Fetching all remotes", raw_output=True, run=_step_fetch),
        console.Step("Migrating stashes", run=_step_stashes),
        console.Step("Creating worktrees", run=_step_worktrees),
    ]
    if not fast:
        steps.append(console.Step("Restoring working directory", run=_step_restore))

    console.run_steps(steps)


def _restore_nested_repos(plan: _Plan, wt_path: Path, *, move: bool = False) -> None:
    """Preserve module object stores, indexes, refs, and relocatable links."""
    admin = Path(_git.query("rev-parse", "--absolute-git-dir", dir=wt_path))
    old_git = plan.repo_root / ".git"

    def destination(relative: Path) -> Path:
        if relative.parts[0] == ".git":
            return admin / relative.relative_to(".git")
        return wt_path / relative

    modules = old_git / "modules"
    if modules.is_dir():
        if move:
            modules.rename(admin / "modules")
        else:
            _fsutil.copy_dir(modules, admin / "modules")
    for relative_path, relative_git in plan.nested_repos:
        src = plan.repo_root / relative_path / ".git"
        dst = wt_path / relative_path / ".git"
        git_dir = destination(relative_git)
        if move and dst.is_dir():
            continue  # Embedded Git metadata moved with the working directory.
        if not move and src.is_dir():
            _fsutil.copy_dir(src, dst)
        else:
            dst.write_text(f"gitdir: {os.path.relpath(git_dir, dst.parent)}\n")

    # Include deinitialized modules: their stores still contain local history.
    configs = list((admin / "modules").rglob("config")) if (admin / "modules").is_dir() else []
    configs.extend(destination(git_dir) / "config" for _, git_dir in plan.nested_repos)
    for config in set(configs):
        try:
            worktree = _git.query_silent("config", "--file", str(config), "core.worktree")
        except _git.GitError:
            continue
        relative_git = config.parent.relative_to(admin) if config.is_relative_to(admin) else None
        old_dir = (
            old_git / relative_git if relative_git is not None else plan.repo_root / config.parent.relative_to(wt_path)
        )
        old_worktree = (old_dir / worktree).resolve()
        if not old_worktree.is_relative_to(plan.repo_root):
            console.error(f"nested repository worktree outside repository: {old_worktree}")
            sys.exit(1)
        new_worktree = wt_path / old_worktree.relative_to(plan.repo_root)
        _git.run("config", "--file", str(config), "core.worktree", os.path.relpath(new_worktree, config.parent))


def _configure_bare(bare: Path) -> None:
    _git.run("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*", dir=bare)
    _git.run("config", "core.logallrefupdates", "true", dir=bare)
    with suppress(_git.GitError):
        _git.run("config", "worktree.useRelativePaths", "true", dir=bare)


def _apply_remotes(bare: Path, remotes: list[_Remote]) -> None:
    # Remove all existing remotes, re-add from captured state
    try:
        existing = _git.query_lines("remote", dir=bare)
    except _git.GitError:
        existing = []

    for name in existing:
        with suppress(_git.GitError):
            _git.run("remote", "remove", name, dir=bare)

    for r in remotes:
        if not r.url:
            continue
        with suppress(_git.GitError):
            _git.run("remote", "add", r.name, r.url, dir=bare)
        for spec in r.fetch_specs:
            with suppress(_git.GitError):
                _git.run("config", "--add", f"remote.{r.name}.fetch", spec, dir=bare)


def _apply_configs(bare: Path, configs: list[_ConfigEntry]) -> None:
    for entry in configs:
        for val in entry.values:
            with suppress(_git.GitError):
                _git.run("config", "--add", entry.key, val, dir=bare)


def _cleanup_local_branch_refs(bare: Path) -> None:
    """Remove local branch refs that exactly match a remote ref (by OID)."""
    try:
        local_refs = _git.query_lines(
            "for-each-ref",
            "--format=%(refname:short) %(objectname)",
            "refs/heads/",
            dir=bare,
        )
        remote_oids: dict[str, str] = {}
        remote_refs = _git.query_lines(
            "for-each-ref",
            "--format=%(refname:short) %(objectname)",
            "refs/remotes/",
            dir=bare,
        )
        for line in remote_refs:
            parts = line.split()
            if len(parts) == 2:
                name = parts[0].split("/", 1)[-1]  # strip remote/ prefix
                remote_oids[name] = parts[1]

        for line in local_refs:
            parts = line.split()
            if len(parts) != 2:
                continue
            branch, oid = parts
            if remote_oids.get(branch) == oid:
                with suppress(_git.GitError):
                    _git.run("branch", "-D", branch, dir=bare)
    except _git.GitError:
        pass


def _create_migration_worktrees(plan: _Plan, new_dir: Path, *, fast: bool = False) -> None:
    bare = new_dir / ".bare"

    def _create(branch: str) -> None:
        wt_path = new_dir / branch
        source = _resolve_source_ref(plan, bare, branch)
        options = ["--no-checkout"] if fast and branch == plan.current_branch else []
        try:
            if source and source != branch:
                _git.run("worktree", "add", *options, "-B", branch, str(wt_path), source, dir=bare)
            else:
                _git.run("worktree", "add", *options, branch, str(wt_path), dir=bare)
        except _git.GitError:
            with suppress(_git.GitError):
                _git.run("worktree", "add", *options, "-b", branch, str(wt_path), dir=bare)
        _fsutil.relativize_worktree_gitdir(wt_path)

    if plan.default_branch == plan.current_branch:
        _create(plan.current_branch)
    else:
        _create(plan.default_branch)
        _create(plan.current_branch)


def _resolve_source_ref(plan: _Plan, bare: Path, branch: str) -> str | None:
    # Try local ref
    if _git.query_ok("rev-parse", "--verify", f"refs/heads/{branch}", dir=bare):
        return f"refs/heads/{branch}"
    # Try preferred remote
    preferred = f"{plan.default_remote}/{branch}"
    if _git.query_ok("rev-parse", "--verify", f"refs/remotes/{preferred}", dir=bare):
        return preferred
    # Try any remote
    try:
        remotes = _git.query_lines("remote", dir=bare)
        for r in remotes:
            ref = f"refs/remotes/{r}/{branch}"
            if _git.query_ok("rev-parse", "--verify", ref, dir=bare):
                return f"{r}/{branch}"
    except _git.GitError:
        pass
    return None


# ---------------------------------------------------------------------------
# Finalize (atomic swap)
# ---------------------------------------------------------------------------


def _fast_recovery_notice(plan: _Plan, new_dir: Path, temp_backup: Path) -> str:
    root = plan.repo_root
    partial = new_dir / plan.current_branch
    recovery = (
        f"find {shlex.quote(str(partial))} -mindepth 1 -maxdepth 1 ! -name .git "
        f"-exec mv -i -- {{}} {shlex.quote(str(root) + '/')} \\;"
    )
    return (
        "Fast migration recovery locations (keep until migration completes):\n"
        f"  Original root: {root}\n"
        f"  Working files: {partial} (later {root / plan.current_branch})\n"
        f"  Original Git metadata: {root / '.git'} (later {temp_backup / '.git'})\n"
        f"  New Git metadata: {new_dir / '.bare'} (later {root / '.bare'})\n"
        "If interrupted during the initial content moves, before Git metadata changes,\n"
        "move the partial contents back, including dotfiles but excluding the generated .git:\n"
        f"  {recovery}\n"
        "For later failures, inspect all locations with ls -la first; the index and\n"
        "submodule metadata may also have moved. No automatic rollback is performed."
    )


def _finalize_fast(plan: _Plan, new_dir: Path, temp_backup: Path) -> None:
    """Adopt original files with renames, preserving the root inode, without rollback."""
    root = plan.repo_root
    if root.stat().st_dev != new_dir.stat().st_dev:
        console.error("--fast requires the repository and staging directory on the same filesystem")
        sys.exit(1)
    wt_path = new_dir / plan.current_branch
    console.info("Moving original working directory (--fast, no rollback)...")
    for item in list(root.iterdir()):
        if item.name != ".git":
            item.rename(wt_path / item.name)

    _restore_nested_repos(plan, wt_path, move=True)
    old_index = root / ".git" / "index"
    if old_index.exists():
        admin = Path(_git.query("rev-parse", "--absolute-git-dir", dir=wt_path))
        old_index.rename(admin / "index")

    temp_backup.mkdir()
    (root / ".git").rename(temp_backup / ".git")
    for item in list(new_dir.iterdir()):
        item.rename(root / item.name)
    _repair_worktree_paths(root)
    _git.query("rev-parse", "--show-toplevel", dir=root / plan.current_branch)
    new_dir.rmdir()
    shutil.rmtree(temp_backup)


def _finalize(plan: _Plan, new_dir: Path, temp_backup: Path) -> None:
    root = plan.repo_root

    # Move old repo contents to backup
    moved_to_backup: list[str] = []
    for item in root.iterdir():
        dest = temp_backup / item.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item), str(dest))
        moved_to_backup.append(item.name)

    # Move new structure into place
    moved_to_root: list[str] = []
    try:
        for item in new_dir.iterdir():
            dest = root / item.name
            shutil.move(str(item), str(dest))
            moved_to_root.append(item.name)
    except Exception as exc:
        # Rollback
        console.error(f"finalization failed: {exc} — attempting rollback")
        for name in reversed(moved_to_root):
            src = root / name
            dst = new_dir / name
            if src.exists():
                shutil.move(str(src), str(dst))
        for name in reversed(moved_to_backup):
            src = temp_backup / name
            dst = root / name
            if src.exists():
                shutil.move(str(src), str(dst))
        raise

    # Validate new layout
    if not (root / ".git").is_file() or not (root / ".bare").is_dir():
        console.error("new layout validation failed — restoring from backup")
        for name in reversed(moved_to_root):
            src = root / name
            if src.exists():
                shutil.move(str(src), str(new_dir / name))
        for name in reversed(moved_to_backup):
            src = temp_backup / name
            if src.exists():
                shutil.move(str(src), str(root / name))
        sys.exit(1)

    # Repair worktree absolute paths that may point to the old new_dir location.
    # (git worktree.useRelativePaths handles this on newer git; this is the fallback.)
    _repair_worktree_paths(root)

    # Cleanup
    if new_dir.exists():
        shutil.rmtree(str(new_dir), ignore_errors=True)
    if temp_backup.exists():
        shutil.rmtree(str(temp_backup), ignore_errors=True)


def _repair_worktree_paths(root: Path) -> None:
    """Fix gitdir pointers in worktree admin records after an atomic move."""
    bare = root / ".bare"
    worktrees_dir = bare / "worktrees"
    if not worktrees_dir.exists():
        return
    for wt_admin in worktrees_dir.iterdir():
        if not wt_admin.is_dir():
            continue
        pointer = Path((wt_admin / "gitdir").read_text().strip())
        if not pointer.is_absolute() and (wt_admin / pointer).is_file():
            continue
        new_wt_path = root / wt_admin.name
        if not new_wt_path.is_dir():
            continue
        # Write absolute paths first so relativize_worktree_gitdir can find the admin dir.
        (wt_admin / "gitdir").write_text(str(new_wt_path / ".git") + "\n")
        (new_wt_path / ".git").write_text(f"gitdir: {wt_admin}\n")
        _fsutil.relativize_worktree_gitdir(new_wt_path)


# ---------------------------------------------------------------------------
# Cleanup context manager
# ---------------------------------------------------------------------------


@contextmanager
def _cleanup_guard(new_dir: Path, temp_backup: Path, *, preserve_on_error: bool = False):
    success = False
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _cleanup(signum, frame):
        _do_cleanup()
        sys.exit(1)

    def _do_cleanup():
        if preserve_on_error:
            console.error(
                f"Fast migration did not complete; no rollback performed. Inspect {new_dir} and {temp_backup} as well as the repository; original files may be split between them. No failure cleanup was performed."
            )
            return
        if new_dir.exists():
            shutil.rmtree(str(new_dir), ignore_errors=True)
        if temp_backup.exists():
            shutil.rmtree(str(temp_backup), ignore_errors=True)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        yield
        success = True
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)
        if not success:
            _do_cleanup()


# ---------------------------------------------------------------------------
# Post-migration output
# ---------------------------------------------------------------------------


def _show_result(plan: _Plan) -> None:
    console.print()
    console.success("Migration complete!")
    console.print()

    # Layout diagram
    console.print(console.bold(plan.repo_name + "/"))
    console.print("  ├── ./.bare   git database")
    console.print("  ├── ./.git    gitdir: ./.bare")
    console.print(f"  ├── {console.accent(plan.default_branch + '/')}   default branch worktree")
    if plan.current_branch != plan.default_branch:
        console.print(f"  └── {console.accent(plan.current_branch + '/')}   current branch worktree")

    console.print()
    console.print(console.subtle("Next steps:"))
    console.print(f"  cd {plan.repo_name}/{plan.current_branch}")
    console.print("  git wt add <branch-name> <branch-name>   add more worktrees")
    if plan.stash_count:
        console.print(f"  {console.accent('git stash list')}  view migrated stashes")
