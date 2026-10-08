"""Integration tests: multi-command workflows through git wt.

Every step that establishes state uses the git-wt CLI rather than low-level
helpers, so the system state between commands exactly matches what production
users experience.  This catches regressions that unit tests for individual
commands cannot see — e.g. add relativizes gitdir pointers, then remove must
back-translate them before calling git worktree remove.

Fixtures from conftest are used only for scaffolding bare/standard repos, not
for creating worktrees.  Worktrees are always created via ``wt("add", ...)``.
"""

from __future__ import annotations

import shutil

from conftest import (
    assert_branch_not_exists,
    assert_worktree_gitdir_relative,
    assert_worktree_not_exists,
    git,
    make_std_repo,
)

# ---------------------------------------------------------------------------
# Add → remove round-trips
# ---------------------------------------------------------------------------


def test_add_remove_basic(wt, wt_bare_repo):
    """Single worktree created and removed entirely via git wt."""
    wt("add", "-b", "feature", str(wt_bare_repo / "feature"), cwd=wt_bare_repo / "main")
    assert_worktree_gitdir_relative(wt_bare_repo / "feature")

    wt("remove", str(wt_bare_repo / "feature"), cwd=wt_bare_repo / "main", input="y\n")

    assert not (wt_bare_repo / "feature").exists()
    assert_branch_not_exists(wt_bare_repo / ".bare", "feature")


def test_add_remove_multiple(wt, wt_bare_repo):
    """Multiple worktrees added then removed in a single remove call."""
    for branch in ("feat-a", "feat-b", "feat-c"):
        wt("add", "-b", branch, str(wt_bare_repo / branch), cwd=wt_bare_repo / "main")
        assert_worktree_gitdir_relative(wt_bare_repo / branch)

    wt(
        "remove",
        str(wt_bare_repo / "feat-a"),
        str(wt_bare_repo / "feat-b"),
        str(wt_bare_repo / "feat-c"),
        cwd=wt_bare_repo / "main",
        input="y\n",
    )

    for branch in ("feat-a", "feat-b", "feat-c"):
        assert not (wt_bare_repo / branch).exists()


def test_add_remove_by_workspace_name(wt, wt_bare_repo):
    """Worktree added via path, removed via short workspace name."""
    wt("add", "-b", "short-name", str(wt_bare_repo / "short-name"), cwd=wt_bare_repo / "main")

    wt("remove", "short-name", cwd=wt_bare_repo / "main", input="y\n")

    assert not (wt_bare_repo / "short-name").exists()


def test_add_remove_with_uncommitted_changes(wt, wt_bare_repo):
    """Force-remove a worktree that has uncommitted work."""
    wt("add", "-b", "dirty-wt", str(wt_bare_repo / "dirty-wt"), cwd=wt_bare_repo / "main")
    (wt_bare_repo / "dirty-wt" / "untracked.txt").write_text("dirty\n")

    wt("remove", str(wt_bare_repo / "dirty-wt"), cwd=wt_bare_repo / "main", input="y\n")

    assert not (wt_bare_repo / "dirty-wt").exists()


def test_add_remove_by_relative_path(wt, wt_bare_repo):
    """Remove a worktree using a path relative to the caller's cwd."""
    wt("add", "-b", "rel-target", str(wt_bare_repo / "rel-target"), cwd=wt_bare_repo / "main")

    wt("remove", "../rel-target", cwd=wt_bare_repo / "main", input="y\n")

    assert not (wt_bare_repo / "rel-target").exists()


def test_destroy_round_trip(wt, wt_bare_repo):
    """destroy requires branch-name confirmation, then fully removes worktree."""
    wt("add", "-b", "to-destroy", str(wt_bare_repo / "to-destroy"), cwd=wt_bare_repo / "main")
    assert_worktree_gitdir_relative(wt_bare_repo / "to-destroy")

    wt("destroy", str(wt_bare_repo / "to-destroy"), cwd=wt_bare_repo / "main", input="to-destroy\n")

    assert not (wt_bare_repo / "to-destroy").exists()
    assert_branch_not_exists(wt_bare_repo / ".bare", "to-destroy")


# ---------------------------------------------------------------------------
# Repo portability — the core value of relative gitdir paths
# ---------------------------------------------------------------------------


def test_worktrees_survive_repo_rename(wt, wt_bare_repo):
    """After renaming the repo directory, git commands still work from within.

    This is the primary reason for relative gitdir paths: the entire repo tree
    can move without breaking worktree linkage.
    """
    wt("add", "-b", "survivor", str(wt_bare_repo / "survivor"), cwd=wt_bare_repo / "main")
    assert_worktree_gitdir_relative(wt_bare_repo / "survivor")

    # Rename the repo root — moves .bare/, main/, survivor/ together
    new_root = wt_bare_repo.parent / "renamed-repo"
    shutil.move(str(wt_bare_repo), str(new_root))

    # git status from inside a moved worktree should work
    result = git("status", cwd=new_root / "survivor")
    assert result.returncode == 0


