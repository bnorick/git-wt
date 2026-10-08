# Application-layout module.
"""Remove worktrees with optional cleanup filters."""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from pathlib import Path

from git_wt import _fsutil, _git, _hooks, _picker, _worktree, console
from git_wt.preview import worktree_preview_cmd


@dataclass
class RemovalItem:
    entry: _worktree.Entry
    action: str = "remove"
    reason: str = ""


def run(
    worktrees: list[str],
    *,
    merged: bool,
    gone: bool,
    stale: bool,
    sweep: bool,
    delete_remote: bool,
    dry_run: bool,
    confirm_dangerous: bool = False,
) -> None:
    entries = _worktree.list_worktrees()

    try:
        root = _worktree.bare_root()
    except Exception:
        root = None

    use_filters = merged or gone or stale or sweep

    if sweep:
        merged = gone = stale = True

    if use_filters:
        candidates = _find_candidates(entries, merged=merged, gone=gone, stale=stale)
        if not candidates:
            console.info("No matching cleanup candidates found.")
            return
        to_remove = _pick_candidates(candidates, root)
        is_cleanup = True
    elif worktrees:
        to_remove = []
        for wt in worktrees:
            try:
                entry = _worktree.resolve(entries, wt, root)
            except ValueError as exc:
                msg = str(exc)
                if "ambiguous" in msg:
                    console.error(msg)
                else:
                    console.error(f"no worktree matching {wt!r}")
                    console.print("Available worktrees:")
                    for e in entries:
                        name = _worktree.workspace_name(e, root) if root else e.path
                        console.print(f"  {name}")
                sys.exit(1)
            to_remove.append(RemovalItem(entry=entry, action="remove"))
        is_cleanup = False
    else:
        # Interactive: multi-select from all worktrees
        items = [
            _picker.Item(
                value=e.path,
                label=_worktree.workspace_name(e, root) if root else e.path,
                desc=_worktree.workspace_name(e, root) if root else e.path,
            )
            for e in entries
        ]
        mode = "remove-remote" if delete_remote else "remove"
        exe = sys.argv[0]
        selected = _picker.run(
            _picker.PickerConfig(
                items=items,
                multi=True,
                prompt="worktree> ",
                header="Select worktrees to remove  (Space to select, Enter to confirm)",
                preview_cmd=worktree_preview_cmd(exe, mode),
            )
        )
        if not selected:
            return
        path_map = {e.path: e for e in entries}
        to_remove = [RemovalItem(entry=path_map[s.value], action="remove") for s in selected if s.value in path_map]
        is_cleanup = False

    if not to_remove:
        return

    # Show plan table
    _show_plan(to_remove, delete_remote=delete_remote, root=root)

    if dry_run:
        console.print(console.subtle("[DRY RUN] No changes made."))
        console.print(console.subtle("  Remote branches are preserved. remote branch deletion skipped."))
        return

    # Confirm
    if is_cleanup:
        confirmed = console.prompt_dangerous(
            f"Type {console.accent('cleanup')} to confirm removal of {len(to_remove)} worktree(s)",
            "cleanup",
        )
    elif delete_remote and len(to_remove) == 1:
        branch_name = to_remove[0].entry.branch or "remove"
        confirmed = console.prompt_dangerous(
            f"This will also delete the remote branch. Type {console.accent(repr(branch_name))} to confirm",
            branch_name,
        )
    elif confirm_dangerous and len(to_remove) == 1:
        branch_name = to_remove[0].entry.branch or "remove"
        confirmed = console.prompt_dangerous(
            f"Type {console.accent(repr(branch_name))} to confirm removal",
            branch_name,
        )
    elif confirm_dangerous:
        confirmed = console.prompt_dangerous(
            'Type "remove" to confirm removal',
            "remove",
        )
    elif len(to_remove) == 1 and not delete_remote:
        item = to_remove[0]
        name = _worktree.workspace_name(item.entry, root) if root else item.entry.path
        confirmed = console.confirm(f"Remove {console.accent(repr(name))} and delete local branch?")
    else:
        confirmed = console.confirm(f"Remove {len(to_remove)} worktree(s)?")

    if not confirmed:
        console.info("Aborted.")
        return

    # Execute
    ok = err = 0

    for item in to_remove:
        entry = item.entry
        name = _worktree.workspace_name(entry, root) if root else entry.path
        bare_root = root or Path.cwd()
        before_context = _hooks.HookContext(path=Path(entry.path), branch=entry.branch, bare_root=bare_root)
        before_hooks = _hooks.load("beforeremove", dir=bare_root)
        try:
            _hooks.run_to_stderr("beforeremove", before_context, before_hooks)
        except _hooks.HookError as exc:
            console.error(f"failed before removing worktree {name!r}: {exc}")
            err += 1
            continue

        try:
            if not Path(entry.path).exists():
                try:
                    _git.run("worktree", "remove", "--force", entry.path)
                except _git.GitError:
                    bare = _worktree.bare_root() / ".bare"
                    _fsutil.delete_worktree_admin(Path(entry.path), bare)
            else:
                # git worktree remove requires absolute paths in the gitdir
                # pointer files; relativize_worktree_gitdir may have made them
                # relative, so restore absolute paths before the removal.
                _fsutil.absolutize_worktree_gitdir(Path(entry.path))
                _git.run("worktree", "remove", "-f", entry.path)
            if entry.branch and not entry.detached and item.reason != "stale":
                with contextlib.suppress(_git.GitError):
                    _git.run("branch", "-D", entry.branch)
                if delete_remote and entry.branch:
                    # Use the branch's configured tracking remote, not default
                    try:
                        branch_remote = _git.query("config", f"branch.{entry.branch}.remote")
                    except _git.GitError:
                        try:
                            branch_remote = _worktree.default_remote()
                        except Exception:
                            branch_remote = "origin"
                    try:
                        has_remote = _git.query_ok("ls-remote", "--exit-code", branch_remote, entry.branch)
                        if has_remote:
                            _git.run("push", branch_remote, "--delete", entry.branch)
                    except _git.GitError:
                        pass
            console.success(f"removed {name}")
            ok += 1
            after_context = _hooks.HookContext(path=Path(entry.path), branch=entry.branch, bare_root=bare_root)
            after_hooks = _hooks.load("afterremove", dir=bare_root)
            try:
                _hooks.run_to_stderr("afterremove", after_context, after_hooks)
            except _hooks.HookError as exc:
                console.error(f"worktree {name!r} was removed, but {exc}")
                err += 1
        except _git.GitError as exc:
            console.error(f"failed to remove {name}: {exc}")
            err += 1

    parts = [f"{ok} removed"]
    if err:
        parts.append(f"{err} failed")
    console.info(console.subtle(" · ".join(parts)))


