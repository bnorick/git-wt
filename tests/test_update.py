"""Tests for git wt update."""

from __future__ import annotations

from pathlib import Path

from conftest import git, make_bare_repo, make_std_repo


def test_update_help(wt, bare_repo):
    """--help shows usage with Fetch in output."""
    r = wt("update", "--help")
    combined = r.stdout + r.stderr
    assert "Usage" in combined or "Fetch" in combined or "update" in combined.lower()


def test_update_u_alias_help(wt, bare_repo):
    """'u' alias forwards to update --help."""
    r = wt("u", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "Usage" in combined or "update" in combined.lower()


def test_update_fails_without_remote(wt, tmp_path):
    """update exits non-zero or warns when no remote is reachable."""
    repo = make_bare_repo(tmp_path / "repo")
    git("remote", "remove", "origin", cwd=repo / ".bare")
    r = wt("update", cwd=repo / "main", check=False)
    combined = (r.stdout + r.stderr).lower()
    assert r.returncode != 0 or "remote" in combined or "error" in combined


def test_update_works_with_remote(wt, bare_repo_with_remote):
    """update succeeds when a valid remote is configured."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"
    git("remote", "set-head", "origin", "main", cwd=bare)
    git("branch", "--set-upstream-to", "origin/main", "main", cwd=bare)
    r = wt("update", cwd=repo / "main")
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Force-push / safe-reset helpers
# ---------------------------------------------------------------------------


def _make_repo_with_committable_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Bare worktree repo with a non-bare origin so tests can commit to it directly."""
    origin = tmp_path / "origin"
    make_std_repo(origin, branch="main")

    repo = tmp_path / "repo"
    repo.mkdir()
    bare = repo / ".bare"
    git("clone", "--bare", str(origin), str(bare))
    (repo / ".git").write_text("gitdir: ./.bare\n")
    git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*", cwd=bare)
    git("config", "remote.origin.url", str(origin), cwd=bare)
    git("config", "core.logallrefupdates", "true", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("worktree", "add", str(repo / "main"), "main", cwd=bare)
    git("branch", "--set-upstream-to", "origin/main", "main", cwd=bare)
    git("remote", "set-head", "origin", "main", cwd=bare)

    return repo, origin


def _setup_force_push_scenario(tmp_path: Path) -> tuple[Path, Path, Path]:
    """
    Repo where origin/main has been force-pushed (commit amended with same diff).

    State after setup:
      - origin/main: A → B' (amended message, same file content as B)
      - local  main: A → B  (old commit, diverged from origin)
      - remote tracking ref updated (fetch already ran)
    """
    repo, origin = _make_repo_with_committable_remote(tmp_path)
    bare = repo / ".bare"

    # Add a commit to origin and sync it into the local worktree
    (origin / "feature.txt").write_text("feature content\n")
    git("add", "feature.txt", cwd=origin)
    git("commit", "-m", "add feature", cwd=origin)
    git("fetch", "--all", cwd=bare)
    git("reset", "--hard", "origin/main", cwd=repo / "main")

    # Simulate force-push: amend on origin (same diff, new SHA)
    git("commit", "--amend", "-m", "add feature (rebased)", cwd=origin)
    git("fetch", "--all", cwd=bare)

    return repo, origin, bare


# ---------------------------------------------------------------------------
# Force-push tests
# ---------------------------------------------------------------------------


def test_update_force_push_safe_reset(wt, tmp_path):
    """update resets to upstream when force-pushed with only equivalent patches."""
    repo, _origin, bare = _setup_force_push_scenario(tmp_path)

    r = wt("update", cwd=repo / "main")
    assert r.returncode == 0

    local_sha = git("rev-parse", "main", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/main", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_force_push_with_uncommitted_changes(wt, tmp_path):
    """update refuses safe reset when tracked files have uncommitted changes."""
    repo, _origin, _bare = _setup_force_push_scenario(tmp_path)

    (repo / "main" / "feature.txt").write_text("locally modified\n")

    r = wt("update", cwd=repo / "main", check=False)
    assert r.returncode != 0
    assert "uncommitted" in (r.stdout + r.stderr).lower()


def test_update_dirty_worktree_hint(wt, tmp_path):
    """On diverged+dirty failure, hint lists dirty files and suggests --force."""
    repo, _origin, _bare = _setup_force_push_scenario(tmp_path)

    (repo / "main" / "feature.txt").write_text("locally modified\n")

    r = wt("update", cwd=repo / "main", check=False)
    combined = r.stdout + r.stderr
    assert r.returncode != 0
    assert "hint" in combined.lower()
    assert "feature.txt" in combined
    assert "--force" in combined or "git wt u --force" in combined


def test_update_dirty_worktree_hint_truncates_at_five(wt, tmp_path):
    """Hint shows at most 5 files and reports the remaining count."""
    repo, origin = _make_repo_with_committable_remote(tmp_path)
    bare = repo / ".bare"

    # Commit 7 tracked files to origin and sync into the worktree
    for i in range(7):
        (origin / f"tracked{i}.txt").write_text(f"original {i}\n")
    git("add", ".", cwd=origin)
    git("commit", "-m", "add tracked files", cwd=origin)
    git("fetch", "--all", cwd=bare)
    git("reset", "--hard", "origin/main", cwd=repo / "main")

    # Simulate force-push: amend on origin so local diverges
    git("commit", "--amend", "-m", "add tracked files (rebased)", cwd=origin)
    git("fetch", "--all", cwd=bare)

    # Dirty all 7 tracked files locally — now local is diverged AND has dirty files
    for i in range(7):
        (repo / "main" / f"tracked{i}.txt").write_text(f"dirty {i}\n")

    r = wt("update", cwd=repo / "main", check=False)
    combined = r.stdout + r.stderr
    assert r.returncode != 0
    assert "2 more file" in combined


def test_update_force_push_with_local_commits(wt, tmp_path):
    """update refuses safe reset when local has commits not mirrored upstream."""
    repo, _origin, _bare = _setup_force_push_scenario(tmp_path)

    (repo / "main" / "local.txt").write_text("local only\n")
    git("add", "local.txt", cwd=repo / "main")
    git("commit", "-m", "local commit", cwd=repo / "main")

    r = wt("update", cwd=repo / "main", check=False)
    assert r.returncode != 0
    assert "mirrored" in (r.stdout + r.stderr).lower()


def test_update_fuzzy_match_after_branch_switch(wt, tmp_path):
    """Fuzzy match resolves by the branch currently checked out in the worktree.

    Scenario: worktree created for feature/foo, then switched to feature/bar.
    Running 'git wt u bar' should pull the worktree now on feature/bar.
    """
    repo, origin = _make_repo_with_committable_remote(tmp_path)
    bare = repo / ".bare"

    # Create feature/foo and feature/bar on origin
    git("checkout", "-b", "feature/foo", cwd=origin)
    (origin / "foo.txt").write_text("foo\n")
    git("add", "foo.txt", cwd=origin)
    git("commit", "-m", "add foo", cwd=origin)

    git("checkout", "-b", "feature/bar", cwd=origin)
    (origin / "bar.txt").write_text("bar\n")
    git("add", "bar.txt", cwd=origin)
    git("commit", "-m", "add bar", cwd=origin)

    # Fetch and create local tracking branches
    git("fetch", "--all", cwd=bare)
    git("branch", "--track", "feature/foo", "origin/feature/foo", cwd=bare)
    git("branch", "--track", "feature/bar", "origin/feature/bar", cwd=bare)

    # Create a worktree initially for feature/foo
    wt_path = repo / "worktree"
    git("worktree", "add", str(wt_path), "feature/foo", cwd=bare)

    # Switch the worktree to feature/bar (simulates user running `git switch`)
    git("checkout", "feature/bar", cwd=wt_path)

    # Push a new commit to origin/feature/bar so there's something to pull
    (origin / "bar2.txt").write_text("more bar\n")
    git("add", "bar2.txt", cwd=origin)
    git("commit", "-m", "more bar work", cwd=origin)

    # 'bar' fuzzy-matches 'feature/bar'; update should pull the switched worktree
    r = wt("update", "bar", cwd=repo / "main")
    assert r.returncode == 0

    # Confirm the worktree pulled the new commit
    local_sha = git("rev-parse", "feature/bar", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/feature/bar", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_force_discards_dirty_tracked_files(wt, tmp_path):
    """--force resets to upstream even when tracked files are modified locally."""
    repo, _origin, bare = _setup_force_push_scenario(tmp_path)

    # Dirty a tracked file in the worktree
    (repo / "main" / "feature.txt").write_text("locally modified\n")

    # Without --force it should fail
    r = wt("update", cwd=repo / "main", check=False)
    assert r.returncode != 0

    # With --force it should succeed and warn about the file
    r = wt("update", "--force", cwd=repo / "main")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "discard" in combined.lower() or "warn" in combined.lower()
    assert "feature.txt" in combined

    # The worktree should now match upstream
    local_sha = git("rev-parse", "main", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/main", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_force_resets_unmirrored_commits_when_confirmed(wt, tmp_path):
    """--force overrides unmirrored local commits after typing force."""
    repo, _origin, bare = _setup_force_push_scenario(tmp_path)

    (repo / "main" / "local.txt").write_text("local only\n")
    git("add", "local.txt", cwd=repo / "main")
    git("commit", "-m", "local commit", cwd=repo / "main")

    r = wt("update", "--force", cwd=repo / "main", input="force\n")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "local commit" in combined.lower()
    assert "mirrored" in combined.lower()
    assert "backup/main" in combined
    assert "git branch backup/main HEAD" in combined

    local_sha = git("rev-parse", "main", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/main", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_force_requires_literal_force_for_unmirrored_commits(wt, tmp_path):
    """Typing y is not enough when --force would discard local commits."""
    repo, _origin, bare = _setup_force_push_scenario(tmp_path)

    (repo / "main" / "local.txt").write_text("local only\n")
    git("add", "local.txt", cwd=repo / "main")
    git("commit", "-m", "local commit", cwd=repo / "main")
    old_sha = git("rev-parse", "main", cwd=bare).stdout.strip()

    r = wt("update", "--force", cwd=repo / "main", input="y\n")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "skip" in combined.lower()
    assert "type 'force'" in combined.lower()

    new_sha = git("rev-parse", "main", cwd=bare).stdout.strip()
    assert new_sha == old_sha


def _setup_feature_force_push_scenario(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """
    Repo where origin/feature/thing has been force-pushed (rebased, same patch, new SHA).

    State after setup:
      - origin/feature/thing: rebased commit F' (same diff as F, different SHA)
      - local feature/thing worktree: old commit F (diverged from upstream)
      - remote tracking ref updated (fetch already ran)
    """
    repo, origin = _make_repo_with_committable_remote(tmp_path)
    bare = repo / ".bare"

    # Create feature/thing on origin with one commit
    git("checkout", "-b", "feature/thing", cwd=origin)
    (origin / "thing.txt").write_text("thing content\n")
    git("add", "thing.txt", cwd=origin)
    git("commit", "-m", "add thing", cwd=origin)

    # Set up local tracking branch and worktree for feature/thing
    git("fetch", "--all", cwd=bare)
    git("branch", "--track", "feature/thing", "origin/feature/thing", cwd=bare)
    wt_feature = repo / "feature-thing"
    git("worktree", "add", str(wt_feature), "feature/thing", cwd=bare)
    git("reset", "--hard", "origin/feature/thing", cwd=wt_feature)

    # Simulate force-push: amend on origin (same diff, new SHA — equivalent to rebase)
    git("commit", "--amend", "-m", "add thing (rebased)", cwd=origin)
    git("fetch", "--all", cwd=bare)

    # Set up main tracking for the update command
    git("remote", "set-head", "origin", "main", cwd=bare)
    git("branch", "--set-upstream-to", "origin/main", "main", cwd=bare)

    return repo, origin, bare, wt_feature


def test_update_force_extra_branch_rebased_onto_main(wt, tmp_path):
    """Reproduces the real workflow: feature rebased (force-pushed), other worktree
    has a dirty tracked file (e.g. uv.lock), 'git wt u feature --force' succeeds."""
    repo, _origin, bare, wt_feature = _setup_feature_force_push_scenario(tmp_path)

    # Dirty a tracked file in the feature worktree (e.g. uv.lock updated by tooling)
    (wt_feature / "thing.txt").write_text("locally modified\n")

    # Without --force it should fail
    r = wt("update", "feature/thing", cwd=repo / "main", check=False)
    assert r.returncode != 0
    assert "uncommitted" in (r.stdout + r.stderr).lower()

    # With --force it should succeed and warn about the dirty file
    r = wt("update", "feature/thing", "--force", cwd=repo / "main")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "discard" in combined.lower() or "warn" in combined.lower()
    assert "thing.txt" in combined

    # Feature worktree should now match upstream
    local_sha = git("rev-parse", "feature/thing", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/feature/thing", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_force_extra_branch_resets_unmirrored_commits(wt, tmp_path):
    """--force on extra branch resets unmirrored local commits after typing force."""
    repo, _origin, bare, wt_feature = _setup_feature_force_push_scenario(tmp_path)

    (wt_feature / "local.txt").write_text("local only\n")
    git("add", "local.txt", cwd=wt_feature)
    git("commit", "-m", "local commit", cwd=wt_feature)

    r = wt("update", "feature/thing", "--force", cwd=repo / "main", input="force\n")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "mirrored" in combined.lower()
    assert "backup/feature/thing" in combined

    local_sha = git("rev-parse", "feature/thing", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/feature/thing", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_force_confirmation_declined_skips_worktree(wt, tmp_path):
    """Declining the confirmation prompt skips the force-reset but exits 0."""
    repo, _origin, bare = _setup_force_push_scenario(tmp_path)
    (repo / "main" / "feature.txt").write_text("locally modified\n")

    old_sha = git("rev-parse", "main", cwd=bare).stdout.strip()

    # Send "n" to the confirmation prompt — should skip the reset
    r = wt("update", "--force", cwd=repo / "main", input="n\n")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "skip" in combined.lower()

    # Branch should NOT have been reset
    new_sha = git("rev-parse", "main", cwd=bare).stdout.strip()
    assert old_sha == new_sha


def test_update_force_confirmation_accepted_resets_worktree(wt, tmp_path):
    """Confirming 'y' at the prompt proceeds with the force-reset."""
    repo, _origin, bare = _setup_force_push_scenario(tmp_path)
    (repo / "main" / "feature.txt").write_text("locally modified\n")

    # Send "y" to the confirmation prompt
    r = wt("update", "--force", cwd=repo / "main", input="y\n")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "feature.txt" in combined

    local_sha = git("rev-parse", "main", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/main", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_force_confirmation_independent_per_worktree(wt, tmp_path):
    """Declining confirmation for main doesn't prevent the extra branch from being confirmed."""
    repo, origin, bare = _setup_force_push_scenario(tmp_path)

    # Create feature branch on origin
    git("checkout", "-b", "feature/thing", cwd=origin)
    (origin / "thing.txt").write_text("thing content\n")
    git("add", "thing.txt", cwd=origin)
    git("commit", "-m", "add thing", cwd=origin)

    # Set up local tracking branch and worktree for feature/thing
    git("fetch", "--all", cwd=bare)
    git("branch", "--track", "feature/thing", "origin/feature/thing", cwd=bare)
    wt_feature = repo / "feature-thing"
    git("worktree", "add", str(wt_feature), "feature/thing", cwd=bare)
    git("reset", "--hard", "origin/feature/thing", cwd=wt_feature)

    # Force-push feature/thing on origin (amend = same diff, new SHA)
    git("commit", "--amend", "-m", "add thing (rebased)", cwd=origin)
    git("fetch", "--all", cwd=bare)

    # Dirty both worktrees so both need confirmation
    (repo / "main" / "feature.txt").write_text("dirty main\n")
    (wt_feature / "thing.txt").write_text("dirty feature\n")

    old_main_sha = git("rev-parse", "main", cwd=bare).stdout.strip()

    # "n" declines main, "y" confirms feature/thing
    r = wt("update", "feature/thing", "--force", cwd=repo / "main", input="n\ny\n")
    assert r.returncode == 0
    combined = r.stdout + r.stderr

    # main was skipped
    assert "skip" in combined.lower()
    new_main_sha = git("rev-parse", "main", cwd=bare).stdout.strip()
    assert old_main_sha == new_main_sha

    # feature/thing was reset
    local_feat = git("rev-parse", "feature/thing", cwd=bare).stdout.strip()
    remote_feat = git("rev-parse", "origin/feature/thing", cwd=bare).stdout.strip()
    assert local_feat == remote_feat


def test_update_from_worktree_subdirectory(wt, bare_repo_with_remote):
    """update works when CWD is a subdirectory inside a worktree."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"
    git("remote", "set-head", "origin", "main", cwd=bare)
    git("branch", "--set-upstream-to", "origin/main", "main", cwd=bare)
    subdir = repo / "main" / "src"
    subdir.mkdir()
    r = wt("update", cwd=subdir)
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Auto-detect current worktree tests
# ---------------------------------------------------------------------------


def _setup_feature_worktree_with_new_commit(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Repo with main and feature/thing worktrees; origin/feature/thing has a new commit."""
    repo, origin = _make_repo_with_committable_remote(tmp_path)
    bare = repo / ".bare"

    git("checkout", "-b", "feature/thing", cwd=origin)
    (origin / "thing.txt").write_text("thing\n")
    git("add", "thing.txt", cwd=origin)
    git("commit", "-m", "add thing", cwd=origin)

    git("fetch", "--all", cwd=bare)
    git("branch", "--track", "feature/thing", "origin/feature/thing", cwd=bare)
    wt_feature = repo / "feature-thing"
    git("worktree", "add", str(wt_feature), "feature/thing", cwd=bare)
    git("reset", "--hard", "origin/feature/thing", cwd=wt_feature)

    git("remote", "set-head", "origin", "main", cwd=bare)
    git("branch", "--set-upstream-to", "origin/main", "main", cwd=bare)

    # Push a new commit to origin/feature/thing that the worktree doesn't have yet
    (origin / "thing2.txt").write_text("more thing\n")
    git("add", "thing2.txt", cwd=origin)
    git("commit", "-m", "more thing", cwd=origin)
    git("fetch", "--all", cwd=bare)

    return repo, origin, bare, wt_feature


def test_update_from_feature_worktree_also_pulls_current(wt, tmp_path):
    """Running update from a non-main worktree auto-pulls that worktree too."""
    _repo, _origin, bare, wt_feature = _setup_feature_worktree_with_new_commit(tmp_path)

    r = wt("update", cwd=wt_feature)
    assert r.returncode == 0

    local_sha = git("rev-parse", "feature/thing", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/feature/thing", cwd=bare).stdout.strip()
    assert local_sha == remote_sha


def test_update_from_main_worktree_no_extra_pull(wt, tmp_path):
    """Running update from main worktree pulls only main (regression guard)."""
    repo, _origin, bare, _wt_feature = _setup_feature_worktree_with_new_commit(tmp_path)

    local_before = git("rev-parse", "feature/thing", cwd=bare).stdout.strip()

    r = wt("update", cwd=repo / "main")
    assert r.returncode == 0

    # feature/thing should not have been pulled
    local_after = git("rev-parse", "feature/thing", cwd=bare).stdout.strip()
    assert local_before == local_after


def test_update_current_worktree_not_duplicated_when_explicit_branch_matches(wt, tmp_path):
    """update feature/thing from within feature/thing worktree pulls it only once."""
    _repo, _origin, bare, wt_feature = _setup_feature_worktree_with_new_commit(tmp_path)

    # 'thing' fuzzy-matches feature/thing; running from wt_feature should not double-pull
    r = wt("update", "thing", cwd=wt_feature)
    assert r.returncode == 0

    local_sha = git("rev-parse", "feature/thing", cwd=bare).stdout.strip()
    remote_sha = git("rev-parse", "origin/feature/thing", cwd=bare).stdout.strip()
    assert local_sha == remote_sha