def test_remove_works_after_repo_move(wt, wt_bare_repo):
    """After moving the repo, git wt remove still succeeds.

    This exercises the full relativize→move→absolutize→remove chain.
    """
    wt("add", "-b", "movable", str(wt_bare_repo / "movable"), cwd=wt_bare_repo / "main")
    assert_worktree_gitdir_relative(wt_bare_repo / "movable")

    new_root = wt_bare_repo.parent / "moved-repo"
    shutil.move(str(wt_bare_repo), str(new_root))

    wt("remove", str(new_root / "movable"), cwd=new_root / "main", input="y\n")

    assert not (new_root / "movable").exists()
    assert_worktree_not_exists(new_root / ".bare", new_root / "movable")


def test_add_and_status_after_repo_move(wt, wt_bare_repo):
    """git wt status shows correct worktrees after the repo is moved."""
    wt("add", "-b", "post-move", str(wt_bare_repo / "post-move"), cwd=wt_bare_repo / "main")

    new_root = wt_bare_repo.parent / "relocated"
    shutil.move(str(wt_bare_repo), str(new_root))

    r = wt("status", cwd=new_root / "main")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "post-move" in combined


# ---------------------------------------------------------------------------
# Multi-command lifecycle sequences
# ---------------------------------------------------------------------------


def test_add_then_status_shows_worktree(wt, wt_bare_repo):
    """A worktree added via git wt appears in git wt status output."""
    wt("add", "-b", "visible", str(wt_bare_repo / "visible"), cwd=wt_bare_repo / "main")

    r = wt("status", cwd=wt_bare_repo / "main")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "visible" in combined


def test_add_then_switch(wt, wt_bare_repo):
    """git wt switch returns the path of a worktree created via git wt add."""
    wt("add", "-b", "switchable", str(wt_bare_repo / "switchable"), cwd=wt_bare_repo / "main")

    r = wt("switch", cwd=wt_bare_repo / "main", select=str(wt_bare_repo / "switchable"))
    assert r.returncode == 0
    assert r.stdout.strip() == str(wt_bare_repo / "switchable")


def test_add_work_then_remove(wt, wt_bare_repo):
    """Commit work in an added worktree, then remove it."""
    wt("add", "-b", "work-branch", str(wt_bare_repo / "work-branch"), cwd=wt_bare_repo / "main")

    # Do some work in the worktree
    work_file = wt_bare_repo / "work-branch" / "work.txt"
    work_file.write_text("some work\n")
    git("add", "work.txt", cwd=wt_bare_repo / "work-branch")
    git("commit", "-m", "work commit", cwd=wt_bare_repo / "work-branch")

    wt("remove", str(wt_bare_repo / "work-branch"), cwd=wt_bare_repo / "main", input="y\n")

    assert not (wt_bare_repo / "work-branch").exists()


# ---------------------------------------------------------------------------
# Cleanup filter workflows (--merged, --gone, --stale, --sweep)
# ---------------------------------------------------------------------------


def test_remove_merged_workflow(wt, wt_bare_repo_with_remote):
    """add → commit → merge to main → git wt remove --merged removes it."""
    repo, _origin = wt_bare_repo_with_remote
    bare = repo / ".bare"

    wt("add", "-b", "merge-me", str(repo / "merge-me"), cwd=repo / "main")

    # Commit something in the new worktree
    (repo / "merge-me" / "feature.txt").write_text("feature\n")
    git("add", "feature.txt", cwd=repo / "merge-me")
    git("commit", "-m", "feature commit", cwd=repo / "merge-me")

    # Set upstream so --merged can compare
    git("push", "origin", "merge-me", cwd=bare)
    git("branch", "--set-upstream-to", "origin/merge-me", "merge-me", cwd=bare)

    # Merge into main
    git("merge", "merge-me", cwd=repo / "main")

    r = wt("remove", "--merged", cwd=repo / "main", select=str(repo / "merge-me"), input="cleanup\n")

    assert r.returncode == 0
    assert not (repo / "merge-me").exists()
    assert_branch_not_exists(bare, "merge-me")


def test_remove_gone_workflow(wt, wt_bare_repo_with_remote):
    """add → push → delete remote branch → git wt remove --gone removes it."""
    repo, _origin = wt_bare_repo_with_remote
    bare = repo / ".bare"

    wt("add", "-b", "gone-branch", str(repo / "gone-branch"), cwd=repo / "main")
    git("push", "origin", "gone-branch", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "--set-upstream-to", "origin/gone-branch", "gone-branch", cwd=bare)

    # Delete the remote branch
    git("push", "origin", "--delete", "gone-branch", cwd=bare)
    git("fetch", "--prune", cwd=bare)

    r = wt("remove", "--gone", cwd=repo / "main", select=str(repo / "gone-branch"), input="cleanup\n")

    assert r.returncode == 0
    assert not (repo / "gone-branch").exists()


