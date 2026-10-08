# Application-layout module.
"""Generate groff man pages for all git-wt commands."""

from __future__ import annotations

import re
from pathlib import Path

# Maps internal cyclopts command names to the display name used in man pages.
_DISPLAY_NAME = {
    "list-passthrough": "list",
}

# Commands to skip (internal or redundant in the man page set).
_SKIP = {"help-print", "agent-skill", "completion"}


def run(directory: str) -> None:
    """Write one .1 man page per visible command into *directory*."""
    from git_wt.app.cli import app as _app  # late import to avoid circular

    outdir = Path(directory)
    outdir.mkdir(parents=True, exist_ok=True)

    # Root page
    root_md = _app.generate_docs(
        output_format="markdown",
        recursive=False,
        include_hidden=False,
    )
    _write_page(outdir, "git-wt", "Manage git worktrees in the bare repository layout.", root_md)

    # One page per visible sub-command
    for sub in _app.subapps:
        if not sub.name or not sub.show:
            continue
        internal = sub.name[0]
        if internal in _SKIP:
            continue
        display = _DISPLAY_NAME.get(internal, internal)
        short = sub.help or ""
        sub_md = sub.generate_docs(
            output_format="markdown",
            recursive=False,
            include_hidden=False,
        )
        _write_page(outdir, f"git-wt-{display}", short, sub_md)


# ---------------------------------------------------------------------------
# Page writer
# ---------------------------------------------------------------------------


def _write_page(outdir: Path, name: str, short: str, markdown: str) -> None:
    title = name.upper().replace("-", "\\-")
    escaped_name = name.replace("-", "\\-")
    escaped_short = _escape(short)
    body = _md_to_man(markdown)
    content = (
        f'.TH "{title}" "1" "" "git-wt" "User Commands"\n'
        f".SH NAME\n"
        f"{escaped_name} \\- {escaped_short}\n"
        f".SH DESCRIPTION\n"
        f"{body}\n"
    )
    (outdir / f"{name}.1").write_text(content)


# ---------------------------------------------------------------------------
# Minimal Markdown → groff converter
# ---------------------------------------------------------------------------


def _md_to_man(md: str) -> str:
    out: list[str] = []
    in_code = False
    for line in md.splitlines():
        if line.startswith("```"):
            if in_code:
                out.append(".fi")
                in_code = False
            else:
                out.append(".nf")
                in_code = True
            continue
        if in_code:
            out.append(_escape(line))
            continue
        if not line.strip():
            out.append(".PP")
            continue
        if line.startswith("### "):
            out.append(f".SS {_escape(line[4:])}")
        elif line.startswith("## "):
            out.append(f".SS {_escape(line[3:])}")
        elif line.startswith("# "):
            pass  # title already in .TH
        elif line.startswith(("* ", "- ")):
            out.append(f"\\[bu] {_inline(line[2:])}")
        else:
            out.append(_inline(line))
    if in_code:
        out.append(".fi")
    return "\n".join(out)


def _inline(text: str) -> str:
    """Convert inline Markdown spans to groff escape sequences."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\\fB\1\\fR", text)
    text = re.sub(r"`(.+?)`", r"\\fB\1\\fR", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # strip links
    return _escape(text)


def _escape(text: str) -> str:
    """Escape characters that have special meaning in groff."""
    return text.replace("\\", "\\\\").replace("'", "\\(aq")
