"""Tests for git wt migrate."""

from __future__ import annotations

import shutil

from conftest import (
    _resolve_worktree_paths,
    assert_bare_layout,
    assert_worktree_gitdir_relative,
    git,
    linked_worktree_count,
    make_std_repo,
)


def test_migrate_dry_run_no_changes(wt, std_repo):
    r = wt("migrate", "--dry-run", cwd=std_repo, input="y\n")
    assert r.returncode == 0
    # .git should still be a directory (not converted)
    assert (std_repo / ".git").is_dir()


def test_migrate_converts_to_bare(wt, std_repo):
    wt("migrate", cwd=std_repo, input="y\n")
    assert_bare_layout(std_repo)


def test_migrate_creates_main_worktree(wt, std_repo):
    wt("migrate", cwd=std_repo, input="y\n")
    # Should have a worktree for the default branch
    bare = std_repo / ".bare"
    assert linked_worktree_count(bare) >= 1


def test_migrate_preserves_uncommitted_changes(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo")
    # Make an uncommitted change
    (repo / "modified.txt").write_text("modified content\n")
    git("add", "modified.txt", cwd=repo)

    wt("migrate", cwd=repo, input="y\n")

    bare = repo / ".bare"
    wt_paths = _resolve_worktree_paths(bare)
    wt_paths = [p for p in wt_paths if p != bare.resolve()]
    assert any((p / "modified.txt").exists() for p in wt_paths)


def test_migrate_creates_current_and_default_worktrees(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo")
    # Create and checkout a different branch from main
    git("checkout", "-b", "feature-work", cwd=repo)
    git("commit", "--allow-empty", "-m", "feature commit", cwd=repo)

    wt("migrate", cwd=repo, input="y\n")

    bare = repo / ".bare"
    assert linked_worktree_count(bare) >= 2


def test_migrate_worktrees_use_relative_gitdir_paths(wt, std_repo):
    """After migrate, all worktree gitdir pointers are relative."""
    wt("migrate", cwd=std_repo, input="y\n")
    # Discover worktree paths from the admin records (git-wt names admin dirs
    # after the worktree, e.g. .bare/worktrees/main -> std_repo/main).
    # Avoid parsing `git worktree list --porcelain` which echoes the gitdir
    # content verbatim (relative paths) rather than the resolved absolute path.
    wt_paths = [
        std_repo / d.name
        for d in (std_repo / ".bare" / "worktrees").iterdir()
        if d.is_dir() and (std_repo / d.name).is_dir()
    ]
    assert wt_paths
    for wt_path in wt_paths:
        assert_worktree_gitdir_relative(wt_path)


def test_migrate_repo_functional_after_move(wt, std_repo):
    """A migrated repo with relative gitdir paths remains functional after being moved."""
    wt("migrate", cwd=std_repo, input="y\n")

    moved = std_repo.parent / "moved-repo"
    shutil.move(str(std_repo), str(moved))

    worktree_dirs = [d for d in moved.iterdir() if d.is_dir() and not d.name.startswith(".")]
    assert worktree_dirs
    result = git("status", cwd=worktree_dirs[0], check=False)
    assert result.returncode == 0, f"git status failed in moved migrated repo: {result.stderr}"


def test_migrate_aborted_when_declined(wt, std_repo):
    """Saying 'n' to the confirmation keeps the repo as-is."""
    wt("migrate", cwd=std_repo, input="n\n")
    # .git should still be a directory
    assert (std_repo / ".git").is_dir()


def test_migrate_fails_if_already_bare(wt, bare_repo):
    """Cannot migrate an already-bare worktree layout."""
    r = wt("migrate", cwd=bare_repo / "main", input="y\n", check=False)
    assert r.returncode != 0
    assert "bare" in r.stderr.lower() or "already" in r.stderr.lower() or r.returncode != 0


def test_migrate_fails_with_submodules(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo")
    (repo / ".gitmodules").write_text("[submodule]\n")
    git("add", ".gitmodules", cwd=repo)
    git("commit", "-m", "add gitmodules", cwd=repo)
    r = wt("migrate", cwd=repo, input="y\n", check=False)
    assert r.returncode != 0
    assert "submodule" in r.stderr.lower()


def test_migrate_shows_plan(wt, std_repo):
    r = wt("migrate", "--dry-run", cwd=std_repo, input="n\n")
    # Plan table should be in stderr
    assert "main" in r.stderr or "repo" in r.stderr.lower()


def test_migrate_fails_in_detached_head(wt, std_repo):
    """migrate fails when HEAD is detached."""
    git("-c", "advice.detachedHead=false", "checkout", "--detach", "HEAD", cwd=std_repo)
    r = wt("migrate", cwd=std_repo, input="y\n", check=False)
    assert r.returncode != 0
    assert "detached" in (r.stdout + r.stderr).lower()


def test_migrate_preserves_modified_tracked_files(wt, tmp_path):
    """Modifications to existing tracked files survive migration."""
    repo = make_std_repo(tmp_path / "repo")
    (repo / "README.md").write_text("modified content\n")

    wt("migrate", cwd=repo, input="y\n")

    bare = repo / ".bare"
    wt_paths = [p for p in _resolve_worktree_paths(bare) if p != bare.resolve()]
    assert any((p / "README.md").read_text() == "modified content\n" for p in wt_paths)


def test_migrate_preserves_local_commits_ahead_of_remote(wt, tmp_path):
    """Local commits made before migrate are present after migration."""
    from conftest import make_std_repo

    origin = make_std_repo(tmp_path / "origin")
    repo = tmp_path / "repo"
    git("clone", str(origin), str(repo))
    git("config", "user.email", "t@t.com", cwd=repo)
    git("config", "user.name", "T", cwd=repo)

    (repo / "ahead.txt").write_text("ahead\n")
    git("add", "ahead.txt", cwd=repo)
    git("commit", "-m", "ahead commit", cwd=repo)
    before_sha = git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    wt("migrate", cwd=repo, input="y\n")

    bare = repo / ".bare"
    wt_paths = [p for p in _resolve_worktree_paths(bare) if p != bare.resolve()]
    assert wt_paths
    after_sha = git("rev-parse", "HEAD", cwd=wt_paths[-1]).stdout.strip()
    assert after_sha == before_sha


def test_migrate_preserves_multiple_remotes(wt, tmp_path):
    """Both origin and a second remote survive migration."""
    from conftest import make_std_repo

    origin = make_std_repo(tmp_path / "origin")
    upstream = make_std_repo(tmp_path / "upstream")
    repo = tmp_path / "repo"
    git("clone", str(origin), str(repo))
    git("config", "user.email", "t@t.com", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    git("remote", "add", "upstream", str(upstream), cwd=repo)

    wt("migrate", cwd=repo, input="y\n")

    bare = repo / ".bare"
    origin_url = git("remote", "get-url", "origin", cwd=bare).stdout.strip()
    upstream_url = git("remote", "get-url", "upstream", cwd=bare).stdout.strip()
    assert "origin" in origin_url or str(origin) in origin_url
    assert str(upstream) in upstream_url


def test_migrate_preserves_symlinks(wt, tmp_path):
    """Symlinks in the working directory survive migration."""
    import os

    repo = make_std_repo(tmp_path / "repo")
    (repo / "target.txt").write_text("real content\n")
    os.symlink("target.txt", repo / "link.txt")
    git("add", "target.txt", "link.txt", cwd=repo)
    git("commit", "-m", "add symlink", cwd=repo)

    wt("migrate", cwd=repo, input="y\n")

    bare = repo / ".bare"
    wt_paths = [p for p in _resolve_worktree_paths(bare) if p != bare.resolve()]
    assert any((p / "link.txt").is_symlink() for p in wt_paths)


def test_migrate_succeeds_with_unreachable_remote(wt, tmp_path):
    """Migration succeeds even when the remote URL is unreachable."""
    from conftest import make_std_repo

    origin = make_std_repo(tmp_path / "origin")
    repo = tmp_path / "repo"
    git("clone", str(origin), str(repo))
    git("config", "user.email", "t@t.com", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    git("remote", "set-url", "origin", "file:///nonexistent-repo-xyz", cwd=repo)

    wt("migrate", cwd=repo, input="y\n")

    assert (repo / ".bare").is_dir()


def test_migrate_fails_when_linked_worktrees_present(wt, std_repo):
    """migrate fails when the repo has linked worktrees."""
    other = std_repo.parent / "other-wt"
    git("worktree", "add", str(other), "-b", "extra-branch", cwd=std_repo, check=False)
    r = wt("migrate", cwd=std_repo, input="y\n", check=False)
    assert r.returncode != 0
    assert "linked worktrees" in (r.stdout + r.stderr).lower() or "worktree" in (r.stdout + r.stderr).lower()


def test_migrate_success_shows_layout_and_hints(wt, std_repo):
    """After successful migration output shows .bare path and git wt add hint."""
    r = wt("migrate", cwd=std_repo, input="y\n")
    combined = r.stdout + r.stderr
    assert ".bare" in combined
    assert "git wt add" in combined


def test_migrate_preserves_hooks_path(wt, tmp_path):
    """core.hooksPath config survives migration into the bare repo."""
    repo = make_std_repo(tmp_path / "repo")
    (repo / ".githooks").mkdir()
    git("config", "core.hooksPath", ".githooks", cwd=repo)

    wt("migrate", cwd=repo, input="y\n")

    bare = repo / ".bare"
    hooks_path = git("config", "core.hooksPath", cwd=bare, check=False).stdout.strip()
    assert hooks_path == ".githooks"


def test_migrate_preserves_repo_inode(wt, tmp_path):
    """The repo directory's inode is unchanged after migration (in-place swap)."""
    import os

    repo = make_std_repo(tmp_path / "repo")
    inode_before = os.stat(repo).st_ino

    wt("migrate", cwd=repo, input="y\n")

    inode_after = os.stat(repo).st_ino
    assert inode_after == inode_before


def test_migrate_fails_with_sparse_checkout(wt, tmp_path):
    """migrate blocks when sparse checkout is enabled."""
    repo = make_std_repo(tmp_path / "repo")
    git("sparse-checkout", "init", "--cone", cwd=repo)

    r = wt("migrate", cwd=repo, input="y\n", check=False)

    assert r.returncode != 0
    assert "sparse" in (r.stdout + r.stderr).lower()
