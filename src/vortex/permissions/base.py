"""工具审批管理器协议。"""

from typing import Protocol

from vortex.domain.permissions import ApprovalOutcome, ToolApprovalRequest


class ApprovalManager(Protocol):
    """在执行工具前返回显式审批结果。"""

    async def authorize(self, request: ToolApprovalRequest) -> ApprovalOutcome:
        """评估或请求用户批准一次工具调用。"""
        ...
