"""Filesystem utilities with symlink and permission preservation."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def copy_dir(src: Path, dst: Path, excludes: tuple[str, ...] = ()) -> None:
    """Recursively copy src to dst, preserving symlinks and permissions.

    Skips any entry whose name or any path component is in excludes.
    dst may already exist. Replaces existing symlinks at destination.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for src_item in src.iterdir():
        if src_item.name in excludes:
            continue
        dst_item = dst / src_item.name
        if src_item.is_symlink():
            link_target = os.readlink(src_item)
            if dst_item.is_symlink() or dst_item.exists():
                dst_item.unlink()
            dst_item.symlink_to(link_target)
        elif src_item.is_dir():
            copy_dir(src_item, dst_item, excludes)
        else:
            shutil.copy2(str(src_item), str(dst_item))


def copy_file(src: Path, dst: Path) -> None:
    """Copy a single file, creating parent dirs and preserving metadata."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))


def copy_file_simple(src: Path, dst: Path) -> None:
    """Copy a file with permission preservation only (no mtime)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(src), str(dst))


def absolutize_worktree_gitdir(wt_path: Path) -> None:
    """Rewrite gitdir pointers to use absolute paths.

    Inverse of relativize_worktree_gitdir. git worktree remove requires the
    admin record's gitdir file to contain an absolute path to the working tree
    (at least on git < 2.35); relative paths cause a validation failure.
    Safe to call when paths are already absolute — the result is idempotent.
    """
    dot_git = wt_path / ".git"
    if not dot_git.is_file():
        return
    content = dot_git.read_text().strip()
    if not content.startswith("gitdir:"):
        return
    raw = content[len("gitdir:") :].strip()
    # pathlib propagates absolute paths (i.e., `path / abs_path == abs_path`),
    # so this handles both cases.
    admin_path = (wt_path / raw).resolve()
    if not admin_path.is_dir():
        return
    abs_dot_git = dot_git.resolve()
    dot_git.write_text(f"gitdir: {admin_path}\n")
    (admin_path / "gitdir").write_text(f"{abs_dot_git}\n")


def delete_worktree_admin(wt_path: Path, bare: Path) -> bool:
    """Delete the admin record for wt_path from bare/worktrees/.

    Safe alternative to `git worktree prune`, which is global and would
    incorrectly remove all worktrees when relative paths are in use.
    Returns True if the admin record was found and deleted.
    """
    worktrees_dir = bare / "worktrees"
    if not worktrees_dir.is_dir():
        return False
    target = (Path(wt_path) / ".git").resolve()
    for admin in worktrees_dir.iterdir():
        if not admin.is_dir():
            continue
        gitdir_file = admin / "gitdir"
        if not gitdir_file.is_file():
            continue
        content = gitdir_file.read_text().strip()
        candidate = Path(content) if Path(content).is_absolute() else admin / content
        if candidate.resolve() == target:
            shutil.rmtree(str(admin))
            return True
    return False


def relativize_worktree_gitdir(wt_path: Path) -> None:
    """Rewrite absolute gitdir pointers for a worktree to use relative paths.

    Git writes absolute paths in two files when it creates a worktree:
      - <wt_path>/.git            (points to the admin record in .bare/worktrees/)
      - <admin_record>/gitdir     (points back to <wt_path>/.git)

    Rewriting both as relative paths lets the entire repo root be moved or
    renamed without breaking worktree linkage (git's worktree.useRelativePaths
    config does the same but requires git >= 2.35).
    """
    dot_git = wt_path / ".git"
    if not dot_git.is_file():
        return
    content = dot_git.read_text().strip()
    if not content.startswith("gitdir:"):
        return
    admin_path = Path(content[len("gitdir:") :].strip())
    if not admin_path.is_absolute() or not admin_path.is_dir():
        return
    gitdir_file = admin_path / "gitdir"
    # Write admin record's gitdir relative to the admin directory itself.
    gitdir_file.write_text(f"{dot_git.relative_to(admin_path, walk_up=True)}\n")
    # Write worktree's .git back-pointer relative to the worktree dir.
    dot_git.write_text(f"gitdir: {admin_path.relative_to(wt_path, walk_up=True)}\n")
