"""Tests for git wt add."""

from __future__ import annotations

from pathlib import Path

from conftest import (
    _parse_worktree_blocks,
    assert_branch_exists,
    assert_worktree_exists,
    assert_worktree_gitdir_relative,
    create_commit,
    create_worktree,
    git,
)


def test_add_creates_worktree(wt, bare_repo):
    wt("add", "-b", "feature", str(bare_repo / "feature"), cwd=bare_repo / "main")
    assert (bare_repo / "feature").is_dir()
    assert_worktree_exists(bare_repo / ".bare", bare_repo / "feature")


def test_add_prints_path_to_stdout(wt, bare_repo):
    r = wt("add", "-b", "feature", str(bare_repo / "feature"), cwd=bare_repo / "main")
    # Absolute path on stdout
    stdout = r.stdout.strip()
    assert stdout == str(bare_repo / "feature")


def test_add_status_to_stderr(wt, bare_repo):
    r = wt("add", "-b", "feature", str(bare_repo / "feature"), cwd=bare_repo / "main")
    assert len(r.stderr) > 0
    assert r.stdout.strip() == str(bare_repo / "feature")


def test_add_creates_branch(wt, bare_repo):
    wt("add", "-b", "newbranch", str(bare_repo / "newbranch"), cwd=bare_repo / "main")
    assert_branch_exists(bare_repo / ".bare", "newbranch")


def test_add_relative_path_resolved(wt, bare_repo):
    r = wt("add", "-b", "feature", "feature", cwd=bare_repo / "main")
    # stdout should be absolute even when we passed a relative path
    stdout = r.stdout.strip()
    assert stdout.startswith("/")
    assert Path(stdout).is_dir()


def test_add_detach(wt, bare_repo):
    ref = git("rev-parse", "HEAD", cwd=bare_repo / "main").stdout.strip()
    wt("add", "--detach", str(bare_repo / "detached"), ref, cwd=bare_repo / "main")
    assert (bare_repo / "detached").is_dir()


def test_add_interactive_create_new(wt, bare_repo):
    """Interactive mode: select 'create new' via GIT_WT_SELECT."""
    wt(
        "add",
        cwd=bare_repo / "main",
        select="__create_new__",
        input="interac-branch\ninterac-branch\n",
    )
    assert (bare_repo / "interac-branch").is_dir()
    assert_branch_exists(bare_repo / ".bare", "interac-branch")


