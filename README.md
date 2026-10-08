# git-wt

`git-wt` manages git **worktrees** using the *bare repository* pattern: instead
of one working tree with a hidden `.git/` directory, a repo becomes a folder
holding a `.bare/` directory for git data plus one sibling directory per branch,
each a full worktree. This lets you keep several branches checked out at once —
each in its own directory — without stashing, re-checking-out, or cloning the
repo multiple times.

It wraps the raw `git worktree` commands with the ergonomics they're missing:
one-step cloning into the bare layout, an interactive branch picker, upstream
tracking set up automatically, a status dashboard, and safe bulk cleanup. Paths
inside the repo use relative gitdir pointers, so the whole tree can be moved or
renamed without breaking.

`git-wt` is a from-scratch reimplementation of
[ahmedelgabri/git-wt](https://github.com/ahmedelgabri/git-wt) (see [`NOTICE`](NOTICE)).

## Quick start

`git-wt` is on your `PATH` inside the workspace (wired up through
`monorepo/bin`), so after the [workspace setup](../../README.md) you can call it
directly. Because git dispatches `git <name>` to a `git-<name>` executable on
`PATH`, both `git-wt` and `git wt` work — this doc uses `git wt`:

```sh
# Clone a repo into the bare worktree layout
git wt clone git@github.com:owner/repo.git

# Inside that repo: create a worktree (interactive picker if no args)
cd repo
git wt add feature-x origin/feature-x
git wt add            # pick a remote branch, or create a new one

# See everything checked out
git wt status

# Jump into a worktree (prints its path — use with cd)
cd "$(git wt switch)"
```

You can also run it straight from the tool directory without the workspace:

```sh
uv run git-wt --help
uv run python -m git_wt --help
```

## How it works

1. **The bare layout.** A `git-wt` repository is a directory containing:

   ```
   repo/
     ├── .bare/        git data (a bare clone)
     ├── .git          a file: "gitdir: ./.bare"
     └── <branch>/     one worktree directory per checked-out branch
   ```

   Because `.git` is a *file* pointing at `.bare`, git commands run from the repo
   root or any worktree resolve to the same shared object store.

2. **Cloning** (`clone`) creates the folder, runs `git clone --bare` into
   `.bare/`, configures the remote fetch refspec and
   `worktree.useRelativePaths`, fetches all remotes, and adds an initial worktree
   for the remote's default branch.

3. **Relative gitdir pointers.** Every worktree's gitdir pointer is rewritten to
   a relative path, so the entire repo tree can be moved or renamed without
   breaking links. A side effect: plain `git worktree prune` misreads relative
   paths and marks *all* worktrees as prunable — running it directly would
   corrupt the repo. Use [`git wt prune`](#prune) instead, which only removes
   records for worktrees actually gone from disk.

4. **Adding worktrees** (`add`) fetches the remote first, resolves the worktree
   path relative to the *repo root* (not your current directory), and — for a
   multi-component path like `bnorick/feature` — derives a matching namespaced
   branch name instead of just the basename. When the branch exists on the
   remote, upstream tracking is set automatically; when it doesn't, it prints a
   `git push -u` hint.

5. **Composability.** `add` and `switch` print the resulting worktree path to
   **stdout** and send all progress, prompts, and hints to **stderr**. That's
   what makes `cd "$(git wt switch)"` work.

## Commands

Run `git wt COMMAND --help` for the full details of any command. All commands
accept the [global options](#global-options).

### `clone`

`git wt clone URL [FOLDER]` — clone a repository and set up the bare worktree
structure.

| Argument | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `URL` *(required)* | str | — | Repository URL to clone. |
| `FOLDER` | str | *(repo name from URL)* | Local folder name for the repo root. |

### `add`

`git wt add [WORKTREE] [COMMITISH]` — create a new worktree. With no arguments,
opens an interactive picker over remote branches (or "create new branch").
Aliased as `new`.

| Argument / option | Type | Default | Description |
| ----------------- | ---- | ------- | ----------- |
| `WORKTREE` | str | *(interactive)* | Worktree path to create (resolved relative to the repo root). |
| `COMMITISH` | str | — | Branch, tag, or commit to check out. |
| `-b`, `--branch` | str | — | Create a new branch at the worktree. |
| `-B`, `--force-branch` | str | — | Create or reset a branch. |
| `-d`, `--detach` | flag | `false` | Detach HEAD at the new worktree. |
| `-f`, `--force` | flag | `false` | Check out even if the branch is checked out elsewhere. |
| `--lock` | flag | `false` | Lock the worktree after creation. |
| `--reason` | str | — | Lock reason (use with `--lock`). |
| `--no-checkout` | flag | `false` | Don't populate the worktree's files. |
| `--from-remote` | flag | `false` | Fetch remotes and pick a branch; the path is auto-derived from the branch name. |
| `--from-local [BRANCH]` | optional str | — | Create the new worktree and branch from a selected local branch, or use `BRANCH` directly. |

Worktree names cannot contain spaces.

Configure lifecycle hooks with repository-local Git config. Repository config is
the supported destination for rules that drive add/remove behavior:

```sh
git config --add wt.afteradd 'direnv allow "$GIT_WT_PATH"'
```

Repeated values run in order and hook output goes to stderr, so `git wt add`
keeps the worktree path on stdout:

| Hook | Working directory |
| --- | --- |
| `wt.beforeadd` | Bare repository root |
| `wt.afteradd` | New worktree |
| `wt.beforeremove` | Worktree being removed |
| `wt.afterremove` | Bare repository root |

### `remove`

`git wt remove [WORKTREES...]` — remove worktrees directly or by safe cleanup
filters. Also deletes each worktree's local branch by default. With no arguments
and no filters, shows an interactive picker. Aliased as `rm`; `destroy` is a
variant that requires branch-name confirmation.

| Argument / option | Type | Default | Description |
| ----------------- | ---- | ------- | ----------- |
| `WORKTREES` | str... | *(interactive)* | Worktree names or paths to remove. |
| `--merged` | flag | `false` | Select worktrees fully merged into the default branch. |
| `--gone` | flag | `false` | Select worktrees whose upstream is gone. |
| `--stale` | flag | `false` | Select stale or prunable worktree metadata. |
| `--sweep` | flag | `false` | Shorthand for `--merged --gone --stale`. |
| `--delete-remote` | flag | `false` | Also delete matching remote branches when possible. |

Combine with the global `--dry-run` to preview what would be removed.

### `switch`

`git wt switch` — open a fuzzy picker over all worktrees and print the chosen
path to stdout. Use with `cd`: `cd "$(git wt switch)"`.

### `update`

`git wt update [BRANCH]` — fetch all remotes (with prune) and pull worktrees.
Always pulls the default branch; pass a branch to also pull that worktree.
Aliased as `u`.

| Argument / option | Type | Default | Description |
| ----------------- | ---- | ------- | ----------- |
| `BRANCH` | str | — | Additional branch worktree to pull. |
| `--force` | flag | `false` | Hard-reset to upstream after confirmation. Dirty tracked-file changes use a y/N prompt; local commits not mirrored upstream require typing `force` and recommend creating `backup/{branch}` first. |

### `status`

`git wt status` — repository-wide dashboard for all worktrees: branch,
clean/dirty state, upstream sync status, last-commit age, and repo-relative path.

### `list`

`git wt list` — like `git worktree list`, but with paths rewritten relative to
the repo root. Accepts the same flags as `git worktree list` (e.g. `--porcelain`,
`-v`). On git versions without native relative-worktree support, it also removes
false `prunable` annotations after directly verifying the relative admin records.
Genuinely missing worktrees remain marked as prunable. Aliased as `ls`.

### `prune`

`git wt prune` — safe replacement for `git worktree prune`: removes admin
records only for worktrees whose directories are truly gone from disk. Necessary
because git's own prune misreads `git-wt`'s relative paths (see
[How it works](#how-it-works)).

### `doctor`

`git wt doctor` — diagnostics for standard and bare layouts: repository layout,
the `.bare` directory, worktree paths, default remote/branch detection, and
migration readiness for standard repos.

### `migrate` *(experimental)*

`git wt migrate` — convert an existing standard repository in-place to the bare
worktree layout. Use the global `--dry-run` to preview first.

### `completion`

`git wt completion [SHELL]` — print a shell completion script. `SHELL` is one of
`bash` (default), `zsh`, `zsh-git`, or `fish`. Pipe it into your rc file:
`git wt completion bash >> ~/.bashrc`.

### `agent-skill`

`git wt agent-skill` — install an [Agent Skills](https://code.claude.com/docs)-compatible
`git-wt` skill definition (`SKILL.md`).

| Option | Type | Default | Description |
| ------ | ---- | ------- | ----------- |
| `--dir` | str | `~/.agents/skills` | Skill root directory (e.g. `~/.claude/skills`). |
| `--print` | flag | `false` | Print the skill markdown instead of installing. |
| `--force` | flag | `false` | Overwrite an existing skill file. |

### Passthrough commands

`lock`, `unlock`, `move`, and `repair` pass straight through to the
corresponding `git worktree` subcommand. `git wt man <dir>` generates man pages
for all commands into `<dir>`.

### Global options

Accepted on every command:

| Option | Description |
| ------ | ----------- |
| `--verbose` | Enable verbose output. |
| `-q`, `--quiet` | Suppress non-essential output. |
| `-n`, `--dry-run` | Show what would be done without making changes. |
| `-h`, `--help` | Show help and exit. |

## Examples

```sh
# Clone into a custom folder name
git wt clone git@github.com:owner/repo.git myrepo

# Add a worktree for an existing remote branch (upstream tracking set up for you)
git wt add feature origin/feature

# Create a brand-new branch off main in a matching directory
git wt add -b new-feature main

# Namespaced path -> namespaced branch (branch is "bnorick/spike", not "spike")
git wt add bnorick/spike

# Interactively pick a remote branch, deriving the path from the branch name
git wt add --from-remote

# Create bnorick/spike from a selected local branch, or directly from local main
git wt add bnorick/spike --from-local
git wt add bnorick/spike --from-local main

# Preview a bulk cleanup, then run it: drop merged / gone / stale worktrees
git wt remove --sweep --dry-run
git wt remove --sweep

# Pull the default branch and a feature worktree
git wt update feature

# cd into a worktree chosen from a fuzzy picker
cd "$(git wt switch)"
```

## Requirements

- **git** (a recent version; relative worktree paths are used automatically).
- **[uv](https://docs.astral.sh/uv/)** to run the tool — the `monorepo/bin`
  launcher invokes it via `uv run --project`.

## Development

This project uses a `just`-based task runner, invoked through `./tasks`:

```sh
./tasks check       # run deptry, Ruff, formatting, ty, and tests
./tasks fix         # apply lint and formatting fixes
./tasks test        # run the test suite
./tasks run git-wt  # run the CLI from source
```

Source is organized as a `cli/` layer (cyclopts argument handling) over an
`actions/` layer (the actual work), with shared helpers for git invocation
(`_git.py`), the worktree model (`_worktree.py`), relative-path rewriting
(`_fsutil.py`), and the interactive picker (`_picker.py`). This keeps the
worktree logic testable independently of the command parser.
