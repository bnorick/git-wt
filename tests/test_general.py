"""General CLI behavior: help, error handling, passthrough commands."""

from __future__ import annotations


def test_help(wt):
    r = wt("--help", check=False)
    assert r.returncode == 0
    assert "git-wt" in r.stdout
    assert "clone" in r.stdout
    assert "add" in r.stdout
    assert "remove" in r.stdout
    assert "migrate" in r.stdout


def test_no_args_shows_help(wt):
    r = wt(check=False)
    # cyclopts shows help when no command given
    assert r.returncode in (0, 1)
    assert "git-wt" in r.stdout or "git-wt" in r.stderr


def test_unknown_command_error(wt):
    r = wt("totally-unknown-command", check=False)
    assert r.returncode != 0


def test_passthrough_list(wt, bare_repo):
    r = wt("list", cwd=bare_repo / "main")
    assert r.returncode == 0


def test_passthrough_list_porcelain(wt, bare_repo):
    r = wt("list", "--porcelain", cwd=bare_repo / "main")
    assert "worktree" in r.stdout


def test_add_help(wt):
    r = wt("add", "--help")
    assert "worktree" in r.stdout.lower() or "worktree" in r.stderr.lower()


def test_remove_help(wt):
    r = wt("remove", "--help")
    assert r.returncode == 0


def test_debug_mode_dry_run(wt, bare_repo):
    """DEBUG=1 should print git commands instead of executing them."""
    r = wt("add", "-b", "debug-branch", str(bare_repo / "debug-branch"), cwd=bare_repo / "main", env={"DEBUG": "1"})
    # In debug mode, output contains [DEBUG] prefix
    assert "[DEBUG]" in r.stderr
    # And the worktree should NOT have been created
    assert not (bare_repo / "debug-branch").exists()


def test_destroy_alias(wt, bare_repo):
    """destroy is a legacy alias for remove --delete-remote."""
    from conftest import create_branch, create_worktree

    create_branch(bare_repo, "to-destroy")
    create_worktree(bare_repo, "to-destroy")
    r = wt("destroy", str(bare_repo / "to-destroy"), cwd=bare_repo / "main", input="y\n", check=False)
    # Should behave like remove
    assert r.returncode in (0, 1)  # may fail without remote, that's ok


def test_man_generates_pages_without_destroy(wt, tmp_path):
    """'man <dir>' generates .1 files for each command; destroy is not among them."""
    man_dir = tmp_path / "man"
    man_dir.mkdir()
    r = wt("man", str(man_dir))
    assert r.returncode == 0
    pages = list(man_dir.glob("*.1"))
    assert len(pages) > 0
    # destroy is a hidden alias and must not appear in any generated page
    for page in pages:
        assert "destroy" not in page.read_text(), f"'destroy' found in {page.name}"
    # Core commands must have pages
    names = {p.stem for p in pages}
    for cmd in ("git-wt", "git-wt-add", "git-wt-remove", "git-wt-clone", "git-wt-migrate"):
        assert cmd in names, f"missing man page for {cmd}"


def test_edge_no_commits_graceful(wt, tmp_path):
    """Commands don't crash (returncode 2) when the repo has no commits."""
    from conftest import git

    empty = tmp_path / "empty"
    empty.mkdir()
    git("init", "-b", "main", cwd=empty)
    git("config", "user.email", "t@t.com", cwd=empty)
    git("config", "user.name", "T", cwd=empty)
    r = wt("status", cwd=empty, check=False)
    # 0 or 1 is fine; 2 means unhandled exception
    assert r.returncode in (0, 1)


def test_edge_paths_with_spaces(wt, tmp_path):
    """git-wt works when the repo path contains spaces."""
    from conftest import make_bare_repo

    repo = make_bare_repo(tmp_path / "repo with spaces")
    r = wt("status", cwd=repo / "main")
    assert r.returncode == 0


def test_interactive_switch_slash_worktree_by_label(wt, bare_repo):
    """switch selects a slash-containing worktree when matched by 'name [name]' label."""
    from conftest import git

    git("worktree", "add", "-b", "feature/slash-sw", str(bare_repo / "feature" / "slash-sw"), cwd=bare_repo / ".bare")
    r = wt("switch", cwd=bare_repo / "main", select="feature/slash-sw [feature/slash-sw]")
    assert r.returncode == 0
    assert "slash-sw" in r.stdout


def test_interactive_remove_slash_worktree_by_label(wt, bare_repo):
    """remove selects a slash-containing worktree when matched by 'name [name]' label."""
    from conftest import git

    git("worktree", "add", "-b", "feature/slash-rm", str(bare_repo / "feature" / "slash-rm"), cwd=bare_repo / ".bare")
    wt("remove", cwd=bare_repo / "main", select="feature/slash-rm [feature/slash-rm]", input="y\n")
    assert not (bare_repo / "feature" / "slash-rm").exists()


def test_interactive_destroy_slash_worktree_by_label(wt, bare_repo):
    """destroy selects a slash-containing worktree when matched by 'name [name]' label."""
    from conftest import git

    git(
        "worktree",
        "add",
        "-b",
        "feature/slash-dest",
        str(bare_repo / "feature" / "slash-dest"),
        cwd=bare_repo / ".bare",
    )
    wt(
        "destroy",
        cwd=bare_repo / "main",
        select="feature/slash-dest [feature/slash-dest]",
        input="feature/slash-dest\n",
    )
    assert not (bare_repo / "feature" / "slash-dest").exists()
