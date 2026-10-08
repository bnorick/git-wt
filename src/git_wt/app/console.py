# Application-layout module.
"""Rich-based UI helpers: colors, prompts, tables, step runner."""

from __future__ import annotations

import io
import os
import re
import sys
import time
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from getpass import getpass
from typing import Any, TextIO

from rich import box as rich_box
from rich.console import Console
from rich.table import Table
from rich.text import TextType

try:
    import readline  # noqa: F401 -- importing installs Python's line editor
except ImportError:
    _READLINE_AVAILABLE = False
else:
    _READLINE_AVAILABLE = True


_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")
_READLINE_PROMPT_START_IGNORE = "\x01"
_READLINE_PROMPT_END_IGNORE = "\x02"


def _mark_readline_nonprinting(prompt: str) -> str:
    """Tell Readline that ANSI escape sequences occupy no screen columns."""
    return _ANSI_ESCAPE_RE.sub(
        lambda match: f"{_READLINE_PROMPT_START_IGNORE}{match.group(0)}{_READLINE_PROMPT_END_IGNORE}",
        prompt,
    )


class ReadlineConsole(Console):
    """A Rich console whose prompts remain intact while Readline edits input."""

    def input(
        self,
        prompt: TextType = "",
        *,
        markup: bool = True,
        emoji: bool = True,
        password: bool = False,
        stream: TextIO | None = None,
    ) -> str:
        prompt_str = ""
        if prompt:
            with self.capture() as capture:
                self.print(prompt, markup=markup, emoji=emoji, end="")
            prompt_str = capture.get()
        if self.legacy_windows:
            self.file.write(prompt_str)
            prompt_str = ""
        if password:
            return getpass(prompt_str, stream=stream)
        if stream:
            self.file.write(prompt_str)
            return stream.readline()
        if _READLINE_AVAILABLE:
            prompt_str = _mark_readline_nonprinting(prompt_str)
        # input() must receive the prompt so Readline knows its visible width.
        # Redirect its prompt output to this console's file (stderr for git-wt).
        with redirect_stdout(self.file):
            return input(prompt_str)


# ---------------------------------------------------------------------------
# Global console - writes to stderr so stdout stays clean for piping
# ---------------------------------------------------------------------------

_console = ReadlineConsole(stderr=True)


def init(debug: bool = False) -> None:
    """Initialize console for the session."""
    global _console
    if not is_interactive():
        # Use a wide console so table columns are never truncated when piped
        _console = ReadlineConsole(stderr=True, no_color=True, width=32768)


def is_interactive() -> bool:
    """Check if stderr is attached to an interactive terminal."""
    return sys.stderr.isatty()


# ---------------------------------------------------------------------------
# TTY detection (kept for picker compatibility)
# ---------------------------------------------------------------------------


def _input_tty() -> bool:
    return sys.stdin.isatty()


def _stdout_tty() -> bool:
    return sys.stdout.isatty()


def can_render_selection() -> bool:
    return _input_tty() and _stdout_tty()


# ---------------------------------------------------------------------------
# Print
# ---------------------------------------------------------------------------


def print(*args: Any, **kwargs: Any) -> None:
    """Print to stderr using Rich formatting."""
    _console.print(*args, **kwargs)


# ---------------------------------------------------------------------------
# Color helpers (respect NO_COLOR)
# ---------------------------------------------------------------------------


def _no_color() -> bool:
    return bool(os.environ.get("NO_COLOR"))


def _style(text: str, style: str) -> str:
    if _no_color():
        return text
    return f"[{style}]{text}[/{style}]"


def green(text: str) -> str:
    return _style(text, "green")


def red(text: str) -> str:
    return _style(text, "red")


def yellow(text: str) -> str:
    return _style(text, "yellow")


def accent(text: str) -> str:
    return _style(text, "cyan")


def subtle(text: str) -> str:
    return _style(text, "dim")


def highlight(text: str) -> str:
    return _style(text, "magenta")


def bold(text: str) -> str:
    return _style(text, "bold")


def dim(text: str) -> str:
    return _style(text, "dim")


def path_style(p: str) -> str:
    """Dim directory prefix, bold basename."""
    import os.path

    dirname = os.path.dirname(p)
    basename = os.path.basename(p)
    if dirname:
        return dim(dirname + "/") + bold(basename)
    return bold(basename)


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------


def error(msg: str) -> None:
    _console.print(f"{red('error')}: {msg}")


def hint(msg: str) -> None:
    _console.print(f"{subtle('hint')}: {msg}")


def warn(msg: str) -> None:
    _console.print(f"{yellow('warn')}: {msg}")


def info(msg: str) -> None:
    _console.print(msg)


