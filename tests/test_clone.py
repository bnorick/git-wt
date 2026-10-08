"""Tests for git wt clone."""

from __future__ import annotations

import shutil

from conftest import (
    assert_bare_layout,
    assert_worktree_gitdir_relative,
    git,
    linked_worktree_count,
    make_std_repo,
)


def test_clone_creates_bare_structure(wt, tmp_path):
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "myrepo"
    wt("clone", str(origin), str(target))
    assert_bare_layout(target)


def test_clone_git_file_points_to_bare(wt, tmp_path):
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "myrepo"
    wt("clone", str(origin), str(target))
    git_file = target / ".git"
    assert git_file.is_file()
    content = git_file.read_text()
    assert ".bare" in content


def test_clone_creates_main_worktree(wt, tmp_path):
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "myrepo"
    wt("clone", str(origin), str(target))
    # Should have a worktree for the default branch (main)
    bare = target / ".bare"
    assert linked_worktree_count(bare) >= 1


def test_clone_target_dir_inferred_from_url(wt, tmp_path):
    # Put the source in a subdirectory so the inferred clone target doesn't collide
    src = tmp_path / "sources"
    origin = make_std_repo(src / "myproject")
    wt("clone", str(origin), cwd=tmp_path)
    # Should create a directory named "myproject" (stem of the URL)
    assert (tmp_path / "myproject").is_dir()
    assert_bare_layout(tmp_path / "myproject")


def test_clone_fails_when_target_exists(wt, tmp_path):
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "exists"
    target.mkdir()
    r = wt("clone", str(origin), str(target), check=False)
    assert r.returncode != 0


def test_clone_messages_to_stderr(wt, tmp_path):
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "myrepo"
    r = wt("clone", str(origin), str(target))
    # Progress messages should go to stderr, not stdout
    assert r.stdout.strip() == "" or "Cloned" not in r.stdout
    assert len(r.stderr) > 0


def test_clone_fails_without_repository_argument(wt, tmp_path):
    """clone exits non-zero when called with no arguments."""
    r = wt("clone", cwd=tmp_path, check=False)
    assert r.returncode != 0


def test_clone_worktree_uses_relative_gitdir_paths(wt, tmp_path):
    """After clone, the initial worktree's gitdir pointers are relative."""
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "myrepo"
    wt("clone", str(origin), str(target))
    worktree_dirs = [d for d in target.iterdir() if d.is_dir() and not d.name.startswith(".")]
    assert worktree_dirs, "clone should create at least one worktree directory"
    for wt_dir in worktree_dirs:
        assert_worktree_gitdir_relative(wt_dir)


def test_clone_repo_functional_after_move(wt, tmp_path):
    """A cloned repo with relative gitdir paths remains functional after being moved."""
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "myrepo"
    wt("clone", str(origin), str(target))

    moved = tmp_path / "moved-repo"
    shutil.move(str(target), str(moved))

    worktree_dirs = [d for d in moved.iterdir() if d.is_dir() and not d.name.startswith(".")]
    assert worktree_dirs
    result = git("status", cwd=worktree_dirs[0], check=False)
    assert result.returncode == 0, f"git status failed in moved repo: {result.stderr}"


def test_clone_hints_show_structure(wt, tmp_path):
    """Post-clone output mentions .bare, .git, and next steps with 'git wt add'."""
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "clone-ui"
    r = wt("clone", str(origin), str(target))

    combined = r.stdout + r.stderr
    assert "clone-ui/.bare" in combined
    assert "clone-ui/.git" in combined
    assert "cd clone-ui" in combined
    assert "git wt add" in combined
