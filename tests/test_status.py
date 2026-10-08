"""Tests for git wt status."""

from __future__ import annotations

from conftest import create_branch, create_worktree


def test_status_shows_worktrees(wt, bare_repo):
    r = wt("status", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert "main" in r.stderr


def test_status_shows_clean(wt, bare_repo):
    r = wt("status", cwd=bare_repo / "main")
    assert "clean" in r.stderr


def test_status_shows_dirty(wt, bare_repo):
    # Create an uncommitted change
    (bare_repo / "main" / "newfile.txt").write_text("dirty\n")
    r = wt("status", cwd=bare_repo / "main")
    assert "dirty" in r.stderr


def test_status_multiple_worktrees(wt, bare_repo):
    create_branch(bare_repo, "featA")
    create_worktree(bare_repo, "featA")
    create_branch(bare_repo, "featB")
    create_worktree(bare_repo, "featB")

    r = wt("status", cwd=bare_repo / "main")
    assert "main" in r.stderr
    assert "featA" in r.stderr or "feat" in r.stderr


def test_status_summary_line(wt, bare_repo):
    r = wt("status", cwd=bare_repo / "main")
    assert "worktree" in r.stderr


def test_status_from_subdirectory(wt, bare_repo):
    subdir = bare_repo / "main" / "sub"
    subdir.mkdir()
    r = wt("status", cwd=subdir)
    assert r.returncode == 0


def test_status_detached_head(wt, bare_repo):
    """A detached-HEAD worktree shows 'detached HEAD' in the branch column."""
    from conftest import git

    ref = git("rev-parse", "HEAD", cwd=bare_repo / "main").stdout.strip()
    git("worktree", "add", "--detach", str(bare_repo / "detached-wt"), ref, cwd=bare_repo / ".bare")

    r = wt("status", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert "detached HEAD" in r.stderr


def test_status_error_count_in_summary(wt, bare_repo):
    """Stale worktree increments the error count in the summary line."""
    import shutil as _shutil

    create_branch(bare_repo, "stale-stat")
    wt_path = create_worktree(bare_repo, "stale-stat")
    _shutil.rmtree(str(wt_path))  # make it stale/error

    r = wt("status", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert "● error" in r.stderr
    # Summary line counts errors separately from clean/dirty
    assert "1 error" in r.stderr
    assert "0 dirty" in r.stderr


def test_status_fails_outside_git_repo(wt, tmp_path):
    """status exits non-zero when run outside any git repository."""
    r = wt("status", cwd=tmp_path, check=False)
    assert r.returncode != 0


def test_status_long_branch_name_not_truncated(wt, bare_repo):
    """A very long branch name is not truncated with '…' in the output."""
    long_branch = "feature-this-is-a-very-long-branch-name-for-status-output"
    create_branch(bare_repo, long_branch)
    create_worktree(bare_repo, long_branch)

    r = wt("status", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert long_branch in r.stderr
    assert "./" + long_branch in r.stderr