def success(msg: str) -> None:
    _console.print(green(msg))


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def confirm(msg: str, eof_default: bool = False) -> bool:
    """Ask y/N. Returns True only for 'y' or 'Y'. eof_default controls the result on EOF."""
    try:
        answer = _console.input(f"{accent('?')} {msg} {subtle('(y/N)')}: ")
    except EOFError:
        return eof_default
    return answer.strip().lower() == "y"


def prompt_input(msg: str, default: str = "") -> str:
    """Prompt for text input."""
    display_default = f" {subtle(f'({default})')}" if default else ""
    try:
        answer = _console.input(f"{accent('?')} {msg}{display_default}: ").strip()
    except EOFError:
        return default
    return answer if answer else default


def prompt_dangerous(msg: str, expected: str) -> bool:
    """Require exact string match for destructive operations."""
    try:
        answer = _console.input(f"{accent('?')} {msg}: ").strip()
    except EOFError:
        return False
    return answer == expected


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


@dataclass
class TableColumn:
    title: str
    min_width: int = 0
    max_width: int = 0
    style: str = ""
    header_style: str = "bold cyan"
    no_wrap: bool = False


def render_table(
    columns: list[TableColumn],
    rows: list[list[str]],
    title: str | None = None,
) -> Table:
    t = Table(box=rich_box.SIMPLE, show_header=True, title=title, title_justify="left")
    for col in columns:
        kwargs: dict = {
            "header_style": col.header_style,
            "no_wrap": col.no_wrap,
        }
        if col.style:
            kwargs["style"] = col.style
        if col.min_width:
            kwargs["min_width"] = col.min_width
        if col.max_width:
            kwargs["max_width"] = col.max_width
        t.add_column(col.title, **kwargs)
    for row in rows:
        t.add_row(*row)
    return t


def print_table(
    columns: list[TableColumn],
    rows: list[list[str]],
    summary: str | None = None,
) -> None:
    t = render_table(columns, rows)
    _console.print(t)
    if summary:
        _console.print(subtle(summary))


# ---------------------------------------------------------------------------
# Step runner
# ---------------------------------------------------------------------------


@dataclass
class Step:
    message: str | Callable[[], str]
    show_output: bool = False
    raw_output: bool = False
    run: Callable[[Callable[[str], None]], None] = field(default=lambda w: None)


def run_steps(steps: list[Step]) -> None:
    """Execute steps sequentially with spinner feedback. Raises on first error."""
    for step in steps:
        msg = step.message if isinstance(step.message, str) else step.message()
        if step.raw_output:
            _console.print(f"{subtle('◇')} {msg}")
            t0 = time.perf_counter()
            try:
                step.run(lambda _: None)
                elapsed = time.perf_counter() - t0
                _console.print(f"{green('◆')} {msg} {subtle(f'({elapsed:.2f}s)')}")
            except Exception:
                elapsed = time.perf_counter() - t0
                _console.print(f"{red('◆')} {msg} {subtle(f'({elapsed:.2f}s)')}")
                raise
        elif is_interactive():
            buf = io.StringIO()

            def _write(data: str, buffer: io.StringIO = buf) -> None:
                buffer.write(data)

            t0 = time.perf_counter()
            with _console.status(f"{dim('◇')} {msg}", spinner="dots"):
                try:
                    step.run(_write)
                except Exception:
                    elapsed = time.perf_counter() - t0
                    _console.print(f"{red('◆')} {msg} {subtle(f'({elapsed:.2f}s)')}")
                    if step.show_output and buf.tell():
                        _console.print(buf.getvalue().rstrip())
                    raise
            elapsed = time.perf_counter() - t0
            _console.print(f"{green('◆')} {msg} {subtle(f'({elapsed:.2f}s)')}")
            if step.show_output and buf.tell():
                _console.print(buf.getvalue().rstrip())
        else:
            buf = io.StringIO()

            def _write(data: str, buffer: io.StringIO = buf) -> None:
                buffer.write(data)

            sys.stderr.write(f"◇ {msg}\n")
            sys.stderr.flush()
            t0 = time.perf_counter()
            try:
                step.run(_write)
                elapsed = time.perf_counter() - t0
                sys.stderr.write(f"◆ {msg} ({elapsed:.2f}s)\n")
                sys.stderr.flush()
            except Exception:
                elapsed = time.perf_counter() - t0
                sys.stderr.write(f"✗ {msg} ({elapsed:.2f}s)\n")
                sys.stderr.flush()
                if step.show_output and buf.tell():
                    sys.stderr.write(buf.getvalue())
                raise
            if step.show_output and buf.tell():
                sys.stderr.write(buf.getvalue())
