# Application-layout module.
"""Generate shell completion scripts."""

from __future__ import annotations

import sys

from git_wt import console

# Bash completion shim that bridges `git wt` → `git-wt`
_BASH_GIT_SHIM = """
_git_wt() {
    local cur prev words cword
    _init_completion || return
    COMP_WORDS=("git-wt" "${COMP_WORDS[@]:2}")
    COMP_CWORD=$((COMP_CWORD - 1))
    _git_wt_completion
}
"""

_ZSH_GIT_SHIM = """
# Bridge for `git wt` completion
_git-wt-git-bridge() {
    local -a words
    words=("git-wt" "${words[@]:2}")
    _git-wt
}
compdef _git-wt-git-bridge git
"""


def run(shell: str) -> None:
    shell = shell.lower()
    if shell not in ("bash", "zsh", "fish"):
        console.error(f"unsupported shell: {shell!r} (bash, zsh, fish)")
        sys.exit(1)

    try:
        from git_wt.app.cli import app

        # Attempt cyclopts completion generation
        try:
            script = app.completion(shell)  # ty: ignore[unresolved-attribute]
        except AttributeError:
            script = _fallback_completion(shell)
    except Exception:
        script = _fallback_completion(shell)

    print(script)

    if shell == "bash":
        print(_BASH_GIT_SHIM)
    elif shell == "zsh":
        print(_ZSH_GIT_SHIM)


def _fallback_completion(shell: str) -> str:
    """Minimal completion stub when cyclopts doesn't expose a completion API."""
    COMMANDS = (
        "clone add remove switch migrate status doctor update agent-skill completion list lock unlock move prune repair"
    )
    if shell == "bash":
        return f"""# git-wt bash completion (basic)
_git_wt_completion() {{
    local commands="{COMMANDS}"
    COMPREPLY=($(compgen -W "$commands" -- "${{COMP_WORDS[COMP_CWORD]}}"))
}}
complete -F _git_wt_completion git-wt
"""
    if shell == "zsh":
        return f"""# git-wt zsh completion (basic)
#compdef git-wt
_git-wt() {{
    local commands
    commands=({COMMANDS})
    _describe 'command' commands
}}
"""
    if shell == "fish":
        cmds = COMMANDS.split()
        lines = [f"complete -c git-wt -f -a {c}" for c in cmds]
        return "\n".join(lines) + "\n"
    return ""
