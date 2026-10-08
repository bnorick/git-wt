# Application-layout module.
"""CLI application entry point."""

from __future__ import annotations

import dataclasses
import os
import sys
from typing import Annotated

import cyclopts

# Patch CommandSpec so the help= kwarg is used only for the unresolved preview
# in the top-level commands list. Once a lazy command resolves to its function,
# App.help falls back to default_command.__doc__ (the full docstring with long
# description and examples). Without this, the one-liner CommandSpec.help
# permanently overrides the resolved app's help string.
from cyclopts.command_spec import CommandSpec as _CommandSpec
from rich.console import Console

_orig_resolve = _CommandSpec.resolve


def _patched_resolve(self, parent_app):
    resolved = _orig_resolve(self, parent_app)
    resolved._help = None
    return resolved


_CommandSpec.resolve = _patched_resolve

from git_wt.app.console import init as console_init
from git_wt.app.context import get_context
from git_wt.app.errors import install_exception_hook, install_signal_handler


@dataclasses.dataclass
class GlobalArgs:
    """Global CLI options available on every subcommand."""

    verbose: Annotated[bool, cyclopts.Parameter(show_default=False, help="Enable verbose output")] = False
    quiet: Annotated[
        bool, cyclopts.Parameter(show_default=False, short_alias=True, help="Suppress non-essential output")
    ] = False
    dry_run: Annotated[
        bool, cyclopts.Parameter(show_default=False, alias="-n", help="Show what would be done without making changes")
    ] = False


def app_launcher(
    *tokens: Annotated[str, cyclopts.Parameter(show=False, allow_leading_hyphen=True)],
    global_args: Annotated[GlobalArgs, cyclopts.Parameter(name="*")] | None = None,
) -> None:
    """Meta-command launcher — runs before every subcommand."""
    context = get_context()
    if global_args is not None:
        context.verbose = global_args.verbose
        context.quiet = global_args.quiet
        context.dry_run = global_args.dry_run
    command, bound, _ = app.parse_args(tokens)
    command(*bound.args, **bound.kwargs)


_GLOBAL_OPTIONS_GROUP = cyclopts.Group("Global options", sort_key=4)

app = cyclopts.App(
    name="git-wt",
    help=(
        "Git worktree management using the bare repository pattern.\n\n"
        "Uses a .bare/ directory for git data with each branch in its own worktree\n"
        "directory. Run 'git-wt COMMAND --help' for details on any command."
    ),
    help_epilogue='Use "git-wt COMMAND --help" for more information about a command.',
    # usage="git-wt [command] [flags]",
    version_flags=[],
    default_parameter=cyclopts.Parameter(negative=(), consume_multiple=True),
    group_commands=_GLOBAL_OPTIONS_GROUP,
    console=Console(width=76),
)
app.meta.group_parameters = _GLOBAL_OPTIONS_GROUP

_SUPPORTED_GROUP = cyclopts.Group("Supported commands:", sort_key=1)
_PASSTHROUGH_GROUP = cyclopts.Group("Passthrough:", sort_key=2)

# Lazy command registration
_COMMANDS = [
    ("clone", "Clone a repository with worktree structure"),
    ("add", "Create a new worktree"),
    ("remove", "Remove worktrees directly or by safe cleanup filters"),
    ("switch", "Interactively switch to a different worktree"),
    ("migrate", "Migrate a repository to use worktrees [EXPERIMENTAL]"),
    ("status", "Show a compact status dashboard for all worktrees"),
    ("doctor", "Run diagnostics on the current repository layout"),
    ("update", "Fetch and pull the default branch worktree (and optionally another)"),
    ("init", "Print shell integration for automatic directory switching"),
]
for _cmd, _help in _COMMANDS:
    app.command(f"git_wt.app.cli.{_cmd}:{_cmd}", group=_SUPPORTED_GROUP, help=_help)

app.command(
    "git_wt.app.cli.list:list_", name="list", group=_SUPPORTED_GROUP, help="List worktrees with repo-relative paths"
)
app.command("git_wt.app.cli.list:list_", name="ls", show=False)

app.command("git_wt.app.cli.add:add", name="new", show=False)

app.command("git_wt.app.cli.remove:destroy", show=False)
app.command("git_wt.app.cli.remove:remove", name="rm", show=False)
app.command("git_wt.app.cli.update:update", name="u", show=False)

app.command(
    "git_wt.app.cli.agent_skill:agent_skill",
    name="agent-skill",
    group=_SUPPORTED_GROUP,
    help="Install the git-wt agent skill",
)
app.command("git_wt.app.cli.completion:completion", group=_SUPPORTED_GROUP, help="Generate shell completion script")
app.command("git_wt.app.cli.preview:preview_", name="_preview", show=False)


def _lock_passthrough() -> None:
    """Pass-through to git worktree lock"""


def _unlock_passthrough() -> None:
    """Pass-through to git worktree unlock"""


def _move_passthrough() -> None:
    """Pass-through to git worktree move"""


def _repair_passthrough() -> None:
    """Pass-through to git worktree repair"""


app.command(_lock_passthrough, name="lock", group=_PASSTHROUGH_GROUP)
app.command(_unlock_passthrough, name="unlock", group=_PASSTHROUGH_GROUP)
app.command(_move_passthrough, name="move", group=_PASSTHROUGH_GROUP)
app.command(_repair_passthrough, name="repair", group=_PASSTHROUGH_GROUP)

app.command(
    "git_wt.app.cli.prune:prune",
    group=_SUPPORTED_GROUP,
    help="Remove metadata for worktrees whose directories no longer exist",
)

app.meta.default(app_launcher)

_PASSTHROUGH = {"lock", "unlock", "move", "repair"}


def run() -> int:
    """Main entry point."""
    debug = os.environ.get("DEBUG") == "1"
    install_exception_hook()
    install_signal_handler()
    console_init(debug=debug)

    args = sys.argv[1:]

    if args and args[0] == "man":
        rest = args[1:]
        if not rest or rest[0] in ("--help", "-h"):
            print("Usage: git wt man <directory>\n\nGenerate man pages for all git-wt commands into <directory>.")
            return 0
        from git_wt.man import run as _man_run

        _man_run(rest[0])
        return 0

    if args and args[0] == "help":
        sys.argv[1:] = ["--help"]
        return app.meta()

    if args and args[0] in _PASSTHROUGH:
        subcmd = args[0]
        rest = args[1:]
        if "--help" in rest or "-h" in rest:
            print(
                f"Usage: git wt {subcmd} [...]\n\nPass-through to git worktree {subcmd}.\n\nRun 'git worktree {subcmd} --help' for full git options."
            )
            return 0
        os.execvp("git", ["git", "worktree", subcmd, *rest])

    return app.meta()
