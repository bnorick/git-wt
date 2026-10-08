# Application-layout module.
"""Interactive fuzzy picker built with Textual (no fzf dependency)."""

from __future__ import annotations

import os
import shlex
from contextlib import suppress
from dataclasses import dataclass
from typing import ClassVar

import duct
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Footer, Input, Label, ListItem, ListView, RichLog
from textual.worker import get_current_worker

from git_wt.app.console import can_render_selection


@dataclass
class Item:
    value: str
    label: str
    desc: str = ""


@dataclass
class PickerConfig:
    items: list[Item]
    multi: bool = False
    prompt: str = "Search: "
    header: str = ""
    preview_cmd: str = ""


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------


def _fuzzy_match(query: str, text: str) -> bool:
    """All chars of query appear in order in text (case-insensitive)."""
    it = iter(text.lower())
    return all(c in it for c in query.lower())


# ---------------------------------------------------------------------------
# Input subclass that routes Up/Down to the list before Input can consume them
# ---------------------------------------------------------------------------


class SearchInput(Input):
    class Navigate(Message):
        def __init__(self, direction: str) -> None:
            super().__init__()
            self.direction = direction

    class ToggleSelect(Message):
        pass

    async def _on_key(self, event: Key) -> None:
        if event.key in ("up", "down"):
            event.prevent_default()
            event.stop()
            self.post_message(self.Navigate(event.key))
        elif event.key == "space":
            event.prevent_default()
            event.stop()
            self.post_message(self.ToggleSelect())
        else:
            await super()._on_key(event)


# ---------------------------------------------------------------------------
# Custom ListItem that carries an Item reference
# ---------------------------------------------------------------------------


class PickerListItem(ListItem):
    def __init__(self, item: Item, selected: bool = False) -> None:
        super().__init__()
        self.picker_item = item
        self._selected = selected

    def compose(self) -> ComposeResult:
        yield Label(self._check_markup(), id="item-check", markup=True)
        yield Label(self._build_label(), id="item-label", markup=True)

    def _check_markup(self) -> str:
        return "[green]✓[/green]" if self._selected else " "

    def _build_label(self) -> str:
        label = self.picker_item.label
        if self.picker_item.desc:
            label += f" [dim]· {self.picker_item.desc}[/dim]"
        return label

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        with suppress(Exception):
            self.query_one("#item-check", Label).update(self._check_markup())


# ---------------------------------------------------------------------------
# Picker Textual App
# ---------------------------------------------------------------------------


class PickerApp(App):
    CSS = """
    Screen {
        layout: horizontal;
    }
    #left {
        width: 50%;
        layout: vertical;
        border-right: solid $primary-darken-3;
    }
    #header-label {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    #selected-count {
        height: 1;
        padding: 0 1;
        color: $text;
    }
    PickerListItem {
        layout: horizontal;
        height: 1;
    }
    PickerListItem > #item-check {
        width: 2;
        background: $surface;
        color: $success;
    }
    PickerListItem > #item-label {
        width: 1fr;
    }
    Input {
        height: 3;
    }
    #list {
        height: 1fr;
    }
    #preview {
        width: 1fr;
        padding: 0 1;
    }
    Footer {
        height: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("space", "toggle_select", "Select", show=True),
        Binding("enter", "confirm", "Confirm"),
    ]

    def __init__(self, config: PickerConfig) -> None:
        super().__init__()
        self.config = config
        self.result: list[Item] = []
        self._selected: set[str] = set()
        self._filtered: list[Item] = list(config.items)

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="left"):
                if self.config.header:
                    yield Label(self.config.header, id="header-label")
                yield SearchInput(placeholder=self.config.prompt, id="search")
                if self.config.multi:
                    yield Label(self._selected_markup(), id="selected-count", markup=True)
                yield ListView(
                    *[PickerListItem(item) for item in self._filtered],
                    id="list",
                )
            yield RichLog(id="preview", highlight=False, markup=False, wrap=True)
        yield Footer()

    def _selected_markup(self) -> str:
        n = len(self._selected)
        return f"[bold]{n} selected[/bold]"

    def _refresh_selected_count(self) -> None:
        with suppress(Exception):
            self.query_one("#selected-count", Label).update(self._selected_markup())

    def on_mount(self) -> None:
        self.query_one("#list", ListView).can_focus = False
        self.query_one("#preview", RichLog).can_focus = False
        self.query_one("#search", Input).focus()
        self._refresh_preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_confirm()

    def on_search_input_navigate(self, event: SearchInput.Navigate) -> None:
        lv = self.query_one("#list", ListView)
        if event.direction == "up":
            lv.action_cursor_up()
        else:
            lv.action_cursor_down()

    def on_search_input_toggle_select(self, event: SearchInput.ToggleSelect) -> None:
        self.action_toggle_select()

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip()
        if query:
            self._filtered = [it for it in self.config.items if _fuzzy_match(query, it.label + " " + it.desc)]
        else:
            self._filtered = list(self.config.items)
        lv = self.query_one("#list", ListView)
        lv.clear()
        for item in self._filtered:
            lv.append(PickerListItem(item, item.value in self._selected))
        self._refresh_preview()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._refresh_preview()

    def _current_item(self) -> Item | None:
        lv = self.query_one("#list", ListView)
        child = lv.highlighted_child
        if isinstance(child, PickerListItem):
            return child.picker_item
        return None

    def _refresh_preview(self) -> None:
        if not self.config.preview_cmd:
            return
        item = self._current_item()
        if item is None:
            return
        self._run_preview(item.value)

    def _run_preview(self, value: str) -> None:
        self.run_worker(
            lambda: self._fetch_preview(value),
            exclusive=True,
            thread=True,
        )

    def _fetch_preview(self, value: str) -> None:
        worker = get_current_worker()
        cmd = self.config.preview_cmd.replace("{value}", shlex.quote(value))
        try:
            output = duct.cmd("sh", "-c", cmd).unchecked().stderr_to_stdout().read() or "(no output)"
        except Exception as exc:
            output = f"(preview error: {exc})"

        if not worker.is_cancelled:
            log = self.query_one("#preview", RichLog)
            self.call_from_thread(log.clear)
            self.call_from_thread(log.write, Text.from_ansi(output))

    def action_toggle_select(self) -> None:
        if not self.config.multi:
            return
        item = self._current_item()
        if item is None:
            return
        lv = self.query_one("#list", ListView)
        child = lv.highlighted_child
        if not isinstance(child, PickerListItem):
            return
        if item.value in self._selected:
            self._selected.discard(item.value)
            child.set_selected(False)
        else:
            self._selected.add(item.value)
            child.set_selected(True)
        self._refresh_selected_count()

    def action_confirm(self) -> None:
        if self.config.multi and self._selected:
            self.result = [it for it in self.config.items if it.value in self._selected]
        else:
            item = self._current_item()
            if item is not None:
                self.result = [item]
        self.exit()

    def action_cancel(self) -> None:
        self.result = []
        self.exit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(config: PickerConfig) -> list[Item]:
    """Run the picker and return selected items (empty list = cancelled)."""
    # Test bypass: GIT_WT_SELECT=value1,value2 (also matches by label or "label [desc]")
    select_env = os.environ.get("GIT_WT_SELECT", "")
    if select_env:
        values = {v.strip() for v in select_env.split(",") if v.strip()}
        return [
            it for it in config.items if it.value in values or it.label in values or f"{it.label} [{it.desc}]" in values
        ]

    if not can_render_selection():
        return []

    app = PickerApp(config)
    app.run()
    return app.result
