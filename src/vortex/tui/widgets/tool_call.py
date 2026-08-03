"""TUI 中可观察的工具调用与 Observation。"""

import json
import shlex
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
        classes = (
            "tool-call running command-call" if call.name == "run_command" else "tool-call running"
        )
        super().__init__(classes=classes)
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
        preview = (
            _command_output_preview(result.content)
            if self.call.name == "run_command"
            else _preview(result.content)
        )
        self.query_one(".tool-call-observation", Static).update(
            Text(preview, style="#fb7185" if result.is_error else "#94a3b8")
        )

    def _summary(self) -> Text:
        arguments = _argument_summary(self.call)
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


def _argument_summary(call: ToolCall) -> str:
    if call.name == "run_command":
        command = call.arguments.get("command")
        if isinstance(command, list) and all(isinstance(item, str) for item in command):
            rendered = shlex.join(command)
            cwd = call.arguments.get("cwd", ".")
            return f"{rendered}  (cwd: {cwd})"
    return json.dumps(call.arguments, ensure_ascii=False, separators=(",", ":"))


def _command_output_preview(value: str, *, max_lines: int = 24, limit: int = 6_000) -> str:
    """命令输出保留换行和首尾，便于用户观察真实验证结果。"""
    lines = value.splitlines()
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines + 1
        lines = [*lines[:16], f"... {omitted} lines omitted ...", *lines[-7:]]
    rendered = "\n".join(lines)
    if len(rendered) > limit:
        return rendered[: limit - 1_503] + "\n... output truncated ...\n" + rendered[-1_480:]
    return rendered
