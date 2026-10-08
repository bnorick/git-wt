"""Unit tests for worktree parsing and resolution (no child processes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from git_wt._worktree import (
    Entry,
    display_path,
    parse_porcelain,
    resolve,
    workspace_name,
)

PORCELAIN_SAMPLE = """\
worktree /repo/.bare
HEAD abc1234
bare

worktree /repo/main
HEAD abc1234
branch refs/heads/main

worktree /repo/feature
HEAD def5678
branch refs/heads/feature

worktree /repo/detached
HEAD aaa0000
detached

worktree /repo/locked-wt
HEAD bbb1111
branch refs/heads/locked-branch
locked locked because reason

worktree /repo/prunable-wt
HEAD ccc2222
branch refs/heads/prunable-branch
prunable gitdir file points to non-existent location
"""


class TestParsePorcelain:
    def test_excludes_bare(self):
        entries = parse_porcelain(PORCELAIN_SAMPLE)
        paths = [e.path for e in entries]
        assert "/repo/.bare" not in paths

    def test_parses_regular(self):
        entries = parse_porcelain(PORCELAIN_SAMPLE)
        main = next(e for e in entries if e.branch == "main")
        assert main.path == "/repo/main"
        assert main.head == "abc1234"
        assert not main.detached
        assert not main.locked
        assert not main.prunable

    def test_parses_detached(self):
        entries = parse_porcelain(PORCELAIN_SAMPLE)
        det = next(e for e in entries if "/detached" in e.path)
        assert det.detached
        assert det.branch == ""

    def test_parses_locked(self):
        entries = parse_porcelain(PORCELAIN_SAMPLE)
        locked = next(e for e in entries if "locked-wt" in e.path)
        assert locked.locked
        assert locked.locked_reason == "locked because reason"

    def test_parses_prunable(self):
        entries = parse_porcelain(PORCELAIN_SAMPLE)
        prunable = next(e for e in entries if "prunable-wt" in e.path)
        assert prunable.prunable
        assert "non-existent" in prunable.prunable_reason

    def test_count(self):
        entries = parse_porcelain(PORCELAIN_SAMPLE)
        assert len(entries) == 5  # bare excluded

    def test_empty_input(self):
        assert parse_porcelain("") == []

    def test_no_trailing_blank_line(self):
        out = "worktree /repo/main\nHEAD abc1234\nbranch refs/heads/main"
        entries = parse_porcelain(out)
        assert len(entries) == 1
        assert entries[0].branch == "main"


class TestResolve:
    def _entries(self) -> list[Entry]:
        return [
            Entry(path="/repo/main", branch="main", head="abc1234"),
            Entry(path="/repo/feature", branch="feature", head="def5678"),
            Entry(path="/repo/sub/nested", branch="sub/nested", head="fff0000"),
        ]

    def test_exact_path(self):
        e = resolve(self._entries(), "/repo/main")
        assert e.branch == "main"

    def test_basename(self):
        e = resolve(self._entries(), "feature")
        assert e.branch == "feature"

    def test_basename_ambiguous(self):
        entries = self._entries()
        entries.append(Entry(path="/other/main", branch="other-main", head="000"))
        with pytest.raises(ValueError, match="ambiguous"):
            resolve(entries, "main")

    def test_no_match(self):
        with pytest.raises(ValueError, match="no worktree"):
            resolve(self._entries(), "nonexistent")

    def test_relative_to_root(self):
        root = Path("/repo")
        e = resolve(self._entries(), "feature", root)
        assert e.branch == "feature"


class TestWorkspaceName:
    def test_top_level(self):
        e = Entry(path="/repo/main", branch="main", head="abc")
        assert workspace_name(e, Path("/repo")) == "main"

    def test_nested(self):
        e = Entry(path="/repo/sub/nested", branch="sub/nested", head="abc")
        assert workspace_name(e, Path("/repo")) == "sub/nested"

    def test_no_root(self):
        e = Entry(path="/repo/main", branch="main", head="abc")
        assert workspace_name(e, Path("/other")) == "main"  # falls back to basename


class TestDisplayPath:
    def test_relative_to_root(self):
        result = display_path("/repo/main", Path("/repo"))
        assert result == "./main"

    def test_home_substitution(self):
        home = str(Path.home())
        result = display_path(f"{home}/something", None)
        assert result.startswith("~/")

    def test_outside_root(self):
        result = display_path("/other/path", Path("/repo"))
        assert "other/path" in result
