"""工具调用审批弹窗。"""

import json

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from vortex.domain.permissions import ApprovalDecision, ToolApprovalRequest

_MAX_ARGUMENT_PREVIEW = 1_200


class ToolApprovalScreen(ModalScreen[ApprovalDecision]):
    """显示工具风险和参数，并返回一次明确的用户决定。"""

    AUTO_FOCUS = "#allow-once"
    BINDINGS = [
        Binding("escape,ctrl+c", "deny", "Deny", show=False, priority=True),
        Binding("o", "allow_once", "Allow once", show=False),
        Binding("s", "allow_session", "Allow for session", show=False),
        Binding("d", "deny", "Deny", show=False),
    ]

    def __init__(self, request: ToolApprovalRequest) -> None:
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        arguments = json.dumps(
            self.request.call.arguments,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        if len(arguments) > _MAX_ARGUMENT_PREVIEW:
            arguments = arguments[: _MAX_ARGUMENT_PREVIEW - 3] + "..."

        with Vertical(id="approval-dialog"):
            yield Static("Tool permission required", id="approval-title")
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
            yield Static(
                "Allow for session applies only to this tool in the current workspace session.",
                id="approval-scope",
            )
            with Horizontal(id="approval-actions"):
                yield Button("Allow once", id="allow-once", variant="primary")
                yield Button("Allow for session", id="allow-session", variant="success")
                yield Button("Deny", id="deny", variant="error")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        """把按钮映射成稳定审批决定。"""
        decisions = {
            "allow-once": ApprovalDecision.ALLOW_ONCE,
            "allow-session": ApprovalDecision.ALLOW_SESSION,
            "deny": ApprovalDecision.DENY,
        }
        decision = decisions.get(event.button.id or "")
        if decision is not None:
            self.dismiss(decision)

    def action_allow_once(self) -> None:
        self.dismiss(ApprovalDecision.ALLOW_ONCE)

    def action_allow_session(self) -> None:
        self.dismiss(ApprovalDecision.ALLOW_SESSION)

    def action_deny(self) -> None:
        self.dismiss(ApprovalDecision.DENY)
