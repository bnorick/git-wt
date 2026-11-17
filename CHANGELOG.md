# Changelog

## 0.7.1

### Fixed

- Remove migration staging and backup directories on Windows instead of
  leaving `<repo>-backup-<pid>` siblings behind. Cleanup clears only the
  owner-write bit Git sets on objects, refuses to delete anything but the
  repository's own `<name>-new-<pid>` and `<name>-backup-<pid>` siblings, and
  warns with the leftover path instead of reporting success when removal
  still fails.
- Write `gitdir` pointers with forward slashes, which Git for Windows requires
  to recognize a linked worktree. Previously `remove` failed with "is not a
  working tree" and left the worktree behind.
- Report worktree names and display paths with slashes so slash-separated
  branch namespaces survive on Windows.
- Exit non-zero when `git wt remove` cannot remove a worktree; lifecycle hook
  failures remain reported without failing the command.
- Write UTF-8 to pipes so status glyphs and table borders survive a non-UTF-8
  Windows console code page.
- Match native `git worktree list` column widths and path separators when
  rendering `git wt list` output.

## 0.7.0

### Fixed

- Preserve slash-separated branch namespaces when deriving branch names from
  multi-component worktree paths on Windows, including `add` and
  `add --from-local`.
- Replace worktree gitdir pointers atomically so Windows does not reject
  in-place writes immediately after `git worktree add`.

## 0.6.0

### Added

- Added `migrate --fast` to move original top-level contents without copying or
  checking out the current branch, preserving the repository root inode. Fast
  mode has no rollback; partial migration data is retained on failure.

### Changed
- `add --from-local [BRANCH]` now defaults the worktree path to the selected
  branch and reuses that branch when the names match.

### Fixed

- Ported migration support for initialized, nested, and deinitialized submodules,
  preserving local history, working state, configuration, and relative links.
  External or linked nested Git metadata is rejected before migration.
- Preserved empty `.git` cache markers, including those created by uv.
- Preserved repository lifecycle hook configuration during migration.
- Corrected migration index lookup for namespaced branches and retained valid
  relative worktree pointers during finalization.
- Updated `doctor` to allow submodule migration and corrected text list rendering
  for continuation and blank lines.

## 0.5.0

### Added

- Added `git wt init <shell>` to print bash, zsh, and fish shell integration for
  automatic worktree switching. The optional `git` wrapper can be omitted with
  `--no-git-wrapper` without affecting `git wt switch` behavior.
- Added structured worktree output to `git wt list --json`. Each row includes
  the worktree path, branch, HEAD, detached state, lock/prunable state, and any
  corresponding reason.
- Added lifecycle hooks for worktree creation and removal:
  `wt.beforeadd`, `wt.afteradd`, `wt.beforeremove`, and `wt.afterremove`.
  Repeated configured values run in order, hook output goes to stderr, and
  every hook receives `GIT_WT_EVENT`, `GIT_WT_PATH`, `GIT_WT_BRANCH`, and
  `GIT_WT_BARE_ROOT` in its environment.

### Changed

- Removed `GIT_WT_ON_NEW_WORKTREE`.
- Lifecycle hooks are now invoked around worktree creation rather than only
  after it; before-hook and after-hook failures preserve distinct exit paths. Configure `wt.afteradd` instead.
  Replace `{worktree}` placeholders with `$GIT_WT_PATH`; for example, use
  `git config --add wt.afteradd 'direnv allow "$GIT_WT_PATH"'`.
