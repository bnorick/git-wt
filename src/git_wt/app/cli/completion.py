# Application-layout module.
from __future__ import annotations

from typing import Annotated

import cyclopts

from git_wt import completion as action


def completion(
    shell: Annotated[
        str, cyclopts.Parameter(show_default=False, help="Shell type: bash, zsh, zsh-git, or fish")
    ] = "bash",
) -> None:
    """Generate a shell completion script.

    Pipe the output to your shell rc file to enable completions, e.g.
    "git wt completion bash >> ~/.bashrc" or
    "git wt completion zsh >> ~/.zshrc".
    """
    action.run(shell)
