"""Tests for git wt switch."""

from __future__ import annotations

from conftest import create_branch, create_worktree


def test_switch_prints_path(wt, bare_repo):
    create_branch(bare_repo, "feature")
    create_worktree(bare_repo, "feature")
    r = wt("switch", cwd=bare_repo / "main", select=str(bare_repo / "feature"))
    assert r.stdout.strip() == str(bare_repo / "feature")
    assert r.returncode == 0


def test_switch_cancelled_exits_nonzero(wt, bare_repo):
    """When GIT_WT_SELECT is empty and no TTY, picker returns nothing → exit 1."""
    r = wt("switch", cwd=bare_repo / "main", select="", check=False)
    assert r.returncode != 0


def test_switch_selects_by_value(wt, bare_repo):
    """GIT_WT_SELECT matches on the item value (path)."""
    create_branch(bare_repo, "branchA")
    create_worktree(bare_repo, "branchA")
    r = wt("switch", cwd=bare_repo / "main", select=str(bare_repo / "branchA"))
    assert r.stdout.strip() == str(bare_repo / "branchA")


def test_switch_no_worktrees_stdout_empty(wt, tmp_path):
    """When no checked-out worktrees exist, stdout is empty and stderr says so."""
    import shutil

    from conftest import git, make_std_repo

    # Bare layout with no checked-out worktrees
    src = make_std_repo(tmp_path / "src")
    repo = tmp_path / "repo"
    repo.mkdir()
    bare = repo / ".bare"
    git("clone", "--bare", str(src), str(bare))
    git("config", "core.bare", "false", cwd=bare)
    (repo / ".git").write_text("gitdir: ./.bare\n")
    shutil.rmtree(str(src))

    r = wt("switch", cwd=repo, check=False)
    assert r.stdout.strip() == ""
    assert "No worktrees" in r.stderr


def test_switch_with_multiple_worktrees(wt, bare_repo):
    for branch in ("featA", "featB"):
        create_branch(bare_repo, branch)
        create_worktree(bare_repo, branch)
    r = wt("switch", cwd=bare_repo / "main", select=str(bare_repo / "featB"))
    assert r.stdout.strip() == str(bare_repo / "featB")