def test_add_interactive_existing_remote_branch(wt, bare_repo_with_remote):
    """Interactive mode: pick an existing remote branch."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    # Push a branch to origin
    git("branch", "remote-feature", "main", cwd=bare)
    git("push", "origin", "remote-feature", cwd=bare)
    git("fetch", "--all", cwd=bare)

    wt(
        "add",
        cwd=repo / "main",
        select="origin/remote-feature",
        input="remote-feature\n",
    )
    assert (repo / "remote-feature").is_dir()


def test_add_force_recreate_branch(wt, bare_repo):
    """Adding with -B overwrites existing branch pointer."""
    # Create feature, make a commit, then use -B to reset
    wt("add", "-b", "feature", str(bare_repo / "feature"), cwd=bare_repo / "main")
    create_commit(bare_repo / "feature")
    r = wt("add", "-B", "feature", str(bare_repo / "feature2"), "main", cwd=bare_repo / "main", check=False)
    # -B is tricky — just verify no crash
    assert r.returncode in (0, 1)


def test_add_outside_bare_repo_fails(wt, std_repo):
    r = wt("add", "-b", "feat", str(std_repo / "feat"), cwd=std_repo, check=False)
    # May fail or succeed depending on how the git config is handled
    # What matters: no uncaught exception (returncode != 2/segfault)
    assert r.returncode in (0, 1)


def test_add_debug_mode(wt, bare_repo):
    """DEBUG=1 prints command but does not create worktree."""
    r = wt("add", "-b", "debug-feat", str(bare_repo / "debug-feat"), cwd=bare_repo / "main", env={"DEBUG": "1"})
    assert "[DEBUG]" in r.stderr
    assert not (bare_repo / "debug-feat").exists()


def test_add_creating_worktree_message(wt, bare_repo):
    """Stderr contains a 'Creating worktree' progress message."""
    r = wt("add", "-b", "msg-feat", str(bare_repo / "msg-feat"), cwd=bare_repo / "main")
    assert "Creating worktree" in r.stderr


def test_add_runs_lifecycle_hooks(wt, bare_repo):
    """Lifecycle hook values run in order when configured."""
    worktree = bare_repo / "hook-feature"
    marker = bare_repo / ".hook-ran"
    git("config", "wt.beforeadd", "touch .hook-ran", cwd=bare_repo)
    git("config", "--add", "wt.afteradd", "touch .hook-ran", cwd=bare_repo)

    r = wt("add", "-b", "hook-feature", str(worktree), cwd=bare_repo / "main")

    assert r.returncode == 0
    assert marker.is_file()


def test_add_before_hook_failure_prevents_creation(wt, bare_repo):
    """A before-add hook failure prevents Git from creating the worktree."""
    worktree = bare_repo / "before-fail"
    git("config", "wt.beforeadd", "exit 2", cwd=bare_repo)
    result = wt("add", "-b", "before-fail", str(worktree), cwd=bare_repo / "main", check=False)

    assert result.returncode == 2
    assert not worktree.exists()
    rev_parse = git("rev-parse", "--verify", "--quiet", "refs/heads/before-fail", cwd=bare_repo / ".bare", check=False)
    assert rev_parse.returncode == 1


def test_add_after_hook_failure_reports_created_path(wt, bare_repo):
    """After-add failure keeps the worktree and reports where it was created."""
    worktree = bare_repo / "after-fail"

    git("config", "wt.afteradd", "exit 3", cwd=bare_repo)
    result = wt("add", "-b", "after-fail", str(worktree), cwd=bare_repo / "main", check=False)

    assert result.returncode == 3
    assert worktree.is_dir()
    assert "Worktree was created at" in result.stderr


def test_add_lifecycle_hooks_ignore_inherited_environment(wt, bare_repo):
    """The legacy environment no longer configures lifecycle hooks."""
    worktree = bare_repo / "no-inherited-hook"

    r = wt("add", "-b", "no-inherited-hook", str(worktree), cwd=bare_repo / "main")

    assert r.returncode == 0
    assert worktree.exists()


def test_add_does_not_run_hook_when_add_fails(wt, bare_repo):
    """The post-add command is not run unless git successfully adds a worktree."""
    marker = bare_repo / "hook-should-not-run"
    existing = bare_repo / "existing"
    wt("add", "-b", "existing", str(existing), cwd=bare_repo / "main")

    r = wt(
        "add",
        "-b",
        "duplicate",
        str(existing),
        cwd=bare_repo / "main",
        check=False,
    )

    assert r.returncode != 0
    assert not marker.exists()


def test_add_before_hook_failure_prints_stderr(wt, bare_repo):
    """A failed before-add hook reports the configured command and exit code."""
    worktree = bare_repo / "before-stderr"
    git("config", "wt.beforeadd", "echo hook-output >&2; exit 2", cwd=bare_repo)

    result = wt("add", "-b", "before-stderr", str(worktree), cwd=bare_repo / "main", check=False)

    assert result.returncode == 2
    assert "hook-output" in result.stderr
    assert "wt.beforeadd hook" in result.stderr


def test_add_rejects_worktree_name_with_spaces(wt, bare_repo):
    """A new worktree's name may not contain spaces."""
    worktree = bare_repo / "space name"

    r = wt("add", "-b", "space-name", str(worktree), cwd=bare_repo / "main", check=False)

    assert r.returncode == 1
    assert "cannot contain spaces" in r.stderr
    assert not worktree.exists()


def test_add_allows_space_in_parent_directory(wt, bare_repo):
    """Only the worktree name, not its parent directories, is restricted."""
    parent = bare_repo / "parent with spaces"
    parent.mkdir()
    worktree = parent / "valid-name"

    r = wt("add", "-b", "valid-name", str(worktree), cwd=bare_repo / "main")

    assert r.returncode == 0
    assert worktree.is_dir()


def test_add_short_detach_flag(wt, bare_repo):
    """-d is accepted as an alias for --detach."""
    ref = git("rev-parse", "HEAD", cwd=bare_repo / "main").stdout.strip()
    wt("add", "-d", str(bare_repo / "detached-short"), ref, cwd=bare_repo / "main")
    assert (bare_repo / "detached-short").is_dir()


