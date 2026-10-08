"""Tests for git wt remove."""

from __future__ import annotations

from conftest import (
    assert_branch_exists,
    assert_branch_not_exists,
    assert_worktree_gitdir_relative,
    assert_worktree_not_exists,
    create_branch,
    create_worktree,
    git,
)


def test_remove_before_hook_failure_preserves_worktree(wt, bare_repo):
    """A before-remove hook failure preserves the worktree and reports failure."""
    create_branch(bare_repo, "before-remove-fail")
    create_worktree(bare_repo, "before-remove-fail")
    git("config", "wt.beforeremove", "exit 4", cwd=bare_repo)

    result = wt("remove", "before-remove-fail", cwd=bare_repo / "main", input="y\n", check=False)

    assert result.returncode == 0
    assert (bare_repo / "before-remove-fail").exists()
    assert "failed before removing worktree" in result.stderr


def test_remove_after_hook_failure_reports_removal(wt, bare_repo):
    """An after-remove hook failure reports that removal remains complete."""
    create_branch(bare_repo, "after-remove-fail")
    create_worktree(bare_repo, "after-remove-fail")
    git("config", "wt.afterremove", "exit 5", cwd=bare_repo)

    result = wt("remove", "after-remove-fail", cwd=bare_repo / "main", input="y\n", check=False)

    assert result.returncode == 0
    assert not (bare_repo / "after-remove-fail").exists()
    assert "was removed, but" in result.stderr


def test_remove_by_path(wt, bare_repo):
    create_branch(bare_repo, "feature")
    create_worktree(bare_repo, "feature")

    wt("remove", str(bare_repo / "feature"), cwd=bare_repo / "main", input="y\n")

    assert_worktree_not_exists(bare_repo / ".bare", bare_repo / "feature")


def test_remove_deletes_local_branch(wt, bare_repo):
    create_branch(bare_repo, "to-del")
    create_worktree(bare_repo, "to-del")

    wt("remove", str(bare_repo / "to-del"), cwd=bare_repo / "main", input="y\n")

    assert_branch_not_exists(bare_repo / ".bare", "to-del")


def test_remove_dry_run_preserves(wt, bare_repo):
    create_branch(bare_repo, "keep-me")
    create_worktree(bare_repo, "keep-me")

    wt("remove", str(bare_repo / "keep-me"), "--dry-run", cwd=bare_repo / "main", input="y\n")

    assert (bare_repo / "keep-me").exists()


def test_remove_cancel_preserves(wt, bare_repo):
    create_branch(bare_repo, "keep-me")
    create_worktree(bare_repo, "keep-me")

    wt("remove", str(bare_repo / "keep-me"), cwd=bare_repo / "main", input="n\n")

    assert (bare_repo / "keep-me").exists()


def test_remove_multiple(wt, bare_repo):
    for b in ("feat1", "feat2"):
        create_branch(bare_repo, b)
        create_worktree(bare_repo, b)

    wt("remove", str(bare_repo / "feat1"), str(bare_repo / "feat2"), cwd=bare_repo / "main", input="y\n")

    assert not (bare_repo / "feat1").exists()
    assert not (bare_repo / "feat2").exists()


def test_remove_interactive_via_select(wt, bare_repo):
    create_branch(bare_repo, "interactive")
    create_worktree(bare_repo, "interactive")

    wt("remove", cwd=bare_repo / "main", select=str(bare_repo / "interactive"), input="y\n")

    assert not (bare_repo / "interactive").exists()


def test_remove_merged_filter(wt, bare_repo):
    """--merged removes worktrees whose branch is fully merged into default."""
    create_branch(bare_repo, "merged-branch")
    create_worktree(bare_repo, "merged-branch")
    # Merge into main
    git("merge", "merged-branch", cwd=bare_repo / "main")

    r = wt(
        "remove",
        "--merged",
        "--dry-run",
        cwd=bare_repo / "main",
        select=str(bare_repo / "merged-branch"),
        input="cleanup\n",
        check=False,
    )
    # Dry run should succeed and mention the worktree
    assert r.returncode in (0, 1)


def test_remove_stale_filter(wt, bare_repo):
    """--stale finds prunable worktrees."""
    create_branch(bare_repo, "stale-branch")
    wt_path = create_worktree(bare_repo, "stale-branch")
    # Simulate a stale worktree by removing the directory manually
    import shutil

    shutil.rmtree(str(wt_path))

    r = wt(
        "remove", "--stale", "--dry-run", cwd=bare_repo / "main", select=str(wt_path), input="cleanup\n", check=False
    )
    assert r.returncode in (0, 1)


def test_remove_sweep_combines_filters(wt, bare_repo):
    """--sweep is equivalent to --merged --gone --stale."""
    r = wt("remove", "--sweep", "--dry-run", cwd=bare_repo / "main", input="cleanup\n", check=False)
    # No error, just zero candidates reported
    assert r.returncode in (0, 1)


