"""工具调用审批弹窗。"""

import json

from rich.syntax import Syntax
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from vortex.domain.permissions import ApprovalDecision, ToolApprovalRequest
from vortex.domain.tools import ToolRisk

_MAX_ARGUMENT_PREVIEW = 1_200


class ToolApprovalScreen(ModalScreen[ApprovalDecision]):
    """显示工具风险和参数，并返回一次明确的用户决定。"""

    BINDINGS = [
        Binding("escape,ctrl+c", "deny", "Deny", show=False, priority=True),
        Binding("o", "allow_once", "Allow once", show=False),
        Binding("s", "allow_session", "Allow for session", show=False),
        Binding("t", "allow_turn", "Allow for this turn", show=False),
        Binding("d", "deny", "Deny", show=False),
    ]

    def __init__(self, request: ToolApprovalRequest) -> None:
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        is_write = ApprovalDecision.ALLOW_TURN in self.request.allowed_decisions
        is_execute = self.request.risk is ToolRisk.EXECUTE
        argument_source = self.request.call.arguments
        if is_write:
            edits = argument_source.get("edits")
            argument_source = {
                "path": argument_source.get("path", ""),
                "edits": len(edits) if isinstance(edits, list) else "invalid",
            }
        elif is_execute:
            command = argument_source.get("command")
            argument_source = {
                "arguments": len(command) if isinstance(command, list) else "invalid",
                "cwd": argument_source.get("cwd", "."),
            }
        arguments = json.dumps(argument_source, ensure_ascii=False, indent=2, sort_keys=True)
        if len(arguments) > _MAX_ARGUMENT_PREVIEW:
            arguments = arguments[: _MAX_ARGUMENT_PREVIEW - 3] + "..."

        with Vertical(id="approval-dialog"):
            yield Static(
                (
                    "Workspace edit permission"
                    if is_write
                    else "Command execution permission"
                    if is_execute
                    else "Tool permission required"
                ),
                id="approval-title",
            )
            yield Static(
                Text.assemble(
                    "Vortex wants to use ",
                    (self.request.call.name, "bold"),
                    " (",
                    (self.request.risk.value, "bold"),
                    ")",
                ),
                id="approval-summary",
            )
            yield Static(arguments, markup=False, id="approval-arguments")
            if self.request.preview:
                yield Static(
                    "Proposed changes" if is_write else "Execution details",
                    id="approval-preview-title",
                )
                with VerticalScroll(id="approval-preview"):
                    if is_write:
                        yield Static(
                            Syntax(
                                self.request.preview,
                                "diff",
                                theme="ansi_dark",
                                word_wrap=True,
                            )
                        )
                    else:
                        yield Static(self.request.preview, markup=False)
            yield Static(
                (
                    "Allow edits this turn covers later apply_patch calls in this task only."
                    if is_write
                    else (
                        "Allow once executes only this command. Its side effects are not "
                        "included in Revert."
                    )
                    if is_execute
                    else "Allow for session applies only to this tool in this workspace session."
                ),
                id="approval-scope",
            )
            with Horizontal(id="approval-actions"):
                if ApprovalDecision.ALLOW_ONCE in self.request.allowed_decisions:
                    yield Button("Allow once", id="allow-once", variant="primary")
                if ApprovalDecision.ALLOW_TURN in self.request.allowed_decisions:
                    yield Button("Allow edits this turn", id="allow-turn", variant="primary")
                if ApprovalDecision.ALLOW_SESSION in self.request.allowed_decisions:
                    yield Button("Allow for session", id="allow-session", variant="success")
                yield Button("Deny", id="deny", variant="error")

    def on_mount(self) -> None:
        """聚焦当前请求实际允许的首个操作。"""
        for decision, selector in (
            (ApprovalDecision.ALLOW_TURN, "#allow-turn"),
            (ApprovalDecision.ALLOW_ONCE, "#allow-once"),
            (ApprovalDecision.ALLOW_SESSION, "#allow-session"),
            (ApprovalDecision.DENY, "#deny"),
        ):
            if decision in self.request.allowed_decisions:
                self.query_one(selector, Button).focus()
                return

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        """把按钮映射成稳定审批决定。"""
        decisions = {
            "allow-once": ApprovalDecision.ALLOW_ONCE,
            "allow-session": ApprovalDecision.ALLOW_SESSION,
            "allow-turn": ApprovalDecision.ALLOW_TURN,
            "deny": ApprovalDecision.DENY,
        }
        decision = decisions.get(event.button.id or "")
        if decision is not None and decision in self.request.allowed_decisions:
            self.dismiss(decision)

    def action_allow_once(self) -> None:
        self._dismiss_if_allowed(ApprovalDecision.ALLOW_ONCE)

    def action_allow_turn(self) -> None:
        self._dismiss_if_allowed(ApprovalDecision.ALLOW_TURN)

    def action_allow_session(self) -> None:
        self._dismiss_if_allowed(ApprovalDecision.ALLOW_SESSION)

    def action_deny(self) -> None:
        self._dismiss_if_allowed(ApprovalDecision.DENY)

    def _dismiss_if_allowed(self, decision: ApprovalDecision) -> None:
        if decision in self.request.allowed_decisions:
            self.dismiss(decision)
