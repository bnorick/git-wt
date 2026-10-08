"""Shared fixtures and helpers for git-wt tests."""

from __future__ import annotations

import os
import shutil
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple

import duct
import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@test.com",
    "GIT_CONFIG_NOSYSTEM": "1",
    # Disable credential helpers and SSH prompts
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "false",
}


# ---------------------------------------------------------------------------
# Low-level git helper
# ---------------------------------------------------------------------------


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def _decode_output(output: bytes | None) -> str:
    """Decode captured command output with text-mode newline handling."""
    return (output or b"").decode().replace("\r\n", "\n").replace("\r", "\n")


def git(
    *args: str,
    cwd: Path | None = None,
    input: str | None = None,
    check: bool = True,
    extra_env: dict | None = None,
) -> CommandResult:
    env = os.environ.copy()
    env.update(GIT_ENV)
    if extra_env:
        env.update(extra_env)
    command = duct.cmd("git", *args).full_env(env).stdout_capture().stderr_capture()
    if cwd is not None:
        command = command.dir(str(cwd))
    if input is not None:
        command = command.stdin_bytes(input)
    if not check:
        command = command.unchecked()
    output = command.run()
    return CommandResult(output.status, _decode_output(output.stdout), _decode_output(output.stderr))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class GitWtRunner:
    """Callable wrapper for invoking git-wt as a child process."""

    def __init__(self, exe: str) -> None:
        self.exe = exe

    def __call__(
        self,
        *args: str,
        cwd: Path | None = None,
        input: str | None = None,
        env: dict | None = None,
        select: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        full_env = os.environ.copy()
        full_env.update(GIT_ENV)
        # Remove any TTY-detection tricks that might hang
        full_env["TERM"] = "dumb"
        if env:
            full_env.update(env)
        if select is not None:
            full_env["GIT_WT_SELECT"] = select

        command = duct.cmd(self.exe, *args).full_env(full_env).stdout_capture().stderr_capture().unchecked()
        if cwd is not None:
            command = command.dir(str(cwd))
        if input is not None:
            command = command.stdin_bytes(input)
        output = command.run()
        result = CommandResult(output.status, _decode_output(output.stdout), _decode_output(output.stderr))
        if check and result.returncode != 0:
            pytest.fail(
                f"`git-wt {' '.join(args)}` failed (exit {result.returncode})\n"
                f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )
        return result


@pytest.fixture(scope="session")
def wt(request) -> GitWtRunner:
    """Session-scoped git-wt runner. Skips if binary not found."""
    exe = shutil.which("git-wt")
    if exe is None:
        venv_exe = Path(__file__).parent.parent / ".venv" / "bin" / "git-wt"
        if venv_exe.exists():
            exe = str(venv_exe)
        else:
            pytest.skip("git-wt not found in PATH or .venv/bin/")
    return GitWtRunner(exe)


# ---------------------------------------------------------------------------
# Repo-building helpers (used by fixtures and tests directly)
# ---------------------------------------------------------------------------


def make_std_repo(path: Path, branch: str = "main") -> Path:
    """Create a standard git repository with an initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", branch, cwd=path)
    git("config", "user.email", "test@test.com", cwd=path)
    git("config", "user.name", "Test User", cwd=path)
    (path / "README.md").write_text("hello\n")
    git("add", ".", cwd=path)
    git("commit", "-m", "initial commit", cwd=path)
    return path


def make_bare_repo(path: Path, branch: str = "main") -> Path:
    """Create a bare worktree layout: .bare/ + .git file + main worktree."""
    path.mkdir(parents=True, exist_ok=True)
    bare = path / ".bare"

    # Clone a temp repo bare, configure, fetch, then clean up
    tmp = path.parent / f".tmp-{path.name}"
    make_std_repo(tmp, branch=branch)
    git("clone", "--bare", str(tmp), str(bare))

    # Write .git pointer
    (path / ".git").write_text("gitdir: ./.bare\n")

    # Configure bare for worktree use (fetch while tmp still exists)
    git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*", cwd=bare)
    git("config", "core.logallrefupdates", "true", cwd=bare)
    git("fetch", "--all", cwd=bare)

    # Remove tmp source now that refs are populated
    shutil.rmtree(str(tmp))

    git("worktree", "add", str(path / branch), branch, cwd=bare)

    return path


def make_bare_repo_with_remote(path: Path, branch: str = "main") -> tuple[Path, Path]:
    """Bare worktree repo with a separate bare origin for push/fetch tests."""
    # Create origin first
    origin_path = path.parent / f"{path.name}-origin"
    tmp = path.parent / f".tmp-{path.name}"
    make_std_repo(tmp, branch=branch)
    git("clone", "--bare", str(tmp), str(origin_path))
    shutil.rmtree(str(tmp))

    # Create the bare repo, pointing at origin
    path.mkdir(parents=True, exist_ok=True)
    bare = path / ".bare"
    git("clone", "--bare", str(origin_path), str(bare))
    (path / ".git").write_text("gitdir: ./.bare\n")
    git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*", cwd=bare)
    git("config", "remote.origin.url", str(origin_path), cwd=bare)
    git("config", "core.logallrefupdates", "true", cwd=bare)
    git("fetch", "--all", cwd=bare)
    git("worktree", "add", str(path / branch), branch, cwd=bare)

    return path, origin_path


def create_branch(repo_root: Path, branch: str, from_ref: str = "main") -> None:
    """Create a new branch in the bare repo (for picker testing)."""
    bare = repo_root / ".bare"
    git("branch", branch, from_ref, cwd=bare)
    # Also push to origin if it exists
    with suppress(Exception):
        origin = git("remote", "get-url", "origin", cwd=bare, check=False)
        if origin.returncode == 0:
            git("push", "origin", branch, cwd=bare, check=False)


def create_worktree(repo_root: Path, branch: str) -> Path:
    """Add a worktree for an existing branch via raw git (absolute gitdir paths)."""
    bare = repo_root / ".bare"
    wt_path = repo_root / branch
    git("worktree", "add", str(wt_path), branch, cwd=bare)
    return wt_path


def create_commit(wt_path: Path, filename: str = "file.txt", msg: str = "add file") -> None:
    """Create a commit in a worktree."""
    (wt_path / filename).write_text(f"content of {filename}\n")
    git("add", filename, cwd=wt_path)
    git("commit", "-m", msg, cwd=wt_path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def std_repo(tmp_path) -> Path:
    return make_std_repo(tmp_path / "repo")


@pytest.fixture
def std_repo_with_remote(tmp_path) -> tuple[Path, Path]:
    origin = make_std_repo(tmp_path / "origin")
    repo = tmp_path / "repo"
    git("clone", str(origin), str(repo))
    git("config", "user.email", "test@test.com", cwd=repo)
    git("config", "user.name", "Test User", cwd=repo)
    return repo, origin


@pytest.fixture
def bare_repo(tmp_path) -> Path:
    return make_bare_repo(tmp_path / "repo")


@pytest.fixture
def bare_repo_with_remote(tmp_path) -> tuple[Path, Path]:
    return make_bare_repo_with_remote(tmp_path / "repo")


@pytest.fixture
def wt_bare_repo(wt, tmp_path) -> Path:
    """Bare worktree repo created via git wt clone (full production state)."""
    origin = make_std_repo(tmp_path / "origin")
    target = tmp_path / "repo"
    wt("clone", str(origin), str(target))
    return target


@pytest.fixture
def wt_bare_repo_with_remote(wt, tmp_path) -> tuple[Path, Path]:
    """Bare worktree repo with a bare remote, created via git wt clone."""
    std = make_std_repo(tmp_path / "src")
    origin = tmp_path / "origin"
    git("clone", "--bare", str(std), str(origin))
    shutil.rmtree(str(std))
    target = tmp_path / "repo"
    wt("clone", str(origin), str(target))
    return target, origin


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_bare_layout(root: Path) -> None:
    assert (root / ".git").is_file(), f"{root}/.git should be a file"
    assert (root / ".bare").is_dir(), f"{root}/.bare should be a directory"


def _parse_worktree_blocks(stdout: str) -> list[dict]:
    """Parse git worktree list --porcelain output into per-worktree attribute dicts.

    Each block is a dict with at least a 'worktree' key; bare worktrees also have
    a 'bare' key.  Works regardless of whether paths are absolute (git >= 2.48) or
    relative (git < 2.48).
    """
    blocks: list[dict] = []
    current: dict = {}
    for line in stdout.splitlines():
        if not line:
            if current:
                blocks.append(current)
                current = {}
        elif line.startswith("worktree "):
            current["worktree"] = line[9:]
        elif " " in line:
            key, _, val = line.partition(" ")
            current[key] = val
        else:
            current[line] = True
    if current:
        blocks.append(current)
    return blocks


def linked_worktree_count(bare: Path) -> int:
    """Return the number of linked (non-bare) worktrees reported by git."""
    result = git("worktree", "list", "--porcelain", cwd=bare)
    return sum(1 for b in _parse_worktree_blocks(result.stdout) if "bare" not in b)


def _resolve_worktree_paths(bare: Path) -> list[Path]:
    """Return resolved absolute paths of all linked worktrees in the porcelain output.

    Reads admin records directly rather than parsing porcelain output, so that
    relative gitdir paths (git < 2.48) are always resolved against the correct
    admin directory regardless of worktree naming collisions.
    """
    # The bare dir itself is always the first (main) worktree.
    paths = [bare.resolve()]
    worktrees_dir = bare / "worktrees"
    if not worktrees_dir.is_dir():
        return paths
    for admin in worktrees_dir.iterdir():
        if not admin.is_dir():
            continue
        gitdir_file = admin / "gitdir"
        if not gitdir_file.is_file():
            continue
        content = gitdir_file.read_text().strip()
        dot_git = Path(content) if Path(content).is_absolute() else (admin / content).resolve()
        paths.append(dot_git.parent.resolve())
    return paths


def assert_worktree_exists(bare: Path, wt_path: Path) -> None:
    paths = _resolve_worktree_paths(bare)
    assert wt_path.resolve() in paths, f"worktree {wt_path} not found.\nResolved worktree paths: {paths}"


def assert_worktree_not_exists(bare: Path, wt_path: Path) -> None:
    paths = _resolve_worktree_paths(bare)
    assert wt_path.resolve() not in paths, f"worktree {wt_path} should not exist.\nResolved worktree paths: {paths}"


def assert_branch_exists(repo: Path, branch: str) -> None:
    result = git("show-ref", "--verify", f"refs/heads/{branch}", cwd=repo, check=False)
    assert result.returncode == 0, f"branch {branch!r} should exist in {repo}"


def assert_branch_not_exists(repo: Path, branch: str) -> None:
    result = git("show-ref", "--verify", f"refs/heads/{branch}", cwd=repo, check=False)
    assert result.returncode != 0, f"branch {branch!r} should not exist in {repo}"


def assert_worktree_gitdir_relative(wt_path: Path) -> None:
    """Assert that both gitdir pointer files for a worktree use relative paths.

    The worktree's .git file pointer is relative to the worktree directory.
    The admin record's gitdir file pointer is relative to GIT_COMMON_DIR (.bare/),
    which is how git resolves these paths at runtime.
    """
    dot_git = wt_path / ".git"
    assert dot_git.is_file(), f"{dot_git} should be a file"
    content = dot_git.read_text().strip()
    assert content.startswith("gitdir:"), f"{dot_git} content should start with 'gitdir:'"
    raw_path = content[len("gitdir:") :].strip()
    assert not Path(raw_path).is_absolute(), f"{dot_git} should use a relative path, got: {raw_path!r}"
    # Resolve to find the admin record directory (relative to worktree dir)
    admin_path = (wt_path / raw_path).resolve()
    assert admin_path.is_dir(), f"admin record {admin_path} should be a directory"
    gitdir_file = admin_path / "gitdir"
    assert gitdir_file.is_file(), f"{gitdir_file} should exist"
    gitdir_content = gitdir_file.read_text().strip()
    assert not Path(gitdir_content).is_absolute(), f"{gitdir_file} should use a relative path, got: {gitdir_content!r}"
    # Verify the admin gitdir resolves back to the worktree's .git file.
    # The path is relative to the admin directory itself.
    assert (admin_path / gitdir_content).resolve() == dot_git.resolve(), (
        f"{gitdir_file} content {gitdir_content!r} does not resolve to {dot_git}"
    )
