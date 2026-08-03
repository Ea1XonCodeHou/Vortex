"""最新 Agent Run 的完整 Diff 审阅弹窗。"""

from rich.syntax import Syntax
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from vortex.domain.changes import TurnChangeSummary


class ChangeReviewScreen(ModalScreen[None]):
    """只读展示一次 Run 的完整统一 Diff。"""

    BINDINGS = [Binding("escape", "close", "Close", show=False)]

    def __init__(self, summary: TurnChangeSummary) -> None:
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="change-review-dialog"):
            yield Static("Review workspace changes", id="change-review-title")
            yield Static(
                f"{len(self.summary.files)} file(s) · "
                f"+{self.summary.additions} -{self.summary.deletions}",
                id="change-review-summary",
            )
            with VerticalScroll(id="change-review-diff"):
                yield Static(
                    Syntax(
                        self.summary.diff,
                        "diff",
                        theme="ansi_dark",
                        word_wrap=True,
                    )
                )
            yield Button("Close", id="close-change-review", variant="primary")

    @on(Button.Pressed, "#close-change-review")
    def close_button(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
