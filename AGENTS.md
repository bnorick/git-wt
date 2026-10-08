# git-wt development guide

`git-wt` manages repositories whose Git data is stored in `.bare/` beside one
directory per worktree. It intentionally uses relative gitdir pointers so the
entire repository tree can be moved.

## Critical invariants

- Never use plain `git worktree prune` in a managed repository. On Git versions
  that mishandle relative worktree metadata it can remove every tracking record.
- Resolve worktree names and multi-component paths relative to the bare
  repository root, not the current worktree or current directory.
- Preserve relative `.git` and `.bare/worktrees/*/gitdir` links across clone,
  add, migrate, move, repair, list, doctor, and prune behavior.
- `add` and `switch` print the selected path to stdout. Prompts, progress, hints,
  and diagnostics belong on stderr so shell composition keeps working.
- Destructive operations must support dry-run where applicable and retain their
  existing confirmation thresholds.

## Code map

- `src/git_wt/cli/`: Cyclopts command definitions and argument handling.
- `src/git_wt/actions/`: command behavior. Keep parsing out of this layer when
  behavior can be called and tested directly.
- `_git.py`: Git command execution and output/error policy.
- `_worktree.py`: worktree metadata model, porcelain parsing, path resolution,
  and compatibility handling for relative links.
- `_fsutil.py`: filesystem operations used by clone and migration.
- `context.py`: shared CLI context and global flags.
- `tests/`: unit and integration coverage using isolated temporary repositories.

## Verification

From `tools/git-wt/`:

```bash
./tasks test tests/test_add.py
./tasks check
```

Add regression coverage for multiple remotes, namespaced branches, standard and
bare layouts, old-Git relative path output, dirty worktrees, and dry-run behavior
when relevant. Never aim tests at the checkout containing the current work.
