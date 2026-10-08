# Application-layout module.
"""Fetch all remotes and pull worktrees for the default branch (and optionally an extra branch)."""

from __future__ import annotations

import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from git_wt import _git, _worktree, console


def _fuzzy_match(query: str, text: str) -> bool:
    """All chars of query appear in order in text (case-insensitive)."""
    it = iter(text.lower())
    return all(c in it for c in query.lower())


def _dirty_lines(path: Path) -> list[str]:
    # Rstrip '\r' per-line to handle CRLF output (WSL git), preserving the
    # leading XY-status columns needed for the [3:] filename slice.
    # Untracked files (??) are excluded: git reset --hard doesn't remove them,
    # so they're not relevant to the "will discard" warning. If an untracked
    # file conflicts with an incoming tracked file, the reset itself will error
    # with a descriptive message.
    return [
        line.rstrip("\r")
        for line in _git.query("status", "--porcelain", dir=path).splitlines()
        if line.strip() and not line.startswith("??")
    ]


class _DirtyWorktreeError(RuntimeError):
    """Raised when a force-reset is required but --force was not passed."""

    def __init__(self, path: Path, dirty_files: list[str]) -> None:
        super().__init__(f"pull failed for {path}: non-fast-forward and worktree has uncommitted changes")
        self.dirty_files = dirty_files


@dataclass
class _ForceResetPlan:
    dirty_files: list[str]
    unmirrored_commits: int = 0


def _pull_or_safe_reset(path: Path, write, force: bool = False) -> _ForceResetPlan | None:
    """Pull with --ff-only; if that fails and the reset is provably safe, signal the caller.

    Returns None when the pull completed (ff succeeded, or clean reset with no dirty files).
    Returns a reset plan when force=True and a hard-reset would discard changes;
    the caller is responsible for confirming with the user and then calling _do_force_reset.
    Raises _DirtyWorktreeError when force=False and dirty files would be lost.
    Raises RuntimeError when local commits are not mirrored upstream and force=False.
    """
    try:
        write(_git.query_combined("pull", "--ff-only", dir=path))
        return None
    except _git.GitError:
        pass

    # Fast-forward failed (likely a force-push/rebase). Check whether local
    # commits would be discarded. git cherry compares patch content, so rebased
    # equivalent commits show as '-' while changed or local-only commits show as '+'.
    cherry = _git.query_combined("cherry", "@{u}", dir=path)
    unmirrored = [line for line in cherry.splitlines() if line.startswith("+")]
    if unmirrored and not force:
        raise RuntimeError(f"pull failed for {path}: {len(unmirrored)} local commit(s) not mirrored upstream")

    # 2. Uncommitted changes in the worktree.
    lines = _dirty_lines(path)
    if lines:
        dirty_files = [line[3:] for line in lines]
        if not force:
            raise _DirtyWorktreeError(path, dirty_files)
        return _ForceResetPlan(
            dirty_files=dirty_files,
            unmirrored_commits=len(unmirrored),
        )  # caller must confirm, then call _do_force_reset

    if unmirrored:
        return _ForceResetPlan(dirty_files=[], unmirrored_commits=len(unmirrored))

    write(_git.query_combined("reset", "--hard", "@{u}", dir=path))
    return None


def _do_force_reset(path: Path, write) -> None:
    write(_git.query_combined("reset", "--hard", "@{u}", dir=path))


def _confirm_force_reset(branch: str, worktree_rel: str, plan: _ForceResetPlan) -> bool:
    """Show what will be discarded and ask for confirmation. Returns True if user confirms.

    In non-interactive mode (piped/scripted), EOF auto-confirms dirty-file-only
    resets so that existing --force usage in scripts keeps working unchanged.
    Local commits require typing "force" explicitly because they will be lost.
    """
    discarded: list[str] = []
    if plan.unmirrored_commits:
        noun = "commit" if plan.unmirrored_commits == 1 else "commits"
        discarded.append(f"{plan.unmirrored_commits} local {noun} not mirrored upstream")
    if plan.dirty_files:
        discarded.append("uncommitted changes")

    console.warn(
        f"Force-resetting {console.accent(branch)} "
        f"({console.path_style(worktree_rel)}) will discard "
        f"{' and '.join(discarded)}:"
    )
    for f in plan.dirty_files:
        console.print(f"  {console.red('−')} {f}")

    if plan.unmirrored_commits:
        backup_branch = f"backup/{branch}"
        console.hint(f"create a backup first with `git branch {backup_branch} HEAD` before overwriting local commits")
        return console.prompt_dangerous(
            f"Type 'force' to overwrite and lose local commits on {console.accent(branch)}",
            "force",
        )

    noun = "these changes" if len(plan.dirty_files) > 1 else "this change"
    return console.confirm(
        f"Discard {noun} and force-reset {console.accent(branch)}?",
        eof_default=not console.is_interactive(),
    )