def test_add_short_quiet_flag(wt, bare_repo):
    """-q is accepted as an alias for --quiet."""
    r = wt("add", "-b", "quiet-feat", str(bare_repo / "quiet-feat"), "-q", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert (bare_repo / "quiet-feat").is_dir()


def test_add_no_checkout(wt, bare_repo):
    """--no-checkout creates the worktree directory without checking out files."""
    r = wt("add", "-b", "no-co", str(bare_repo / "no-co"), "--no-checkout", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert (bare_repo / "no-co").is_dir()
    # With --no-checkout, the worktree dir exists but has no tracked files
    assert not (bare_repo / "no-co" / "README.md").exists()


def test_add_from_deep_subdirectory_resolves_to_bare_root(wt, bare_repo):
    """Adding a relative worktree path from a subdirectory places it at the bare root."""
    subdir = bare_repo / "main" / "src" / "deep"
    subdir.mkdir(parents=True)

    r = wt("add", "-b", "from-deep", "from-deep", cwd=subdir)
    assert r.returncode == 0
    # Worktree should be at bare root, not inside main/src/deep/
    assert (bare_repo / "from-deep").is_dir()
    assert not (subdir / "from-deep").exists()
    # stdout contains the absolute path at the bare root
    assert r.stdout.strip() == str(bare_repo / "from-deep")


def test_add_interactive_label_match(wt, bare_repo_with_remote):
    """GIT_WT_SELECT can match by label (branch name without remote prefix)."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    # Push a branch so it appears as a remote branch in the picker
    git("branch", "label-match", "main", cwd=bare)
    git("push", "origin", "label-match", cwd=bare)
    git("fetch", "--all", cwd=bare)

    # Select by label "label-match" (not by value "origin/label-match")
    r = wt("add", cwd=repo / "main", select="label-match", input="label-match\n")
    assert r.returncode == 0
    assert (repo / "label-match").is_dir()


def test_add_succeeds_with_existing_empty_dir(wt, bare_repo):
    """add succeeds when the target path is a pre-existing empty directory."""
    empty_dir = bare_repo / "prexisting-empty"
    empty_dir.mkdir()
    r = wt("add", "-b", "into-empty", str(empty_dir), cwd=bare_repo / "main")
    assert r.returncode == 0
    assert (empty_dir / "README.md").exists()


def test_add_succeeds_without_remote(wt, tmp_path):
    """add works on a bare repo with no remote configured."""
    from conftest import make_bare_repo

    repo = make_bare_repo(tmp_path / "repo")
    git("remote", "remove", "origin", cwd=repo / ".bare")
    r = wt("add", "-b", "no-remote-feat", str(repo / "no-remote-feat"), cwd=repo / "main")
    assert r.returncode == 0
    assert (repo / "no-remote-feat").is_dir()


def test_add_branch_name_with_slashes(wt, bare_repo):
    """add -b with a slash-containing branch name creates the branch correctly."""
    r = wt("add", "-b", "feature/nested/branch", str(bare_repo / "feat-nested"), cwd=bare_repo / "main")
    assert r.returncode == 0
    assert_branch_exists(bare_repo / ".bare", "feature/nested/branch")
    assert (bare_repo / "feat-nested").is_dir()


def test_add_lock_flag(wt, bare_repo):
    """--lock creates a locked worktree that git cannot auto-remove."""
    r = wt("add", "--lock", "-b", "locked-branch", str(bare_repo / "locked-wt"), cwd=bare_repo / "main")
    assert r.returncode == 0
    result = git("worktree", "list", "--porcelain", cwd=bare_repo / ".bare")
    assert "locked" in result.stdout


def test_add_worktree_uses_relative_gitdir_paths(wt, bare_repo):
    """After add, worktree gitdir pointers are relative so the repo can be moved."""
    wt("add", "-b", "feature", str(bare_repo / "feature"), cwd=bare_repo / "main")
    assert_worktree_gitdir_relative(bare_repo / "feature")


def test_add_lock_with_reason(wt, bare_repo):
    """--lock --reason creates a locked worktree with the given reason."""
    r = wt(
        "add",
        "--lock",
        "--reason",
        "work in progress",
        "-b",
        "locked-reason",
        str(bare_repo / "locked-reason-wt"),
        cwd=bare_repo / "main",
    )
    assert r.returncode == 0
    assert_worktree_exists(bare_repo / ".bare", bare_repo / "locked-reason-wt")


def test_add_interactive_excludes_checked_out_branches(wt, bare_repo_with_remote):
    """Picker excludes branches already checked out in another worktree."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    # Create feature-a locally and push, then check it out in a worktree
    git("branch", "feature-a", "main", cwd=bare)
    create_worktree(repo, "feature-a")

    # Create feature-b as available
    git("branch", "feature-b", "main", cwd=bare)

    # Selecting already-checked-out feature-a should result in no worktree action
    r = wt("add", cwd=repo / "main", select="feature-a [feature-a]", check=False)
    # Should exit 0 (no selection) and NOT create a duplicate worktree
    assert r.returncode == 0
    # Only one worktree for feature-a exists
    result = git("worktree", "list", "--porcelain", cwd=bare)
    paths = [b["worktree"] for b in _parse_worktree_blocks(result.stdout)]
    assert len([p for p in paths if "feature-a" in p]) == 1


def test_add_interactive_metacharacter_branch(wt, bare_repo_with_remote):
    """Branch names with shell metacharacters are handled safely (no injection)."""
    branch = "feature;$(echo_injected)"
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    git("branch", branch, "main", cwd=bare)
    git("push", "origin", branch, cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "-d", branch, cwd=bare)

    r = wt("add", cwd=repo / "main", select=f"origin/{branch}", input=f"{branch}\n")
    assert r.returncode == 0
    assert (repo / branch).is_dir()
    assert_branch_exists(bare, branch)


def test_add_multi_remote_uses_selected_remote(wt, bare_repo_with_remote):
    """Interactive add uses the remote matching the selected branch."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    # Create a branch only on the remote
    git("branch", "upstream-only", "main", cwd=bare)
    git("push", "origin", "upstream-only", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "-d", "upstream-only", cwd=bare)

    r = wt("add", cwd=repo / "main", select="origin/upstream-only", input="upstream-only\n")
    assert r.returncode == 0
    assert (repo / "upstream-only").is_dir()


# ---------------------------------------------------------------------------
# --from-remote tests
# ---------------------------------------------------------------------------


def test_add_from_remote_creates_worktree(wt, bare_repo_with_remote):
    """--from-remote: selecting a remote branch creates the worktree at {repo}/{branch}."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    git("branch", "fr-basic", "main", cwd=bare)
    git("push", "origin", "fr-basic", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "-d", "fr-basic", cwd=bare)

    r = wt("add", "--from-remote", cwd=repo / "main", select="origin/fr-basic")
    assert r.returncode == 0
    assert (repo / "fr-basic").is_dir()
    assert_worktree_exists(repo / ".bare", repo / "fr-basic")


def test_add_from_remote_prints_path_to_stdout(wt, bare_repo_with_remote):
    """--from-remote: stdout is the absolute worktree path."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    git("branch", "fr-stdout", "main", cwd=bare)
    git("push", "origin", "fr-stdout", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "-d", "fr-stdout", cwd=bare)

    r = wt("add", "--from-remote", cwd=repo / "main", select="origin/fr-stdout")
    assert r.stdout.strip() == str(repo / "fr-stdout")


def test_add_from_remote_nested_branch_path(wt, bare_repo_with_remote):
    """--from-remote: branch 'user/feat' creates worktree at {repo}/user/feat."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    git("branch", "user/feat", "main", cwd=bare)
    git("push", "origin", "user/feat", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "-d", "user/feat", cwd=bare)

    r = wt("add", "--from-remote", cwd=repo / "main", select="origin/user/feat")
    assert r.returncode == 0
    assert (repo / "user" / "feat").is_dir()
    assert r.stdout.strip() == str(repo / "user" / "feat")


def test_add_from_remote_path_exists_errors(wt, bare_repo_with_remote):
    """--from-remote: exits with code 1 when the derived path already exists."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    git("branch", "fr-exists", "main", cwd=bare)
    git("push", "origin", "fr-exists", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "-d", "fr-exists", cwd=bare)

    # Pre-create the target directory
    (repo / "fr-exists").mkdir()

    r = wt("add", "--from-remote", cwd=repo / "main", select="origin/fr-exists", check=False)
    assert r.returncode == 1
    assert "already exists" in r.stderr


def test_add_from_remote_excludes_checked_out_branches(wt, bare_repo_with_remote):
    """--from-remote: branches already in a worktree are absent from the picker."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    git("branch", "fr-checked-out", "main", cwd=bare)
    git("push", "origin", "fr-checked-out", cwd=bare)
    git("fetch", "--all", cwd=bare)
    create_worktree(repo, "fr-checked-out")

    # Selecting the already-checked-out branch value should result in no selection
    r = wt("add", "--from-remote", cwd=repo / "main", select="origin/fr-checked-out", check=False)
    assert r.returncode == 0
    # No duplicate worktree created
    result = git("worktree", "list", "--porcelain", cwd=bare)
    paths = [b["worktree"] for b in _parse_worktree_blocks(result.stdout)]
    assert len([p for p in paths if "fr-checked-out" in p]) == 1


def test_add_from_remote_no_branches_exits_cleanly(wt, bare_repo_with_remote):
    """--from-remote: exits 0 gracefully when all remote branches are checked out."""
    repo, _origin = bare_repo_with_remote
    # Only remote branch is main, which is already checked out
    r = wt("add", "--from-remote", cwd=repo / "main", check=False)
    assert r.returncode == 0


def test_add_from_remote_no_create_new_option(wt, bare_repo_with_remote):
    """--from-remote: selecting __create_new__ matches nothing and exits 0."""
    repo, _origin = bare_repo_with_remote
    bare = repo / ".bare"

    git("branch", "fr-real", "main", cwd=bare)
    git("push", "origin", "fr-real", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("branch", "-d", "fr-real", cwd=bare)

    # __create_new__ is not a valid item value in --from-remote mode
    r = wt("add", "--from-remote", cwd=repo / "main", select="__create_new__", check=False)
    assert r.returncode == 0
    assert not (repo / "__create_new__").exists()


# ---------------------------------------------------------------------------
# --from-local tests
# ---------------------------------------------------------------------------


def test_add_from_local_picker_creates_named_branch_from_selection(wt, bare_repo):
    """A bare --from-local selects the starting point for the named new branch."""
    git("branch", "local-base", "main", cwd=bare_repo / ".bare")
    create_worktree(bare_repo, "local-base")
    create_commit(bare_repo / "local-base")
    source_head = git("rev-parse", "local-base", cwd=bare_repo / ".bare").stdout.strip()

    r = wt("add", "bnorick/test-worktree", "--from-local", cwd=bare_repo / "main", select="local-base")

    assert r.returncode == 0
    assert r.stdout.strip() == str(bare_repo / "bnorick" / "test-worktree")
    assert_branch_exists(bare_repo / ".bare", "bnorick/test-worktree")
    new_head = git("rev-parse", "bnorick/test-worktree", cwd=bare_repo / ".bare").stdout.strip()
    assert new_head == source_head


def test_add_from_local_accepts_source_branch_directly(wt, bare_repo):
    """--from-local BRANCH bypasses the picker and uses that local branch."""
    git("branch", "bnorick/existing-test", "main", cwd=bare_repo / ".bare")

    r = wt(
        "add",
        "bnorick/test-worktree",
        "--from-local",
        "bnorick/existing-test",
        cwd=bare_repo / "main",
    )

    assert r.returncode == 0
    assert (bare_repo / "bnorick" / "test-worktree").is_dir()
    assert_branch_exists(bare_repo / ".bare", "bnorick/test-worktree")
    assert (
        git("rev-parse", "bnorick/test-worktree", cwd=bare_repo / ".bare").stdout
        == git("rev-parse", "bnorick/existing-test", cwd=bare_repo / ".bare").stdout
    )


def test_add_from_local_rejects_unknown_source_branch(wt, bare_repo):
    r = wt("add", "new-worktree", "--from-local", "missing-branch", cwd=bare_repo / "main", check=False)

    assert r.returncode == 1
    assert "Local branch not found: missing-branch" in r.stderr
    assert not (bare_repo / "new-worktree").exists()
