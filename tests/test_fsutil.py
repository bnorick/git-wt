"""Unit tests for _fsutil.relativize_worktree_gitdir."""

from __future__ import annotations

from pathlib import Path

from git_wt._fsutil import relativize_worktree_gitdir


def _make_worktree_structure(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a minimal fake worktree structure with absolute gitdir pointers.

    Returns (wt_path, admin_path, dot_git_path).
    """
    admin = tmp_path / ".bare" / "worktrees" / "main"
    admin.mkdir(parents=True)
    wt = tmp_path / "main"
    wt.mkdir()
    dot_git = wt / ".git"
    dot_git.write_text(f"gitdir: {admin}\n")
    (admin / "gitdir").write_text(str(dot_git) + "\n")
    return wt, admin, dot_git


class TestRelativizeWorktreeGitdir:
    def test_rewrites_absolute_dot_git_to_relative(self, tmp_path):
        wt, _admin, dot_git = _make_worktree_structure(tmp_path)
        relativize_worktree_gitdir(wt)
        raw = dot_git.read_text().strip()[len("gitdir:") :].strip()
        assert not Path(raw).is_absolute()

    def test_rewrites_absolute_admin_gitdir_to_relative(self, tmp_path):
        wt, admin, _ = _make_worktree_structure(tmp_path)
        relativize_worktree_gitdir(wt)
        raw = (admin / "gitdir").read_text().strip()
        assert not Path(raw).is_absolute()

    def test_relative_path_in_dot_git_resolves_to_admin(self, tmp_path):
        wt, admin, dot_git = _make_worktree_structure(tmp_path)
        relativize_worktree_gitdir(wt)
        raw = dot_git.read_text().strip()[len("gitdir:") :].strip()
        assert (wt / raw).resolve() == admin.resolve()

    def test_relative_path_in_admin_gitdir_resolves_to_dot_git(self, tmp_path):
        wt, admin, dot_git = _make_worktree_structure(tmp_path)
        relativize_worktree_gitdir(wt)
        raw = (admin / "gitdir").read_text().strip()
        # admin gitdir is relative to the admin directory itself
        assert (admin / raw).resolve() == dot_git.resolve()

    def test_noop_when_already_relative(self, tmp_path):
        wt, admin, dot_git = _make_worktree_structure(tmp_path)
        # Pre-write relative paths
        rel_admin = admin.relative_to(wt, walk_up=True)
        dot_git.write_text(f"gitdir: {rel_admin}\n")
        original = dot_git.read_text()
        relativize_worktree_gitdir(wt)
        # dot_git unchanged because the guard (is_absolute) short-circuits
        assert dot_git.read_text() == original

    def test_noop_when_dot_git_missing(self, tmp_path):
        wt = tmp_path / "main"
        wt.mkdir()
        relativize_worktree_gitdir(wt)  # should not raise

    def test_noop_when_dot_git_is_directory(self, tmp_path):
        wt = tmp_path / "repo"
        wt.mkdir()
        (wt / ".git").mkdir()
        relativize_worktree_gitdir(wt)  # should not raise

    def test_noop_when_dot_git_has_no_gitdir_prefix(self, tmp_path):
        wt = tmp_path / "main"
        wt.mkdir()
        (wt / ".git").write_text("not a gitdir pointer\n")
        relativize_worktree_gitdir(wt)  # should not raise
