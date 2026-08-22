from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from vibe.cli.textual_ui.shortcut_hints import shortcut, shortcut_hint
from vibe.cli.textual_ui.widgets.banner.petit_chat import PetitChat
from vibe.cli.textual_ui.widgets.navigable_option_list import NavigableOptionList
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic


def _build_option_text(label: str, session_count: int) -> Text:
    display = Path(label).name or label
    text = Text(no_wrap=True)
    text.append(display, style="bold")
    text.append(f"  ({session_count} session{'s' if session_count != 1 else ''})")
    return text


class ProjectPickerApp(Container):
    """Picker for selecting a project to view aggregated usage."""

    can_focus_children = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False)
    ]

    class ProjectSelected(Message):
        def __init__(self, cwd: str) -> None:
            self.cwd = cwd
            super().__init__()

    class Cancelled(Message):
        def __init__(self) -> None:
            super().__init__()

    def __init__(
        self,
        projects: list[tuple[str, int]],
        animate_mascot: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(id="projectpicker-app", **kwargs)
        self._projects = projects
        self._animate_mascot = animate_mascot

    def compose(self) -> ComposeResult:
        options = [
            Option(_build_option_text(cwd, count), id=cwd)
            for cwd, count in self._projects
        ]
        count = len(self._projects)
        with Vertical(id="projectpicker-content"):
            yield PetitChat(
                animate=self._animate_mascot, classes="projectpicker-mascot"
            )
            yield NoMarkupStatic("Select Project", classes="projectpicker-title")
            yield NoMarkupStatic(
                f"{count} project{'s' if count != 1 else ''}",
                classes="projectpicker-count",
            )
            yield NavigableOptionList(*options, id="projectpicker-options")
            yield NoMarkupStatic(
                shortcut_hint(
                    f"{shortcut('↑↓/jk')} Navigate  {shortcut('Enter')} Select  "
                    f"{shortcut('Esc')} Cancel"
                ),
                classes="projectpicker-help",
            )

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        if self._projects:
            option_list.highlighted = 0
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.post_message(self.ProjectSelected(event.option.id))

    def action_cancel(self) -> None:
        self.post_message(self.Cancelled())