def _find_candidates(
    entries: list[_worktree.Entry],
    *,
    merged: bool,
    gone: bool,
    stale: bool,
) -> list[RemovalItem]:
    candidates: list[RemovalItem] = []

    try:
        remote = _worktree.default_remote()
        default_branch = _worktree.default_branch(remote)
    except Exception:
        remote = "origin"
        default_branch = "main"

    for entry in entries:
        if entry.branch == default_branch:
            continue

        if stale and not Path(entry.path).exists():
            candidates.append(RemovalItem(entry=entry, action="remove", reason="stale"))
            continue

        if gone and entry.branch:
            try:
                tracking = _git.query(
                    "for-each-ref",
                    "--format=%(upstream:track)",
                    f"refs/heads/{entry.branch}",
                )
                if "[gone]" in tracking:
                    candidates.append(RemovalItem(entry=entry, action="remove", reason="gone"))
                    continue
            except _git.GitError:
                pass

        if merged and entry.branch:
            # Skip branches with no upstream configured
            try:
                upstream = _git.query(
                    "for-each-ref",
                    "--format=%(upstream)",
                    f"refs/heads/{entry.branch}",
                )
                if not upstream.strip():
                    continue
            except _git.GitError:
                continue
            # Skip dirty worktrees
            if Path(entry.path).exists():
                try:
                    dirty_out = _git.query("status", "--porcelain=v1", dir=Path(entry.path))
                    if dirty_out.strip():
                        continue
                except _git.GitError:
                    pass
            try:
                _git.query("merge-base", "--is-ancestor", entry.branch, default_branch)
                candidates.append(RemovalItem(entry=entry, action="remove", reason="merged"))
            except _git.GitError:
                pass

    return candidates


def _pick_candidates(
    candidates: list[RemovalItem],
    root,
) -> list[RemovalItem]:
    items = [
        _picker.Item(
            value=c.entry.path,
            label=(_worktree.workspace_name(c.entry, root) if root else c.entry.path),
            desc=c.reason,
        )
        for c in candidates
    ]
    exe = sys.argv[0]
    selected = _picker.run(
        _picker.PickerConfig(
            items=items,
            multi=True,
            prompt="worktree> ",
            header="Select worktrees to clean up  (Space to select, Enter to confirm)",
            preview_cmd=worktree_preview_cmd(exe, "remove"),
        )
    )
    if not selected:
        return []
    selected_paths = {s.value for s in selected}
    return [c for c in candidates if c.entry.path in selected_paths]


def _show_plan(items: list[RemovalItem], *, delete_remote: bool, root) -> None:
    from git_wt.app.console import TableColumn, print_table

    rows = []
    for item in items:
        entry = item.entry
        name = _worktree.workspace_name(entry, root) if root else entry.path
        branch = entry.branch or console.subtle("(detached)")
        effect = "worktree + branch"
        if delete_remote and entry.branch:
            effect += " + remote"
        rows.append(
            [
                console.accent(item.action),
                name,
                branch,
                effect,
                item.reason or "",
            ]
        )

    print_table(
        [
            TableColumn("ACTION"),
            TableColumn("WORKTREE"),
            TableColumn("BRANCH"),
            TableColumn("EFFECT"),
            TableColumn("REASON"),
        ],
        rows,
    )
