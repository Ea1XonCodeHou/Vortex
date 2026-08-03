"""当前进程会话内的交互式工具审批缓存。"""

from collections.abc import Awaitable, Callable

from vortex.domain.permissions import (
    ApprovalDecision,
    ApprovalOutcome,
    ToolApprovalRequest,
)

type ApprovalPrompt = Callable[[ToolApprovalRequest], Awaitable[ApprovalDecision]]


class SessionApprovalManager:
    """按工具名称缓存当前工作区会话的允许决定。"""

    def __init__(self) -> None:
        self._allowed_tools: set[str] = set()
        self._allowed_turn_tools: dict[str, str] = {}
        self._prompt: ApprovalPrompt | None = None

    def set_prompt(self, prompt: ApprovalPrompt | None) -> None:
        """连接或移除具体客户端提供的交互实现。"""
        self._prompt = prompt

    async def authorize(self, request: ToolApprovalRequest) -> ApprovalOutcome:
        """复用会话允许项，否则等待客户端做出决定。"""
        if (
            ApprovalDecision.ALLOW_SESSION in request.allowed_decisions
            and request.call.name in self._allowed_tools
        ):
            return ApprovalOutcome(ApprovalDecision.ALLOW_SESSION, cached=True)
        if (
            ApprovalDecision.ALLOW_TURN in request.allowed_decisions
            and self._allowed_turn_tools.get(request.call.name) == request.run_id
        ):
            return ApprovalOutcome(ApprovalDecision.ALLOW_TURN, cached=True)

        if self._prompt is None:
            return ApprovalOutcome(ApprovalDecision.DENY)

        decision = await self._prompt(request)
        if decision not in request.allowed_decisions:
            return ApprovalOutcome(ApprovalDecision.DENY)
        if decision is ApprovalDecision.ALLOW_SESSION:
            self._allowed_tools.add(request.call.name)
        elif decision is ApprovalDecision.ALLOW_TURN:
            self._allowed_turn_tools[request.call.name] = request.run_id
        return ApprovalOutcome(decision)
