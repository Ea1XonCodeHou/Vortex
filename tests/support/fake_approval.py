"""Runtime 测试使用的确定性审批管理器。"""

from vortex.domain.permissions import (
    ApprovalDecision,
    ApprovalOutcome,
    ToolApprovalRequest,
)


class FakeApprovalManager:
    """记录请求并始终返回预设决定。"""

    def __init__(self, decision: ApprovalDecision = ApprovalDecision.ALLOW_ONCE) -> None:
        self.decision = decision
        self.requests: list[ToolApprovalRequest] = []

    async def authorize(self, request: ToolApprovalRequest) -> ApprovalOutcome:
        self.requests.append(request)
        return ApprovalOutcome(self.decision)