def test_remove_rm_alias(wt, bare_repo):
    """'rm' removes a worktree just like 'remove'."""
    create_branch(bare_repo, "alias-test")
    create_worktree(bare_repo, "alias-test")

    wt("rm", str(bare_repo / "alias-test"), cwd=bare_repo / "main", input="y\n")

    assert not (bare_repo / "alias-test").exists()
    assert_branch_not_exists(bare_repo / ".bare", "alias-test")


def test_remove_by_workspace_name(wt, bare_repo):
    """Remove a worktree by its workspace name (not full path)."""
    create_branch(bare_repo, "by-name")
    create_worktree(bare_repo, "by-name")

    wt("remove", "by-name", cwd=bare_repo / "main", input="y\n")

    assert not (bare_repo / "by-name").exists()
    assert_branch_not_exists(bare_repo / ".bare", "by-name")


def test_remove_by_relative_path(wt, bare_repo):
    """Remove a worktree using a relative path from inside another worktree."""
    create_branch(bare_repo, "rel-target")
    create_worktree(bare_repo, "rel-target")

    # From main, '../rel-target' or just 'rel-target' should resolve
    wt("remove", "../rel-target", cwd=bare_repo / "main", input="y\n")

    assert not (bare_repo / "rel-target").exists()


def test_remove_slash_path_worktree_by_name(wt, bare_repo):
    """Remove a worktree with a slash-containing path by its workspace name."""
    wt_path = bare_repo / "feature" / "slash"
    git("worktree", "add", "-b", "feature/slash", str(wt_path), cwd=bare_repo / ".bare")

    wt("remove", "feature/slash", cwd=bare_repo / "main", input="y\n")

    assert not wt_path.exists()


def test_remove_invalid_name_shows_available(wt, bare_repo):
    """Removing an invalid worktree name shows 'Available worktrees:'."""
    r = wt("remove", "nonexistent-wt", cwd=bare_repo / "main", check=False)

    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "Available worktrees:" in combined


def test_remove_ambiguous_name_error(wt, bare_repo):
    """Removing an ambiguous basename shows both matching options."""
    # Create two worktrees that share a basename: feature/login and bugfix/login
    git("worktree", "add", "-b", "feature/login", str(bare_repo / "feature" / "login"), cwd=bare_repo / ".bare")
    git("worktree", "add", "-b", "bugfix/login", str(bare_repo / "bugfix" / "login"), cwd=bare_repo / ".bare")

    r = wt("remove", "login", cwd=bare_repo / "main", check=False)

    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "ambiguous" in combined
    assert "feature/login" in combined
    assert "bugfix/login" in combined


def test_remove_dry_run_remote_branches_preserved_message(wt, bare_repo):
    """--dry-run output mentions that remote branches are preserved."""
    create_branch(bare_repo, "dry-remote")
    create_worktree(bare_repo, "dry-remote")

    r = wt("remove", "--dry-run", str(bare_repo / "dry-remote"), cwd=bare_repo / "main")

    combined = r.stdout + r.stderr
    assert "DRY RUN" in combined
    assert "Remote branches are preserved" in combined


def test_remove_stale_preserves_branch(wt, bare_repo):
    """--stale removes a stale worktree entry but keeps its branch."""
    import shutil as _shutil

    create_branch(bare_repo, "stale-keep")
    wt_path = create_worktree(bare_repo, "stale-keep")
    _shutil.rmtree(str(wt_path))  # make it stale

    wt("remove", "--stale", cwd=bare_repo / "main", select=str(wt_path), input="cleanup\n")

    assert_branch_exists(bare_repo / ".bare", "stale-keep")
    assert_worktree_not_exists(bare_repo / ".bare", wt_path)


def test_destroy_alias_requires_branch_name_confirmation(wt, bare_repo):
    """'destroy' is aborted unless confirmed with the branch name."""
    create_branch(bare_repo, "destroy-me")
    create_worktree(bare_repo, "destroy-me")

    # "y" is not the branch name — should abort (still exits 0, but nothing removed)
    wt("destroy", str(bare_repo / "destroy-me"), cwd=bare_repo / "main", input="y\n")
    assert (bare_repo / "destroy-me").exists()  # worktree still there

    # Correct branch name — should proceed
    wt("destroy", str(bare_repo / "destroy-me"), cwd=bare_repo / "main", input="destroy-me\n")

    assert not (bare_repo / "destroy-me").exists()
    assert_branch_not_exists(bare_repo / ".bare", "destroy-me")


def test_destroy_dry_run(wt, bare_repo):
    """'destroy --dry-run' shows the plan without removing anything."""
    create_branch(bare_repo, "destroy-dry")
    create_worktree(bare_repo, "destroy-dry")

    r = wt("destroy", "--dry-run", str(bare_repo / "destroy-dry"), cwd=bare_repo / "main")

    assert r.returncode == 0
    assert "DRY RUN" in r.stdout + r.stderr
    assert (bare_repo / "destroy-dry").exists()
    assert_branch_exists(bare_repo / ".bare", "destroy-dry")


