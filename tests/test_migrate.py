"""Tests for git wt migrate."""

from __future__ import annotations

import shutil

import pytest
from conftest import (
    _resolve_worktree_paths,
    assert_bare_layout,
    assert_worktree_gitdir_relative,
    git,
    linked_worktree_count,
    make_std_repo,
    requires_symlinks,
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


def test_migrate_accepts_gitmodules_without_initialized_modules(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo")
    (repo / ".gitmodules").write_text('[submodule "missing"]\npath = missing\nurl = /unreachable\n')
    git("add", ".gitmodules", cwd=repo)
    git("commit", "-m", "add gitmodules", cwd=repo)
    wt("migrate", cwd=repo, input="y\n")
    assert (repo / "main" / ".gitmodules").is_file()


@pytest.mark.parametrize("strategy", ["python", "auto", "fast"])
def test_migrate_preserves_uv_cache_git_marker(wt, tmp_path, strategy):
    repo = make_std_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(".cache/\n.env\n")
    git("add", ".gitignore", cwd=repo)
    git("commit", "-m", "ignore setup resources", cwd=repo)
    cache = repo / ".cache/uv/cache/sdists-v9"
    cache.mkdir(parents=True)
    (cache / ".git").touch()
    (cache / "cached.txt").write_text("cached source\n")
    (repo / ".env").write_text("SETUP_TEST=1\n")

    wt("migrate", "--dry-run", cwd=repo)
    assert (repo / ".git").is_dir()
    wt(
        "migrate",
        *(["--fast"] if strategy == "fast" else []),
        cwd=repo,
        input="y\n",
        env={"GIT_WT_MIGRATE_STRATEGY": strategy},
    )

    current = repo / "main"
    assert (current / ".cache/uv/cache/sdists-v9/.git").read_bytes() == b""
    assert (current / ".cache/uv/cache/sdists-v9/cached.txt").read_text() == "cached source\n"
    assert (current / ".env").read_text() == "SETUP_TEST=1\n"
    assert git("status", "--porcelain", cwd=current).stdout == ""


def test_migrate_rejects_malformed_nested_pointer_before_changes(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo")
    nested = repo / "nested"
    nested.mkdir()
    (nested / ".git").write_text("not a gitdir pointer\n")

    r = wt("migrate", cwd=repo, input="y\n", check=False)

    assert r.returncode != 0
    assert "invalid nested repository pointer" in r.stderr
    assert (repo / ".git").is_dir()


@pytest.mark.parametrize("strategy", ["python", "auto", "fast"])
def test_migrate_preserves_nested_submodules_and_move(wt, tmp_path, strategy):
    leaf = make_std_repo(tmp_path / "leaf")
    module = make_std_repo(tmp_path / "module")
    git("-c", "protocol.file.allow=always", "submodule", "add", str(leaf), "nested", cwd=module)
    git("commit", "-am", "nested submodule", cwd=module)
    repo = make_std_repo(tmp_path / "repo", branch="feature/topic")
    git(
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "--name",
        "custom-name",
        str(module),
        "deps/module",
        cwd=repo,
    )
    git("commit", "-am", "submodule", cwd=repo)
    git("-c", "protocol.file.allow=always", "submodule", "update", "--init", "--recursive", cwd=repo)
    sub = repo / "deps/module"
    nested = sub / "nested"
    (sub / "local.txt").write_text("local commit\n")
    git("add", "local.txt", cwd=sub)
    git("commit", "-m", "local only", cwd=sub)
    local_head = git("rev-parse", "HEAD", cwd=sub).stdout
    for path in (sub, nested):
        (path / "README.md").write_text("staged\n")
        git("add", "README.md", cwd=path)
        (path / "README.md").write_text("unstaged\n")
        (path / "untracked.txt").write_text("untracked\n")
    before = [git("status", "--porcelain", cwd=p).stdout for p in (repo, sub, nested)]
    git("config", "submodule.custom-name.url", "/unreachable", cwd=repo)
    wt(
        "migrate",
        *(["--fast"] if strategy == "fast" else []),
        cwd=repo,
        input="y\n",
        env={"GIT_WT_MIGRATE_STRATEGY": strategy},
    )
    moved = tmp_path / "moved"
    shutil.move(str(repo), str(moved))
    current = moved / "feature/topic"
    paths = (current, current / "deps/module", current / "deps/module/nested")
    assert [git("status", "--porcelain", cwd=p).stdout for p in paths] == before
    assert git("rev-parse", "HEAD", cwd=paths[1]).stdout == local_head
    assert git("config", "submodule.custom-name.url", cwd=current).stdout.strip() == "/unreachable"
    assert_worktree_gitdir_relative(current)
    assert "not supported" not in wt("doctor", cwd=current).stderr


def test_migrate_rejects_external_nested_metadata_before_changes(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo")
    external = make_std_repo(tmp_path / "external")
    nested = repo / "nested"
    nested.mkdir()
    (nested / ".git").write_text(f"gitdir: {external / '.git'}\n")
    r = wt("migrate", cwd=repo, input="y\n", check=False)
    assert r.returncode != 0
    assert "external or linked" in r.stderr
    assert (repo / ".git").is_dir()


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


@requires_symlinks
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


def test_migrate_preserves_lifecycle_hook_config(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo")
    commands = ["echo first", "echo second"]
    for command in commands:
        git("config", "--add", "wt.afteradd", command, cwd=repo)

    wt("migrate", cwd=repo, input="y\n")

    assert git("config", "--get-all", "wt.afteradd", cwd=repo / ".bare").stdout.splitlines() == commands


@pytest.mark.parametrize("fast", [False, True])
def test_migrate_preserves_repo_inode(wt, tmp_path, fast):
    """The repo directory's inode is unchanged after migration (in-place swap)."""
    import os

    repo = make_std_repo(tmp_path / "repo")
    inode_before = os.stat(repo).st_ino

    wt("migrate", *(["--fast"] if fast else []), cwd=repo, input="y\n")

    inode_after = os.stat(repo).st_ino
    assert inode_after == inode_before


@pytest.mark.parametrize("fast", [False, True])
def test_migrate_cleans_up_sibling_directories(wt, tmp_path, fast):
    """Successful migration leaves no staging or backup directories behind."""
    repo = make_std_repo(tmp_path / "repo")

    wt("migrate", *(["--fast"] if fast else []), cwd=repo, input="y\n")

    assert sorted(path.name for path in tmp_path.iterdir()) == ["repo"]


class TestRemoveMigrationPath:
    @pytest.fixture
    def repo(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        return root

    @pytest.mark.parametrize("kind", ["new", "backup"])
    def test_removes_expected_sibling(self, repo, kind):
        from git_wt import migrate

        path = repo.parent / f"repo-{kind}-1234"
        path.mkdir()
        (path / "leftover").write_text("content\n")

        migrate._remove_migration_path(path, repo)

        assert not path.exists()
        assert repo.is_dir()

    @pytest.mark.parametrize("name", ["repo-new-x", "repo-backup-123x", "repo-1234", "other-new-1234"])
    def test_refuses_unexpected_names(self, repo, name):
        from git_wt import migrate

        path = repo.parent / name
        path.mkdir()

        with pytest.raises(ValueError, match="unexpected migration path"):
            migrate._remove_migration_path(path, repo, ignore_errors=True)

        assert path.is_dir()

    def test_refuses_repository_root(self, repo):
        from git_wt import migrate

        with pytest.raises(ValueError, match="repository root"):
            migrate._remove_migration_path(repo, repo)

        assert repo.is_dir()

    def test_refuses_path_outside_repository_parent(self, repo):
        from git_wt import migrate

        path = repo.parent / "elsewhere" / "repo-new-1234"
        path.mkdir(parents=True)

        with pytest.raises(ValueError, match="outside repository parent"):
            migrate._remove_migration_path(path, repo)

        assert path.is_dir()


def test_migrate_fails_with_sparse_checkout(wt, tmp_path):
    """migrate blocks when sparse checkout is enabled."""
    repo = make_std_repo(tmp_path / "repo")
    git("sparse-checkout", "init", "--cone", cwd=repo)

    r = wt("migrate", cwd=repo, input="y\n", check=False)

    assert r.returncode != 0
    assert "sparse" in (r.stdout + r.stderr).lower()


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("deinitialized", [False, True])
def test_migrate_preserves_module_metadata(wt, tmp_path, deinitialized, fast):
    module = make_std_repo(tmp_path / "module")
    repo = make_std_repo(tmp_path / "repo")
    git("-c", "protocol.file.allow=always", "submodule", "add", str(module), "module", cwd=repo)
    git("commit", "-am", "submodule", cwd=repo)
    sub = repo / "module"
    git("commit", "--allow-empty", "-m", "local only", cwd=sub)
    head = git("rev-parse", "HEAD", cwd=sub).stdout
    if deinitialized:
        git("submodule", "deinit", "--force", "module", cwd=repo)
    else:
        # Exercise the old embedded .git directory layout.
        metadata = repo / ".git/modules/module"
        (sub / ".git").unlink()
        shutil.move(str(metadata), str(sub / ".git"))
        git("config", "--unset", "core.worktree", cwd=sub)
    wt("migrate", *(["--fast"] if fast else []), cwd=repo, input="y\n")
    moved = tmp_path / "moved"
    shutil.move(str(repo), str(moved))
    sub = moved / "main/module"
    if deinitialized:
        git("-c", "protocol.file.allow=always", "submodule", "update", "--init", cwd=moved / "main")
        metadata = next((moved / ".bare/worktrees").iterdir()) / "modules/module"
        assert git("cat-file", "-t", head.strip(), cwd=metadata).stdout.strip() == "commit"
    else:
        assert git("rev-parse", "HEAD", cwd=sub).stdout == head
    git("status", cwd=sub)


@requires_symlinks
def test_fast_migrate_preserves_original_files_and_index(wt, tmp_path):
    repo = make_std_repo(tmp_path / "repo", branch="feature/topic")
    git("branch", "main", cwd=repo)
    git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main", cwd=repo)
    git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)
    (repo / "README.md").write_text("staged\n")
    git("add", "README.md", cwd=repo)
    (repo / "README.md").write_text("unstaged\n")
    (repo / "deleted.txt").write_text("delete me\n")
    git("add", "deleted.txt", cwd=repo)
    (repo / "deleted.txt").unlink()
    cache = repo / ".cache/deep"
    cache.mkdir(parents=True)
    (cache / "payload").write_bytes(b"cached payload")
    (cache / ".git").touch()
    (repo / "link").symlink_to(".cache/deep/payload")
    before = git("status", "--porcelain", cwd=repo).stdout
    files = [repo / "README.md", cache, cache / "payload", cache / ".git", repo / "link"]
    inodes = [p.lstat().st_ino for p in files]

    result = wt("migrate", "--fast", cwd=repo, input="y\n")

    current = repo / "feature/topic"
    assert "no rollback" in result.stderr
    assert "Fast migration recovery locations" in result.stderr
    assert result.stderr.index("Fast migration recovery locations") < result.stderr.index(
        "Moving original working directory"
    )
    assert [current.joinpath(p.relative_to(repo)).lstat().st_ino for p in files] == inodes
    assert git("status", "--porcelain", cwd=current).stdout == before
    assert not (current / "deleted.txt").exists()
    assert_worktree_gitdir_relative(current)
    assert (repo / "main/README.md").read_text() == "hello\n"


def test_fast_migrate_dry_run_leaves_original_files(wt, std_repo):
    inode = (std_repo / "README.md").stat().st_ino
    result = wt("migrate", "--fast", "--dry-run", cwd=std_repo)
    assert "no rollback" in result.stderr
    assert (std_repo / "README.md").stat().st_ino == inode
    assert (std_repo / ".git").is_dir()
    assert not list(std_repo.parent.glob(f"{std_repo.name}-new-*"))


def test_fast_migrate_failure_keeps_moved_files(tmp_path, monkeypatch):
    from pathlib import Path

    from git_wt import migrate

    repo = make_std_repo(tmp_path / "repo")
    (repo / "payload").write_text("keep me\n")
    monkeypatch.chdir(repo)
    plan = migrate._build_plan()
    staging = tmp_path / "staging"
    backup = tmp_path / "backup"
    migrate._build_migrated(plan, staging, fast=True)
    assert {p.name for p in (staging / "main").iterdir()} == {".git"}
    original_rename = Path.rename
    moved = []

    def fail_after_first_move(path, target):
        if path.parent == repo and path.name != ".git":
            if moved:
                raise OSError
            moved.append(path.name)
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_after_first_move)
    with pytest.raises(OSError), migrate._cleanup_guard(staging, backup, root=repo, preserve_on_error=True):
        migrate._finalize_fast(plan, staging, backup)

    assert (staging / "main" / moved[0]).exists()
    assert (repo / ".git").is_dir()
    for name in ("README.md", "payload"):
        assert (repo / name).exists() or (staging / "main" / name).exists()


def test_fast_recovery_command_restores_dotfiles(tmp_path, monkeypatch):
    import duct

    from git_wt import migrate

    repo = make_std_repo(tmp_path / "original's repo")
    monkeypatch.chdir(repo)
    plan = migrate._build_plan()
    staging = tmp_path / "partial's staging"
    partial = staging / "main"
    partial.mkdir(parents=True)
    (partial / ".git").write_text("generated worktree pointer\n")
    (partial / ".env").write_text("SETUP_TEST=1\n")
    (partial / ".cache").mkdir()
    (partial / ".cache/payload").write_text("cached\n")
    (partial / "untracked").write_text("local\n")
    notice = migrate._fast_recovery_notice(plan, staging, tmp_path / "backup")
    command = next(line.strip() for line in notice.splitlines() if line.startswith("  find "))

    duct.cmd("sh", "-c", command).run()

    assert (repo / ".git").is_dir()
    assert (partial / ".git").read_text() == "generated worktree pointer\n"
    assert (repo / ".env").read_text() == "SETUP_TEST=1\n"
    assert (repo / ".cache/payload").read_text() == "cached\n"
    assert (repo / "untracked").read_text() == "local\n"
