"""供应商与界面无关的工具审批对象。"""

from dataclasses import dataclass
from enum import StrEnum

from vortex.domain.tools import ToolCall, ToolRisk


class ApprovalDecision(StrEnum):
    """用户对一次工具审批请求的决定。"""

    ALLOW_ONCE = "allow_once"
    ALLOW_SESSION = "allow_session"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class ToolApprovalRequest:
    """Runtime 在执行工具前提交的审批请求。"""

    run_id: str
    iteration: int
    call: ToolCall
    risk: ToolRisk


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """审批结果及其是否来自当前会话缓存。"""

    decision: ApprovalDecision
    cached: bool = False
