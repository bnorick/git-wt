from __future__ import annotations

import io
from collections.abc import Callable

import pytest

from git_wt.app import console


def test_mark_readline_nonprinting_wraps_ansi_sequences() -> None:
    prompt = "\x1b[1;32mcmd>\x1b[0m "

    assert console._mark_readline_nonprinting(prompt) == "\x01\x1b[1;32m\x02cmd>\x01\x1b[0m\x02 "


def test_console_input_passes_colored_prompt_to_readline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readline_console = console.ReadlineConsole(
        file=io.StringIO(),
        force_terminal=True,
        color_system="standard",
    )
    received_prompt = ""

    def fake_input(prompt: str) -> str:
        nonlocal received_prompt
        received_prompt = prompt
        return "yes"

    monkeypatch.setattr(console, "_READLINE_AVAILABLE", True)
    monkeypatch.setattr("builtins.input", fake_input)

    assert readline_console.input("[bold red]Danger[/bold red]: ") == "yes"
    ansi_prompt = received_prompt.replace("\x01", "").replace("\x02", "")
    assert "\x1b[" in ansi_prompt
    assert received_prompt == console._mark_readline_nonprinting(ansi_prompt)
    assert console._ANSI_ESCAPE_RE.sub("", ansi_prompt) == "Danger: "


@pytest.mark.parametrize(
    ("prompt", "answer", "expected"),
    [
        (lambda: console.confirm("Continue?"), "y", True),
        (lambda: console.prompt_input("Branch name", default="main"), "", "main"),
        (lambda: console.prompt_dangerous("Type branch name", "main"), "main", True),
    ],
)
def test_prompt_helpers_pass_the_complete_prompt_to_readline(
    monkeypatch: pytest.MonkeyPatch,
    prompt: Callable[[], object],
    answer: str,
    expected: object,
) -> None:
    readline_console = console.ReadlineConsole(file=io.StringIO(), no_color=True)
    received_prompt = ""

    def fake_input(value: str) -> str:
        nonlocal received_prompt
        received_prompt = value
        return answer

    monkeypatch.setattr(console, "_console", readline_console)
    monkeypatch.setattr("builtins.input", fake_input)

    assert prompt() == expected
    assert received_prompt.startswith("? ")
    assert received_prompt.endswith(": ")
