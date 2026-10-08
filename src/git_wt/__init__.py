"""git-wt — Manage git worktrees in the bare repository layout."""

from __future__ import annotations

from git_wt.app import console
from git_wt.app import tui as _picker
from git_wt.app.console import (
    Step,
    TableColumn,
    accent,
    bold,
    confirm,
    dim,
    error,
    green,
    highlight,
    info,
    is_interactive,
    path_style,
    print,  # noqa: A004
    print_table,
    prompt_dangerous,
    prompt_input,
    red,
    render_table,
    run_steps,
    subtle,
    success,
    warn,
    yellow,
)
from git_wt.app.console import (
    init as console_init,
)
from git_wt.app.context import Context, get_context
from git_wt.app.errors import CliError, install_exception_hook, install_signal_handler

__all__ = [
    "_picker",
    "CliError",
    "Context",
    "Step",
    "TableColumn",
    "accent",
    "bold",
    "confirm",
    "console_init",
    "console",
    "dim",
    "error",
    "get_context",
    "green",
    "highlight",
    "info",
    "install_exception_hook",
    "install_signal_handler",
    "is_interactive",
    "path_style",
    "print",
    "print_table",
    "prompt_dangerous",
    "prompt_input",
    "red",
    "render_table",
    "run_steps",
    "subtle",
    "success",
    "warn",
    "yellow",
]