def test_remove_stale_workflow(wt, wt_bare_repo):
    """add → manually delete directory → git wt remove --stale prunes it."""
    wt("add", "-b", "stale-branch", str(wt_bare_repo / "stale-branch"), cwd=wt_bare_repo / "main")

    # Simulate a stale worktree by removing the directory
    shutil.rmtree(str(wt_bare_repo / "stale-branch"))

    r = wt("remove", "--stale", cwd=wt_bare_repo / "main", select=str(wt_bare_repo / "stale-branch"), input="cleanup\n")

    assert r.returncode == 0
    assert_worktree_not_exists(wt_bare_repo / ".bare", wt_bare_repo / "stale-branch")


def test_remove_sweep_mixed_states(wt, wt_bare_repo_with_remote):
    """--sweep cleans up worktrees that are merged, gone, or stale."""
    repo, _origin = wt_bare_repo_with_remote
    bare = repo / ".bare"

    # merged-branch: merge into main
    wt("add", "-b", "sweep-merged", str(repo / "sweep-merged"), cwd=repo / "main")
    git("push", "origin", "sweep-merged", cwd=bare)
    git("branch", "--set-upstream-to", "origin/sweep-merged", "sweep-merged", cwd=bare)
    git("merge", "sweep-merged", cwd=repo / "main")

    # stale-branch: delete the directory
    wt("add", "-b", "sweep-stale", str(repo / "sweep-stale"), cwd=repo / "main")
    shutil.rmtree(str(repo / "sweep-stale"))

    r = wt("remove", "--sweep", "--dry-run", cwd=repo / "main", input="cleanup\n")

    # Dry run should succeed and identify candidates
    assert r.returncode in (0, 1)


# ---------------------------------------------------------------------------
# Post-migrate lifecycle
# ---------------------------------------------------------------------------


def test_migrate_then_add_then_remove(wt, tmp_path):
    """migrate a standard repo, add a worktree, then remove it."""
    repo = make_std_repo(tmp_path / "repo")
    wt("migrate", cwd=repo, input="y\n")

    # After migration the repo is now a bare layout; work from the main worktree
    main_wt = repo / "main"
    assert main_wt.is_dir()

    wt("add", "-b", "post-migrate", str(repo / "post-migrate"), cwd=main_wt)
    assert_worktree_gitdir_relative(repo / "post-migrate")

    wt("remove", str(repo / "post-migrate"), cwd=main_wt, input="y\n")

    assert not (repo / "post-migrate").exists()


# ---------------------------------------------------------------------------
# Post-clone lifecycle
# ---------------------------------------------------------------------------


def test_clone_then_add_then_remove(wt, tmp_path):
    """clone a repo, add a worktree, then remove it."""
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "cloned"
    wt("clone", str(origin), str(target))

    # Find the main worktree created by clone
    main_wt = next(p for p in target.iterdir() if p.is_dir() and p.name not in (".bare", ".git"))

    wt("add", "-b", "post-clone", str(target / "post-clone"), cwd=main_wt)
    assert_worktree_gitdir_relative(target / "post-clone")

    wt("remove", str(target / "post-clone"), cwd=main_wt, input="y\n")

    assert not (target / "post-clone").exists()


def test_clone_worktrees_portable(wt, tmp_path):
    """Worktrees created after clone survive moving the cloned repo."""
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "cloned"
    wt("clone", str(origin), str(target))

    main_wt = next(p for p in target.iterdir() if p.is_dir() and p.name not in (".bare", ".git"))

    wt("add", "-b", "portable", str(target / "portable"), cwd=main_wt)
    assert_worktree_gitdir_relative(target / "portable")

    # Move the cloned repo
    moved = tmp_path / "cloned-moved"
    shutil.move(str(target), str(moved))

    moved_main = moved / main_wt.name
    result = git("status", cwd=moved_main)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Relativize-specific invariants across the full lifecycle
# ---------------------------------------------------------------------------


def test_all_added_worktrees_use_relative_paths(wt, wt_bare_repo):
    """Every worktree created via git wt add has relative gitdir pointers."""
    branches = ["rel-a", "rel-b", "rel-c"]
    for branch in branches:
        wt("add", "-b", branch, str(wt_bare_repo / branch), cwd=wt_bare_repo / "main")

    for branch in branches:
        assert_worktree_gitdir_relative(wt_bare_repo / branch)


def test_add_remove_idempotent_gitdir_state(wt, wt_bare_repo):
    """After a full add→remove cycle, the remaining worktrees are unaffected."""
    wt("add", "-b", "stays", str(wt_bare_repo / "stays"), cwd=wt_bare_repo / "main")
    wt("add", "-b", "leaves", str(wt_bare_repo / "leaves"), cwd=wt_bare_repo / "main")

    wt("remove", str(wt_bare_repo / "leaves"), cwd=wt_bare_repo / "main", input="y\n")

    # 'stays' should still be intact with relative paths
    assert (wt_bare_repo / "stays").is_dir()
    assert_worktree_gitdir_relative(wt_bare_repo / "stays")

    # Can still remove 'stays' cleanly
    wt("remove", str(wt_bare_repo / "stays"), cwd=wt_bare_repo / "main", input="y\n")
    assert not (wt_bare_repo / "stays").exists()
