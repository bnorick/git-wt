"""Worktree data model, parsing, and resolution."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from git_wt import _git


@dataclass
class Entry:
    path: str
    branch: str = ""
    head: str = ""
    detached: bool = False
    locked: bool = False
    locked_reason: str = ""
    prunable: bool = False
    prunable_reason: str = ""


def parse_porcelain(output: str) -> list[Entry]:
    """Parse `git worktree list --porcelain` output, excluding the bare worktree."""
    entries: list[Entry] = []
    current: dict = {}

    def _flush() -> None:
        if current and not current.get("bare"):
            path = current.get("path", "")
            # Also exclude by path suffix as a safety net
            if not path.endswith("/.bare") and not path.endswith("\\.bare"):
                entries.append(
                    Entry(
                        path=path,
                        branch=current.get("branch", ""),
                        head=current.get("head", ""),
                        detached=current.get("detached", False),
                        locked=current.get("locked", False),
                        locked_reason=current.get("locked_reason", ""),
                        prunable=current.get("prunable", False),
                        prunable_reason=current.get("prunable_reason", ""),
                    )
                )

    for line in output.splitlines():
        if not line:
            _flush()
            current = {}
        elif line.startswith("worktree "):
            current["path"] = line[9:]
        elif line.startswith("HEAD "):
            current["head"] = line[5:12]
        elif line.startswith("branch refs/heads/"):
            current["branch"] = line[18:]
        elif line == "branch":
            current["branch"] = ""
        elif line == "detached":
            current["detached"] = True
        elif line == "bare":
            current["bare"] = True
        elif line.startswith("locked"):
            current["locked"] = True
            current["locked_reason"] = line[7:].strip() if len(line) > 7 else ""
        elif line.startswith("prunable"):
            current["prunable"] = True
            current["prunable_reason"] = line[9:].strip() if len(line) > 9 else ""

    _flush()
    return entries


def list_worktrees(dir: Path | None = None) -> list[Entry]:
    output = _git.query("worktree", "list", "--porcelain", dir=dir)
    entries = parse_porcelain(output)
    targets = gitdir_targets(dir=dir)
    verified_live: list[bool] = []
    for entry in entries:
        target = targets.get(entry.path)
        if target is not None:
            verified_live.append(target.is_file())
        elif Path(entry.path).is_absolute():
            verified_live.append((Path(entry.path) / ".git").is_file())
        else:
            verified_live.append(False)
    # When gitdir pointer files use relative paths (after relativize_worktree_gitdir
    # on git < 2.48), git outputs relative paths in the 'worktree' field.  Resolve
    # them to absolute so that all callers can rely on entry.path being absolute.
    _absolutize_entry_paths(entries, dir=dir, path_map=targets)
    # Git versions without native relative-worktree support resolve a relative
    # admin gitdir from the wrong directory and falsely mark a live worktree as
    # prunable.  Only clear the flag when the worktree's .git link proves that
    # the admin record resolves to a live worktree.
    for entry, is_live in zip(entries, verified_live, strict=True):
        if entry.prunable and is_live:
            entry.prunable = False
            entry.prunable_reason = ""
    return entries


def gitdir_targets(dir: Path | None = None) -> dict[str, Path]:
    """Map Git's listed worktree paths to their resolved .git link targets.

    Older Git echoes the raw value from ``worktrees/<id>/gitdir`` (without its
    trailing ``/.git``) in ``git worktree list``.  Relative values are relative
    to the admin directory, not the repository root.  Keeping this mapping in
    one place lets both the data model and list formatter correct old Git
    without changing the portable on-disk metadata.
    """
    try:
        root = bare_root(dir=dir)
    except Exception:
        return {}

    worktrees_dir = root / ".bare" / "worktrees"
    targets: dict[str, Path] = {}
    if not worktrees_dir.is_dir():
        return targets

    for admin in worktrees_dir.iterdir():
        if not admin.is_dir():
            continue
        gitdir_file = admin / "gitdir"
        if not gitdir_file.is_file():
            continue
        try:
            content = gitdir_file.read_text().strip()
        except OSError, UnicodeError:
            continue
        if not content:
            continue
        raw = Path(content)
        target = raw if raw.is_absolute() else (admin / raw).resolve()
        if content.endswith("/.git") or content.endswith("\\.git"):
            listed_path = content[:-5]
        else:
            continue
        targets[listed_path] = target
        # Native relative-worktree-aware Git lists the resolved absolute path.
        targets[str(target.parent)] = target
    return targets


def _absolutize_entry_paths(
    entries: list[Entry],
    dir: Path | None = None,
    path_map: dict[str, Path] | None = None,
) -> None:
    """Resolve relative entry.path values to absolute by reading admin records.

    When relative gitdir paths are in use, git echoes the raw admin gitdir content
    (minus the /.git suffix) as the worktree path in porcelain output.  That path
    is relative to the admin directory, not the repo root, so we build a lookup
    table by reading each admin record's gitdir file and resolving from there.
    """
    if all(Path(e.path).is_absolute() for e in entries):
        return
    try:
        root = bare_root(dir=dir)
    except Exception:
        return
    if path_map is None:
        path_map = gitdir_targets(dir=dir)
    for e in entries:
        if not Path(e.path).is_absolute():
            target = path_map.get(e.path)
            e.path = str(target.parent) if target else str((root / e.path).resolve())


def bare_root(dir: Path | None = None) -> Path:
    """Return the repo root (parent of .bare)."""
    common = _git.query("rev-parse", "--git-common-dir", dir=dir)
    p = Path(common).resolve()
    # Strip trailing /.bare
    if p.name == ".bare":
        return p.parent
    return p


def current_root(dir: Path | None = None) -> Path:
    return Path(_git.query_silent("rev-parse", "--show-toplevel", dir=dir))


def workspace_name(entry: Entry, root: Path) -> str:
    """Relative path of this worktree from the bare root (preserves slash paths)."""
    try:
        return str(Path(entry.path).relative_to(root))
    except ValueError:
        return Path(entry.path).name


def display_path(path: str, root: Path | None = None) -> str:
    """Pretty-print a path: ./name relative to root, or ~-substituted."""
    p = Path(path)
    if root is not None:
        try:
            rel = p.relative_to(root)
            return "./" + str(rel)
        except ValueError:
            pass
    home = Path.home()
    try:
        return "~/" + str(p.relative_to(home))
    except ValueError:
        return str(p)


def resolve(entries: list[Entry], input: str, root: Path | None = None) -> Entry:
    """Resolve a user-supplied worktree identifier to an Entry.

    Strategies (in order):
    1. Exact path match
    2. Relative-to-bare-root match
    3. Realpath match
    4. Unique basename match
    """
    if root is None:
        try:
            root = bare_root()
        except Exception:
            root = None

    # 1. Exact path match
    for e in entries:
        if e.path == input:
            return e

    # 2. Relative-to-bare-root
    if root is not None:
        candidate = str(root / input)
        for e in entries:
            if e.path == candidate:
                return e

    # 3. Realpath match
    with suppress(Exception):
        real_input = str(Path(input).resolve())
        for e in entries:
            if str(Path(e.path).resolve()) == real_input:
                return e

    # 4. Unique basename match
    matches = [e for e in entries if Path(e.path).name == Path(input).name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = [workspace_name(e, root) if root else e.path for e in matches]
        raise ValueError(f"ambiguous worktree {input!r}: {', '.join(names)}")

    available = ", ".join(workspace_name(e, root) if root else e.path for e in entries)
    raise ValueError(f"no worktree matching {input!r}. Available: {available}")


def validate(entries: list[Entry], input: str, root: Path | None = None) -> Entry:
    """Like resolve but raises a user-friendly error listing available worktrees."""
    try:
        return resolve(entries, input, root)
    except ValueError as exc:
        raise ValueError(str(exc)) from None


def default_remote(dir: Path | None = None) -> str:
    """Determine the primary remote.

    Priority: single remote > current branch's configured remote > 'origin' > first.
    """
    try:
        remotes = _git.query_lines("remote", dir=dir)
    except _git.GitError:
        return "origin"

    if not remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]

    # Try current branch's configured remote
    try:
        branch = _git.query("rev-parse", "--abbrev-ref", "HEAD", dir=dir)
        if branch and branch != "HEAD":
            try:
                remote = _git.query("config", f"branch.{branch}.remote", dir=dir)
                if remote and remote in remotes:
                    return remote
            except _git.GitError:
                pass
    except _git.GitError:
        pass

    if "origin" in remotes:
        return "origin"
    return remotes[0]


def default_branch(remote: str, dir: Path | None = None) -> str:
    """Determine the remote's default branch.

    Tries local symbolic-ref first (fast), falls back to `git remote show`.
    """
    # Try local symbolic ref
    try:
        ref = _git.query_silent("symbolic-ref", f"refs/remotes/{remote}/HEAD", dir=dir)
        prefix = f"refs/remotes/{remote}/"
        if ref.startswith(prefix):
            return ref[len(prefix) :]
    except _git.GitError:
        pass

    # Fall back to remote show (network call)
    try:
        output = _git.query("remote", "show", remote, dir=dir)
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("HEAD branch:"):
                return stripped.split(":", 1)[1].strip()
    except _git.GitError:
        pass

    return "main"
