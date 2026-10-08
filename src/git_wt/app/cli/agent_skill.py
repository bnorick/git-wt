# Application-layout module.
from __future__ import annotations

from typing import Annotated

import cyclopts

from git_wt import agent_skill as action


def agent_skill(
    *,
    force: Annotated[bool, cyclopts.Parameter(show_default=False, help="Overwrite an existing skill file")] = False,
    print_only: Annotated[
        bool,
        cyclopts.Parameter(name=["--print"], show_default=False, help="Print the skill markdown instead of installing"),
    ] = False,
    dir: Annotated[
        str, cyclopts.Parameter(show_default=False, help='Skill root directory (default "~/.agents/skills")')
    ] = "",
) -> None:
    """Install an Agent Skills-compatible git-wt skill definition.

    Writes ~/.agents/skills/git-wt/SKILL.md by default. Use --dir to
    target a different skill root (e.g. ~/.claude/skills), --print to
    review the skill without installing it, or --force to overwrite an
    existing skill file.
    """
    action.run(force=force, print_only=print_only, dir=dir)
