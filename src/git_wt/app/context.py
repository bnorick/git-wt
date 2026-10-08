# Application-layout module.
"""Runtime execution context."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class Context:
    verbose: bool = False
    quiet: bool = False
    dry_run: bool = False


_CONTEXT = Context()


def get_context() -> Context:
    return _CONTEXT
