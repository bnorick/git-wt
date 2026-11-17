# Development

Application framework code belongs under the app package. CLI construction lives in app/cli/__init__.py and individual command adapters live in app/cli/COMMAND.py. Reusable behavior remains in top-level package modules.

Treat CLI arguments, stdout, stderr, and exit codes as compatibility surfaces. Normal --help is concise; the help command is detailed and pager-aware. TUI initialization must not occur while rendering help.

Use the local tasks script for formatting, linting, type checking, dependency checking, and tests. Characterize external commands and destructive behavior with mocks before refactoring.
