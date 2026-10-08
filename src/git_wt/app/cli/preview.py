# Application-layout module.
from __future__ import annotations

from git_wt import preview as action


def preview_(type_: str, value: str, mode: str = "") -> None:
    """Internal: render picker preview pane content."""
    action.run(type_, value, mode)
