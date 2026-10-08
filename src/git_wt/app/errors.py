# Application-layout module.
"""Error handling and exception formatting."""

from __future__ import annotations

import signal
import sys
from typing import Any


class CliError(Exception):
    """Base exception for user-facing CLI errors (no traceback)."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def install_exception_hook() -> None:
    """Install a Rich-formatted exception hook."""

    def _hook(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        if isinstance(exc_value, CliError):
            from git_wt.app.console import _console

            _console.print(f"[bold red]error:[/bold red] {exc_value.message}")
            sys.exit(exc_value.exit_code)
        from git_wt.app.console import _console, is_interactive

        if is_interactive():
            try:
                from rich.traceback import Traceback

                _console.print(Traceback.from_exception(exc_type, exc_value, exc_traceback))
            except Exception:
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
        else:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _hook


def install_signal_handler() -> None:
    """Install signal handlers for graceful shutdown."""

    def _handler(signum: int, frame: Any) -> None:
        from git_wt.app.console import _console

        _console.print("\n[bold yellow]Interrupted[/bold yellow]")
        sys.exit(130 if signum == signal.SIGINT else 143)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
