#!/usr/bin/env bash
# Sets up two diverged-after-rebase scenarios for manually testing
# `git wt update --force` confirmation prompts.
#
# Both the main worktree and an extra feature worktree are left in a state
# where their remote branch has been force-pushed (same diff, new SHA) and
# they each have a dirty tracked file — the exact conditions that trigger
# the per-worktree confirmation prompt.
#
# Usage (run from tools/git-wt):
#   bash tests/manual/setup-local-divergence-after-rebase.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BASE="/tmp/test-local-divergence-after-rebase"
GIT_WT="git wt"
INTIAL_DIR=$(pwd)

export GIT_AUTHOR_NAME="Test User"
export GIT_AUTHOR_EMAIL="test@example.com"
export GIT_COMMITTER_NAME="Test User"
export GIT_COMMITTER_EMAIL="test@example.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

bold()    { printf '\033[1m%s\033[0m' "$*"; }
cyan()    { printf '\033[1;36m%s\033[0m' "$*"; }
yellow()  { printf '\033[33m%s\033[0m' "$*"; }
green()   { printf '\033[1;32m%s\033[0m' "$*"; }
dim()     { printf '\033[2m%s\033[0m' "$*"; }

heading() { printf '\n%s\n' "$(cyan "=== $1 ===")" ; }
step()    { printf '  %s %s\n' "$(yellow '→')" "$1"; }

# ---------------------------------------------------------------------------
# Tear down any previous run
# ---------------------------------------------------------------------------
if [[ -d "$BASE" ]]; then
    heading "Removing previous setup"
    rm -rf "$BASE"
fi
mkdir -p "$BASE"

# ---------------------------------------------------------------------------
# origin: a plain (non-bare) repo that plays the role of the remote server
# ---------------------------------------------------------------------------
heading "Creating origin"

ORIGIN="$BASE/origin"
mkdir "$ORIGIN"
git init -b main "$ORIGIN" -q
git -C "$ORIGIN" config user.email "test@example.com"
git -C "$ORIGIN" config user.name "Test User"

echo "hello" > "$ORIGIN/README.md"
git -C "$ORIGIN" add README.md
git -C "$ORIGIN" commit -q -m "initial commit"

# A commit on main that will be "force-pushed" (amended) later
echo "feature content" > "$ORIGIN/feature.txt"
git -C "$ORIGIN" add feature.txt
git -C "$ORIGIN" commit -q -m "add feature"

# A feature branch with its own commit that will also be force-pushed
git -C "$ORIGIN" checkout -q -b feature/thing
echo "thing content" > "$ORIGIN/thing.txt"
git -C "$ORIGIN" add thing.txt
git -C "$ORIGIN" commit -q -m "add thing"
git -C "$ORIGIN" checkout -q main

step "main and feature/thing branches created"

# ---------------------------------------------------------------------------
# local: bare worktree layout cloned from origin
# ---------------------------------------------------------------------------
heading "Creating local bare worktree layout"

LOCAL="$BASE/local"
mkdir "$LOCAL"

git clone --bare -q "$ORIGIN" "$LOCAL/.bare"
echo "gitdir: ./.bare" > "$LOCAL/.git"

# Full refspec so all remote branches are tracked
git -C "$LOCAL/.bare" config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
git -C "$LOCAL/.bare" config remote.origin.url "$ORIGIN"
git -C "$LOCAL/.bare" config core.logallrefupdates true
git -C "$LOCAL/.bare" fetch --all -q

git -C "$LOCAL/.bare" branch --set-upstream-to origin/main main
git -C "$LOCAL/.bare" remote set-head origin main

# main worktree
git -C "$LOCAL/.bare" worktree add -q "$LOCAL/main" main
git -C "$LOCAL/main" reset -q --hard origin/main

# feature/thing worktree (branch already exists in bare clone — just set tracking)
git -C "$LOCAL/.bare" branch --set-upstream-to origin/feature/thing feature/thing
git -C "$LOCAL/.bare" worktree add -q "$LOCAL/feature-thing" feature/thing
git -C "$LOCAL/feature-thing" reset -q --hard origin/feature/thing

step "bare layout with main + feature-thing worktrees"

# ---------------------------------------------------------------------------
# Simulate force-push: amend commits on origin so they have new SHAs
# ---------------------------------------------------------------------------
heading "Simulating force-push (rebase with same diff, new SHA)"

git -C "$ORIGIN" commit -q --amend -m "add feature (rebased)"
step "origin/main: commit amended"

git -C "$ORIGIN" checkout -q feature/thing
git -C "$ORIGIN" commit -q --amend -m "add thing (rebased)"
git -C "$ORIGIN" checkout -q main
step "origin/feature/thing: commit amended"

# Fetch so local tracking refs see the new SHAs — worktrees are now diverged
git -C "$LOCAL/.bare" fetch --all -q
step "local: fetched — both worktrees now diverged from upstream"

# ---------------------------------------------------------------------------
# Dirty tracked files in both worktrees
# ---------------------------------------------------------------------------
heading "Dirtying tracked files (uncommitted local changes)"

echo "locally modified content" > "$LOCAL/main/feature.txt"
step "main/feature.txt modified"

echo "locally modified thing" > "$LOCAL/feature-thing/thing.txt"
step "feature-thing/thing.txt modified"

# ---------------------------------------------------------------------------
# Print usage instructions
# ---------------------------------------------------------------------------
printf '\n%s\n\n' "$(green '✓ Setup complete')"

printf '%s  %s\n' "$(bold 'Local repo:')" "$LOCAL"
printf '%s  %s\n\n' "$(bold 'Origin:    ')" "$ORIGIN"

cat <<EOF
Both worktrees are diverged from upstream (rebased remote commits) and have
uncommitted changes — the exact state that triggers force-reset confirmation.

  $(bold 'main')          → $LOCAL/main
                 dirty file: feature.txt

  $(bold 'feature/thing') → $LOCAL/feature-thing
                 dirty file: thing.txt

EOF

printf '%s\n\n' "$(yellow 'Test scenarios — cd into the local repo first:')"

printf '  %s\n' "$(dim "cd $LOCAL")"
printf '\n'

printf '  %s\n' "$(bold '1. Force-reset main only (one prompt):')"
printf '     %s\n' "$GIT_WT update --force"

printf '\n'
printf '  %s\n' "$(bold '2. Force-reset main + feature/thing (two independent prompts):')"
printf '     %s\n' "$GIT_WT update feature/thing --force"

printf '\n'
printf '  %s\n' "$(bold '3. No --force: should fail with \"uncommitted changes\" error:')"
printf '     %s\n' "$GIT_WT update feature/thing"

printf '\n'
printf '  %s\n' "$(dim "cd $INTIAL_DIR")"
printf '\n'

printf '\n%s\n' "$(dim 'Re-run this script at any time to reset the scenario from scratch.')"