def run(branch: str = "", force: bool = False) -> None:
    try:
        remote = _worktree.default_remote()
    except Exception:
        remote = "origin"

    root = _worktree.bare_root()

    def _rel(path: str) -> str:
        try:
            return str(Path(path).relative_to(root.parent))
        except ValueError:
            return path

    default_path: list[str] = []
    default_branch: list[str] = []
    extra_path: list[str] = []
    resolved_branch: list[str] = []
    current_wt_path: list[str] = []
    current_wt_branch: list[str] = []

    def _fetch(write):
        _git.run("fetch", "--all", "--prune", "--prune-tags", "--progress")

    def _resolve_worktrees(write):
        entries = _worktree.list_worktrees()

        target = _worktree.default_branch(remote)
        default_match = next((e for e in entries if e.branch == target), None)
        if default_match is None:
            available = ", ".join(e.branch or e.path for e in entries)
            raise RuntimeError(f"no worktree for default branch {target!r}. Available: {available}")
        default_path.append(default_match.path)
        default_branch.append(default_match.branch)

        if branch:
            extra_match = next((e for e in entries if e.branch == branch), None)
            if extra_match is None:
                fuzzy = [e for e in entries if e.branch and _fuzzy_match(branch, e.branch)]
                if len(fuzzy) == 1:
                    extra_match = fuzzy[0]
                elif len(fuzzy) > 1:
                    names = ", ".join(e.branch for e in fuzzy)
                    raise RuntimeError(f"{branch!r} matches multiple branches: {names}")
                else:
                    available = ", ".join(e.branch or e.path for e in entries)
                    raise RuntimeError(f"no worktree for branch {branch!r}. Available: {available}")
            extra_path.append(extra_match.path)
            resolved_branch.append(extra_match.branch)

        # Auto-detect the current worktree and include it if it's not already covered.
        with suppress(Exception):
            cwd_root = _worktree.current_root()
            cur_match = next(
                (e for e in entries if Path(e.path).resolve() == cwd_root.resolve()),
                None,
            )
            if (
                cur_match is not None
                and cur_match.branch
                and cur_match.path != default_match.path
                and (not extra_path or cur_match.path != extra_path[-1])
            ):
                current_wt_path.append(cur_match.path)
                current_wt_branch.append(cur_match.branch)

    # Phase 1: fetch and resolve worktrees
    try:
        console.run_steps(
            [
                console.Step("Fetching from all remotes", raw_output=True, run=_fetch),
                console.Step("Resolving worktree details", run=_resolve_worktrees),
            ]
        )
    except RuntimeError as exc:
        console.error(str(exc))
        sys.exit(1)
    except _git.GitError as exc:
        console.error(str(exc))
        sys.exit(1)

    # Phase 2: try ff pull for each worktree; collect those that need force-reset.
    # _pull_or_safe_reset returns a list of dirty filenames instead of discarding
    # them when confirmation is required — including the case where --ff-only fails
    # due to dirty conflicting files even though HEAD is topologically an ancestor
    # of @{u} (which a pre-flight check cannot detect without running the pull).
    default_needs_force: list[_ForceResetPlan] = []
    extra_needs_force: list[_ForceResetPlan] = []
    current_wt_needs_force: list[_ForceResetPlan] = []

    def _pull_default(write):
        if not default_path:
            return
        result = _pull_or_safe_reset(Path(default_path[-1]), write, force=force)
        if result is not None:
            default_needs_force.append(result)

    def _pull_extra(write):
        if not extra_path:
            return
        result = _pull_or_safe_reset(Path(extra_path[-1]), write, force=force)
        if result is not None:
            extra_needs_force.append(result)

    def _pull_current_wt(write):
        if not current_wt_path:
            return
        result = _pull_or_safe_reset(Path(current_wt_path[-1]), write, force=force)
        if result is not None:
            current_wt_needs_force.append(result)

    pull_steps = [
        console.Step(
            lambda: (
                f"Pulling {console.accent(default_branch[-1])} for worktree {console.path_style(_rel(default_path[-1]))}"
            ),
            show_output=True,
            run=_pull_default,
        ),
    ]
    if branch:
        pull_steps.append(
            console.Step(
                lambda: (
                    f"Pulling {console.accent(resolved_branch[-1])} for worktree {console.path_style(_rel(extra_path[-1]))}"
                ),
                show_output=True,
                run=_pull_extra,
            )
        )
    if current_wt_path:
        pull_steps.append(
            console.Step(
                lambda: (
                    f"Pulling {console.accent(current_wt_branch[-1])} for worktree {console.path_style(_rel(current_wt_path[-1]))}"
                ),
                show_output=True,
                run=_pull_current_wt,
            )
        )

    try:
        console.run_steps(pull_steps)
    except _DirtyWorktreeError as exc:
        console.error(str(exc))
        hint = ["there are files with uncommitted changes"]
        shown = exc.dirty_files[:5]
        hint_files_indent = " " * (len("hint: ") + 2)
        for f in shown:
            hint.append(f"{hint_files_indent}{f}")
        remaining = len(exc.dirty_files) - len(shown)
        if remaining > 0:
            hint.append(f"{hint_files_indent}... and {remaining} more file{'s' if remaining != 1 else ''}")
        hint.append("\nuse `git wt u --force` to discard changes and force-reset")
        console.hint("\n".join(hint))
        sys.exit(1)
    except RuntimeError as exc:
        console.error(str(exc))
        sys.exit(1)
    except _git.GitError as exc:
        console.error(str(exc))
        sys.exit(1)

    # Phase 3: confirm and force-reset worktrees that need it.
    # Confirmation happens here, outside run_steps, so it never competes with a spinner.
    # Each worktree is confirmed independently — declining one doesn't skip the other.
    # Non-interactive (scripts/CI): EOF auto-confirms so --force keeps working unchanged.
    force_steps = []

    if default_needs_force:
        if _confirm_force_reset(default_branch[-1], _rel(default_path[-1]), default_needs_force[-1]):
            _path = default_path[-1]
            force_steps.append(
                console.Step(
                    lambda: (
                        f"Force-resetting {console.accent(default_branch[-1])} for worktree {console.path_style(_rel(default_path[-1]))}"
                    ),
                    show_output=True,
                    run=lambda w, p=_path: _do_force_reset(Path(p), w),
                )
            )
        else:
            console.info(f"Skipping {console.accent(default_branch[-1])}.")

    if extra_needs_force:
        if _confirm_force_reset(resolved_branch[-1], _rel(extra_path[-1]), extra_needs_force[-1]):
            _path = extra_path[-1]
            force_steps.append(
                console.Step(
                    lambda: (
                        f"Force-resetting {console.accent(resolved_branch[-1])} for worktree {console.path_style(_rel(extra_path[-1]))}"
                    ),
                    show_output=True,
                    run=lambda w, p=_path: _do_force_reset(Path(p), w),
                )
            )
        else:
            console.info(f"Skipping {console.accent(resolved_branch[-1])}.")

    if current_wt_needs_force:
        if _confirm_force_reset(current_wt_branch[-1], _rel(current_wt_path[-1]), current_wt_needs_force[-1]):
            _path = current_wt_path[-1]
            force_steps.append(
                console.Step(
                    lambda: (
                        f"Force-resetting {console.accent(current_wt_branch[-1])} for worktree {console.path_style(_rel(current_wt_path[-1]))}"
                    ),
                    show_output=True,
                    run=lambda w, p=_path: _do_force_reset(Path(p), w),
                )
            )
        else:
            console.info(f"Skipping {console.accent(current_wt_branch[-1])}.")

    if not force_steps:
        return

    try:
        console.run_steps(force_steps)
    except RuntimeError as exc:
        console.error(str(exc))
        sys.exit(1)
    except _git.GitError as exc:
        console.error(str(exc))
        sys.exit(1)
