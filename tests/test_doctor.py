"""Tests for git wt doctor."""

from __future__ import annotations

from conftest import create_branch, create_worktree


def test_doctor_bare_layout_healthy(wt, bare_repo):
    r = wt("doctor", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert "ok" in r.stderr


def test_doctor_detects_bare_layout(wt, bare_repo):
    r = wt("doctor", cwd=bare_repo / "main")
    assert "bare" in r.stderr.lower()


def test_doctor_detects_standard_layout(wt, std_repo):
    r = wt("doctor", cwd=std_repo, check=False)
    # Standard layout should be flagged as warn
    assert "standard" in r.stderr.lower() or "migrate" in r.stderr.lower()


def test_doctor_from_subdirectory(wt, bare_repo):
    """Doctor should work from any subdirectory inside a worktree."""
    subdir = bare_repo / "main" / "subdir"
    subdir.mkdir()
    r = wt("doctor", cwd=subdir)
    assert r.returncode == 0


def test_doctor_lists_all_worktrees(wt, bare_repo):
    create_branch(bare_repo, "feature")
    create_worktree(bare_repo, "feature")
    r = wt("doctor", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert "feature" in r.stderr


def test_doctor_exit_code_errors(wt, tmp_path):
    """Doctor in a non-git dir exits non-zero."""
    r = wt("doctor", cwd=tmp_path, check=False)
    assert r.returncode != 0


def test_doctor_from_bare_root(wt, bare_repo):
    """Doctor works when run from the bare repo root (not inside a worktree)."""
    r = wt("doctor", cwd=bare_repo)
    assert r.returncode == 0
    assert "Repository" in r.stderr
    # Path to the repo root appears in output
    assert str(bare_repo) in r.stderr
    assert ".bare directory" in r.stderr


def test_doctor_default_remote_capitalized(wt, bare_repo_with_remote):
    """The default remote check uses 'Default remote' (capitalized)."""
    repo, _origin = bare_repo_with_remote
    r = wt("doctor", cwd=repo / "main")
    assert r.returncode == 0
    assert "Default remote" in r.stderr


def test_doctor_standard_layout_migration_readiness(wt, std_repo):
    """Standard git repo shows 'standard git layout' and 'Migration readiness'."""
    r = wt("doctor", cwd=std_repo, check=False)
    assert "standard git layout" in r.stderr
    assert "Migration readiness" in r.stderr


def test_doctor_migration_blockers_nonzero(wt, std_repo):
    """Doctor exits non-zero when there are migration blockers (linked worktrees)."""
    from conftest import git

    # Add a linked worktree to create a blocker
    other = std_repo.parent / "other-wt"
    git("worktree", "add", str(other), "-b", "feature-blocker", cwd=std_repo, check=False)

    r = wt("doctor", cwd=std_repo, check=False)
    assert r.returncode != 0
    assert "linked worktrees" in r.stderr
