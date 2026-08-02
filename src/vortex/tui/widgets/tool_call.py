"""TUI 中可观察的工具调用与 Observation。"""

import json
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from vortex.domain.tools import ToolCall, ToolResult

ToolViewState = Literal["running", "succeeded", "failed"]


class ToolCallView(Vertical):
    """按安全摘要展示一次工具调用、结果与耗时。"""

    def __init__(self, call: ToolCall) -> None:
        super().__init__(classes="tool-call running")
        self.call = call
        self.state: ToolViewState = "running"
        self.result: ToolResult | None = None
        self.elapsed_ms = 0

    def compose(self) -> ComposeResult:
        yield Static(self._summary(), classes="tool-call-summary")
        yield Static("", classes="tool-call-observation")

    def finish(self, result: ToolResult, elapsed_ms: int) -> None:
        """用最终 Observation 更新正在运行的工具块。"""
        self.result = result
        self.elapsed_ms = elapsed_ms
        self.state = "failed" if result.is_error else "succeeded"
        self.remove_class("running")
        self.add_class(self.state)
        self.query_one(".tool-call-summary", Static).update(self._summary())
        self.query_one(".tool-call-observation", Static).update(
            Text(_preview(result.content), style="#fb7185" if result.is_error else "#94a3b8")
        )

    def _summary(self) -> Text:
        arguments = json.dumps(
            self.call.arguments,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        arguments = _preview(arguments, limit=120)
        if self.state == "running":
            return Text.assemble(
                ("→ ", "bold #67e8f9"),
                (self.call.name, "bold #e2e8f0"),
                (f"  {arguments}", "#94a3b8"),
            )
        marker = "✗" if self.state == "failed" else "✓"
        color = "#fb7185" if self.state == "failed" else "#4ade80"
        return Text.assemble(
            (f"{marker} ", f"bold {color}"),
            (self.call.name, "bold #e2e8f0"),
            (f"  {arguments}  ·  {self.elapsed_ms}ms", "#94a3b8"),
        )


def _preview(value: str, *, limit: int = 320) -> str:
    """折叠空白并限制 TUI Observation 长度。"""
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."