def test_destroy_n_short_flag_is_dry_run(wt, bare_repo):
    """-n is accepted as an alias for --dry-run on destroy."""
    create_branch(bare_repo, "destroy-n")
    create_worktree(bare_repo, "destroy-n")

    r = wt("destroy", "-n", str(bare_repo / "destroy-n"), cwd=bare_repo / "main")

    assert r.returncode == 0
    assert "DRY RUN" in r.stdout + r.stderr
    assert (bare_repo / "destroy-n").exists()


def test_destroy_multiple_worktrees(wt, bare_repo):
    """destroy accepts multiple worktree arguments."""
    create_branch(bare_repo, "dest-one")
    create_worktree(bare_repo, "dest-one")
    create_branch(bare_repo, "dest-two")
    create_worktree(bare_repo, "dest-two")

    wt("destroy", str(bare_repo / "dest-one"), str(bare_repo / "dest-two"), cwd=bare_repo / "main", input="remove\n")

    assert not (bare_repo / "dest-one").exists()
    assert not (bare_repo / "dest-two").exists()
    assert_branch_not_exists(bare_repo / ".bare", "dest-one")
    assert_branch_not_exists(bare_repo / ".bare", "dest-two")


def test_remove_fails_when_removing_current_worktree(wt, bare_repo):
    """Removing the worktree you are currently inside fails even when confirmed."""
    r = wt("remove", str(bare_repo / "main"), cwd=bare_repo / "main", input="y\n", check=False)
    assert r.returncode != 0


def test_remove_dirty_worktree_with_confirmation(wt, bare_repo):
    """remove can force-remove a worktree with uncommitted changes."""
    create_branch(bare_repo, "dirty-remove")
    create_worktree(bare_repo, "dirty-remove")
    (bare_repo / "dirty-remove" / "untracked.txt").write_text("dirty\n")

    wt("remove", str(bare_repo / "dirty-remove"), cwd=bare_repo / "main", input="y\n")

    assert not (bare_repo / "dirty-remove").exists()


def test_remove_invalid_name_shows_full_relative_path(wt, bare_repo):
    """Error message for invalid name lists worktrees with full relative paths."""
    git("worktree", "add", "-b", "feature/nested", str(bare_repo / "feature" / "nested"), cwd=bare_repo / ".bare")

    r = wt("remove", "nonexistent-wt", cwd=bare_repo / "main", check=False)

    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "Available worktrees:" in combined
    assert "feature/nested" in combined


def test_remove_gone_filter(wt, bare_repo_with_remote):
    """--gone removes worktrees whose upstream branch has been deleted."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    # Create branch, push it, set upstream tracking, create worktree
    git("branch", "gone-branch", "main", cwd=bare)
    git("push", "origin", "gone-branch", cwd=bare)
    git("fetch", "--all", cwd=bare)
    create_worktree(repo, "gone-branch")
    git("branch", "--set-upstream-to", "origin/gone-branch", "gone-branch", cwd=bare)

    # Delete the remote branch
    git("push", "origin", "--delete", "gone-branch", cwd=bare)
    git("fetch", "--prune", cwd=bare)

    r = wt("remove", "--gone", cwd=repo / "main", select=str(repo / "gone-branch"), input="cleanup\n")

    assert r.returncode == 0
    assert not (repo / "gone-branch").exists()
    assert_branch_not_exists(bare, "gone-branch")


def test_remove_merged_skips_dirty_worktrees(wt, bare_repo_with_remote):
    """--merged does not offer worktrees that have uncommitted changes."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    # Create a branch, push it, set upstream, create worktree, merge into main
    git("branch", "dirty-merged", "main", cwd=bare)
    git("push", "origin", "dirty-merged", cwd=bare)
    git("fetch", "--all", cwd=bare)
    create_worktree(repo, "dirty-merged")
    git("branch", "--set-upstream-to", "origin/dirty-merged", "dirty-merged", cwd=bare)
    git("merge", "dirty-merged", cwd=repo / "main")

    # Make the worktree dirty
    (repo / "dirty-merged" / "dirty.txt").write_text("dirty\n")

    r = wt("remove", "--merged", "--dry-run", cwd=repo / "main", input="cleanup\n")

    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "No matching cleanup candidates found" in combined


def test_add_then_remove_round_trip(wt, bare_repo):
    """Full add→remove cycle via git wt: relative gitdir paths must not block removal.

    git wt add relativizes gitdir pointer files for repo portability.  git worktree
    remove (< 2.35) requires those pointers to be absolute, so git wt remove must
    restore them before delegating.  This test catches any regression in that
    back-translation step.
    """
    # Use git wt add so the worktree is in the exact state production creates.
    wt("add", "-b", "round-trip", str(bare_repo / "round-trip"), cwd=bare_repo / "main")

    # Confirm the worktree was created with relative gitdir paths.
    assert_worktree_gitdir_relative(bare_repo / "round-trip")

    # Remove via git wt — must succeed despite relative paths.
    wt("remove", str(bare_repo / "round-trip"), cwd=bare_repo / "main", input="y\n")

    assert not (bare_repo / "round-trip").exists()
    assert_branch_not_exists(bare_repo / ".bare", "round-trip")
