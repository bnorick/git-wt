"""Tests for git wt list."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from conftest import create_branch, create_worktree, git

from git_wt import _worktree
from git_wt.list import _sanitize_human, _sanitize_porcelain


def _native_list(cwd, *extra_args):
    """Run native git worktree list and return stdout."""
    return git("worktree", "list", *extra_args, cwd=cwd).stdout


def _has_prunable_annotation(output: str) -> bool:
    return any(
        line.startswith("prunable ") or line.lstrip().startswith("prunable:") or line.endswith(" prunable")
        for line in output.splitlines()
    )


def _relativize(output: str, repo_root: Path) -> str:
    """Strip repo_root prefix from each path line in git worktree list output."""
    prefix = str(repo_root) + "/"
    lines = output.splitlines(keepends=True)
    result = []
    for line in lines:
        text = line.rstrip("\n\r")
        nl = line[len(text) :]
        if text.startswith(prefix):
            result.append(text.removeprefix(prefix) + nl)
        else:
            result.append(line)
    return "".join(result)


def _normalize_columns(output: str) -> str:
    """Normalize Git's version-dependent list alignment separators."""
    return "\n".join(re.sub(r"\s+", " ", line).rstrip() for line in output.splitlines())


def test_list_shows_relative_paths(wt, bare_repo):
    """list output uses paths relative to the repo root."""
    r = wt("list", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert str(bare_repo) not in r.stdout
    assert ".bare" in r.stdout
    assert "main" in r.stdout


def test_list_passes_through_detached_worktrees(wt, bare_repo):
    """list output includes detached worktrees with relative paths."""
    ref = git("rev-parse", "HEAD", cwd=bare_repo / "main").stdout.strip()
    git("worktree", "add", "--detach", str(bare_repo / "detached-wt"), ref, cwd=bare_repo / ".bare")

    native = _native_list(bare_repo / "main")
    expected = _relativize(native, bare_repo)
    r = wt("list", cwd=bare_repo / "main")
    assert r.returncode == 0
    assert _normalize_columns(r.stdout) == _normalize_columns(expected)


def test_list_works_from_worktree_subdirectory(wt, bare_repo):
    """list works when CWD is a subdirectory inside a worktree."""
    create_branch(bare_repo, "sub-feat")
    create_worktree(bare_repo, "sub-feat")
    subdir = bare_repo / "main" / "inner"
    subdir.mkdir()

    native = _native_list(subdir)
    expected = _relativize(native, bare_repo)
    r = wt("list", cwd=subdir)
    assert r.returncode == 0
    assert _normalize_columns(r.stdout) == _normalize_columns(expected)


def test_list_debug_mode_does_not_suppress_output(wt, bare_repo):
    """DEBUG=1 does not suppress list output."""
    create_branch(bare_repo, "debug-list")
    create_worktree(bare_repo, "debug-list")

    native = _native_list(bare_repo / "main")
    expected = _relativize(native, bare_repo)
    r = wt("list", cwd=bare_repo / "main", env={"DEBUG": "1"})
    assert r.returncode == 0
    assert _normalize_columns(r.stdout) == _normalize_columns(expected)


def test_list_json_outputs_structured_entries(wt, bare_repo):
    """--json returns machine-readable entries and never prints progress to stdout."""
    create_branch(bare_repo, "json-feature")
    create_worktree(bare_repo, "json-feature")

    r = wt("list", "--json", cwd=bare_repo / "main")
    assert r.returncode == 0
    rows = json.loads(r.stdout)
    assert "json-feature" in {row["path"] for row in rows}
    assert {row["branch"] for row in rows} >= {"main", "json-feature"}


def test_list_ls_alias(wt, bare_repo):
    """ls is an alias for list."""
    r_list = wt("list", cwd=bare_repo / "main")
    r_ls = wt("ls", cwd=bare_repo / "main")
    assert r_list.returncode == 0
    assert r_ls.returncode == 0
    assert r_ls.stdout == r_list.stdout


def test_list_hides_false_prunable_for_live_relative_worktree(wt, wt_bare_repo):
    """Old Git's false annotation is corrected in every text format."""
    cwd = wt_bare_repo / "main"

    for args in (("list",), ("list", "-v"), ("list", "--porcelain")):
        r = wt(*args, cwd=cwd)
        assert not _has_prunable_annotation(r.stdout)


def test_list_model_clears_false_prunable(wt_bare_repo):
    entries = _worktree.list_worktrees(dir=wt_bare_repo / "main")
    main = next(entry for entry in entries if entry.branch == "main")
    assert not main.prunable
    assert main.prunable_reason == ""


def test_list_preserves_genuine_prunable_worktree(wt, wt_bare_repo):
    """A missing worktree remains prunable in every text format."""
    main = wt_bare_repo / "main"
    shutil.rmtree(main)

    for args in (("list",), ("list", "-v"), ("list", "--porcelain")):
        r = wt(*args, cwd=wt_bare_repo)
        assert _has_prunable_annotation(r.stdout)


def test_sanitize_porcelain_preserves_newline_delimiters(tmp_path):
    dot_git = tmp_path / "work tree" / ".git"
    dot_git.parent.mkdir()
    dot_git.write_text("gitdir: admin\n")
    targets = {"../work tree": dot_git}
    raw = "worktree ../work tree\nHEAD abc123\nprunable gitdir file points to non-existent location\n\n"

    assert _sanitize_porcelain(raw, targets, "\n") == ("worktree ../work tree\nHEAD abc123\n\n")


def test_sanitize_porcelain_preserves_nul_delimiters(tmp_path):
    dot_git = tmp_path / "main" / ".git"
    dot_git.parent.mkdir()
    dot_git.write_text("gitdir: admin\n")
    targets = {"../main": dot_git}
    raw = "worktree ../main\0HEAD abc123\0prunable gitdir file points to non-existent location\0\0"

    assert _sanitize_porcelain(raw, targets, "\0") == ("worktree ../main\0HEAD abc123\0\0")


def test_sanitize_human_handles_worktree_path_with_spaces(tmp_path):
    dot_git = tmp_path / "work tree" / ".git"
    dot_git.parent.mkdir()
    dot_git.write_text("gitdir: admin\n")
    targets = {"../work tree": dot_git}

    output = "../work tree  abc123 [main] prunable"
    assert _sanitize_human(output, targets) == "../work tree  abc123 [main]"
