"""一次 Agent Run 的文件变化摘要与操作入口。"""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static

from vortex.domain.changes import TurnChangeSummary


class TurnChangesCard(Vertical):
    """展示最新 Run 的净修改，并只允许整体 Review 或 Revert。"""

    class ReviewRequested(Message):
        """用户请求查看完整 Diff。"""

        def __init__(self, card: "TurnChangesCard") -> None:
            super().__init__()
            self.card = card

    class RevertRequested(Message):
        """用户请求整体撤销当前卡片对应的 Run。"""

        def __init__(self, card: "TurnChangesCard") -> None:
            super().__init__()
            self.card = card

    def __init__(self, summary: TurnChangeSummary) -> None:
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        count = len(self.summary.files)
        noun = "file" if count == 1 else "files"
        with Horizontal(classes="change-card-header"):
            yield Static(
                Text.assemble(
                    (f"Edited {count} {noun}", "bold #f8fafc"),
                    (f"   +{self.summary.additions}", "#4ade80"),
                    (f" -{self.summary.deletions}", "#fb7185"),
                ),
                classes="change-card-summary",
            )
            with Horizontal(classes="change-card-actions"):
                yield Button("Review", classes="review-changes")
                yield Button("Revert", classes="revert-changes", variant="warning")
        lines = Text()
        for index, file in enumerate(self.summary.files):
            if index:
                lines.append("\n")
            lines.append(file.path, style="#cbd5e1")
            lines.append(f"  +{file.additions}", style="#4ade80")
            lines.append(f" -{file.deletions}", style="#fb7185")
        yield Static(lines, classes="change-card-files")
        yield Static("", classes="change-card-state")

    @on(Button.Pressed, ".review-changes")
    def review_changes(self) -> None:
        self.post_message(self.ReviewRequested(self))

    @on(Button.Pressed, ".revert-changes")
    def revert_changes(self) -> None:
        self.query_one(".revert-changes", Button).disabled = True
        self.query_one(".change-card-state", Static).update("Reverting all changes…")
        self.post_message(self.RevertRequested(self))

    def mark_accepted(self) -> None:
        """新 Run 开始后，上一轮修改已被默认保留。"""
        self.query_one(".revert-changes", Button).disabled = True
        self.query_one(".change-card-state", Static).update("Changes kept")

    def mark_reverted(self, message: str) -> None:
        self.add_class("reverted")
        self.query_one(".revert-changes", Button).disabled = True
        self.query_one(".change-card-state", Static).update(message)

    def mark_revert_failed(self, message: str) -> None:
        self.query_one(".revert-changes", Button).disabled = False
        self.query_one(".change-card-state", Static).update(Text(message, style="#fb7185"))
