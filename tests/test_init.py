"""Tests for git wt init shell integration."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_init_prints_shell_integration(wt, shell):
    result = wt("init", shell)

    assert result.returncode == 0
    assert "git-wt" in result.stdout
    assert "switch" in result.stdout
    assert "cd " in result.stdout
    assert "add" not in result.stdout


@pytest.mark.parametrize("shell", ["bash", "fish"])
def test_init_git_wrapper(wt, shell):
    with_wrapper = wt("init", shell)
    without_wrapper = wt("init", shell, "--no-git-wrapper")

    assert with_wrapper.returncode == 0
    assert without_wrapper.returncode == 0
    assert "command git " in with_wrapper.stdout
    wrapper = "git() {" if shell == "bash" else "function git "
    assert wrapper not in without_wrapper.stdout
    assert len(without_wrapper.stdout) < len(with_wrapper.stdout)


def test_init_rejects_unsupported_shell(wt):
    result = wt("init", "powershell", check=False)

    assert result.returncode != 0
    assert "unsupported shell" in result.stderr + result.stdout
