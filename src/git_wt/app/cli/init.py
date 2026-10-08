# Application-layout module.
from __future__ import annotations

import sys
from typing import Annotated

import cyclopts

POSIX_INTEGRATION = """\
# git-wt shell integration
# Wraps git-wt so 'switch' changes directory in the current shell.
git-wt() {
	case "$1" in
	switch)
		local dir
		dir="$(command git-wt "$@")" || return $?
		if [ -n "$dir" ] && [ -d "$dir" ]; then
			cd "$dir" || return 1
		elif [ -n "$dir" ]; then
			printf '%s\n' "$dir"
		fi
		;;
	*)
		command git-wt "$@"
		;;
	esac
}
"""

POSIX_GIT_WRAPPER = """
# Route 'git wt ...' through the git-wt function above so it can cd too.
# All other git commands pass through unchanged.
git() {
	if [ "$1" = "wt" ]; then
		shift
		git-wt "$@"
	else
		command git "$@"
	fi
}
"""

FISH_INTEGRATION = """\
# git-wt shell integration
# Wraps git-wt so 'switch' changes directory in the current shell.
function git-wt --wraps git-wt
    if test "$argv[1]" = switch
        set -l dir (command git-wt $argv)
        set -l code $status
        test $code -ne 0; and return $code
        if test -n "$dir" -a -d "$dir"
            cd $dir
        else if test -n "$dir"
            printf '%s\n' $dir
        end
    else
        command git-wt $argv
    end
end
"""

FISH_GIT_WRAPPER = """
# Route 'git wt ...' through the git-wt function above so it can cd too.
# All other git commands pass through unchanged.
function git --wraps git
    if test "$argv[1]" = wt
        git-wt $argv[2..]
    else
        command git $argv
    end
end
"""


def init(
    shell: Annotated[str, cyclopts.Parameter(show_default=False, help="Target shell")],
    *,
    no_git_wrapper: Annotated[
        bool, cyclopts.Parameter(show_default=False, help="Omit the git() wrapper function")
    ] = False,
) -> None:
    """Print shell integration for automatic directory switching."""
    run(shell, no_git_wrapper=no_git_wrapper)


def run(shell: str, *, no_git_wrapper: bool = False) -> int:
    """Render the integration and write it to stdout."""
    script = _render(shell, not no_git_wrapper)
    if script is None:
        raise ValueError(f"unsupported shell: {shell} (supported: bash, zsh, fish)")
    sys.stdout.write(script)
    return 0


def _render(shell: str, with_git_wrapper: bool) -> str | None:
    if shell in ("bash", "zsh"):
        return POSIX_INTEGRATION + (POSIX_GIT_WRAPPER if with_git_wrapper else "")
    if shell == "fish":
        return FISH_INTEGRATION + (FISH_GIT_WRAPPER if with_git_wrapper else "")
    return None
