# Changelog

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
